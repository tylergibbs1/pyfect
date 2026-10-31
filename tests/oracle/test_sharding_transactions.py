"""Ports of the ``WithTransaction`` cases of Effect's
``test/cluster/Sharding.test.ts`` and of "reprocesses a completed volatile
request id without MessageStorage", which need storages Effect builds in
the test file (``RollbackMemoryStorage`` and ``Layer.updateService`` over the
memory storage). Each test's docstring is the Effect test title."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never

import pyfect as fx
from pyfect import exit as Exit
from pyfect import testing
from pyfect.clock import Clock
from pyfect.cluster import (
    message_storage,
    sharding,
    snowflake,
)
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.envelope import make_request
from pyfect.cluster.message import OutgoingRequest
from pyfect.cluster.message_storage import (
    MemoryEncoded,
    MemoryTransaction,
    MessageStorage,
    MessageStorageService,
    make_encoded,
)
from pyfect.cluster.reply import Encoded as ReplyEncoded
from pyfect.cluster.reply import ReplyWithContext
from pyfect.cluster.snowflake import Snowflake
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.latch import Latch
from pyfect.layer import Layer

from . import _cluster_entities as entities
from ._cluster_entities import (
    BoomError,
    IdKeyPayload,
    TestEntity,
)
from ._sharding_fixtures import test_config, test_sharding_without_storage, update_storage

EntityState = entities.TestEntityState


def _with_storage(storage: Layer[MessageStorage, Never, Any]) -> Layer[Any]:
    return (
        test_sharding_without_storage.pipe(fx.layer.provide(storage))
        .pipe(fx.layer.provide(test_config))
        .pipe(fx.layer.provide(snowflake.layer_generator))
    )


def _updated_memory(
    update: Callable[[MessageStorageService], MessageStorageService],
) -> Layer[MessageStorage, Never, Any]:
    """The memory storage passed through ``update`` (Effect's
    ``Layer.updateService`` over ``MessageStorage.layerMemory``)."""
    return update_storage(update).pipe(fx.layer.provide(message_storage.layer_memory))


type Wrap = Callable[[fx.Effect[Any, Any, Any], int], fx.Effect[Any, Any, Any]]


class _RollbackEncoded(MemoryEncoded):
    """Memory storage that discards replies saved inside a failed
    transaction, like a SQL rollback. ``wrap`` runs around each transaction
    with its 1-based attempt."""

    def __init__(self, clock: Any, wrap: Wrap) -> None:
        super().__init__(clock)
        self._wrap = wrap
        self._attempts = 0
        self._saved: list[Snowflake] = []

    def with_transaction[A, E, R](self, effect: fx.Effect[A, E, R], /) -> fx.Effect[A, E, R]:
        def attempt() -> fx.Effect[A, E, R]:
            self._attempts += 1
            return self._wrap(
                super(_RollbackEncoded, self).with_transaction(effect), self._attempts
            )

        def settle(exit: Exit.Exit[A, E]) -> fx.Effect[None]:
            rolled_back, self._saved = self._saved, []
            if isinstance(exit, Exit.Success):
                return fx.void
            return fx.for_each(rolled_back, lambda id_: self.clear_replies(id_).or_die()).as_void()

        return fx.suspend(attempt).on_exit(settle)

    def save_reply(self, reply: ReplyEncoded, /) -> fx.Effect[None, Any]:
        def save(in_transaction: bool) -> fx.Effect[None, Any]:
            if in_transaction:
                self._saved.append(Snowflake(int(reply["requestId"])))
            return super(_RollbackEncoded, self).save_reply(reply)

        return MemoryTransaction().flat_map(save)


def _rollback_memory_storage(wrap: Wrap) -> Layer[MessageStorage, Never, Any]:
    @fx.gen
    def make():
        clock = yield from Clock()
        return (yield from make_encoded(_RollbackEncoded(clock, wrap)))

    return fx.layer.effect(MessageStorage, make).pipe(fx.layer.provide(snowflake.layer_generator))


@testing.effect
def test_reprocesses_a_completed_volatile_request_id_without_message_storage():
    """reprocesses a completed volatile request id without MessageStorage"""

    @fx.gen
    def body():
        yield from testing.adjust(0.001)
        service = yield from sharding.Sharding()
        state = yield from EntityState()
        rpc = TestEntity.rpcs["GetUserVolatile"]
        entity_id = EntityId("1")
        request_id = yield from service.get_snowflake

        @fx.gen
        def send():
            replied = yield from Deferred[None, Never].make()
            yield from service.send_outgoing(
                OutgoingRequest(
                    envelope=make_request(
                        request_id=request_id,
                        address=EntityAddress(
                            shard_id=service.get_shard_id(entity_id, "default"),
                            entity_type=TestEntity.type,
                            entity_id=entity_id,
                        ),
                        tag="GetUserVolatile",
                        payload={"id": 1},
                    ),
                    annotations=rpc.annotations,
                    context=Context.empty(),
                    rpc=rpc,
                    last_received_reply=None,
                    respond=lambda _: replied.succeed(None).as_void(),
                ),
                False,
            )
            yield from replied.wait()

        yield from send
        assert state.envelopes.size_unsafe() == 1
        yield from send
        assert state.envelopes.size_unsafe() == 2

    yield from body.pipe(
        fx.provide(
            test_sharding_without_storage.pipe(fx.layer.provide(message_storage.layer_noop)).pipe(
                fx.layer.provide(snowflake.layer_generator)
            )
        )
    )


@testing.effect
def test_with_transaction_is_propagated_to_the_entity_handler():
    """WithTransaction is propagated to the entity handler"""
    flags = {"is_transaction": False, "transaction_open": False}

    class _Observed(MessageStorageService):
        def with_transaction[A, E, R](self, effect: fx.Effect[A, E, R], /) -> fx.Effect[A, E, R]:
            def open_() -> fx.Effect[A, E, R]:
                flags["transaction_open"] = True
                return super(_Observed, self).with_transaction(effect)

            def close() -> None:
                flags["transaction_open"] = False

            return fx.suspend(open_).ensuring(fx.sync(close))

        def save_reply(self, reply: ReplyWithContext, /) -> Any:
            def save(is_transaction: bool) -> Any:
                flags["is_transaction"] = is_transaction
                assert flags["transaction_open"]
                return super(_Observed, self).save_reply(reply)

            return MemoryTransaction().flat_map(save)

    @fx.gen
    def body():
        make_client = yield from TestEntity.client()
        yield from testing.adjust(0.001)
        client = make_client("1")
        result = yield from client.with_transaction({"id": 1})
        assert result is True
        assert flags["is_transaction"] is True

    yield from body.pipe(
        fx.provide(_with_storage(_updated_memory(lambda storage: _Observed(storage.base))))
    )


@testing.effect
def test_with_transaction_persists_a_failure_reply_after_rollback():
    """WithTransaction persists a failure reply after rollback"""

    class _RollingBack(MessageStorageService):
        """Replies saved inside a failed transaction are discarded, like a
        SQL rollback."""

        saved: list[Snowflake]

        def with_transaction[A, E, R](self, effect: fx.Effect[A, E, R], /) -> fx.Effect[A, E, R]:
            def settle(exit: Exit.Exit[A, E]) -> fx.Effect[None]:
                rolled_back, self.saved = self.saved, []
                if isinstance(exit, Exit.Success):
                    return fx.void
                return fx.for_each(
                    rolled_back, lambda id_: self.clear_replies(id_).or_die()
                ).as_void()

            return super().with_transaction(effect).on_exit(settle)

        def save_reply(self, reply: ReplyWithContext, /) -> Any:
            def save(in_transaction: bool) -> Any:
                if in_transaction:
                    self.saved.append(reply.reply.request_id)
                return super(_RollingBack, self).save_reply(reply)

            return MemoryTransaction().flat_map(save)

    def rolling_back(storage: MessageStorageService) -> MessageStorageService:
        wrapped = _RollingBack(storage.base)
        wrapped.saved = []
        return wrapped

    @fx.gen
    def body():
        state = yield from EntityState()
        make_client = yield from TestEntity.client()
        yield from testing.adjust(0.001)
        client = make_client("1")
        first = yield from client.fail_with_transaction(IdKeyPayload(id=1)).flip()
        assert isinstance(first, BoomError)

        # The retry must be answered from storage without rerunning the handler.
        retry = yield from client.fail_with_transaction(IdKeyPayload(id=1)).flip().timeout(5).fork()
        yield from testing.adjust(5)
        second = yield from retry.join()
        assert isinstance(second, BoomError)
        assert state.envelopes.size_unsafe() == 1

    yield from body.pipe(fx.provide(_with_storage(_updated_memory(rolling_back))))


@testing.effect
def test_with_transaction_delivers_a_success_only_after_commit():
    """WithTransaction delivers a success only after commit"""
    committing = Latch()
    commit = Latch()

    def wrap(transaction: fx.Effect[Any, Any, Any], _attempt: int) -> fx.Effect[Any, Any, Any]:
        return transaction.tap(lambda _: committing.open().and_then(commit.wait()))

    @fx.gen
    def body():
        make_client = yield from TestEntity.client()
        yield from testing.adjust(0.001)
        result = yield from make_client("1").with_transaction({"id": 1}).fork()
        yield from committing.wait()
        yield from testing.adjust(1)
        assert result.poll_unsafe() is None
        yield from commit.open()
        assert (yield from result.join()) is True

    yield from body.pipe(fx.provide(_with_storage(_rollback_memory_storage(wrap))))


@testing.effect
def test_with_transaction_replays_the_request_without_replying_when_commit_dies():
    """WithTransaction replays the request without replying when COMMIT dies"""

    def wrap(transaction: fx.Effect[Any, Any, Any], attempt: int) -> fx.Effect[Any, Any, Any]:
        if attempt == 1:
            return transaction.and_then(fx.die(RuntimeError("COMMIT failed")))
        return transaction

    @fx.gen
    def body():
        state = yield from EntityState()
        make_client = yield from TestEntity.client()
        yield from testing.adjust(0.001)
        # Count handler runs when the reply arrives: only the replay may reply.
        result = yield from (
            make_client("1")
            .with_transaction({"id": 1})
            .map(lambda value: (value, state.envelopes.size_unsafe()))
            .fork()
        )
        yield from testing.adjust(5)
        assert (yield from result.join()) == (True, 2)

    yield from body.pipe(fx.provide(_with_storage(_rollback_memory_storage(wrap))))


@testing.effect
def test_with_transaction_replays_the_request_without_replying_when_rollback_dies():
    """WithTransaction replays the request without replying when ROLLBACK dies"""

    def wrap(transaction: fx.Effect[Any, Any, Any], attempt: int) -> fx.Effect[Any, Any, Any]:
        if attempt == 1:
            return transaction.catch_cause(lambda _: fx.die(RuntimeError("ROLLBACK failed")))
        return transaction

    @fx.gen
    def body():
        state = yield from EntityState()
        make_client = yield from TestEntity.client()
        yield from testing.adjust(0.001)
        # Count handler runs when the reply arrives: only the replay may reply.
        result = yield from (
            make_client("1")
            .fail_with_transaction(IdKeyPayload(id=1))
            .flip()
            .map(lambda error: (type(error).__name__, state.envelopes.size_unsafe()))
            .fork()
        )
        yield from testing.adjust(5)
        assert (yield from result.join()) == ("BoomError", 2)

    yield from body.pipe(fx.provide(_with_storage(_rollback_memory_storage(wrap))))
