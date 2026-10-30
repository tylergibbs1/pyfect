"""Ports of Effect's ``test/cluster`` tests for the core values and
storage: ``ShardingConfig.test.ts``, ``interruptors.test.ts``,
``RunnerStorage.test.ts`` and ``ResourceMap.test.ts``.

Each test's docstring is the Effect test title. ``ShardingConfig.layer({
... })`` is ``sharding_config.layer(replace(DEFAULTS, ...))``; an absent
listen address is ``None``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import replace
from typing import Never

import pyfect as fx
from pyfect import config_provider, testing
from pyfect.cluster import (
    entity_address,
    entity_id,
    entity_type,
    runner,
    runner_address,
    runner_storage,
    shard_id,
    sharding_config,
)
from pyfect.cluster._interruptors import (
    acquire_entity,
    around_entity_type,
    is_active,
    release_entity,
)
from pyfect.cluster._resource_map import ResourceMap
from pyfect.cluster.sharding_config import DEFAULTS, ShardingConfig
from pyfect.config import ConfigError
from pyfect.exit import Failure, Success


def _parse(values: Mapping[str, str]):
    return sharding_config.config.parse(config_provider.from_unknown(values))


@testing.effect
def test_sharding_config_bounds_residency_by_default():
    """bounds runner residency and storage reads by default"""
    assert DEFAULTS.max_resident_entities == 10_000
    assert DEFAULTS.unprocessed_message_batch_size == 1024

    defaults = yield from _parse({})
    assert defaults.max_resident_entities == 10_000
    assert defaults.unprocessed_message_batch_size == 1024

    from_env = yield from _parse(
        {"maxResidentEntities": "500", "unprocessedMessageBatchSize": "128"}
    )
    assert from_env.max_resident_entities == 500
    assert from_env.unprocessed_message_batch_size == 128

    invalid = yield from _parse({"maxResidentEntities": "unbounded"}).flip()
    assert isinstance(invalid, ConfigError)

    config_layer = sharding_config.layer(replace(DEFAULTS, max_resident_entities="unbounded"))
    settings = yield from ShardingConfig().pipe(fx.provide(config_layer))
    assert settings.max_resident_entities == "unbounded"


@testing.effect
def test_sharding_config_omits_listen_address_without_host():
    """omits the optional listen address when its host is absent"""
    defaults = yield from _parse({})
    assert defaults.runner_listen_address is None

    with_host = yield from _parse({"listenHost": "0.0.0.0"})
    assert with_host.runner_listen_address == runner_address.make("0.0.0.0", 34431)

    missing_host = yield from _parse({"listenPort": "8080"})
    assert missing_host.runner_listen_address is None

    invalid_port = yield from _parse({"listenHost": "0.0.0.0", "listenPort": "invalid"}).flip()
    assert invalid_port.cause.message == (
        'Expected a string representing a finite number\n  at ["listenPort"]'
    )


@testing.effect
def test_sharding_config_rejects_non_positive_limits():
    """rejects non-positive residency and batch limits"""
    for values in (
        {"maxResidentEntities": "0"},
        {"maxResidentEntities": "-1"},
        {"unprocessedMessageBatchSize": "0"},
        {"unprocessedMessageBatchSize": "-1"},
    ):
        error = yield from _parse(values).flip()
        assert isinstance(error, ConfigError)


_ADDRESS = entity_address.make(
    shard_id=shard_id.make("active-teardown-unit", 1),
    entity_type=entity_type.make("ActiveTeardownUnit"),
    entity_id=entity_id.make("1"),
)


def test_interruptors_release_returns_to_baseline() -> None:
    """releases entity keys so membership returns to baseline"""
    acquire_entity(_ADDRESS)
    assert is_active(_ADDRESS)
    release_entity(_ADDRESS)
    assert not is_active(_ADDRESS)


def test_interruptors_refcount_overlapping_acquires() -> None:
    """refcounts overlapping acquires"""
    acquire_entity(_ADDRESS)
    acquire_entity(_ADDRESS)
    release_entity(_ADDRESS)
    assert is_active(_ADDRESS)
    release_entity(_ADDRESS)
    assert not is_active(_ADDRESS)


@testing.effect
def test_interruptors_around_entity_type_restores():
    """aroundEntityType restores the key after the effect"""

    def check() -> None:
        assert is_active(_ADDRESS)

    yield from around_entity_type("ActiveTeardownUnit", fx.sync(check))
    assert not is_active(_ADDRESS)


@testing.effect
def test_runner_storage_tracks_health_in_memory():
    """tracks runner health in memory"""
    storage = yield from runner_storage.make_memory()
    address = runner_address.make("localhost", 41001)
    yield from storage.register(runner.make(address=address, groups=("default",), weight=1), False)
    assert (yield from storage.get_runners)[0][1] is False
    yield from storage.set_runner_health(address, True)
    assert (yield from storage.get_runners)[0][1] is True


@testing.effect
def test_runner_storage_acquire_accepts_one_shot_iterable():
    """memory acquire accepts a one-shot iterable"""
    storage = yield from runner_storage.make_memory()
    address = runner_address.make("localhost", 1234)
    shards = [shard_id.make("default", 1), shard_id.make("default", 2)]
    acquired = yield from storage.acquire(address, iter(shards))
    assert acquired == shards
    assert (yield from storage.refresh(address, [])) == shards


@testing.effect
def test_resource_map_closes_failed_lookup_scope():
    """closes a failed lookup scope"""
    finalized = 0

    def count(_: object) -> fx.Effect[None]:
        def run() -> None:
            nonlocal finalized
            finalized += 1

        return fx.sync(run)

    def lookup(_key: str) -> fx.Effect[int, str, fx.Scope]:
        return fx.add_finalizer(count).and_then(fx.fail("failed"))

    resource_map = yield from ResourceMap.make(lookup)
    yield from resource_map.get("key").exit()
    assert finalized == 1


@testing.effect
def test_resource_map_shares_lookup_until_all_interrupted():
    """shares a lookup until every get is interrupted, then starts fresh"""
    lookups = 0
    started = yield from fx.Deferred[None].make()
    finalizing = yield from fx.Deferred[None].make()
    finish_finalizer = yield from fx.Deferred[None].make()

    def lookup(_key: str) -> fx.Effect[int]:
        def body() -> fx.Effect[int]:
            nonlocal lookups
            lookups += 1
            if lookups > 1:
                return fx.succeed(lookups)
            return (
                started.succeed(None)
                .and_then(fx.never)
                .on_interrupt(finalizing.succeed(None).and_then(finish_finalizer.wait()))
            )

        return fx.suspend(body)

    resource_map = yield from ResourceMap.make(lookup)
    first = yield from resource_map.get("key").fork(start_immediately=True)
    yield from started.wait()
    second = yield from resource_map.get("key").fork(start_immediately=True)
    yield from first.interrupt()
    assert not (yield from finalizing.is_done())

    interrupt_second = yield from second.interrupt().fork(start_immediately=True)
    yield from finalizing.wait()
    fresh = yield from resource_map.get("key").fork(start_immediately=True)
    yield from finish_finalizer.succeed(None)
    yield from interrupt_second.join()
    assert (yield from fresh.await_exit()) == Success(2)


@testing.effect
def test_resource_map_abandoned_lookup_keeps_replacement():
    """an abandoned lookup does not remove a replacement entry"""
    lookups = 0
    started = yield from fx.Deferred[None].make()
    release = yield from fx.Deferred[None].make()

    def lookup(_key: str) -> fx.Effect[int]:
        def body() -> fx.Effect[int]:
            nonlocal lookups
            lookups += 1
            current = lookups
            if current == 1:
                return started.succeed(None).and_then(fx.never)
            return release.wait().as_(current)

        return fx.suspend(body)

    resource_map = yield from ResourceMap.make(lookup)
    abandoned = yield from resource_map.get("key").fork(start_immediately=True)
    yield from started.wait()
    yield from resource_map.remove("key")
    replacement = yield from resource_map.get("key").fork(start_immediately=True)
    yield from abandoned.interrupt()
    joiner = yield from resource_map.get("key").fork(start_immediately=True)

    yield from release.succeed(None)
    assert (yield from replacement.await_exit()) == Success(2)
    assert (yield from joiner.await_exit()) == Success(2)


@testing.effect
def test_resource_map_close_interrupts_pending_lookup():
    """closing the map interrupts a pending lookup and closes its scope"""
    finalized = 0
    started = yield from fx.Deferred[None].make()

    def count(_: object) -> fx.Effect[None]:
        def run() -> None:
            nonlocal finalized
            finalized += 1

        return fx.sync(run)

    def lookup(_key: str) -> fx.Effect[int, Never, fx.Scope]:
        return fx.add_finalizer(count).and_then(started.succeed(None)).and_then(fx.never)

    map_scope = fx.CloseableScope()
    resource_map = yield from ResourceMap.make(lookup).pipe(fx.provide_service(fx.Scope, map_scope))
    getter = yield from resource_map.get("key").fork(start_immediately=True)
    yield from started.wait()
    yield from map_scope.close(Success(None))

    assert finalized == 1
    ex = yield from getter.await_exit()
    assert isinstance(ex, Failure) and ex.cause.has_interrupts
