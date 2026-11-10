"""Confirms a shard lock before a persisted request's final reply is stored.

This runner's view of its shards lags lock storage by up to one refresh, or
longer while the process is paused. So the reply is stored only once a
refresh of its shard's lock confirms it. Anything short of that, including a
refresh that failed, timed out, was interrupted, or never started because
shutdown closed the sharding scope, leaves the reply for the shard's next
owner. Concurrent writers on a shard share one refresh, which outlives an
interrupted writer. Entities draining from a released shard still hold its
lock."""

from __future__ import annotations

from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.shard_id import ShardId
from pyfect.effect import succeed, suspend
from pyfect.exit import Exit, Success
from pyfect.scope import fork_in

from ._state import ShardingState


class ShardFence:
    __slots__ = ("_pending", "_state")

    def __init__(self, state: ShardingState) -> None:
        self._state = state
        self._pending: dict[ShardId, Fiber[bool, object]] = {}

    def is_shard_owned(self, runner_address: RunnerAddress, shard_id: ShardId) -> Effect[bool]:
        """Whether a lock refresh confirms this runner still holds
        ``shard_id``."""
        state = self._state

        def confirmed(exit: Exit[bool, object]) -> bool:
            return isinstance(exit, Success) and exit.value

        def body() -> Effect[bool]:
            if shard_id not in state.acquired_shards and shard_id not in state.releasing_shards:
                return succeed(False)
            pending = self._pending.get(shard_id)
            check = (
                succeed(pending)
                if pending is not None
                else self._start_check(runner_address, shard_id)
            )
            return check.flat_map(lambda fiber: fiber.await_exit()).map(confirmed)

        return suspend(body)

    def _start_check(
        self, runner_address: RunnerAddress, shard_id: ShardId
    ) -> Effect[Fiber[bool, object]]:
        state = self._state

        def apply(acquired: list[ShardId]) -> bool:
            state.release_lost_shards([shard_id], acquired)
            return shard_id in acquired

        refresh = (
            state.runner_storage.refresh(runner_address, [shard_id])
            .map(apply)
            .timeout_option(state.shard_lock_interval)
            .map(lambda found: found is not None and found.value)
            .catch_all(lambda _: succeed(False))
        )

        def track(fiber: Fiber[bool, object]) -> Fiber[bool, object]:
            self._pending[shard_id] = fiber

            def forget(_: Exit[bool, object]) -> None:
                if self._pending.get(shard_id) is fiber:
                    del self._pending[shard_id]

            fiber.add_observer_unsafe(forget)
            return fiber

        return fork_in(refresh, state.sharding_scope, start_immediately=True).map(track)


__all__ = ["ShardFence"]
