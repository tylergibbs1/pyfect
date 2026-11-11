"""Where runners register and lock the shards they own (Effect's
``RunnerStorage``). ``make_memory`` / ``layer_memory`` keep everything in
the process: one runner, no locking. ``make_encoded`` wraps a driver that
stores addresses, runners and shard ids as text
(``pyfect.cluster.sql_runner_storage``)."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Sequence
from typing import Any, Protocol, Self

from pyfect import layer as layer_
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._service_copy import replaced
from pyfect.cluster import shard_id as shard_id_
from pyfect.cluster.cluster_error import PersistenceError
from pyfect.cluster.machine_id import MachineId
from pyfect.cluster.runner import Runner
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.shard_id import ShardId
from pyfect.context import Tag
from pyfect.effect import succeed, sync


class RunnerStorageService:
    """Where the cluster's runners register and lock their shards
    (Effect's ``RunnerStorage``). ``copy.replace(storage, acquire=...)``
    swaps an operation."""

    __slots__ = (
        "_acquire",
        "_get_runners",
        "_refresh",
        "_register",
        "_release",
        "_release_all",
        "_set_runner_health",
        "_unregister",
    )

    def __replace__(self, **changes: Any) -> Self:
        """A copy with ``changes`` to the constructor's arguments (``copy.replace``)."""
        return replaced(self, changes)

    def __init__(
        self,
        *,
        register: Callable[[Runner, bool], Effect[MachineId, PersistenceError]],
        unregister: Callable[[RunnerAddress], Effect[None, PersistenceError]],
        get_runners: Effect[list[tuple[Runner, bool]], PersistenceError],
        set_runner_health: Callable[[RunnerAddress, bool], Effect[None, PersistenceError]],
        acquire: Callable[
            [RunnerAddress, Iterable[ShardId]], Effect[list[ShardId], PersistenceError]
        ],
        refresh: Callable[
            [RunnerAddress, Iterable[ShardId]], Effect[list[ShardId], PersistenceError]
        ],
        release: Callable[[RunnerAddress, ShardId], Effect[None, PersistenceError]],
        release_all: Callable[[RunnerAddress], Effect[None, PersistenceError]],
    ) -> None:
        self._register = register
        self._unregister = unregister
        self._get_runners = get_runners
        self._set_runner_health = set_runner_health
        self._acquire = acquire
        self._refresh = refresh
        self._release = release
        self._release_all = release_all

    def register(self, runner: Runner, healthy: bool) -> Effect[MachineId, PersistenceError]:
        """Registers ``runner`` (replacing one at its address) with its
        health, and gives the machine id it is assigned. Fails with
        ``PersistenceError`` when the storage cannot be written."""
        return self._register(runner, healthy)

    def unregister(self, address: RunnerAddress) -> Effect[None, PersistenceError]:
        """Removes the runner at ``address``. Fails with
        ``PersistenceError`` when the storage cannot be written."""
        return self._unregister(address)

    @property
    def get_runners(self) -> Effect[list[tuple[Runner, bool]], PersistenceError]:
        """Every registered runner with whether it is healthy (a stored
        runner that does not decode is skipped). Fails with
        ``PersistenceError`` when the storage cannot be read."""
        return self._get_runners

    def set_runner_health(
        self, address: RunnerAddress, healthy: bool
    ) -> Effect[None, PersistenceError]:
        """Records whether the runner at ``address`` is healthy. Fails with
        ``PersistenceError`` when the storage cannot be written."""
        return self._set_runner_health(address, healthy)

    def acquire(
        self, address: RunnerAddress, shard_ids: Iterable[ShardId]
    ) -> Effect[list[ShardId], PersistenceError]:
        """Takes for the runner at ``address`` the locks it can of
        ``shard_ids``, and gives back the shards it now holds. Fails with
        ``PersistenceError`` when the storage cannot be written."""
        return self._acquire(address, shard_ids)

    def refresh(
        self, address: RunnerAddress, shard_ids: Iterable[ShardId]
    ) -> Effect[list[ShardId], PersistenceError]:
        """Extends the locks of ``shard_ids`` the runner at ``address``
        still holds, and gives back those shards. Fails with
        ``PersistenceError`` when the storage cannot be written."""
        return self._refresh(address, shard_ids)

    def release(self, address: RunnerAddress, shard_id: ShardId) -> Effect[None, PersistenceError]:
        """Releases the lock the runner at ``address`` holds on
        ``shard_id``. Fails with ``PersistenceError`` when the storage
        cannot be written."""
        return self._release(address, shard_id)

    def release_all(self, address: RunnerAddress) -> Effect[None, PersistenceError]:
        """Releases every shard lock the runner at ``address`` holds. Fails
        with ``PersistenceError`` when the storage cannot be written."""
        return self._release_all(address)


class RunnerStorage(Tag[RunnerStorageService], key="effect/cluster/RunnerStorage"):
    """The runner storage of this cluster."""


class EncodedRunnerStorage(Protocol):
    """What a runner storage driver implements (Effect's
    ``RunnerStorage.Encoded``): addresses are ``host:port``, runners their
    JSON text, shards ``group:id``. ``acquire`` gets at least one shard."""

    @property
    def get_runners(self) -> Effect[list[tuple[str, bool]], PersistenceError]: ...

    def register(
        self, address: str, runner: str, healthy: bool, /
    ) -> Effect[int, PersistenceError]: ...

    def unregister(self, address: str, /) -> Effect[None, PersistenceError]: ...

    def set_runner_health(
        self, address: str, healthy: bool, /
    ) -> Effect[None, PersistenceError]: ...

    def acquire(
        self, address: str, shard_ids: Sequence[str], /
    ) -> Effect[list[str], PersistenceError]: ...

    def refresh(
        self, address: str, shard_ids: Sequence[str], /
    ) -> Effect[list[str], PersistenceError]: ...

    def release(self, address: str, shard_id: str, /) -> Effect[None, PersistenceError]: ...

    def release_all(self, address: str, /) -> Effect[None, PersistenceError]: ...


_runner_json = S.from_json_string(Runner)
_encode_runner = S.encode_sync(_runner_json)
_decode_runner = S.decode_unknown_sync(_runner_json)


def encode_runner(runner: Runner) -> str:
    """A runner as stored: its JSON text."""
    return _encode_runner(runner)


def encode_runner_address(address: RunnerAddress) -> str:
    return f"{address.host}:{address.port}"


def _decode_runners(rows: list[tuple[str, bool]]) -> list[tuple[Runner, bool]]:
    """The rows that decode (a malformed runner is left out)."""
    runners: list[tuple[Runner, bool]] = []
    for text, healthy in rows:
        try:
            runners.append((_decode_runner(text), healthy))
        except S.SchemaError:
            continue
    return runners


def make_encoded(encoded: EncodedRunnerStorage) -> RunnerStorageService:
    """A runner storage on the driver ``encoded``."""

    def acquire(
        address: RunnerAddress, shard_ids: Iterable[ShardId]
    ) -> Effect[list[ShardId], PersistenceError]:
        shards = [str(s) for s in shard_ids]
        if not shards:
            return succeed([])
        return encoded.acquire(encode_runner_address(address), shards).map(_shard_ids)

    def refresh(
        address: RunnerAddress, shard_ids: Iterable[ShardId]
    ) -> Effect[list[ShardId], PersistenceError]:
        shards = [str(s) for s in shard_ids]
        return encoded.refresh(encode_runner_address(address), shards).map(_shard_ids)

    return RunnerStorageService(
        register=lambda runner, healthy: encoded.register(
            encode_runner_address(runner.address), encode_runner(runner), healthy
        ).map(MachineId),
        unregister=lambda address: encoded.unregister(encode_runner_address(address)),
        get_runners=encoded.get_runners.map(_decode_runners),
        set_runner_health=lambda address, healthy: encoded.set_runner_health(
            encode_runner_address(address), healthy
        ),
        acquire=acquire,
        refresh=refresh,
        release=lambda address, shard: encoded.release(encode_runner_address(address), str(shard)),
        release_all=lambda address: encoded.release_all(encode_runner_address(address)),
    )


def _shard_ids(shards: list[str]) -> list[ShardId]:
    return [shard_id_.from_string(s) for s in shards]


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

__all__ = [
    "EncodedRunnerStorage",
    "PersistenceError",
    "RunnerStorage",
    "RunnerStorageService",
    "encode_runner",
    "encode_runner_address",
    "layer_memory",
    "make_encoded",
    "make_memory",
]
