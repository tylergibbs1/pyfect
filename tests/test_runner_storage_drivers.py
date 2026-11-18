"""A runner storage missing an operation fails when it is made, naming the operation, not with
an ``AttributeError`` when the operation is first used (``release_many``, added after 0.6.12, only
runs when a runner stops)."""

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect.cluster.runner_storage import RunnerStorageService, make_encoded


class _DriverWithoutReleaseMany:
    """An ``EncodedRunnerStorage`` written before ``release_many`` existed."""

    @property
    def get_runners(self) -> fx.Effect[list[tuple[str, bool]], Any]:
        return fx.succeed([])

    def register(self, address: str, runner: str, healthy: bool, /) -> fx.Effect[int, Any]:
        return fx.succeed(1)

    def unregister(self, address: str, /) -> fx.Effect[None, Any]:
        return fx.void

    def set_runner_health(self, address: str, healthy: bool, /) -> fx.Effect[None, Any]:
        return fx.void

    def acquire(self, address: str, shard_ids: Any, /) -> fx.Effect[list[str], Any]:
        return fx.succeed(list(shard_ids))

    def refresh(self, address: str, shard_ids: Any, /) -> fx.Effect[list[str], Any]:
        return fx.succeed(list(shard_ids))

    def release(self, address: str, shard_id: str, /) -> fx.Effect[None, Any]:
        return fx.void

    def release_all(self, address: str, /) -> fx.Effect[None, Any]:
        return fx.void


def test_an_encoded_driver_without_release_many_fails_when_wrapped():
    with pytest.raises(TypeError, match=r"_DriverWithoutReleaseMany .*release_many"):
        make_encoded(_DriverWithoutReleaseMany())  # pyright: ignore[reportArgumentType]


def test_a_storage_service_without_release_many_fails_when_made():
    with pytest.raises(TypeError, match="release_many"):
        RunnerStorageService(  # pyright: ignore[reportCallIssue]
            register=lambda _runner, _healthy: fx.die("unused"),
            unregister=lambda _address: fx.void,
            get_runners=fx.succeed([]),
            set_runner_health=lambda _address, _healthy: fx.void,
            acquire=lambda _address, _shards: fx.succeed([]),
            refresh=lambda _address, _shards: fx.succeed([]),
            release=lambda _address, _shard: fx.void,
            release_all=lambda _address: fx.void,
        )
