"""Keeps this runner's view of the runners and shard assignments in sync
with ``RunnerStorage``, and runs the health checks of the other runners
as a singleton. It shuts down after the clients, which may still need
shard assignments while entities shut down."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, Never

from pyfect import cause as Cause
from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect.clock import sleep
from pyfect.cluster import cluster_metrics
from pyfect.cluster.runner import Runner
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.shard_id import ShardId
from pyfect.context import Context
from pyfect.duration import Seconds
from pyfect.effect import gen, succeed
from pyfect.hash_ring import HashRing
from pyfect.logger import log_debug, log_warning
from pyfect.schedule import spaced

from ._state import ShardingState

_VOID: Effect[None] = succeed(None)


def _with_timeout[A, E](effect: Effect[A, E]) -> Effect[A, Any]:
    return effect.timeout(5)


def sync_loop(state: ShardingState) -> Effect[Never]:  # noqa: PLR0915
    self_runner = state.self_runner

    @gen
    def run():  # noqa: PLR0912, PLR0915
        rings: dict[str, HashRing[RunnerAddress]] = {}
        next_runners: dict[Runner, bool] = {}
        healthy_runners: set[Runner] = set()

        def register_self():
            if state.is_shutdown or self_runner is None:
                return
            yield from log_debug("Registering runner", self_runner)
            machine_id = yield from _with_timeout(state.runner_storage.register(self_runner, True))
            yield from state.snowflakes.set_machine_id(machine_id)

        while True:
            # Make sure this runner is registered.
            if (
                self_runner is not None
                and not state.is_shutdown
                and self_runner not in state.all_runners
            ):
                yield from state.registration_lock.with_permits(gen(register_self))

            runners = yield from _with_timeout(state.runner_storage.get_runners)
            changed = False
            for runner, healthy in runners:
                next_runners[runner] = healthy
                was_healthy = runner in healthy_runners
                if not healthy or was_healthy:
                    if healthy == was_healthy or not was_healthy:
                        # No change.
                        state.all_runners.pop(runner, None)
                    continue
                changed = True
                healthy_runners.add(runner)
                state.all_runners.pop(runner, None)
                for group in runner.groups:
                    ring = rings.get(group)
                    if ring is None:
                        ring = HashRing[RunnerAddress]()
                        rings[group] = ring
                    ring.add(runner.address, weight=runner.weight)

            # Remove the runners no longer present or healthy.
            for runner in list(state.all_runners):
                changed = True
                del state.all_runners[runner]
                healthy_runners.discard(runner)
                state.run_fork(state.runners.on_runner_unavailable(runner.address))
                for group in runner.groups:
                    found = rings.get(group)
                    if found is not None:
                        found.remove(runner.address)

            previous = state.all_runners
            state.all_runners = next_runners
            next_runners = previous
            next_runners.clear()
            state.healthy_runner_count = len(healthy_runners)

            # Make sure this runner is registered.
            if (
                self_runner is not None
                and not state.is_shutdown
                and self_runner not in state.all_runners
            ):
                continue

            # Recompute the shard assignments when the healthy runners changed.
            if changed:
                state.self_shards.clear()
                for group, ring in rings.items():
                    assignments = ring.get_shards(state.config.shards_per_group)
                    for i in range(state.config.shards_per_group):
                        shard = ShardId(group=group, id=i + 1)
                        if assignments is not None:
                            owner = assignments[i]
                            state.shard_assignments[shard] = owner
                            if state.shard_locks_healthy_latch.is_open() and state.is_local_runner(
                                owner
                            ):
                                state.self_shards.add(shard)
                        else:
                            state.shard_assignments.pop(shard, None)
                yield from log_debug("New shard assignments", sorted(map(str, state.self_shards)))
                state.active_shards_latch.open_unsafe()
                yield from state.notify_shard_lock_waiters()
                if self_runner is not None:
                    cluster_metrics.runners_healthy.update_unsafe(
                        1 if self_runner in healthy_runners else 0, Context.empty()
                    )

            if self_runner is not None and not healthy_runners:
                yield from log_warning("No healthy runners available")
                # To prevent a deadlock, mark this runner healthy to start the
                # health check singleton again.
                yield from _with_timeout(
                    state.runner_storage.set_runner_health(self_runner.address, True)
                )

            yield from sleep(state.config.refresh_assignments_interval)

    def failed(cause: Cause.Cause[Any]) -> Effect[None]:
        return log_debug(cause)

    return (
        run.catch_cause(failed)
        .repeat(spaced(Seconds(1)))
        .annotate_logs(
            {
                "module": "effect/cluster/Sharding",
                "fiber": "RunnerStorage sync",
                "runner": state.runner_address,
            }
        )
        .forever()
    )


def health_check(state: ShardingState) -> Effect[Never]:
    """Check the other runners' health and record it in storage; the
    last healthy runner is never marked unhealthy."""

    def check(item: tuple[Runner, bool]) -> Effect[None, Any]:
        runner, healthy = item

        def decided(alive: bool) -> Effect[None, Any]:
            if healthy == alive:
                return _VOID
            if alive:
                state.healthy_runner_count += 1
                return log_debug("Runner is healthy", runner).and_then(
                    state.runner_storage.set_runner_health(runner.address, alive)
                )
            if state.healthy_runner_count <= 1:
                return _VOID
            state.healthy_runner_count -= 1
            return log_debug("Runner is unhealthy", runner).and_then(
                state.runner_storage.set_runner_health(runner.address, alive)
            )

        return state.runner_health.is_alive(runner.address).flat_map(decided)

    @gen
    def run():
        while True:
            # Skip health checks when this is the only runner.
            if len(state.all_runners) > 1:
                yield from for_each(list(state.all_runners.items()), check, concurrency=10)
            yield from sleep(state.config.runner_health_check_interval)

    def failed(cause: Cause.Cause[Any]) -> Effect[None]:
        return log_debug("Runner health check failed", cause)

    return (
        run.catch_cause(failed)
        .forever()
        .annotate_logs({"module": "effect/cluster/Sharding", "fiber": "Runner health check"})
    )


__all__ = ["health_check", "sync_loop"]
