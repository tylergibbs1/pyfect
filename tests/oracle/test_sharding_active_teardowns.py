"""Ports of the "Sharding active teardowns" cases of Effect's
``test/cluster/Sharding.test.ts``. Each test's docstring is the Effect test
title. "swallows persisted interrupts when the caller's shard is released"
releases the shard through Effect's ``FailoverStorage`` and lives in
``test_sharding_failover``.
"""

from __future__ import annotations

from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.cluster import (
    _interruptors,
    message_storage,
    runner_health,
    runner_storage,
    runners,
    sharding,
)
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity
from pyfect.cluster.entity_address import EntityAddress
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.entity_type import EntityType
from pyfect.cluster.message_storage import MemoryDriver, MemoryDriverService
from pyfect.duration import Seconds
from pyfect.layer import Layer
from pyfect.rpc import make as make_rpc

from . import _cluster_entities as entities
from ._cluster_entities import TestEntity, test_entity_no_state, test_entity_state_layer
from ._sharding_fixtures import make_config, test_sharding

EntityState = entities.TestEntityState


class ActiveTeardownCaller(Entity, type="ActiveTeardownCaller"):
    arm = make_rpc("Arm").annotate(Persisted, False)


@fx.gen
def _build_active_teardown_caller():
    receiver = yield from TestEntity.client()
    yield from receiver("nested-target").never().fork_scoped()
    c = ActiveTeardownCaller
    return c.handlers().handle(c.arm)(lambda _: fx.void)


active_teardown_caller_layer = ActiveTeardownCaller.to_layer_effect(_build_active_teardown_caller)


def _active_teardown_sharding(**changes: Any) -> Layer[Any]:
    return (
        fx.layer.merge(active_teardown_caller_layer, test_entity_no_state)
        .pipe(fx.layer.provide_merge(sharding.layer))
        .pipe(fx.layer.provide(runner_storage.layer_memory))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide_merge(test_entity_state_layer))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide_merge(message_storage.layer_memory))
        .pipe(fx.layer.provide(make_config(**changes)))
    )


class ReapStormEntity(Entity, type="ReapStormEntity"):
    ping = make_rpc("Ping")


reap_storm_sharding = (
    ReapStormEntity.to_layer(
        ReapStormEntity.handlers().handle(ReapStormEntity.ping)(lambda _: fx.void)
    )
    .pipe(fx.layer.provide_merge(sharding.layer))
    .pipe(fx.layer.provide(runner_storage.layer_memory))
    .pipe(fx.layer.provide(runner_health.layer_noop))
    .pipe(fx.layer.provide(runners.layer_noop))
    .pipe(fx.layer.provide_merge(message_storage.layer_memory))
    .pipe(
        fx.layer.provide(
            make_config(entity_max_idle_time=Seconds(0.001), entity_termination_timeout=Seconds(0))
        )
    )
)


def _journal_interrupts(driver: MemoryDriverService) -> int:
    return len([e for e in driver.encoded.journal if e["_tag"] == "Interrupt"])


def _wait_for_idle_reap(service: sharding.ShardingService, remaining: int) -> fx.Effect[None]:
    @fx.gen
    def run():
        for _ in range(12):
            if (yield from service.active_entity_count) <= remaining:
                return
            yield from testing.adjust(5)
        assert (yield from service.active_entity_count) <= remaining

    return run


def _address(service: sharding.ShardingService, entity_type: str, id_: str) -> EntityAddress:
    entity_id = EntityId(id_)
    return EntityAddress(
        shard_id=service.get_shard_id(entity_id, "default"),
        entity_type=EntityType(entity_type),
        entity_id=entity_id,
    )


@testing.effect
def test_swallows_persisted_interrupts_from_an_idle_reaped_nested_proxy_call():
    """swallows persisted interrupts from an idle-reaped nested proxy call"""

    @fx.gen
    def body():
        yield from testing.adjust(0.001)
        driver = yield from MemoryDriver()
        state = yield from EntityState()
        service = yield from sharding.Sharding()
        caller = (yield from ActiveTeardownCaller.client())("1")
        yield from caller.arm()
        yield from testing.adjust(0.001)
        assert state.envelopes.size_unsafe() == 1
        assert _journal_interrupts(driver) == 0

        yield from _wait_for_idle_reap(service, 1)
        assert state.envelopes.size_unsafe() == 1
        assert state.interrupts.size_unsafe() == 0
        assert _journal_interrupts(driver) == 0

    yield from body.pipe(fx.provide(_active_teardown_sharding(entity_max_idle_time=Seconds(0.001))))


@testing.effect
def test_treats_node_shutdown_interrupts_as_transient_via_is_shutdown():
    """treats node shutdown interrupts as transient via isShutdown"""
    seen: dict[str, Any] = {}

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        state = yield from EntityState()
        seen["driver"] = driver
        yield from testing.adjust(0.001)
        yield from (yield from ActiveTeardownCaller.client())("1").arm()
        yield from testing.adjust(0.001)
        assert state.envelopes.size_unsafe() == 1

    yield from body.pipe(fx.provide(_active_teardown_sharding()))
    driver: MemoryDriverService = seen["driver"]
    assert _journal_interrupts(driver) == 0
    assert len(driver.encoded.journal) == 1


@testing.effect
def test_forwards_replayed_storage_interrupts_that_have_no_local_provenance():
    """forwards replayed storage interrupts that have no local provenance"""

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        state = yield from EntityState()
        service = yield from sharding.Sharding()
        make_client = yield from TestEntity.client()
        yield from testing.adjust(0.001)
        client = make_client("1")
        yield from client.never().fork(start_immediately=True)
        yield from testing.adjust(0.001)
        assert state.envelopes.size_unsafe() == 1

        request: Any = driver.encoded.journal[0]
        assert request["_tag"] == "Request"
        interrupt: Any = {
            "id": str((yield from service.get_snowflake)),
            "_tag": "Interrupt",
            "requestId": request["requestId"],
            "address": request["address"],
        }
        yield from driver.encoded.save_envelope(interrupt, None, None)

        yield from testing.adjust(5)
        assert state.interrupts.size_unsafe() == 1
        assert _journal_interrupts(driver) == 1

    yield from body.pipe(fx.provide(test_sharding))


@testing.effect
def test_forwards_interrupts_from_an_external_same_node_caller():
    """forwards interrupts from an external same-node caller"""

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        state = yield from EntityState()
        make_client = yield from TestEntity.client()
        yield from testing.adjust(0.001)
        client = make_client("1")
        fiber = yield from client.never().fork(start_immediately=True)
        yield from testing.adjust(0.001)
        yield from fiber.interrupt()
        yield from testing.adjust(0.001)
        assert _journal_interrupts(driver) == 1
        assert state.interrupts.size_unsafe() == 1

    yield from body.pipe(fx.provide(test_sharding))


@testing.effect
def test_forwards_interrupts_from_an_external_same_node_caller_during_entity_teardown():
    """forwards interrupts from an external same-node caller during entity teardown"""

    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        state = yield from EntityState()
        service = yield from sharding.Sharding()
        make_client = yield from TestEntity.client()
        yield from testing.adjust(0.001)
        client = make_client("external-teardown")
        address = _address(service, TestEntity.type, "external-teardown")

        fiber = yield from client.never().fork(start_immediately=True)
        yield from testing.adjust(0.001)
        _interruptors.acquire_entity(address)
        yield from fiber.interrupt().ensuring(
            fx.sync(lambda: _interruptors.release_entity(address))
        )
        yield from testing.adjust(0.001)
        assert _journal_interrupts(driver) == 1
        assert state.interrupts.size_unsafe() == 1

    yield from body.pipe(fx.provide(test_sharding))


@testing.effect
def test_returns_registry_size_to_baseline_after_entity_reap_storms():
    """returns registry size to baseline after entity reap storms"""

    @fx.gen
    def body():
        yield from testing.adjust(0.001)
        service = yield from sharding.Sharding()
        make_client = yield from ReapStormEntity.client()

        @fx.fn
        def storm(offset: int):
            for i in range(20):
                yield from make_client(str(offset + i)).ping()
            assert (yield from service.active_entity_count) == 20
            yield from _wait_for_idle_reap(service, 0)
            assert (yield from service.active_entity_count) == 0
            for i in range(20):
                assert not _interruptors.is_active(
                    _address(service, "ReapStormEntity", str(offset + i))
                )

        yield from storm(0)
        yield from storm(100)

    yield from body.pipe(fx.provide(reap_storm_sharding))
