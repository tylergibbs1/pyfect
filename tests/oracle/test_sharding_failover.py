"""Ports of the "Sharding shard lock failover" cases of Effect's
``test/cluster/Sharding.test.ts`` (and the active-teardown case that
releases a shard through the same runner storage fake), over Effect's
``FailoverStorage`` (``_failover_storage``). Each test's docstring is the
Effect test title. The rest of this group is in
``test_sharding_forced_release``."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import replace
from typing import Any, Never

import pyfect as fx
from pyfect import exit as Exit
from pyfect import stream, testing
from pyfect.cluster import (
    cluster_metrics,
    message_storage,
    runner_health,
    runners,
    sharding,
    sharding_config,
    snowflake,
)
from pyfect.cluster.cluster_error import PersistenceError
from pyfect.cluster.cluster_schema import InterruptOnTermination, Persisted, Uninterruptible
from pyfect.cluster.entity import Entity
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.message_storage import MemoryDriver
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runner_storage import RunnerStorageService
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.shard_id import make as shard
from pyfect.cluster.snowflake import Snowflake
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.duration import millis
from pyfect.layer import Layer
from pyfect.logger import LogLevel
from pyfect.queue import Queue
from pyfect.rpc import make as make_rpc

from . import _cluster_entities as entities
from ._cluster_entities import (
    KeyPayload,
    TestEntity,
    User,
    test_entity_no_state,
    test_entity_state_layer,
)
from ._failover_storage import FailoverState, failover_storage_layer
from .test_sharding_active_teardowns import ActiveTeardownCaller, active_teardown_caller_layer

EntityState = entities.TestEntityState

_runner_address = RunnerAddress(host="localhost", port=1234)


def _config(**changes: Any) -> Layer[sharding_config.ShardingConfig]:
    return sharding_config.layer(
        replace(sharding_config.DEFAULTS, runner_address=_runner_address, **changes)
    )


def _sharding_over(
    storage: Layer[Any], config: Layer[sharding_config.ShardingConfig]
) -> Layer[Any]:
    return (
        sharding.layer.pipe(fx.layer.provide(storage))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide(message_storage.layer_memory))
        .pipe(fx.layer.provide(snowflake.layer_generator))
        .pipe(fx.layer.provide(config))
    )


@testing.effect
def test_interrupts_entities_and_reacquires_shards_after_lock_storage_recovers():
    """interrupts entities and reacquires shards after lock storage recovers"""
    warnings: list[Any] = []

    def log(options: Any) -> None:
        if options.log_level == LogLevel.WARN:
            warnings.append(options.message)

    state = FailoverState()
    layer = (
        test_entity_no_state.pipe(fx.layer.provide_merge(sharding.layer))
        .pipe(fx.layer.provide(failover_storage_layer(state)))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide_merge(test_entity_state_layer))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide(message_storage.layer_memory))
        .pipe(fx.layer.provide(snowflake.layer_generator))
        .pipe(
            fx.layer.provide(
                _config(
                    shards_per_group=1,
                    shard_lock_expiration=millis(300),
                    shard_lock_refresh_interval=millis(1000),
                    entity_termination_timeout=millis(30_000),
                    entity_message_poll_interval=millis(10),
                    refresh_assignments_interval=millis(10),
                    send_retry_interval=millis(10),
                )
            )
        )
    )

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        entity_state = yield from EntityState()
        make_client = yield from TestEntity.client()
        client = make_client("1")
        shard_id = service.get_shard_id(EntityId("1"), "default")

        while not service.has_shard_id(shard_id):
            yield from testing.adjust("10 millis")
        while not any(call.shards for call in state.refresh_calls):
            yield from testing.adjust("100 millis")

        entity_fiber = yield from client.never_volatile().fork(start_immediately=True)
        yield from testing.adjust("1 millis")
        assert entity_state.envelopes.size_unsafe() == 1

        acquire_count = len(state.acquire_calls)
        partitioned_at = yield from fx.clock.current_time_millis()
        state.blackholed = True

        yield from testing.adjust("201 millis")

        assert not service.has_shard_id(shard_id)
        assert not (yield from service.is_shutdown)
        entity_exit = entity_fiber.poll_unsafe()
        assert isinstance(entity_exit, Exit.Failure) and entity_exit.cause.has_interrupts
        assert cluster_metrics.shards.value_unsafe(Context.empty()).value == 0

        failed_refreshes = [
            call for call in state.refresh_calls if call.at >= partitioned_at and call.shards
        ]
        assert len(failed_refreshes) <= 2

        yield from testing.adjust("1 second")
        assert len(state.acquire_calls) == acquire_count
        assert any(call.at >= partitioned_at and not call.shards for call in state.refresh_calls)
        assert all(
            not call.shards for call in state.refresh_calls if call.at >= partitioned_at + 200
        )

        state.blackholed = False
        yield from testing.adjust("101 millis")
        while not service.has_shard_id(shard_id):
            yield from testing.adjust("10 millis")

        assert len(state.acquire_calls) > acquire_count
        assert any(s.id == shard_id.id for s in state.acquire_calls[-1].shards)
        assert (yield from client.get_user_volatile({"id": 2})) == User(id=2, name="User 2")
        assert entity_state.envelopes.size_unsafe() == 2
        assert any(
            isinstance(message, (list, tuple))
            and "Shard lock storage is still unhealthy" in message
            for message in warnings
        )

    yield from fx.scoped(body).pipe(fx.provide(layer)).with_logger(fx.Logger.make(log))


@testing.effect
def test_keeps_shards_acquired_while_an_earlier_lock_refresh_is_in_flight():
    """keeps shards acquired while an earlier lock refresh is in flight"""
    state = FailoverState()
    acquire_started = Deferred[None, Never]()
    refresh_started = Deferred[None, Never]()
    acquire_done = Deferred[None, Never]()

    def update(storage: RunnerStorageService) -> RunnerStorageService:
        @fx.fn
        def acquire(address: RunnerAddress, shard_ids: Iterable[ShardId]):
            if (yield from acquire_done.is_done()):
                return (yield from storage.acquire(address, shard_ids))
            yield from acquire_started.succeed(None)
            yield from refresh_started.wait()
            acquired = yield from storage.acquire(address, shard_ids)
            yield from acquire_done.succeed(None)
            return acquired

        @fx.fn
        def refresh(address: RunnerAddress, shard_ids: Iterable[ShardId]):
            shards = list(shard_ids)
            if (yield from acquire_started.is_done()) and not (yield from acquire_done.is_done()):
                assert shards == []
                yield from refresh_started.succeed(None)
                yield from acquire_done.wait()
            return (yield from storage.refresh(address, shards))

        return replace(storage, acquire=acquire, refresh=refresh)

    layer = _sharding_over(
        failover_storage_layer(state, update),
        _config(
            shards_per_group=1,
            shard_lock_expiration=millis(3000),
            shard_lock_refresh_interval=millis(100),
            entity_termination_timeout=millis(0),
            refresh_assignments_interval=millis(10),
        ),
    )

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        shard_id = shard("default", 1)
        yield from testing.adjust("100 millis")
        assert (yield from acquire_done.is_done())
        assert service.has_shard_id(shard_id)
        yield from testing.adjust("500 millis")
        assert service.has_shard_id(shard_id), "shard acquired during the refresh was dropped"
        assert state.release_calls == []
        assert len(state.acquire_calls) == 1

    yield from body.pipe(fx.provide(layer))


@testing.effect
def test_releases_a_lost_requested_shard_without_dropping_a_shard_acquired_during_refresh():
    """releases a lost requested shard without dropping a shard acquired during refresh"""
    state = FailoverState()
    first_shard = shard("default", 1)
    second_shard = shard("default", 2)
    refresh_started = Deferred[None, Never]()
    refresh_response = Deferred[None, Never]()
    counts = {"acquire": 0, "lost": 0}

    def update(storage: RunnerStorageService) -> RunnerStorageService:
        @fx.fn
        def acquire(address: RunnerAddress, shard_ids: Iterable[ShardId]):
            counts["acquire"] += 1
            if counts["acquire"] == 1:
                return (yield from storage.acquire(address, [first_shard]))
            if counts["acquire"] == 2:
                yield from refresh_started.wait()
            return (
                yield from storage.acquire(
                    address, [s for s in shard_ids if s.id != first_shard.id]
                )
            )

        @fx.fn
        def refresh(address: RunnerAddress, shard_ids: Iterable[ShardId]):
            shards = list(shard_ids)
            if not counts["lost"] and shards:
                counts["lost"] = 1
                assert shards == [first_shard]
                yield from refresh_started.succeed(None)
                yield from refresh_response.wait()
                lost: list[ShardId] = []
                return lost
            return (yield from storage.refresh(address, shards))

        return replace(storage, acquire=acquire, refresh=refresh)

    layer = _sharding_over(
        failover_storage_layer(state, update),
        _config(
            shards_per_group=2,
            shard_lock_expiration=millis(30_000),
            shard_lock_refresh_interval=millis(2000),
            entity_termination_timeout=millis(0),
            refresh_assignments_interval=millis(10),
        ),
    )

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        yield from testing.adjust("2 seconds")
        assert (yield from refresh_started.is_done())
        assert service.has_shard_id(first_shard)
        assert service.has_shard_id(second_shard)

        yield from refresh_response.succeed(None)
        yield from testing.adjust("1 millis")
        assert not service.has_shard_id(first_shard)
        assert service.has_shard_id(second_shard)

        yield from testing.adjust("1 second")
        assert not service.has_shard_id(first_shard)
        assert service.has_shard_id(second_shard)
        assert state.release_calls == [first_shard]

    yield from body.pipe(fx.provide(layer))


@testing.effect
def test_swallows_persisted_interrupts_when_the_callers_shard_is_released():
    """swallows persisted interrupts when the caller's shard is released"""
    state = FailoverState()
    layer = (
        fx.layer.merge(active_teardown_caller_layer, test_entity_no_state)
        .pipe(fx.layer.provide_merge(sharding.layer))
        .pipe(fx.layer.provide(failover_storage_layer(state)))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide_merge(test_entity_state_layer))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide_merge(message_storage.layer_memory))
        .pipe(fx.layer.provide(snowflake.layer_generator))
        .pipe(
            fx.layer.provide(
                _config(
                    shards_per_group=1,
                    entity_termination_timeout=millis(0),
                    entity_message_poll_interval=millis(1000),
                    refresh_assignments_interval=millis(1000),
                    send_retry_interval=millis(10),
                )
            )
        )
    )

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        entity_state = yield from EntityState()
        service = yield from sharding.Sharding()
        shard_id = service.get_shard_id(EntityId("1"), "default")
        while not service.has_shard_id(shard_id):
            yield from testing.adjust("10 millis")

        yield from (yield from ActiveTeardownCaller.client())("1").arm()
        yield from testing.adjust("1 millis")
        assert entity_state.envelopes.size_unsafe() == 1

        state.assign_self = False
        # The acquisition loop waits one second between passes. Advance by
        # that interval instead of repeatedly waking 10ms polling loops.
        while service.has_shard_id(shard_id):
            yield from testing.adjust("1 second")
        while (yield from service.active_entity_count) > 0:
            yield from testing.adjust("1 millis")

        interrupts = [e for e in driver.encoded.journal if e["_tag"] == "Interrupt"]
        assert len(interrupts) == 0

    yield from fx.scoped(body).pipe(fx.provide(layer))


@testing.effect
def test_refreshes_a_newly_acquired_shard_when_retrying_a_failed_lock_refresh():
    """refreshes a newly acquired shard when retrying a failed lock refresh"""
    state = FailoverState()
    acquire_started = Deferred[None, Never]()
    refresh_failed = Deferred[None, Never]()
    retry_shards = Deferred[list[ShardId], Never]()

    def update(storage: RunnerStorageService) -> RunnerStorageService:
        @fx.fn
        def acquire(address: RunnerAddress, shard_ids: Iterable[ShardId]):
            yield from acquire_started.succeed(None)
            yield from refresh_failed.wait()
            return (yield from storage.acquire(address, shard_ids))

        @fx.fn
        def refresh(address: RunnerAddress, shard_ids: Iterable[ShardId]):
            shards = list(shard_ids)
            if (yield from refresh_failed.is_done()):
                yield from retry_shards.succeed(shards)
            elif (yield from acquire_started.is_done()):
                assert shards == []
                yield from refresh_failed.succeed(None)
                return (yield from fx.fail(PersistenceError(cause=RuntimeError("refresh failed"))))
            return (yield from storage.refresh(address, shards))

        return replace(storage, acquire=acquire, refresh=refresh)

    layer = _sharding_over(
        failover_storage_layer(state, update),
        _config(
            shards_per_group=1,
            shard_lock_expiration=millis(30_000),
            shard_lock_refresh_interval=millis(1000),
            entity_termination_timeout=millis(0),
            refresh_assignments_interval=millis(10),
        ),
    )

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        shard_id = shard("default", 1)
        yield from testing.adjust("1 second")
        assert (yield from refresh_failed.is_done())
        assert service.has_shard_id(shard_id)
        assert not (yield from retry_shards.is_done())

        yield from testing.adjust("50 millis")
        assert (yield from retry_shards.is_done())
        assert (yield from retry_shards.wait()) == [shard_id]
        assert service.has_shard_id(shard_id)
        assert state.release_calls == []

    yield from body.pipe(fx.provide(layer))


def _entity_sharding(state: FailoverState, **config: Any) -> Layer[Any]:
    return (
        test_entity_no_state.pipe(fx.layer.provide_merge(sharding.layer))
        .pipe(fx.layer.provide(failover_storage_layer(state)))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide_merge(test_entity_state_layer))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide(message_storage.layer_memory))
        .pipe(fx.layer.provide(snowflake.layer_generator))
        .pipe(fx.layer.provide(_config(**config)))
    )


@testing.effect
def test_reacquires_shards_when_the_liveness_probe_succeeds_while_lock_refresh_is_hung():
    """reacquires shards when the liveness probe succeeds while lock refresh is hung"""
    state = FailoverState()
    layer = _entity_sharding(
        state,
        shards_per_group=1,
        shard_lock_expiration=millis(300),
        shard_lock_refresh_interval=millis(1000),
        entity_termination_timeout=millis(30_000),
        entity_message_poll_interval=millis(10),
        refresh_assignments_interval=millis(10),
        send_retry_interval=millis(10),
    )

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        make_client = yield from TestEntity.client()
        client = make_client("1")
        shard_id = service.get_shard_id(EntityId("1"), "default")
        while not service.has_shard_id(shard_id):
            yield from testing.adjust("10 millis")
        while not any(call.shards for call in state.refresh_calls):
            yield from testing.adjust("100 millis")

        acquire_count = len(state.acquire_calls)
        state.blackhole_non_empty_refresh = True
        yield from testing.adjust("201 millis")
        assert not service.has_shard_id(shard_id)

        # recovery only needs the empty liveness probe to succeed
        while not service.has_shard_id(shard_id):
            yield from testing.adjust("10 millis")

        assert len(state.acquire_calls) > acquire_count
        assert any(not call.shards for call in state.refresh_calls)
        assert (yield from client.get_user_volatile({"id": 3})) == User(id=3, name="User 3")

    yield from fx.scoped(body).pipe(fx.provide(layer))


def _termination_sharding(
    entity_layer: Layer[Never, Never, Any], state: FailoverState, **changes: Any
) -> Layer[Any]:
    defaults: dict[str, Any] = {
        "shards_per_group": 1,
        "shard_lock_expiration": millis(3000),
        "shard_lock_refresh_interval": millis(100),
        "entity_termination_timeout": millis(1000),
        "entity_message_poll_interval": millis(10),
        "entity_reply_poll_interval": millis(10),
        "refresh_assignments_interval": millis(10),
        "send_retry_interval": millis(10),
    }
    return (
        entity_layer.pipe(fx.layer.provide_merge(sharding.layer))
        .pipe(fx.layer.provide(failover_storage_layer(state)))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide_merge(message_storage.layer_memory))
        .pipe(fx.layer.provide(snowflake.layer_generator))
        .pipe(fx.layer.provide(_config(**(defaults | changes))))
    )


def _wait_for_termination_ownership(
    service: sharding.ShardingService, owned: bool
) -> fx.Effect[None]:
    @fx.gen
    def run():
        shard_id = shard("default", 1)
        for _ in range(100):
            if service.has_shard_id(shard_id) == owned:
                return
            yield from testing.adjust("10 millis")
        assert service.has_shard_id(shard_id) == owned

    return run


class TerminationStreams(
    Entity, type=TestEntity.type, rpc_annotations=Context.make(InterruptOnTermination, True)
):
    stream_with_key = TestEntity.stream_with_key.annotate(Persisted, False)
    request_with_key = TestEntity.request_with_key.annotate(Persisted, False).annotate(
        Uninterruptible, "server"
    )


@testing.effect
def test_interrupts_opted_in_streams_on_reassignment_but_respects_uninterruptible():
    """interrupts opted-in streams on reassignment but respects Uninterruptible"""
    state = FailoverState()
    e = TerminationStreams

    @fx.gen
    def outer():
        started = yield from Queue[None, Never].unbounded()
        finish = yield from Deferred[None, Never].make()
        entity_layer = e.to_layer(
            e.handlers()
            .handle(e.stream_with_key)(
                lambda _: stream.from_effect(started.offer(None).and_then(fx.never))
            )
            .handle(e.request_with_key)(lambda _: started.offer(None).and_then(finish.wait())),
            concurrency="unbounded",
        )

        @fx.gen
        def body():
            service = yield from sharding.Sharding()
            yield from _wait_for_termination_ownership(service, True)
            # Let the acquisition backoff finish before testing reassignment.
            yield from testing.adjust("1 second")
            client = (yield from e.client())("termination-stream")
            running_stream = yield from (
                client.stream_with_key(KeyPayload(key="run"))
                .run_drain()
                .fork(start_immediately=True)
            )
            protected = yield from client.request_with_key(KeyPayload(key="run")).fork(
                start_immediately=True
            )
            yield from started.take()
            yield from started.take()
            state.assign_self = False
            yield from _wait_for_termination_ownership(service, False)
            yield from testing.adjust("100 millis")
            early_exit = running_stream.poll_unsafe()
            protected_exit = protected.poll_unsafe()
            held = len(state.release_calls) == 0
            yield from finish.succeed(None)
            yield from testing.adjust("100 millis")
            early_releases = list(state.release_calls)
            # Finish a broken implementation's grace period before asserting.
            yield from testing.adjust("1 second")
            assert isinstance(early_exit, Exit.Failure) and early_exit.cause.has_interrupts
            assert protected_exit is None
            assert held
            assert protected.poll_unsafe() == Exit.succeed(None)
            assert early_releases == [shard("default", 1)]

        yield from fx.scoped(body).pipe(fx.provide(_termination_sharding(entity_layer, state)))

    yield from outer


class TerminationPersisted(
    Entity, type=TestEntity.type, rpc_annotations=Context.make(InterruptOnTermination, True)
):
    request_with_key = TestEntity.request_with_key


@testing.effect
def test_resumes_an_opted_in_persisted_request_after_early_shard_release():
    """resumes an opted-in persisted request after early shard release"""
    state = FailoverState()
    e = TerminationPersisted

    @fx.gen
    def outer():
        started = yield from Queue[Snowflake, Never].unbounded()
        finish = yield from Deferred[None, Never].make()
        entity_layer = e.to_layer(
            e.handlers().handle(e.request_with_key)(
                lambda request: started.offer(request.request_id).and_then(finish.wait())
            )
        )

        @fx.gen
        def body():
            service = yield from sharding.Sharding()
            yield from _wait_for_termination_ownership(service, True)
            yield from testing.adjust("1 second")
            client = (yield from e.client())("termination-persisted")
            running = yield from client.request_with_key(KeyPayload(key="run")).fork(
                start_immediately=True
            )
            request_id = yield from started.take()
            state.assign_self = False
            yield from _wait_for_termination_ownership(service, False)
            yield from testing.adjust("100 millis")
            early_releases = list(state.release_calls)
            yield from testing.adjust("1 second")
            assert early_releases == [shard("default", 1)]
            assert running.poll_unsafe() is None

            # A replay with the same ID and successful completion proves
            # termination neither saved a terminal reply nor marked the
            # request processed.
            state.assign_self = True
            yield from _wait_for_termination_ownership(service, True)
            yield from service.poll_storage
            yield from testing.adjust("10 millis")
            assert started.take_unsafe() == Exit.succeed(request_id)
            yield from finish.succeed(None)
            yield from testing.adjust("100 millis")
            assert running.poll_unsafe() == Exit.succeed(None)

        yield from fx.scoped(body).pipe(fx.provide(_termination_sharding(entity_layer, state)))

    yield from outer


class ReleaseDuringRestart(Entity, type="ReleaseDuringRestart"):
    defect = make_rpc("Defect").annotate(Persisted, True)


@testing.effect
def test_releases_a_shard_reassigned_while_a_defected_entity_waits_to_restart():
    """releases a shard reassigned while a defected entity waits to restart"""
    state = FailoverState()
    defected = Deferred[None, Never]()
    attempts = [0]
    e = ReleaseDuringRestart

    def defect(_: Any) -> fx.Effect[None]:
        def run() -> fx.Effect[None]:
            attempts[0] += 1
            if attempts[0] == 1:
                return defected.succeed(None).and_then(fx.die(RuntimeError("boom")))
            return fx.void

        return fx.suspend(run)

    entity_layer = e.to_layer(e.handlers().handle(e.defect)(defect))

    @fx.gen
    def body():
        service = yield from sharding.Sharding()
        yield from _wait_for_termination_ownership(service, True)
        yield from testing.adjust("1 second")
        yield from (yield from e.client())("restarting").defect().fork(start_immediately=True)
        yield from defected.wait().race_first(testing.adjust("1 millis").forever())

        # Reassign the shard during the 500ms defect retry sleep.
        state.assign_self = False
        yield from _wait_for_termination_ownership(service, False)
        yield from testing.adjust("1 second")
        releases = list(state.release_calls)
        # Finish a broken implementation's termination timeout before asserting.
        yield from testing.adjust("10 seconds")
        assert releases == [shard("default", 1)]

    yield from fx.scoped(body).pipe(
        fx.provide(
            _termination_sharding(entity_layer, state, entity_termination_timeout=millis(10_000))
        )
    )
