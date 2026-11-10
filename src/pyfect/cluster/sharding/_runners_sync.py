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
from pyfect.duration import millis, to_millis
from pyfect.effect import gen, succeed
from pyfect.hash_ring import HashRing
from pyfect.logger import log_debug, log_warning
from pyfect.schedule import spaced

from ._state import ShardingState

_VOID: Effect[None] = succeed(None)


def _with_timeout[A, E](effect: Effect[A, E]) -> Effect[A, Any]:
    return effect.timeout("5 seconds")


class _Membership:
    """The sync loop's view of the runners, kept outside the loop so a
    restart after a storage failure neither drops it nor publishes pending
    joins early."""

    def __init__(self, state: ShardingState) -> None:
        self.state = state
        self.rings: dict[str, HashRing[RunnerAddress]] = {}
        self.next_runners: dict[Runner, bool] = {}
        self.healthy_runners: set[Runner] = set()
        self.join_debounce = to_millis(state.config.runner_join_debounce)
        # When the first pending join and the latest pending change were seen.
        self.pending_since = 0
        self.pending_changed_at = 0
        # The initial assignment never waits, even if this runner gets no shards.
        self.assignments_published = False
        # Stays set until the assignments are actually recomputed.
        self.changed = False

    def add_to_rings(self, runner: Runner) -> None:
        for group in runner.groups:
            ring = self.rings.get(group)
            if ring is None:
                ring = HashRing[RunnerAddress]()
                self.rings[group] = ring
            ring.add(runner.address, weight=runner.weight)

    def observe(self, runners: list[tuple[Runner, bool]]) -> None:
        """Apply one membership read: joins (held back while assignments
        settle), departures and health changes."""
        state = self.state
        pending = state.pending_runners
        now = state.now_millis()
        for runner, healthy in runners:
            self.next_runners[runner] = healthy
            was_healthy = runner in self.healthy_runners
            if not healthy or was_healthy:
                if healthy == was_healthy or not was_healthy:
                    # No change.
                    state.all_runners.pop(runner, None)
                continue
            self.healthy_runners.add(runner)
            state.all_runners.pop(runner, None)
            if self.join_debounce > 0 and self.assignments_published:
                if not pending:
                    self.pending_since = now
                self.pending_changed_at = now
                pending.add(runner)
                continue
            self.changed = True
            self.add_to_rings(runner)

        # Remove the runners no longer present or healthy.
        for runner in list(state.all_runners):
            del state.all_runners[runner]
            self.healthy_runners.discard(runner)
            state.run_fork(state.runners.on_runner_unavailable(runner.address))
            # A pending runner owns no shards, so its departure only restarts
            # the quiet period instead of publishing the other joins mid-burst.
            if runner in pending:
                pending.discard(runner)
                self.pending_changed_at = now
                if not pending:
                    # Let the acquisition loop take the shards it held off on.
                    state.active_shards_latch.open_unsafe()
                continue
            self.changed = True
            for group in runner.groups:
                found = self.rings.get(group)
                if found is not None:
                    found.remove(runner.address)

        # Publish pending joins once the healthy set has settled, the cap is
        # reached, or the assignments are recomputed anyway.
        if pending and (
            self.changed
            or now - self.pending_changed_at >= self.join_debounce
            or now - self.pending_since >= self.join_debounce * 4
        ):
            self.changed = True
            for runner in pending:
                self.add_to_rings(runner)
            pending.clear()

        previous = state.all_runners
        state.all_runners = self.next_runners
        self.next_runners = previous
        self.next_runners.clear()
        state.healthy_runner_count = len(self.healthy_runners)


def sync_loop(state: ShardingState) -> Effect[Never]:
    self_runner = state.self_runner
    membership = _Membership(state)

    def register_self():
        if state.is_shutdown or self_runner is None:
            return
        yield from log_debug("Registering runner", self_runner)
        machine_id = yield from _with_timeout(state.runner_storage.register(self_runner, True))
        yield from state.snowflakes.set_machine_id(machine_id)

    def publish():
        """Recompute the shard assignments from the hash rings."""
        membership.changed = False
        membership.assignments_published = True
        state.self_shards.clear()
        for group, ring in membership.rings.items():
            assignments = ring.get_shards(state.config.shards_per_group)
            for i in range(state.config.shards_per_group):
                shard = ShardId(group=group, id=i + 1)
                if assignments is not None:
                    owner = assignments[i]
                    state.shard_assignments[shard] = owner
                    if state.shard_locks_healthy_latch.is_open() and state.is_local_runner(owner):
                        state.self_shards.add(shard)
                else:
                    state.shard_assignments.pop(shard, None)
        yield from log_debug("New shard assignments", sorted(map(str, state.self_shards)))
        state.active_shards_latch.open_unsafe()
        yield from state.notify_shard_lock_waiters()
        if self_runner is not None:
            cluster_metrics.runners_healthy.update_unsafe(
                1 if self_runner in membership.healthy_runners else 0, Context.empty()
            )

    def unregistered() -> bool:
        return (
            self_runner is not None
            and not state.is_shutdown
            and self_runner not in state.all_runners
        )

    @gen
    def run():
        while True:
            # Make sure this runner is registered.
            if unregistered():
                yield from state.registration_lock.with_permits(gen(register_self))

            runners = yield from _with_timeout(state.runner_storage.get_runners)
            membership.observe(runners)

            # Make sure this runner is registered.
            if unregistered():
                continue

            # Recompute the shard assignments when the healthy runners changed.
            if membership.changed:
                yield from gen(publish)

            if self_runner is not None and not membership.healthy_runners:
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
        .repeat(spaced(millis(1000)))
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
