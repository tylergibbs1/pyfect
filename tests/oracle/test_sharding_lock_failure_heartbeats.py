"""pyfect-only: how much heartbeat slack a runner keeps while its shard lock
operations fail, on the test clock, over an in-memory runner storage whose
registrations expire like ``SqlRunnerStorage``'s (modelled on the shared
cluster storage of Effect-TS/effect#10676's tests).

The lock interval I is at most a third of ``shard_lock_expiration`` E, so a
healthy runner, heartbeating every I, survives a missed heartbeat. While its
lock operations fail it heartbeats only on probe ticks, every 2I, as Effect
4.1.4 does (``Sharding.ts`` lines 740-764), so one missed probe expires it.
After E of failures it unregisters itself on purpose (Effect-TS/effect#10689),
which is not counted as a missed read here."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass, field, replace
from typing import Any, Literal

import pytest

import pyfect as fx
from pyfect import exit as Exit
from pyfect import testing
from pyfect.clock import Clock, ClockService
from pyfect.cluster import (
    message_storage,
    runner_health,
    runners,
    sharding,
    sharding_config,
    snowflake,
)
from pyfect.cluster.cluster_error import PersistenceError
from pyfect.cluster.machine_id import MachineId
from pyfect.cluster.runner import Runner
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runner_storage import RunnerStorage, RunnerStorageService
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.shard_id import make as shard
from pyfect.duration import millis
from pyfect.scope import CloseableScope

INTERVAL = 500
"""Long enough for a failing refresh's retries (5 x 50 ms) to end before
its deadline, so the next tick probes."""
EXPIRATION = 3 * INTERVAL
LATE = INTERVAL // 2
"""How late a probe's heartbeat lands, within its deadline of one interval."""

_address = RunnerAddress(host="localhost", port=1234)
_shards = [shard("default", i + 1) for i in range(8)]

type Probe = Literal["hang"] | int
"""What the next probe does: never finish (its deadline cuts it off), or
write its heartbeat that many milliseconds late."""


@dataclass(eq=False)
class _Storage:
    clock: ClockService
    heartbeats: dict[RunnerAddress, tuple[Runner, float]] = field(
        default_factory=dict[RunnerAddress, tuple[Runner, float]]
    )
    fail_locks: bool = False
    probes: list[Probe] = field(default_factory=list[Probe])
    expired_reads: int = 0
    """Reads of the runners that missed the registered runner."""
    unregistered: int = 0
    """Times the runner unregistered itself."""

    def now(self) -> float:
        return self.clock.current_time_millis_unsafe()

    def heartbeat(self, address: RunnerAddress) -> None:
        entry = self.heartbeats.get(address)
        if entry is not None:
            self.heartbeats[address] = (entry[0], self.now())

    def service(self) -> RunnerStorageService:
        locks_failed: fx.Effect[Any, PersistenceError] = fx.fail(
            PersistenceError(cause="lock operation failed")
        )

        def get_runners() -> list[tuple[Runner, bool]]:
            # Registrations expire as in SqlRunnerStorage: alive while
            # last_heartbeat > now - expiration
            alive = [r for r, at in self.heartbeats.values() if at > self.now() - EXPIRATION]
            if self.heartbeats and not alive:
                self.expired_reads += 1
            return [(r, True) for r in alive]

        def register(runner: Runner, _healthy: bool) -> fx.Effect[MachineId, PersistenceError]:
            def run() -> MachineId:
                self.heartbeats[runner.address] = (runner, self.now())
                return MachineId(1)

            return fx.sync(run)

        def locked(shard_ids: Iterable[ShardId]) -> fx.Effect[list[ShardId], PersistenceError]:
            requested = list(shard_ids)
            return fx.suspend(lambda: locks_failed if self.fail_locks else fx.succeed(requested))

        def refresh(
            address: RunnerAddress, shard_ids: Iterable[ShardId]
        ) -> fx.Effect[list[ShardId], PersistenceError]:
            requested = list(shard_ids)

            def run() -> fx.Effect[list[ShardId], PersistenceError]:
                if requested:
                    # The heartbeat and the lock refresh fail together, as
                    # in SqlRunnerStorage's one statement deadline.
                    if self.fail_locks:
                        return locks_failed
                    self.heartbeat(address)
                    return fx.succeed(requested)
                probe = self.probes.pop(0) if self.probes else 0
                if probe == "hang":
                    return fx.never
                empty: list[ShardId] = []
                write = fx.sync(lambda: self.heartbeat(address)).as_(empty)
                return write.delay(millis(probe)) if probe else write

            return fx.suspend(run)

        def unregister(address: RunnerAddress) -> fx.Effect[None, PersistenceError]:
            def run() -> None:
                self.unregistered += 1
                self.heartbeats.pop(address, None)

            return fx.sync(run)

        def release(_address: RunnerAddress, _shard: ShardId) -> fx.Effect[None, PersistenceError]:
            return fx.suspend(lambda: locks_failed if self.fail_locks else fx.void)

        def release_all(_address: RunnerAddress) -> fx.Effect[None, PersistenceError]:
            return fx.suspend(lambda: locks_failed if self.fail_locks else fx.void)

        return RunnerStorageService(
            get_runners=fx.sync(get_runners),
            register=register,
            unregister=unregister,
            set_runner_health=lambda _address, _healthy: fx.void,
            acquire=lambda _address, shard_ids: locked(shard_ids),
            refresh=refresh,
            release=release,
            release_many=lambda address, shards: fx.for_each(
                shards, lambda shard: release(address, shard), discard=True
            ),
            release_all=release_all,
        )


def _expired_reads_after_lock_failure(probes: list[Probe]) -> fx.Effect[tuple[int, int]]:
    """Starts a runner, fails its lock operations for well over E and plays
    ``probes``, and counts the reads of the runners that missed it while it
    was registered, and its unregistrations."""
    config = replace(
        sharding_config.DEFAULTS,
        runner_address=_address,
        shards_per_group=len(_shards),
        entity_termination_timeout=millis(0),
        refresh_assignments_interval=millis(50),
        shard_lock_refresh_interval=millis(INTERVAL),
        shard_lock_expiration=millis(EXPIRATION),
    )

    @fx.gen
    def run():
        storage = _Storage((yield from Clock()))
        layer = (
            sharding.layer.pipe(
                fx.layer.provide(fx.layer.succeed(RunnerStorage, storage.service()))
            )
            .pipe(fx.layer.provide(runner_health.layer_noop))
            .pipe(fx.layer.provide(runners.layer_noop))
            .pipe(
                fx.layer.provide(
                    fx.layer.merge(message_storage.layer_memory, snowflake.layer_generator)
                )
            )
            .pipe(fx.layer.provide(sharding_config.layer(config)))
        )
        scope = CloseableScope()
        context = yield from layer.build_with_scope(scope)
        service = context.get_unsafe(sharding.Sharding)
        for _ in range(200):
            yield from testing.adjust("10 millis")
        assert all(service.has_shard_id(s) for s in _shards), "The runner did not take its shards"

        storage.fail_locks = True
        storage.probes = list(probes)
        for _ in range(400):
            yield from testing.adjust("10 millis")
        expired, unregistered = storage.expired_reads, storage.unregistered

        closing = yield from scope.close(Exit.succeed(None)).fork()
        while closing.poll_unsafe() is None:
            yield from testing.adjust("100 millis")
        return expired, unregistered

    return run


@testing.effect
def test_a_runner_whose_lock_operations_fail_survives_a_late_probe():
    expired, unregistered = yield from _expired_reads_after_lock_failure([LATE])
    assert expired == 0, f"{expired} reads missed the runner"
    # Its probes kept working, yet it left once the lock operations had failed for E.
    assert unregistered == 1, f"unregistered {unregistered} times"


@pytest.mark.xfail(
    strict=True,
    reason=(
        "Effect heartbeats only on probe ticks while lock storage fails (2I cadence); "
        "see Effect #10676"
    ),
)
@testing.effect
def test_a_runner_whose_lock_operations_fail_survives_a_probe_one_interval_late():
    # The first probe misses its deadline of one interval; the next is on time
    expired, _ = yield from _expired_reads_after_lock_failure(["hang"])
    assert expired == 0, f"{expired} reads missed the runner"
