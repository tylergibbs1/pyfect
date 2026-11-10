"""``runners.make`` at its boundary, past Effect's ``Runners.test.ts``
(``tests/oracle/test_runners.py``): a duplicate persisted request runs under
its original id, and the caller still sees its own."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, cast

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import envelope, sharding_config, snowflake
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.message import IncomingLocal, OutgoingEnvelope, OutgoingRequest
from pyfect.cluster.message_storage import (
    MessageStorage,
    MessageStorageService,
    SaveDuplicate,
    SaveResult,
    StorageBase,
    layer_memory,
)
from pyfect.cluster.reply import Reply, ReplyWithContext, WithExit
from pyfect.cluster.runners import Runners
from pyfect.cluster.runners import layer_noop as runners_layer_noop
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.snowflake import Snowflake
from pyfect.context import Context
from pyfect.layer import Layer
from pyfect.rpc import make as make_rpc
from pyfect.scope import fork_scoped

Persistent = make_rpc("Persistent", success=S.Int).annotate(Persisted, True)

_ADDRESS = EntityAddress(
    shard_id=ShardId(group="default", id=1),
    entity_type=EntityType("Persistent"),
    entity_id=EntityId("1"),
)


class _Duplicating:
    """A storage base that saves each request as a duplicate of
    ``original_id`` and records the envelopes it saves."""

    def __init__(self, base: StorageBase, original_id: Snowflake) -> None:
        self.base = base
        self.original_id = original_id
        self.envelopes: list[OutgoingEnvelope] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)

    def save_request(self, _: OutgoingRequest) -> fx.Effect[SaveResult, Any]:
        return fx.succeed(SaveDuplicate(original_id=self.original_id, last_received_reply=None))

    def save_envelope(self, message: OutgoingEnvelope) -> fx.Effect[None, Any]:
        self.envelopes.append(message)
        return fx.void


def _layer(original_id: Snowflake) -> Layer[Runners | MessageStorage]:
    def wrap(storage: MessageStorageService) -> MessageStorageService:
        return MessageStorageService(cast("StorageBase", _Duplicating(storage.base, original_id)))

    wrapped = fx.layer.effect(MessageStorage, MessageStorage().map(wrap)).pipe(
        fx.layer.provide(layer_memory)
    )
    config = replace(sharding_config.DEFAULTS, entity_reply_poll_interval=fx.duration.Duration(1))
    return (
        runners_layer_noop.pipe(fx.layer.provide_merge(wrapped))
        .pipe(fx.layer.provide(snowflake.layer_generator))
        .pipe(fx.layer.provide(sharding_config.layer(config)))
    )


def _no_notify(_: IncomingLocal) -> fx.Effect[None]:
    return fx.void


@testing.effect
def test_a_duplicate_request_runs_under_its_original_id():
    ids = snowflake.make_generator()
    generator = yield from ids
    original_id = generator.next_unsafe()
    duplicate_id = generator.next_unsafe()
    replies: list[Reply] = []

    def record(reply: Reply) -> fx.Effect[None]:
        return fx.sync(lambda: replies.append(reply))

    request = OutgoingRequest(
        envelope=envelope.make_request(
            request_id=duplicate_id, address=_ADDRESS, tag=Persistent.tag, payload=None
        ),
        rpc=Persistent,
        context=Context.empty(),
        last_received_reply=None,
        respond=record,
        annotations=Context.empty(),
    )

    @fx.gen
    def body():
        runners = yield from Runners()
        storage = yield from MessageStorage()
        duplicating = cast("_Duplicating", storage.base)
        original = replace(request, envelope=request.envelope.with_request_id(original_id))
        yield from duplicating.base.save_request(original)
        pending = yield from fork_scoped(
            runners.notify_local(request, notify=_no_notify, discard=False)
        )
        yield from testing.adjust(0)
        interrupt = OutgoingEnvelope(
            envelope=envelope.Interrupt(
                id=generator.next_unsafe(), address=_ADDRESS, request_id=duplicate_id
            ),
            rpc=Persistent,
        )
        yield from runners.notify_local(interrupt, notify=_no_notify, discard=False)
        [saved] = duplicating.envelopes
        assert saved.envelope.request_id == original_id, "an envelope follows the original id"

        reply = WithExit(request_id=original_id, id=generator.next_unsafe(), exit=Exit.succeed(1))
        yield from storage.save_reply(ReplyWithContext(reply, Context.empty(), Persistent))
        yield from testing.adjust("1 second")
        yield from pending.join()
        [answered] = replies
        assert isinstance(answered, WithExit)
        assert answered.request_id == duplicate_id, "the caller sees its own request id"

    yield from body.pipe(fx.provide(_layer(original_id)))
