"""Shard acquisition: takes the locks of the shards assigned to this
runner from ``RunnerStorage``, refreshes them, releases the shards that
moved away (stopping their entities and singletons first), and hands
every shard off on shutdown. It shuts down last, once every entity has
stopped, so they can move to another runner."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
from collections.abc import Sequence
from typing import Any, Never

from pyfect import cause as Cause
from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect.clock import sleep
from pyfect.cluster import cluster_metrics
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.shard_id import ShardId
from pyfect.duration import Seconds
from pyfect.effect import gen, succeed, suspend, sync
from pyfect.fiber_map import FiberMap
from pyfect.logger import log_error, log_info, log_warning
from pyfect.schedule import fixed, spaced
from pyfect.scope import CloseableScope, fork_in

from ._singletons import Singletons
from ._state import ShardingState

_VOID: Effect[None] = succeed(None)


class ShardAcquisition:
    """The acquisition loop's state on a runner with an address."""

    __slots__ = (
        "_forced_release_running",
        "_release_map",
        "_release_scope",
        "_self_address",
        "_state",
    )

    def __init__(
        self,
        state: ShardingState,
        self_address: RunnerAddress,
        release_scope: CloseableScope,
        release_map: FiberMap[ShardId, Any, Any],
    ) -> None:
        self._state = state
        self._self_address = self_address
        self._release_scope = release_scope
        self._release_map = release_map
        self._forced_release_running = False

    @property
    def _singletons(self) -> Singletons:
        """Made after the loops fork, which wait on ``singletons_ready``."""
        singletons = self._state.singletons
        assert singletons is not None, "the loops wait on singletons_ready"
        return singletons

    def _annotations(self, fiber: str, **extra: object) -> dict[str, object]:
        return {
            "module": "effect/cluster/Sharding",
            "runner": self._self_address,
            "fiber": fiber,
            **extra,
        }

    # --- interrupting a shard's entities --------------------------------------------------

    def fork_interrupt_shards(
        self, shard_ids: Sequence[ShardId], force: bool
    ) -> Effect[list[Fiber[None, Never]]]:
        """Interrupt the shards' entities on every open entity manager."""
        state = self._state

        @gen
        def run():
            fibers: list[Fiber[None, Never]] = []
            for shard_id in shard_ids:
                for manager in list(state.entity_managers.values()):
                    if manager.status == "closed":
                        continue
                    fiber = yield from fork_in(
                        manager.manager.interrupt_shard(shard_id, force=force),
                        self._release_scope,
                        start_immediately=True,
                    )
                    fibers.append(fiber)
            return fibers

        return run

    # --- releasing ------------------------------------------------------------------------

    def forced_release_pending(self) -> bool:
        """The forced release ends with ``release_all``, which drops every
        lock of this runner: shards are not reacquired while it is
        pending, or it would wipe a lock already considered acquired."""
        return self._forced_release_running or bool(self._state.force_releasing_shards)

    def check_handed_off(self) -> None:
        """Called from the acquisition loop only, so no ``acquire`` is in
        flight."""
        state = self._state
        if (
            state.handoff_latch.is_open()
            and not state.acquired_shards
            and not state.releasing_shards
            and not self.forced_release_pending()
        ):
            state.handed_off_latch.open_unsafe()

    def _run_release(
        self, shard_ids: Sequence[ShardId], force: bool, release: Effect[None, Any]
    ) -> Effect[None, Any]:
        """Interrupt the shards' entities, wait for lock health, release,
        then clear the shards' bookkeeping."""
        state = self._state

        @gen
        def run():
            fibers = yield from self.fork_interrupt_shards(shard_ids, force)
            yield from Fiber.join_all(fibers)
            # Stop the singletons of shards no longer acquired, and wait for
            # those on the released shards.
            yield from self._singletons.start_sync()
            yield from self._singletons.await_stopping(shard_ids)
            yield from state.shard_locks_healthy_latch.wait()
            yield from release
            for shard_id in shard_ids:
                state.releasing_shards.discard(shard_id)
                state.force_releasing_shards.discard(shard_id)
                state.update_releasing_gauge()
                # On shutdown, parked waiters are interrupted: this runner
                # never sees the reply. On a rebalance they fail with
                # ``EntityNotAssignedToRunner`` and fall back to storage.
                yield from state.storage.unregister_shard_reply_handlers(
                    shard_id, interrupt=state.is_shutdown
                )
            # Let the acquisition loop check whether the handoff has ended.
            if state.handoff_latch.is_open():
                state.active_shards_latch.open_unsafe()

        return run

    def _retry_release[A](self, effect: Effect[A, Any], fiber: str, **extra: object) -> Effect[A]:
        state = self._state
        annotations = self._annotations(fiber, **extra)

        def run() -> Effect[A]:
            last_warning = [-math.inf]

            def warn(cause: Cause.Cause[Any]) -> Effect[None]:
                def check() -> Effect[None]:
                    now = state.now_millis()
                    if now - last_warning[0] < 30_000:
                        return _VOID
                    last_warning[0] = now
                    return log_warning("Could not release shards, retrying", cause)

                # ``eventually`` retries at once, so space failures to avoid
                # hot-looping while storage is unavailable.
                return suspend(check).annotate_logs(annotations).and_then(sleep(Seconds(0.05)))

            return effect.sandbox().tap_error(warn).eventually()

        return suspend(run)

    def release_shard(self, shard_id: ShardId) -> Effect[None]:
        state = self._state
        release = self._run_release(
            [shard_id],
            shard_id in state.force_releasing_shards,
            state.runner_storage.release(self._self_address, shard_id),
        )

        def record(timed: tuple[Seconds, None]) -> Effect[None]:
            return cluster_metrics.shard_release_duration.update(timed[0])

        tracked = (
            self._retry_release(release, "releaseShard", shardId=shard_id).timed().flat_map(record)
        )
        return self._release_map.run(shard_id, tracked, only_if_missing=True).as_void()

    def _warn_forced_release_pending(self) -> Effect[None]:
        state = self._state

        def run() -> Effect[None]:
            forced = list(state.force_releasing_shards)
            entity_types = [
                entity_type
                for entity_type, manager in state.entity_managers.items()
                if any(manager.manager.has_servers_unsafe(shard_id) for shard_id in forced)
            ]
            names: dict[str, None] = {}
            for shard_id in forced:
                for address in self._singletons.addresses_of(shard_id):
                    if self._singletons.is_running_unsafe(address):
                        names[address.name] = None
            for address in self._singletons.stopping_addresses():
                if address.shard_id in state.force_releasing_shards:
                    names[address.name] = None
            return log_warning(
                "Forced shard release is still pending; reacquisition is blocked until release "
                "completes"
            ).annotate_logs(
                {
                    "module": "effect/cluster/Sharding",
                    "runner": self._self_address,
                    "shardIds": [str(shard_id) for shard_id in forced],
                    "entityTypes": entity_types,
                    "singletonNames": list(names),
                }
            )

        return suspend(run)

    def release_forced_shards(self) -> Effect[None]:
        state = self._state

        def start() -> Effect[None]:
            if self._forced_release_running or not state.force_releasing_shards:
                return _VOID
            self._forced_release_running = True
            shard_ids = tuple(state.force_releasing_shards)
            interval = Seconds(max(state.config.shard_lock_expiration, 30))

            @gen
            def run():
                # Observe independently: a timeout around the release cannot
                # interrupt uninterruptible work, and must not allow locks
                # to be reacquired.
                monitor = yield from fork_in(
                    self._warn_forced_release_pending()
                    .repeat(spaced(interval))
                    .delay(state.config.shard_lock_expiration)
                    .interruptible(),
                    self._release_scope,
                )
                released = self._run_release(
                    shard_ids, True, state.runner_storage.release_all(self._self_address)
                )
                yield from self._retry_release(released, "releaseForcedShards").ensuring(
                    monitor.interrupt()
                )

            def done() -> None:
                self._forced_release_running = False
                state.active_shards_latch.open_unsafe()

            return fork_in(run.ensuring(sync(done)), self._release_scope).as_void()

        return suspend(start)

    def release_shards(self) -> Effect[None]:
        state = self._state

        @gen
        def run():
            yield from self.release_forced_shards()
            for shard_id in list(state.releasing_shards):
                if shard_id in state.force_releasing_shards:
                    continue
                if self._release_map.has_unsafe(shard_id):
                    continue
                yield from self.release_shard(shard_id)

        return run

    # --- the loops ------------------------------------------------------------------------

    def acquisition_loop(self) -> Effect[None]:
        state = self._state
        address = self._self_address

        @gen
        def body():
            yield from state.singletons_ready.wait()
            state.active_shards_latch.open_unsafe()
            while True:
                yield from state.active_shards_latch.wait()
                state.active_shards_latch.close_unsafe()

                # Release the shards no longer assigned to this runner, or
                # every shard when handing off.
                handing_off = state.handoff_latch.is_open()
                for shard_id in list(state.acquired_shards):
                    if not handing_off and shard_id in state.self_shards:
                        continue
                    state.acquired_shards.discard(shard_id)
                    state.releasing_shards.add(shard_id)
                state.update_shard_gauges()

                if state.releasing_shards or state.force_releasing_shards:
                    yield from fork_in(self._singletons.sync(), state.sharding_scope)
                    yield from self.release_shards()
                self.check_handed_off()

                if not state.shard_locks_healthy_latch.is_open():
                    continue
                # Wait for the pending bulk release before reacquiring, so
                # it cannot drop a lock acquired here.
                if self.forced_release_pending():
                    continue
                # A runner that is shutting down takes no new shards.
                if state.is_shutdown:
                    continue

                unacquired = [
                    shard_id
                    for shard_id in state.self_shards
                    if shard_id not in state.acquired_shards
                    and shard_id not in state.releasing_shards
                ]
                if not unacquired:
                    continue

                found = yield from state.runner_storage.acquire(address, unacquired).timeout_option(
                    state.shard_lock_interval
                )
                if found is None:
                    state.active_shards_latch.open_unsafe()
                    continue
                acquired = found.value
                yield from (
                    state.storage.reset_shards(acquired)
                    .ignore()
                    .timeout_option(state.shard_lock_interval)
                )
                # A forced release can start while ``acquire`` is in flight,
                # so check it here as well as before acquiring.
                forced_pending = self.forced_release_pending()
                for shard_id in acquired:
                    if (
                        not state.shard_locks_healthy_latch.is_open()
                        or forced_pending
                        or shard_id in state.releasing_shards
                        or shard_id not in state.self_shards
                    ):
                        state.releasing_shards.add(shard_id)
                        continue
                    state.acquired_shards.add(shard_id)
                state.update_shard_gauges()
                if acquired:
                    yield from state.notify_shard_lock_waiters()
                    yield from state.storage_read_latch.open()
                    yield from fork_in(self._singletons.sync(), state.sharding_scope)
                # The shutdown handoff releases the shards acquired here
                # without waiting.
                yield from sleep(Seconds(1)).race_first(state.handoff_latch.wait())
                state.active_shards_latch.open_unsafe()

        def failed(cause: Cause.Cause[Any]) -> Effect[None]:
            return log_warning("Could not acquire/release shards", cause)

        return (
            body.catch_cause(failed)
            .repeat(spaced(state.config.entity_message_poll_interval))
            .as_void()
            .annotate_logs(
                {
                    "module": "effect/cluster/Sharding",
                    "fiber": "Shard acquisition loop",
                    "runner": address,
                }
            )
        )

    def _mark_unhealthy(self, cause: Cause.Cause[Any]) -> Effect[None]:
        state = self._state

        def run() -> Effect[None]:
            if not state.shard_locks_healthy_latch.close_unsafe():
                return _VOID
            affected = tuple(dict.fromkeys((*state.acquired_shards, *state.releasing_shards)))
            state.self_shards.clear()
            state.acquired_shards.clear()
            for shard_id in affected:
                state.releasing_shards.add(shard_id)
                state.force_releasing_shards.add(shard_id)
            state.update_shard_gauges()
            state.active_shards_latch.open_unsafe()

            @gen
            def after():
                yield from state.notify_shard_lock_waiters()
                yield from log_error("Shard lock storage is unhealthy", cause)
                yield from fork_in(
                    self._singletons.sync(), state.sharding_scope, start_immediately=True
                )
                yield from self.fork_interrupt_shards(affected, True)
                state.active_shards_latch.open_unsafe()

            return after

        return suspend(run)

    def _mark_healthy(self) -> Effect[None]:
        state = self._state

        def run() -> Effect[None]:
            if not state.shard_locks_healthy_latch.open_unsafe():
                return _VOID
            state.self_shards.clear()
            for shard_id, runner in state.shard_assignments.items():
                if state.is_local_runner(runner):
                    state.self_shards.add(shard_id)
            state.active_shards_latch.open_unsafe()
            return log_info("Shard lock storage has recovered")

        return suspend(run)

    def _refresh(self) -> Effect[None]:
        state = self._state
        address = self._self_address

        @gen
        def run():
            refreshed = [*state.acquired_shards, *state.releasing_shards]
            acquired = yield from state.runner_storage.refresh(address, refreshed)
            # Shards acquired during the request are absent from its response.
            for shard_id in refreshed:
                if shard_id in state.acquired_shards and shard_id not in acquired:
                    state.acquired_shards.discard(shard_id)
                    state.releasing_shards.add(shard_id)
            for shard_id in acquired:
                if shard_id not in state.self_shards:
                    state.acquired_shards.discard(shard_id)
                    state.releasing_shards.add(shard_id)
            state.update_shard_gauges()
            if state.releasing_shards:
                yield from state.active_shards_latch.open()

        return (
            run.retry(times=5, schedule=spaced(Seconds(0.05)))
            .timeout(state.shard_lock_interval)
            .catch_cause(self._mark_unhealthy)
        )

    def _probe(self) -> Effect[None]:
        state = self._state

        def failed(cause: Cause.Cause[Any]) -> Effect[None]:
            return log_warning("Shard lock storage is still unhealthy", cause)

        return (
            state.runner_storage.refresh(self._self_address, [])
            .timeout(state.shard_lock_interval)
            .and_then(self._mark_healthy())
            .catch_cause(failed)
        )

    def refresh_loop(self) -> Effect[Never]:
        """Refresh the locks at the lease-safe interval, or probe storage
        while lock ownership is uncertain."""
        state = self._state

        def step() -> Effect[None]:
            return self._refresh() if state.shard_locks_healthy_latch.is_open() else self._probe()

        return state.singletons_ready.wait().and_then(
            suspend(step).repeat(fixed(state.shard_lock_interval)).forever()
        )

    def make_handoff(self) -> Effect[None]:
        """Release every held shard through the per-shard path, forcing
        their entities to stop. Best effort: the wait is bounded, and a
        final ``release_all`` takes what is left."""
        state = self._state

        def start() -> Effect[list[Fiber[None, Never]]]:
            if state.handoff_latch.open_unsafe():
                state.active_shards_latch.open_unsafe()
            return self.fork_interrupt_shards(
                list(dict.fromkeys([*state.acquired_shards, *state.releasing_shards])), True
            )

        return (
            suspend(start)
            .and_then(state.handed_off_latch.wait().timeout_option(state.shard_lock_interval))
            .as_void()
        )


__all__ = ["ShardAcquisition"]
