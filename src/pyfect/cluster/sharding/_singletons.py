"""Singletons on this runner: each runs while its shard is acquired and
stops when the shard is released. A stopping singleton counts as running,
so it is not restarted, and shard releases wait for it."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Sequence
from typing import Any, Never

from pyfect._concurrency import for_each
from pyfect._core import Effect, _Locally
from pyfect._fiber import Fiber
from pyfect.cluster import cluster_metrics
from pyfect.cluster._interruptors import around_shard
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.shard_id import ShardId
from pyfect.cluster.sharding_registration_event import SingletonRegistered
from pyfect.cluster.singleton_address import SingletonAddress
from pyfect.context import Context, Tag
from pyfect.effect import context, die, gen, never, succeed, suspend, sync
from pyfect.fiber_map import FiberMap
from pyfect.logger import CurrentLogAnnotations, log_debug
from pyfect.scope import add_finalizer, scoped
from pyfect.semaphore import Semaphore

from ._state import ShardingState

_VOID: Effect[None] = succeed(None)


class SingletonShard(Tag[ShardId], key="effect/cluster/Sharding/SingletonShard"):
    """The shard of the singleton running the current fiber."""


class Singletons:
    __slots__ = ("_fibers", "_lock", "_registered", "_state", "_stopping")

    def __init__(self, state: ShardingState, fibers: FiberMap[SingletonAddress, Any, Any]) -> None:
        self._state = state
        self._fibers = fibers
        self._lock = Semaphore(1)
        self._registered: dict[ShardId, dict[SingletonAddress, Effect[Never]]] = {}
        self._stopping: dict[SingletonAddress, Fiber[Any, Any]] = {}

    # --- reading --------------------------------------------------------------------------

    def is_registered(self, address: SingletonAddress) -> bool:
        found = self._registered.get(address.shard_id)
        return found is not None and address in found

    def is_running_unsafe(self, address: SingletonAddress) -> bool:
        return self._fibers.has_unsafe(address)

    def is_stopping(self, address: SingletonAddress) -> bool:
        return address in self._stopping

    def stopping_addresses(self) -> list[SingletonAddress]:
        return list(self._stopping)

    def addresses_of(self, shard_id: ShardId) -> list[SingletonAddress]:
        return list(self._registered.get(shard_id, {}))

    # --- stopping -------------------------------------------------------------------------

    def _stop_unsafe(self, address: SingletonAddress, active_teardown: bool) -> Effect[None]:
        """Called with the lock held: start stopping the singleton and give
        the wait for its teardown, to run without the lock."""
        stopping = self._stopping.get(address)
        if stopping is not None:
            return stopping.join()
        fiber = self._fibers.get_unsafe(address)
        if fiber is None:
            return _VOID
        interrupting = fiber.interrupt()
        if active_teardown:
            interrupting = around_shard(address.shard_id, interrupting)
        state = self._state
        parent = Fiber.get_current()
        assert parent is not None
        stop = parent._fork(
            _Locally(interrupting, lambda _: state.services), daemon=True, start_immediately=True
        )
        self._stopping[address] = stop

        def stopped(_: Any) -> None:
            self._stopping.pop(address, None)
            # A registration made while the previous singleton was stopping.
            if self.is_registered(address):
                state.run_fork(self.sync())

        stop.add_observer_unsafe(stopped)
        return stop.join()

    def await_stopping(self, shard_ids: Sequence[ShardId]) -> Effect[None]:
        """Wait for the singletons of ``shard_ids`` that are still stopping."""

        def run() -> Effect[None]:
            stops = [
                stop for address, stop in self._stopping.items() if address.shard_id in shard_ids
            ]
            return Fiber.join_all(stops).as_void()

        return suspend(run)

    # --- syncing --------------------------------------------------------------------------

    def start_sync(self) -> Effect[list[Effect[None]]]:
        """Start and stop singletons to match the acquired shards, giving
        the waits for the stopped ones."""
        state = self._state

        @gen
        def run():
            stops: list[Effect[None]] = []
            for shard_id, registered in list(self._registered.items()):
                for address, run_singleton in list(registered.items()):
                    stopping = address in self._stopping
                    running = stopping or self._fibers.has_unsafe(address)
                    should_run = shard_id in state.acquired_shards
                    if running and not should_run:
                        if not stopping:
                            yield from log_debug("Stopping singleton", address)
                        stops.append(self._stop_unsafe(address, True))
                    elif not running and should_run:
                        yield from log_debug("Starting singleton", address)
                        yield from self._fibers.run(address, run_singleton)
            cluster_metrics.singletons.update_unsafe(len(list(self._fibers)), Context.empty())
            return stops

        return self._lock.with_permits(run)

    def sync(self) -> Effect[None]:
        """``start_sync``, then wait for the stopped singletons without
        the lock."""
        return self.start_sync().flat_map(
            lambda stops: for_each(stops, lambda stop: stop).as_void()
        )

    # --- registering ----------------------------------------------------------------------

    def register(
        self, name: str, run: Effect[None, Any, Any], shard_group: str | None
    ) -> Effect[None, Never, Any]:
        state = self._state

        @gen
        def register_now():
            group = "default" if shard_group is None else shard_group
            address = SingletonAddress(
                shard_id=state.get_shard_id(EntityId(name), group), name=name
            )
            registered = self._registered.setdefault(address.shard_id, {})
            if address in registered:
                return (yield from die(RuntimeError(f"Singleton '{name}' is already registered")))
            services = yield from context()
            run_services = services.add(SingletonShard, address.shard_id)
            body: Effect[Never, Any] = _Locally(
                scoped(run.and_then(never)),
                lambda _: run_services.add(CurrentLogAnnotations, {}),
            )
            wrapped: Effect[Never] = body.or_die().interruptible()
            registered[address] = wrapped
            yield from state.events.publish(SingletonRegistered(address))
            # Start if this runner holds the shard, unless a previous
            # registration of this singleton is still stopping.
            if address.shard_id in state.acquired_shards and address not in self._stopping:
                yield from log_debug("Starting singleton", address)
                yield from self._fibers.run(address, wrapped)

            def unregister(_: Any) -> Effect[None]:
                def remove() -> Effect[None]:
                    self._registered.get(address.shard_id, {}).pop(address, None)
                    return self._stop_unsafe(address, False)

                return self._lock.with_permits(sync(remove)).flatten()

            yield from add_finalizer(unregister)

        return self._lock.with_permits(register_now)


__all__ = ["SingletonShard", "Singletons"]
