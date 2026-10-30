"""Where runners register and lock the shards they own (Effect's
``RunnerStorage``). ``make_memory`` / ``layer_memory`` keep everything in
the process: one runner, no locking."""

from __future__ import annotations

from collections.abc import Callable, Iterable
from dataclasses import dataclass

from pyfect import layer as layer_
from pyfect._core import Effect
from pyfect.cluster.cluster_error import PersistenceError
from pyfect.cluster.machine_id import MachineId
from pyfect.cluster.runner import Runner
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.shard_id import ShardId
from pyfect.context import Tag
from pyfect.effect import succeed, sync


@dataclass(frozen=True, slots=True, kw_only=True)
class RunnerStorageService:
    """``acquire`` takes the locks it can of ``shard_ids`` and gives back
    the shards now held; ``refresh`` extends the locks still held."""

    register: Callable[[Runner, bool], Effect[MachineId, PersistenceError]]
    unregister: Callable[[RunnerAddress], Effect[None, PersistenceError]]
    get_runners: Effect[list[tuple[Runner, bool]], PersistenceError]
    set_runner_health: Callable[[RunnerAddress, bool], Effect[None, PersistenceError]]
    acquire: Callable[[RunnerAddress, Iterable[ShardId]], Effect[list[ShardId], PersistenceError]]
    refresh: Callable[[RunnerAddress, Iterable[ShardId]], Effect[list[ShardId], PersistenceError]]
    release: Callable[[RunnerAddress, ShardId], Effect[None, PersistenceError]]
    release_all: Callable[[RunnerAddress], Effect[None, PersistenceError]]


class RunnerStorage(Tag[RunnerStorageService], key="effect/cluster/RunnerStorage"):
    """The runner storage of this cluster."""


def _make_memory() -> RunnerStorageService:
    runners: dict[RunnerAddress, tuple[Runner, bool]] = {}
    acquired: list[ShardId] = []
    next_id = 0

    def register(runner: Runner, healthy: bool) -> Effect[MachineId, PersistenceError]:
        def run() -> MachineId:
            nonlocal next_id
            runners[runner.address] = (runner, healthy)
            next_id += 1
            return MachineId(next_id - 1)

        return sync(run)

    def unregister(address: RunnerAddress) -> Effect[None, PersistenceError]:
        return sync(lambda: runners.pop(address, None)).as_void()

    def set_runner_health(address: RunnerAddress, healthy: bool) -> Effect[None, PersistenceError]:
        def run() -> None:
            entry = runners.get(address)
            if entry is not None:
                runners[address] = (entry[0], healthy)

        return sync(run)

    def acquire(
        _address: RunnerAddress, shard_ids: Iterable[ShardId]
    ) -> Effect[list[ShardId], PersistenceError]:
        def run() -> list[ShardId]:
            acquired[:] = shard_ids
            return list(acquired)

        return sync(run)

    def refresh(
        _address: RunnerAddress, _shard_ids: Iterable[ShardId]
    ) -> Effect[list[ShardId], PersistenceError]:
        return sync(lambda: list(acquired))

    def release(_address: RunnerAddress, _shard_id: ShardId) -> Effect[None, PersistenceError]:
        return succeed(None)

    def release_all(_address: RunnerAddress) -> Effect[None, PersistenceError]:
        return succeed(None)

    return RunnerStorageService(
        register=register,
        unregister=unregister,
        get_runners=sync(lambda: list(runners.values())),
        set_runner_health=set_runner_health,
        acquire=acquire,
        refresh=refresh,
        release=release,
        release_all=release_all,
    )


def make_memory() -> Effect[RunnerStorageService]:
    """Runner storage in memory (Effect's ``makeMemory``)."""
    return sync(_make_memory)


layer_memory: layer_.Layer[RunnerStorage] = layer_.effect(RunnerStorage, make_memory())

__all__ = ["RunnerStorage", "RunnerStorageService", "layer_memory", "make_memory"]
