"""Runner storages written before ``release_many`` existed keep working: without it, a storage
releases several shards one ``release`` at a time, through its current ``release``."""

from __future__ import annotations

import copy
from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from oracle._failover_storage import FailoverState, failover_storage_layer

import pyfect as fx
from pyfect import testing
from pyfect.cluster import (
    message_storage,
    runner_health,
    runners,
    sharding,
    sharding_config,
    snowflake,
)
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runner_storage import RunnerStorageService, make_encoded
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.shard_id import make as shard
from pyfect.duration import millis
from pyfect.exit import Success
from pyfect.scope import CloseableScope

_address = RunnerAddress(host="localhost", port=1234)
_shards = [shard("default", n) for n in (1, 2, 3)]


def _storage_without_release_many(released: list[ShardId]) -> RunnerStorageService:
    def release(_address: RunnerAddress, shard_id: ShardId) -> fx.Effect[None]:
        return fx.sync(lambda: released.append(shard_id))

    return RunnerStorageService(
        register=lambda _runner, _healthy: fx.die("unused"),
        unregister=lambda _address: fx.void,
        get_runners=fx.succeed([]),
        set_runner_health=lambda _address, _healthy: fx.void,
        acquire=lambda _address, shard_ids: fx.succeed(list(shard_ids)),
        refresh=lambda _address, shard_ids: fx.succeed(list(shard_ids)),
        release=release,
        release_all=lambda _address: fx.void,
    )


@testing.effect
def test_a_storage_without_release_many_hands_every_shard_off():
    state = FailoverState()
    config = replace(
        sharding_config.DEFAULTS,
        runner_address=_address,
        shards_per_group=len(_shards),
        entity_termination_timeout=millis(0),
        entity_message_poll_interval=millis(10),
        refresh_assignments_interval=millis(10),
    )
    layer = (
        sharding.layer.pipe(fx.layer.provide(failover_storage_layer(state)))
        .pipe(fx.layer.provide(runner_health.layer_noop))
        .pipe(fx.layer.provide(runners.layer_noop))
        .pipe(fx.layer.provide(message_storage.layer_memory))
        .pipe(fx.layer.provide(snowflake.layer_generator))
        .pipe(fx.layer.provide(sharding_config.layer(config)))
    )

    @fx.gen
    def body():
        scope = CloseableScope()
        built = yield from layer.build_with_scope(scope)
        service = built.get_unsafe(sharding.Sharding)
        for _ in range(100):
            if all(service.has_shard_id(s) for s in _shards):
                break
            yield from testing.adjust("10 millis")
        assert all(service.has_shard_id(s) for s in _shards)

        closing = yield from scope.close(Success(None)).fork()
        for _ in range(100):
            if closing.poll_unsafe() is not None:
                break
            yield from testing.adjust("10 millis")
        assert closing.poll_unsafe() == Success(None)
        assert sorted(state.release_calls, key=str) == sorted(_shards, key=str)

    yield from body


@testing.effect
def test_a_copy_wrapping_release_sees_every_shard_released_many():
    released: list[ShardId] = []
    wrapped: list[ShardId] = []
    storage = _storage_without_release_many(released)

    def release(address: RunnerAddress, shard_id: ShardId) -> fx.Effect[None, Any]:
        return fx.sync(lambda: wrapped.append(shard_id)).and_then(
            storage.release(address, shard_id)
        )

    copied = copy.replace(storage, release=release)
    yield from copied.release_many(_address, _shards)
    assert wrapped == _shards
    assert released == _shards


class _DriverWithoutReleaseMany:
    """An ``EncodedRunnerStorage`` written before ``release_many`` existed."""

    def __init__(self) -> None:
        self.released: list[str] = []

    @property
    def get_runners(self) -> fx.Effect[list[tuple[str, bool]], Any]:
        return fx.succeed([])

    def register(self, address: str, runner: str, healthy: bool, /) -> fx.Effect[int, Any]:
        return fx.succeed(1)

    def unregister(self, address: str, /) -> fx.Effect[None, Any]:
        return fx.void

    def set_runner_health(self, address: str, healthy: bool, /) -> fx.Effect[None, Any]:
        return fx.void

    def acquire(self, address: str, shard_ids: Sequence[str], /) -> fx.Effect[list[str], Any]:
        return fx.succeed(list(shard_ids))

    def refresh(self, address: str, shard_ids: Sequence[str], /) -> fx.Effect[list[str], Any]:
        return fx.succeed(list(shard_ids))

    def release(self, address: str, shard_id: str, /) -> fx.Effect[None, Any]:
        return fx.sync(lambda: self.released.append(f"{address} {shard_id}"))

    def release_all(self, address: str, /) -> fx.Effect[None, Any]:
        return fx.void


@testing.effect
def test_an_encoded_driver_without_release_many_releases_one_shard_at_a_time():
    driver = _DriverWithoutReleaseMany()
    storage = make_encoded(driver)
    assert (yield from storage.acquire(_address, _shards)) == _shards
    yield from storage.release_many(_address, _shards)
    assert driver.released == [f"localhost:1234 {s}" for s in _shards]
