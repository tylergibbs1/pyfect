"""Ports of the "Sharding claim release regressions" cases of Effect's
``test/cluster/Sharding.test.ts``. Each test's docstring is the Effect test
title. They run over ``CappedSharding`` with a storage that records which
requests a read claims and which claims are released."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never

import pyfect as fx
from pyfect import schedule, testing
from pyfect.cluster import sharding
from pyfect.cluster.cluster_error import PersistenceError
from pyfect.cluster.cluster_schema import Persisted, Uninterruptible
from pyfect.cluster.entity import Entity, EntityHandlers
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.message import IncomingRequest, OutgoingEnvelope
from pyfect.cluster.message_storage import MemoryDriver, MessageStorageService
from pyfect.cluster.snowflake import Snowflake
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.duration import Seconds
from pyfect.layer import Layer
from pyfect.queue import Queue
from pyfect.rpc import fork
from pyfect.rpc import make as make_rpc

from . import _cluster_entities as entities
from ._cluster_entities import KeyPayload, TestEntity
from ._sharding_fixtures import capped, patched, save_get_user_request

EntityState = entities.TestEntityState

_TEN_MINUTES = 600


class _ClaimLog:
    """The claims a storage read takes and the claims released, by request id."""

    def __init__(self) -> None:
        self.claimed: list[Snowflake] = []
        self.released: list[Snowflake] = []

    def clear(self) -> None:
        self.claimed.clear()
        self.released.clear()

    def storage(self, storage: MessageStorageService, **extra: Any) -> MessageStorageService:
        def reset_requests(ids: Any) -> fx.Effect[None, PersistenceError]:
            self.released.extend(ids)
            return storage.reset_requests(ids)

        def record(messages: list[Any]) -> None:
            for message in messages:
                if isinstance(message, IncomingRequest):
                    self.claimed.append(message.envelope.request_id)

        def unprocessed(shard_ids: Any, **options: Any) -> Any:
            return storage.unprocessed_messages(shard_ids, **options).tap(
                lambda messages: fx.sync(lambda: record(messages))
            )

        return patched(
            storage, reset_requests=reset_requests, unprocessed_messages=unprocessed, **extra
        )


def _poll_three_times(service: sharding.ShardingService) -> fx.Effect[None]:
    @fx.gen
    def run():
        for _ in range(3):
            yield from service.poll_storage
            yield from testing.adjust("1 millis")

    return run


def _with_claims(log: _ClaimLog, **extra: Any) -> Layer[Any]:
    return capped(
        lambda storage: log.storage(storage, **extra), refresh_assignments_interval=Seconds(60)
    )


class ClaimDefectReplay(
    Entity, type="ClaimDefectReplay", rpc_annotations=Context.make(Persisted, True)
):
    run = make_rpc("Run")
    defect = make_rpc("Defect")


@testing.effect
def test_keeps_the_claim_of_an_active_request_replayed_after_an_entity_defect():
    """keeps the claim of an active request replayed after an entity defect"""
    log = _ClaimLog()
    counts = {"starts": 0, "active": 0, "layer_builds": 0, "defect_attempts": 0}
    e = ClaimDefectReplay

    @fx.gen
    def outer():
        started = yield from Queue[int, Never].unbounded()

        def build() -> EntityHandlers[Any, Never]:
            counts["layer_builds"] += 1

            def stop() -> None:
                counts["active"] -= 1

            @fx.gen
            def run_body():
                counts["starts"] += 1
                counts["active"] += 1
                yield from started.offer(counts["starts"])
                return (yield from fx.never)

            def defect() -> fx.Effect[None]:
                counts["defect_attempts"] += 1
                if counts["defect_attempts"] == 1:
                    return fx.die(RuntimeError("restart entity"))
                return fx.void

            return (
                e.handlers()
                .handle(e.run)(lambda _: fork(run_body.ensuring(fx.sync(stop))))
                .handle(e.defect)(lambda _: fx.suspend(defect))
            )

        entity_layer: Layer[Never, Never, Any] = e.to_layer_effect(
            fx.sync(build), defect_retry_policy=schedule.forever
        )
        layer = entity_layer.pipe(fx.layer.provide_merge(_with_claims(log)))

        @fx.gen
        def body():
            yield from testing.adjust("1 millis")
            service = yield from sharding.Sharding()
            driver = yield from MemoryDriver()
            client = (yield from e.client())("replay")
            running = yield from client.run().fork(start_immediately=True)
            yield from testing.adjust("1 millis")
            assert (yield from started.take()) == 1
            request: Any = driver.encoded.journal[0]
            assert request["_tag"] == "Request"

            # Defecting another handler rebuilds the entity and replays Run.
            yield from client.defect()
            assert (yield from started.take()) == 2, (
                "in-flight handler must replay after the defect"
            )
            assert counts["layer_builds"] == 2
            assert counts["defect_attempts"] == 2
            assert counts["active"] == 1
            assert running.poll_unsafe() is None
            log.clear()

            yield from testing.adjust(Seconds(_TEN_MINUTES))
            yield from _poll_three_times(service)
            request_id = Snowflake(int(request["requestId"]))
            assert request_id in log.claimed
            assert counts["starts"] == 2, "polling must not deliver the replayed request again"
            assert counts["layer_builds"] == 2, "polling must not restart the entity again"
            assert counts["active"] == 1, "replayed handler must remain active"
            assert running.poll_unsafe() is None
            assert log.released == [], "replayed active request claim must not be released"
            assert log.claimed == [request_id], (
                "replayed request must not be reclaimed on every poll"
            )

        yield from body.pipe(fx.provide(layer))

    yield from outer


class ClaimRestart(Entity, type="ClaimRestart"):
    run = make_rpc("Run").annotate(Persisted, True).annotate(Uninterruptible, True)


@testing.effect
def test_keeps_the_claim_of_an_active_uninterruptible_request_after_restarting():
    """keeps the claim of an active uninterruptible request after restarting"""
    log = _ClaimLog()
    counts = {"starts": 0, "active": 0}
    e = ClaimRestart

    @fx.gen
    def outer():
        started = yield from Queue[int, Never].unbounded()

        def stop() -> None:
            counts["active"] -= 1

        @fx.gen
        def run_body():
            counts["starts"] += 1
            counts["active"] += 1
            yield from started.offer(counts["starts"])
            return (yield from fx.never)

        layer = e.to_layer(
            e.handlers().handle(e.run)(lambda _: run_body.ensuring(fx.sync(stop)))
        ).pipe(fx.layer.provide_merge(_with_claims(log)))

        @fx.gen
        def body():
            yield from testing.adjust("1 millis")
            service = yield from sharding.Sharding()
            driver = yield from MemoryDriver()
            client = (yield from e.client())("restart")
            running = yield from client.run().fork(start_immediately=True)
            assert (yield from started.take()) == 1
            request: Any = driver.encoded.journal[0]
            assert request["_tag"] == "Request"

            # A persisted interrupt restarts the uninterruptible request.
            interrupt: Any = {
                "_tag": "Interrupt",
                "id": str((yield from service.get_snowflake)),
                "requestId": request["requestId"],
                "address": request["address"],
            }
            yield from driver.encoded.save_envelope(interrupt, None, None)
            yield from service.poll_storage
            yield from testing.adjust("1 millis")
            assert (yield from started.take()) == 2, (
                "handler must restart after the stored interrupt"
            )
            assert counts["active"] == 1
            assert running.poll_unsafe() is None
            log.clear()

            yield from testing.adjust(Seconds(_TEN_MINUTES))
            yield from _poll_three_times(service)
            request_id = Snowflake(int(request["requestId"]))
            assert request_id in log.claimed
            assert counts["starts"] == 2, "polling must not deliver the restarted request again"
            assert counts["active"] == 1, "restarted handler must remain active"
            assert running.poll_unsafe() is None
            assert log.released == [], "restarted active request claim must not be released"
            assert log.claimed == [request_id], (
                "restarted request must not be reclaimed on every poll"
            )

        yield from body.pipe(fx.provide(layer))

    yield from outer


@testing.effect
def test_keeps_the_claim_of_an_active_stream_after_an_acknowledged_chunk():
    """keeps the claim of an active stream after an acknowledged chunk"""
    log = _ClaimLog()
    acked = Deferred[None, Never]()

    def save_envelope_of(storage: MessageStorageService) -> Callable[[OutgoingEnvelope], Any]:
        def save_envelope(message: OutgoingEnvelope) -> Any:
            def after(_: object) -> fx.Effect[Any]:
                if type(message.envelope).__name__ == "AckChunk":
                    return acked.succeed(None)
                return fx.void

            return storage.save_envelope(message).tap(after)

        return save_envelope

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        service = yield from sharding.Sharding()
        state = yield from EntityState()
        client = (yield from TestEntity.client())("active-stream")
        values: list[int] = []

        def push(value: int) -> fx.Effect[None]:
            return fx.sync(lambda: values.append(value))

        running = yield from (
            client.stream_with_key(KeyPayload(key="run"))
            .run_for_each(push)
            .fork(start_immediately=True)
        )
        yield from state.stream_messages.offer(None)
        yield from testing.adjust("1 second")
        yield from acked.wait()
        assert values == [0]
        assert running.poll_unsafe() is None
        log.clear()

        # Await the ack because memory storage does not model SQL reply filtering.
        yield from testing.adjust(Seconds(_TEN_MINUTES))
        yield from _poll_three_times(service)
        assert len(log.claimed) > 0
        assert running.poll_unsafe() is None
        assert values == [0]
        assert log.released == [], "active stream claim must not be released after a chunk"
        assert len(log.claimed) == 1, "active stream must not be reclaimed on every poll"

    def transform(storage: MessageStorageService) -> MessageStorageService:
        return log.storage(storage, save_envelope=save_envelope_of(storage))

    yield from body.pipe(fx.provide(capped(transform, refresh_assignments_interval=Seconds(60))))


class _PausedRead:
    """Pauses the next storage read until ``release`` completes."""

    def __init__(self) -> None:
        self.pause_next = False
        self.started = Deferred[None, Never]()
        self.release = Deferred[None, Never]()

    def wrap(self, read: fx.Effect[Any, Any, Any]) -> fx.Effect[Any, Any, Any]:
        @fx.gen
        def run():
            if self.pause_next:
                self.pause_next = False
                yield from self.started.succeed(None)
                yield from self.release.wait()
            return (yield from read)

        return run


@testing.effect
def test_releases_capped_addresses_even_when_targeted_claim_release_fails():
    """releases capped addresses even when targeted claim release fails"""
    paused = _PausedRead()
    failed_releases: list[Snowflake] = []
    capped_releases: list[EntityAddress] = []
    claimed: list[str] = []

    def transform(storage: MessageStorageService) -> MessageStorageService:
        def reset_requests(ids: Any) -> fx.Effect[None, PersistenceError]:
            def fail() -> fx.Effect[None, PersistenceError]:
                failed_releases.extend(ids)
                return fx.fail(
                    PersistenceError(cause=RuntimeError("injected targeted release failure"))
                )

            return fx.suspend(fail)

        def reset_addresses(addresses: Any) -> fx.Effect[None, PersistenceError]:
            capped_releases.extend(addresses)
            return storage.reset_addresses(addresses)

        def record(messages: list[Any]) -> list[Any]:
            claimed.extend(m.envelope.address.entity_id for m in messages)
            return messages

        def unprocessed(shard_ids: Any, **options: Any) -> Any:
            return paused.wrap(
                fx.suspend(lambda: storage.unprocessed_messages(shard_ids, **options))
            ).map(record)

        return patched(
            storage,
            reset_requests=reset_requests,
            reset_addresses=reset_addresses,
            unprocessed_messages=unprocessed,
        )

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        service = yield from sharding.Sharding()
        state = yield from EntityState()
        client = yield from TestEntity.client()
        first_run = (
            yield from client("completed")
            .request_with_key(KeyPayload(key="run"))
            .fork(start_immediately=True)
        )
        request = yield from state.envelopes.take()
        paused.pause_next = True
        yield from service.poll_storage
        yield from paused.started.wait()
        yield from state.messages.offer(None)
        yield from first_run.join()
        yield from testing.adjust("1 millis")
        yield from service.reset(request.request_id)
        yield from save_get_user_request("capped", 42)

        # Fill capacity during the read so its batch also contains a capped address.
        yield from client("resident").never_volatile().fork(start_immediately=True)
        yield from state.envelopes.take()
        assert (yield from service.active_entity_count) == 2
        yield from paused.release.succeed(None)
        yield from testing.adjust("1 millis")
        assert "completed" in claimed
        assert "capped" in claimed
        assert failed_releases == [request.request_id]
        assert [address.entity_id for address in capped_releases] == ["capped"], (
            "failed targeted release must not skip capped-address release from the same batch"
        )

    yield from body.pipe(fx.provide(capped(transform, max_resident_entities=2)))


@testing.effect
def test_redelivers_a_request_reset_while_an_asynchronous_storage_read_is_pending():
    """redelivers a request reset while an asynchronous storage read is pending"""
    paused = _PausedRead()
    claimed: list[Snowflake] = []

    def transform(storage: MessageStorageService) -> MessageStorageService:
        def record(messages: list[Any]) -> list[Any]:
            claimed.extend(m.envelope.request_id for m in messages)
            return messages

        def unprocessed(shard_ids: Any, **options: Any) -> Any:
            return paused.wrap(
                fx.suspend(lambda: storage.unprocessed_messages(shard_ids, **options))
            ).map(record)

        return patched(storage, unprocessed_messages=unprocessed)

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        service = yield from sharding.Sharding()
        state = yield from EntityState()
        client = (yield from TestEntity.client())("reset-race")
        first_run = yield from client.request_with_key(KeyPayload(key="run")).fork(
            start_immediately=True
        )
        request = yield from state.envelopes.take()

        # Pause after clearing processed IDs but before storage claims rows.
        paused.pause_next = True
        yield from service.poll_storage
        yield from paused.started.wait()

        # Complete the request while the read is paused.
        yield from state.messages.offer(None)
        yield from first_run.join()
        yield from testing.adjust("1 millis")
        assert (yield from service.reset(request.request_id))
        yield from service.poll_storage
        claimed.clear()

        # The reset must be redelivered before its new claim expires.
        yield from paused.release.succeed(None)
        yield from testing.adjust("5 seconds")
        assert request.request_id in claimed
        deliveries_before_claim_expiry = state.envelopes.size_unsafe()

        yield from testing.adjust(Seconds(_TEN_MINUTES))
        assert state.envelopes.size_unsafe() == 1
        assert deliveries_before_claim_expiry == 1, (
            "reset request was claimed but not redelivered before claim expiry"
        )

    yield from body.pipe(fx.provide(capped(transform, refresh_assignments_interval=Seconds(60))))
