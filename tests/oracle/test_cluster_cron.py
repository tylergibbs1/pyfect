"""Ports of Effect's ``test/cluster/ClusterCron.test.ts``. Each test's
docstring is the Effect test title."""

from __future__ import annotations

import itertools
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any, Never

import pyfect as fx
from pyfect import testing
from pyfect.cluster import (
    cluster_cron,
    message_storage,
    runner_health,
    runner_storage,
    runners,
    sharding,
    sharding_config,
)
from pyfect.cluster.cluster_error import PersistenceError
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity
from pyfect.cluster.message import OutgoingRequest
from pyfect.cluster.message_storage import (
    MemoryDriver,
    MessageStorage,
    MessageStorageService,
    SaveResult,
    StorageBase,
)
from pyfect.cron import next as cron_next
from pyfect.cron import parse_unsafe
from pyfect.date_time import format_iso, now
from pyfect.duration import Seconds
from pyfect.rpc import make as make_rpc
from pyfect.schema import Class, DateTimeUtc, field
from pyfect.scope import scoped

EVERY_SECOND = parse_unsafe("* * * * * *", "UTC")

_deploy_config = sharding_config.layer(
    replace(
        sharding_config.DEFAULTS,
        entity_registration_timeout=Seconds(1),
        entity_termination_timeout=Seconds(0),
        entity_message_poll_interval=Seconds(0.1),
    )
)


def deploy(entities: fx.Layer[Never, Never, Any], millis: int) -> fx.Effect[None, Never, Any]:
    """Each deploy is a fresh Sharding instance over the same message storage."""

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        layer = (
            entities.pipe(fx.layer.provide_merge(sharding.layer))
            .pipe(
                fx.layer.provide(
                    fx.layer.merge(
                        runner_storage.layer_memory, runner_health.layer_noop, runners.layer_noop
                    )
                )
            )
            .pipe(fx.layer.provide(fx.layer.succeed(MessageStorage, driver.storage)))
            .pipe(fx.layer.provide(_deploy_config))
        )
        yield from layer.build()
        for _ in range(millis // 100):
            yield from testing.adjust("100 millis")

    return scoped(body)


@dataclass(slots=True)
class _FailingSaves:
    """A storage whose ``save_request`` goes through ``save``."""

    inner: StorageBase
    save: Any

    def __getattr__(self, name: str) -> Any:
        return getattr(self.inner, name)

    def save_request(self, message: OutgoingRequest, /) -> fx.Effect[SaveResult, Any]:
        return self.save(self.inner, message)


def _sharding_with_saves(save: Any) -> fx.Layer[Any, Never, Any]:
    def update(storage: MessageStorageService) -> MessageStorageService:
        return replace(storage, base=_FailingSaves(storage.base, save))

    updated = fx.layer.effect(MessageStorage, MessageStorage().map(update)).pipe(
        fx.layer.provide(message_storage.layer_memory)
    )
    config = sharding_config.layer(
        replace(sharding_config.DEFAULTS, entity_message_poll_interval=Seconds(0.1))
    )
    return (
        sharding.layer.pipe(
            fx.layer.provide(
                fx.layer.merge(
                    runner_storage.layer_memory, runner_health.layer_noop, runners.layer_noop
                )
            )
        )
        .pipe(fx.layer.provide(updated))
        .pipe(fx.layer.provide(config))
    )


class LegacyCronPayload(Class, identifier="LegacyCronPayload"):
    date_time: datetime = field(DateTimeUtc)

    def primary_key(self) -> str:
        return ""

    def deliver_at(self) -> datetime:
        return self.date_time


class LegacyCronEntity(Entity, type="ClusterCron/test"):
    run = make_rpc("run", payload=LegacyCronPayload).annotate(Persisted, True)


def _persistence_error() -> PersistenceError:
    return PersistenceError(cause=ConnectionResetError("connection reset"))


@testing.effect
def test_recovers_from_a_transient_failure_to_schedule_the_initial_run():
    """recovers from a transient failure to schedule the initial run"""
    failed = [False]
    runs = [0]

    def save(inner: StorageBase, message: OutgoingRequest) -> fx.Effect[SaveResult, Any]:
        def run() -> fx.Effect[SaveResult, Any]:
            if not failed[0] and message.envelope.address.entity_type == "ClusterCron/test":
                failed[0] = True
                return fx.fail(_persistence_error())
            return inner.save_request(message)

        return fx.suspend(run)

    def count() -> None:
        runs[0] += 1

    layer = cluster_cron.make(name="test", cron=EVERY_SECOND, execute=fx.sync(count)).pipe(
        fx.layer.provide(_sharding_with_saves(save))
    )

    @fx.gen
    def body():
        for _ in range(20):
            yield from testing.adjust("100 millis")
        assert failed[0]
        assert runs[0] == 2

    yield from body.pipe(fx.provide(layer))


@testing.effect
def test_keeps_the_initial_runs_instant_while_scheduling_it_is_retried_across_a_cron_boundary():
    """keeps the initial run's instant while scheduling it is retried across a cron boundary"""
    attempts: list[str] = []
    recovered = [False]

    def save(inner: StorageBase, message: OutgoingRequest) -> fx.Effect[SaveResult, Any]:
        def run(at: datetime) -> fx.Effect[SaveResult, Any]:
            address = message.envelope.address
            if recovered[0] or address.entity_type != "ClusterCron/test":
                return inner.save_request(message)
            attempts.append(str(address.entity_id))
            # Storage stays down until the first scheduled instant has passed.
            if at.timestamp() < 1:
                return fx.fail(_persistence_error())
            recovered[0] = True
            return inner.save_request(message)

        return now().flat_map(run)

    layer = cluster_cron.make(name="test", cron=EVERY_SECOND, execute=fx.void).pipe(
        fx.layer.provide(_sharding_with_saves(save))
    )

    @fx.gen
    def body():
        for _ in range(25):
            yield from testing.adjust("100 millis")
        assert recovered[0]
        assert len(attempts) > 1
        assert attempts == ["1970-01-01T00:00:01.000Z"] * len(attempts)

    yield from body.pipe(fx.provide(layer))


class Other(Entity, type="Other"):
    ping = make_rpc("Ping")


other_layer = Other.to_layer(Other.handlers().handle(Other.ping)(lambda _: fx.void))


@testing.effect
def test_resumes_with_calculate_next_run_from_previous_after_its_pending_run_fails():
    """resumes with calculateNextRunFromPrevious after its pending run fails"""
    runs = [0]

    def count() -> None:
        runs[0] += 1

    cron = cluster_cron.make(
        name="test",
        cron=EVERY_SECOND,
        calculate_next_run_from_previous=True,
        execute=fx.sync(count),
    )

    @fx.gen
    def body():
        yield from deploy(fx.layer.merge(cron, other_layer), 3500)
        before_removal = runs[0]
        assert before_removal > 0

        # The pending run fails once the cron entity misses its registration timeout.
        yield from deploy(other_layer, 3000)
        assert runs[0] == before_removal

        yield from deploy(fx.layer.merge(cron, other_layer), 3500)
        assert runs[0] > before_removal

    yield from body.pipe(fx.provide(message_storage.memory_driver_layer))


@testing.effect
def test_catches_up_in_order_with_calculate_next_run_from_previous_after_a_restart():
    """catches up in order with calculateNextRunFromPrevious after a restart"""
    scheduled: list[str] = []
    running = [0]
    overlapped = [False]
    slow = [False]

    @fx.gen
    def execute():
        scheduled.append(format_iso((yield from cluster_cron.CurrentScheduledTime())))
        running[0] += 1
        if running[0] > 1:
            overlapped[0] = True
        if slow[0]:
            yield from fx.sleep("2 seconds")
        running[0] -= 1

    cron = cluster_cron.make(
        name="test", cron=EVERY_SECOND, calculate_next_run_from_previous=True, execute=execute
    )

    @fx.gen
    def body():
        yield from deploy(cron, 1500)
        # The pending run falls behind while no runner is up.
        yield from testing.adjust("3 seconds")
        slow[0] = True
        scheduled.clear()
        yield from deploy(cron, 6000)

        assert len(scheduled) > 1
        assert not overlapped[0]
        assert scheduled == sorted(scheduled)

    yield from body.pipe(fx.provide(message_storage.memory_driver_layer))


@testing.effect
def test_retries_a_failed_run_with_calculate_next_run_from_previous_before_later_instants():
    """retries a failed run with calculateNextRunFromPrevious before later instants"""
    attempts: list[str] = []

    @fx.gen
    def execute():
        attempts.append(format_iso((yield from cluster_cron.CurrentScheduledTime())))
        if len(attempts) == 1:
            return (yield from fx.fail("boom"))

    cron = cluster_cron.make(
        name="test", cron=EVERY_SECOND, calculate_next_run_from_previous=True, execute=execute
    )

    @fx.gen
    def body():
        yield from deploy(cron, 3500)
        assert len(attempts) > 2
        assert attempts[1] == attempts[0]
        assert attempts == sorted(attempts)

    yield from body.pipe(fx.provide(message_storage.memory_driver_layer))


@testing.effect
def test_replays_an_interrupted_run_with_calculate_next_run_from_previous_when_finalizer_fails():
    """replays an interrupted run with calculateNextRunFromPrevious when its finalizer fails"""
    attempts: list[str] = []

    @fx.gen
    def execute():
        attempts.append(format_iso((yield from cluster_cron.CurrentScheduledTime())))
        if len(attempts) == 1:
            return (yield from fx.interrupt().ensuring(fx.die(RuntimeError("cleanup failed"))))

    cron = cluster_cron.make(
        name="test", cron=EVERY_SECOND, calculate_next_run_from_previous=True, execute=execute
    )

    @fx.gen
    def body():
        yield from deploy(cron, 3500)
        assert len(attempts) > 2
        assert attempts[1] == attempts[0]

    yield from body.pipe(fx.provide(message_storage.memory_driver_layer))


@testing.effect
def test_runs_each_instant_once_across_a_legacy_pending_run_and_a_redeploy():
    """runs each instant once across a legacy pending run and a redeploy"""
    scheduled: list[str] = []

    @fx.gen
    def execute():
        scheduled.append(format_iso((yield from cluster_cron.CurrentScheduledTime())))

    cron = cluster_cron.make(
        name="test", cron=EVERY_SECOND, calculate_next_run_from_previous=True, execute=execute
    )

    def assert_each_instant_once(first: str) -> None:
        assert len(scheduled) > 1
        assert scheduled[0] == first
        for previous, current in itertools.pairwise(scheduled):
            after = datetime.fromisoformat(previous)
            assert current == format_iso(cron_next(EVERY_SECOND, after))

    @fx.gen
    def body():
        # A pending run written by an earlier release, at a per-instant
        # address with an empty primary key.
        legacy = cron_next(EVERY_SECOND, (yield from now())).astimezone(UTC)

        @fx.gen
        def send_legacy():
            make_client = yield from LegacyCronEntity.client()
            client = make_client(format_iso(legacy))
            yield from client.run.discard(LegacyCronPayload(date_time=legacy)).or_die()

        yield from deploy(fx.layer.effect_discard(send_legacy), 0)

        yield from deploy(cron, 2500)
        assert_each_instant_once(format_iso(legacy))

        # Redeploy while the chain has a healthy pending run.
        yield from deploy(cron, 2500)
        assert_each_instant_once(format_iso(legacy))

    yield from body.pipe(fx.provide(message_storage.memory_driver_layer))
