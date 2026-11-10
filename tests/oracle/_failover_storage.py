"""Effect's ``FailoverStorage`` runner storage fake from
``test/cluster/Sharding.test.ts``: lock storage a test can partition
(``blackholed``), deny, slow down or fail, recording each call."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Any

import pyfect as fx
from pyfect.clock import Clock, ClockService
from pyfect.cluster.cluster_error import PersistenceError
from pyfect.cluster.machine_id import MachineId
from pyfect.cluster.runner import Runner
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runner_storage import RunnerStorage, RunnerStorageService
from pyfect.cluster.shard_id import ShardId
from pyfect.latch import Latch
from pyfect.layer import Layer

other_runner = Runner(
    address=RunnerAddress(host="localhost", port=5678), groups=("default",), weight=1
)


@dataclass(slots=True, eq=False)
class AcquireCall:
    shards: list[ShardId]
    completed_release_alls: int


@dataclass(slots=True, eq=False)
class RefreshCall:
    at: float
    """Milliseconds."""
    shards: list[ShardId]


@dataclass(slots=True, eq=False)
class ReleaseAllCall:
    releases: int
    completed: bool = False


@dataclass(slots=True, eq=False)
class FailoverState:
    blackholed: bool = False
    blackhole_non_empty_refresh: bool = False
    """Hang only non-empty refreshes, so the empty liveness probe can succeed."""
    assign_self: bool = True
    lock_held_elsewhere: bool = False
    """Fail lock acquisition, as when another runner still holds the locks."""
    other_runner_healthy: bool = False
    release_all_duration: float = 0
    """Test clock seconds ``release_all`` stays in flight for."""
    release_failures: float = 0
    """Number of ``release`` calls that fail before succeeding (``math.inf``
    for every call)."""
    runner: Runner | None = None
    unregister_gate: Latch | None = None
    """Holds ``unregister`` until opened, when set."""
    acquire_denied: list[ShardId] = field(default_factory=list[ShardId])
    """Shards ``acquire`` does not grant, as if another runner holds them."""
    acquire_calls: list[AcquireCall] = field(default_factory=list[AcquireCall])
    refresh_calls: list[RefreshCall] = field(default_factory=list[RefreshCall])
    release_calls: list[ShardId] = field(default_factory=list[ShardId])
    release_all_calls: list[ReleaseAllCall] = field(default_factory=list[ReleaseAllCall])


def make_failover_storage(state: FailoverState, clock: ClockService) -> RunnerStorageService:
    def get_runners() -> list[tuple[Runner, bool]]:
        if state.runner is None:
            return []
        if not state.assign_self:
            return [(state.runner, False), (other_runner, True)]
        if state.other_runner_healthy:
            return [(state.runner, True), (other_runner, True)]
        return [(state.runner, True)]

    def register(runner: Runner, _healthy: bool) -> fx.Effect[MachineId, PersistenceError]:
        def run() -> MachineId:
            state.runner = runner
            return MachineId(1)

        return fx.sync(run)

    def unregister(_address: RunnerAddress) -> fx.Effect[None, PersistenceError]:
        def run() -> None:
            state.runner = None

        gate = state.unregister_gate
        return fx.sync(run) if gate is None else gate.wait().and_then(fx.sync(run))

    def acquire(
        _address: RunnerAddress, shard_ids: Iterable[ShardId]
    ) -> fx.Effect[list[ShardId], PersistenceError]:
        def run() -> list[ShardId]:
            shards = list(shard_ids)
            state.acquire_calls.append(
                AcquireCall(shards, len([c for c in state.release_all_calls if c.completed]))
            )
            if state.lock_held_elsewhere:
                return []
            return [s for s in shards if s not in state.acquire_denied]

        return fx.sync(run)

    def refresh(
        _address: RunnerAddress, shard_ids: Iterable[ShardId]
    ) -> fx.Effect[list[ShardId], PersistenceError]:
        def run() -> fx.Effect[list[ShardId], PersistenceError]:
            shards = list(shard_ids)
            state.refresh_calls.append(RefreshCall(clock.current_time_millis_unsafe(), shards))
            if state.blackholed or (state.blackhole_non_empty_refresh and shards):
                return fx.never
            return fx.succeed(shards)

        return fx.suspend(run)

    def release(_address: RunnerAddress, shard_id: ShardId) -> fx.Effect[None, PersistenceError]:
        def run() -> fx.Effect[None, PersistenceError]:
            state.release_calls.append(shard_id)
            if state.release_failures > 0:
                state.release_failures -= 1
                return fx.fail(PersistenceError(cause=RuntimeError("release failed")))
            return fx.void

        return fx.suspend(run)

    def release_all(_address: RunnerAddress) -> fx.Effect[None, PersistenceError]:
        def run() -> fx.Effect[None, PersistenceError]:
            call = ReleaseAllCall(releases=len(state.release_calls))
            state.release_all_calls.append(call)

            def complete() -> None:
                call.completed = True

            return fx.sleep(fx.duration.seconds(state.release_all_duration)).and_then(
                fx.sync(complete)
            )

        return fx.suspend(run)

    return RunnerStorageService(
        register=register,
        unregister=unregister,
        get_runners=fx.sync(get_runners),
        set_runner_health=lambda _address, _healthy: fx.void,
        acquire=acquire,
        refresh=refresh,
        release=release,
        release_all=release_all,
    )


def failover_storage_layer(state: FailoverState, update: Any = None) -> Layer[RunnerStorage]:
    """``RunnerStorage`` over the fake; ``update`` may wrap the service it
    makes (Effect's ``{ ...storage, acquire }``)."""

    def make(clock: ClockService) -> RunnerStorageService:
        storage = make_failover_storage(state, clock)
        return storage if update is None else update(storage)

    return fx.layer.effect(RunnerStorage, Clock().map(make))
