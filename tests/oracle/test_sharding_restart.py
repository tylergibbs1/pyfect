"""Ports of the "replays a durable caller parked on a queued request when its
target closes" cases of Effect's ``test/cluster/Sharding.test.ts``: a runner
restarts over a message storage shared across runners (Effect's
``makeSharedMemoryStorage``) that persists a request it never reads back
(``unreadStorage``), through Effect's ``RestartSharding``. Each test's
docstring is the Effect test title."""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field, replace
from typing import Any

import pytest

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import (
    message_storage,
    runner_health,
    runner_storage,
    runners,
    sharding,
    sharding_config,
)
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.message import Incoming, IncomingRequest, OutgoingRequest
from pyfect.cluster.message_storage import MessageStorage, MessageStorageService
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.snowflake import Snowflake
from pyfect.duration import millis
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.rpc import make as make_rpc
from pyfect.scope import CloseableScope

from ._sharding_fixtures import patched

_VOID = Exit.succeed(None)


class IdPayload(S.Class):
    id: str

    def primary_key(self) -> str:
        return self.id


class ClosingTarget(Entity, type="ClosingTarget"):
    warm = make_rpc("Warm").annotate(Persisted, False)
    child = make_rpc("Child", payload=IdPayload, success=S.String).annotate(Persisted, True)


class ClosingTargetCaller(Entity, type="ClosingTargetCaller"):
    call = make_rpc("Call", payload=IdPayload, success=S.String).annotate(Persisted, True)


@dataclass(slots=True, eq=False)
class _State:
    children: int = 0
    continued: list[str] = field(default_factory=list[str])


def _closing_target_layer(state: _State) -> Layer[Any, Any, Any]:
    def child(_: Any) -> fx.Effect[str]:
        def run() -> str:
            state.children += 1
            return "child"

        return fx.sync(run)

    e = ClosingTarget
    return e.to_layer(e.handlers().handle(e.warm)(lambda _: fx.void).handle(e.child)(child))


def _closing_target_caller_layer(state: _State) -> Layer[Any, Any, Any]:
    """``Call`` is an ordinary durable handler that continues after a
    ``ClosingTarget`` request."""
    e = ClosingTargetCaller

    @fx.gen
    def build():
        target = yield from ClosingTarget.client()

        def call(_: Any) -> fx.Effect[str]:
            def record(value: str) -> fx.Effect[None]:
                return fx.sync(lambda: state.continued.append(value))

            return target("1").child(IdPayload(id="child")).or_die().tap(record)

        return e.handlers().handle(e.call)(call)

    return e.to_layer_effect(build)


def _unread_storage(
    storage: MessageStorageService, tag: str, saved: Latch
) -> MessageStorageService:
    """Persists requests with ``tag``, but never reads them back for
    delivery."""

    def is_unread(message: Incoming) -> bool:
        return isinstance(message, IncomingRequest) and message.envelope.tag == tag

    def save_request(message: OutgoingRequest) -> fx.Effect[Any, Any]:
        opened = saved.open() if message.envelope.tag == tag else fx.void
        return storage.save_request(message).tap(lambda _: opened)

    def read(messages: list[Incoming]) -> list[Incoming]:
        return [message for message in messages if not is_unread(message)]

    def unprocessed_messages(
        shard_ids: Iterable[ShardId],
        *,
        limit: int | None = None,
        addresses: Sequence[EntityAddress] | None = None,
    ) -> fx.Effect[list[Incoming], Any]:
        return storage.unprocessed_messages(shard_ids, limit=limit, addresses=addresses).map(read)

    def unprocessed_messages_by_id(ids: Iterable[Snowflake]) -> fx.Effect[list[Incoming], Any]:
        return storage.unprocessed_messages_by_id(ids).map(read)

    return patched(
        storage,
        save_request=save_request,
        unprocessed_messages=unprocessed_messages,
        unprocessed_messages_by_id=unprocessed_messages_by_id,
    )


def _restart_sharding(
    entity_layer: Layer[Any, Any, Any], storage: MessageStorageService, **config: Any
) -> Layer[Any]:
    return (
        entity_layer.pipe(fx.layer.provide_merge(sharding.layer))
        .pipe(fx.layer.provide(runner_storage.layer_memory))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide(fx.layer.succeed(MessageStorage, storage)))
        .pipe(
            fx.layer.provide(
                sharding_config.layer(
                    replace(
                        sharding_config.DEFAULTS,
                        entity_mailbox_capacity=10,
                        entity_message_poll_interval=millis(5000),
                        refresh_assignments_interval=millis(0),
                        entity_termination_timeout=millis(60_000),
                        entity_reply_poll_interval=millis(1),
                        send_retry_interval=millis(10),
                        **config,
                    )
                )
            )
        )
    )


def _advance_until[A, E, R](effect: fx.Effect[A, E, R]) -> fx.Effect[A, E, R]:
    """Steps the test clock until ``effect`` completes."""
    return effect.race_first(testing.adjust("1 millis").forever())


# Shared across runners, so a restarted runner sees the previous runner's
# requests.
_make_shared_memory_storage = (
    message_storage.layer_memory.pipe(fx.layer.provide(sharding_config.layer_defaults))
    .build()
    .map(lambda context: context.get_unsafe(MessageStorage))
)


# Preemptive shutdown abandons the parked caller during the drain; otherwise
# it must stay parked rather than store an interrupt as its reply.
@pytest.mark.parametrize("preemptive_shutdown", [True, False])
@testing.effect
def test_replays_a_durable_caller_parked_on_a_queued_request_when_its_target_closes(
    preemptive_shutdown: bool,
):
    """replays a durable caller parked on a queued request when its target closes (preemptiveShutdown: ${preemptiveShutdown})"""  # noqa: E501
    storage = yield from _make_shared_memory_storage
    queued = Latch()
    state = _State()
    runner_scope = CloseableScope()
    target_scope = CloseableScope()
    runner = yield from _restart_sharding(
        _closing_target_caller_layer(state),
        _unread_storage(storage, "Child", queued),
        preemptive_shutdown=preemptive_shutdown,
    ).build_with_scope(runner_scope)

    @fx.gen
    def first():
        yield from _closing_target_layer(state).build_with_scope(target_scope)
        # The target entity is resident while the caller waits on its queued
        # request.
        yield from _advance_until((yield from ClosingTarget.client())("1").warm())
        yield from (yield from ClosingTargetCaller.client())("1").call.discard(IdPayload(id="call"))
        yield from queued.wait()

    yield from first.pipe(fx.provide(runner))
    yield from _advance_until(target_scope.close(_VOID))
    # A caller left parked waits out ``entity_termination_timeout``.
    closing = yield from runner_scope.close(_VOID).fork(start_immediately=True)
    for _ in range(100):
        if closing.poll_unsafe() is not None:
            break
        yield from testing.adjust("1 second")
    yield from closing.join()
    assert (state.children, state.continued) == (0, [])

    @fx.gen
    def second():
        client = (yield from ClosingTargetCaller.client())("1")
        return (yield from _advance_until(client.call(IdPayload(id="call")).exit()))

    exit = yield from fx.scoped(second).pipe(
        fx.provide(
            _restart_sharding(
                fx.layer.merge(_closing_target_caller_layer(state), _closing_target_layer(state)),
                storage,
                preemptive_shutdown=preemptive_shutdown,
            )
        )
    )
    assert exit == Exit.succeed("child")
    assert (state.children, state.continued) == (1, ["child"])
