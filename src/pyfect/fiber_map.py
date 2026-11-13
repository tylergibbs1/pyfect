"""``FiberMap[K, A, E]``: at most one fiber per key, inside one scope.

Running or setting a fiber under a key that holds another interrupts the
old one (``only_if_missing=True`` keeps it and interrupts the newcomer
instead). Each fiber leaves the map when it completes; replaced fibers stay
owned until they finish interrupting, so closing the scope waits for their
cleanup too. ``join`` fails with the first member failure; interrupts only
count with ``propagate_interruption=True``, and never those the map sends
itself (replacing, ``remove``, ``clear``).

``runtime(*tags)`` returns a runner that forks root fibers into the map
from plain code, as Effect's ``FiberMap.runtime``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import threading
from collections.abc import Hashable, Iterator
from typing import Any, Generic, Never, TypeVar

from pyfect._core import (
    Effect,
    _AfterStarted,
    _Gen,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
)
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect._fiber_collections import (
    INTERNAL_FIBER_ID,
    CapturedRuntime,
    future_of,
    interrupted_fiber,
    live_items,
    reports_failure,
)
from pyfect._interrupt_reason import closed, interrupt_closed
from pyfect.context import TagLike
from pyfect.deferred import Deferred
from pyfect.exit import Exit
from pyfect.scheduler import Scheduler
from pyfect.scope import Scope, acquire_release


class _Entry[A, E]:
    """A key's place in the map. Replacing the fiber under a key keeps the
    entry; a key that leaves and comes back gets a new one, so ``clear``
    can tell the two apart as Effect's live ``Map`` iteration does."""

    __slots__ = ("fiber",)

    def __init__(self, fiber: Fiber[A, E]) -> None:
        self.fiber = fiber


class _Open[K, A, E]:
    __slots__ = ("by_key", "owned")

    def __init__(self) -> None:
        self.by_key: dict[K, _Entry[A, E]] = {}
        # Every fiber the map still owns: the keyed ones, plus replaced
        # fibers that are still interrupting.
        self.owned: dict[Fiber[A, E], None] = {}


K = TypeVar("K", bound=Hashable)
A_co = TypeVar("A_co", covariant=True, default=object)
E_co = TypeVar("E_co", covariant=True, default=object)


class FiberMap(Generic[K, A_co, E_co]):
    """Make one with ``FiberMap[K, A, E].make()`` inside a scope."""

    __slots__ = ("_lock", "_state", "deferred")

    def __init__(self) -> None:
        self._state: _Open[K, A_co, E_co] | None = _Open()  # None once the scope has closed
        # Runs on other threads share a map: its keys and owned fibers change
        # holding this; no fiber is interrupted or observed while it is held.
        self._lock = threading.Lock()
        # Completed by the first reported failure, or when the scope closes.
        # Typed as Effect's ``Deferred<void, unknown>``, so the class stays covariant.
        self.deferred: Deferred[None, Any] = Deferred()

    @classmethod
    def make(cls) -> Effect[FiberMap[K, A_co, E_co], Never, Scope]:
        """A map whose fibers are interrupted when the current scope closes."""
        return acquire_release(_Sync(cls), lambda m, _: m._close())

    @classmethod
    def make_runtime[XA, XE, R = Never](
        cls: type[FiberMap[K, XA, XE]], *tags: TagLike[Any, R]
    ) -> Effect[FiberMapRuntime[K, XA, XE, R], Never, Scope | R]:
        """``make`` and ``runtime`` in one."""
        return cls.make().flat_map(lambda m: m.runtime(*tags))

    @classmethod
    def make_runtime_async[XA, XE, R = Never](
        cls: type[FiberMap[K, XA, XE]], *tags: TagLike[Any, R]
    ) -> Effect[FiberMapAsyncRuntime[K, XA, XE, R], Never, Scope | R]:
        """``make`` and ``runtime_async`` in one."""
        return cls.make().flat_map(lambda m: m.runtime_async(*tags))

    def __iter__(self) -> Iterator[tuple[K, Fiber[A_co, E_co]]]:
        return iter([(key, entry.fiber) for key, entry in self._entries()])

    def _entries(self) -> list[tuple[K, _Entry[A_co, E_co]]]:
        with self._lock:
            return [] if self._state is None else list(self._state.by_key.items())

    def __repr__(self) -> str:
        state = self._state
        return "FiberMap(closed)" if state is None else f"FiberMap(size={len(state.by_key)})"

    def set_unsafe[XA, XE](
        self: FiberMap[K, XA, XE],
        key: K,
        fiber: Fiber[XA, XE],
        *,
        only_if_missing: bool = False,
        propagate_interruption: bool = False,
    ) -> None:
        """Put a running fiber under ``key``, interrupting the one there
        (or, with ``only_if_missing``, interrupting ``fiber`` instead). Into
        a closed map the fiber is interrupted."""
        previous: Fiber[XA, XE] | None = None
        with self._lock:
            state = self._state
            entry = None if state is None else state.by_key.get(key)
            if state is None:
                outcome = "closed"
            elif entry is not None and entry.fiber is fiber:
                outcome = "there"
            elif entry is not None and only_if_missing:
                outcome = "refused"
            else:
                outcome = "set"
                state.owned[fiber] = None
                if entry is None:
                    state.by_key[key] = _Entry(fiber)
                else:
                    # Install the replacement before the interrupt can re-enter
                    # the map through a finalizer.
                    previous, entry.fiber = entry.fiber, fiber
        match outcome:
            case "closed":
                fiber.interrupt_as_unsafe(INTERNAL_FIBER_ID, closed("FiberMap"))
                return
            case "there":
                return
            case "refused":
                fiber.interrupt_as_unsafe(INTERNAL_FIBER_ID)
                return
            case "set":
                if previous is not None:
                    previous.interrupt_as_unsafe(INTERNAL_FIBER_ID)

        def observer(ex: Exit[XA, XE]) -> None:
            with self._lock:
                state = self._state
                if state is not None:
                    state.owned.pop(fiber, None)
                    entry = state.by_key.get(key)
                    if entry is not None and entry.fiber is fiber:
                        del state.by_key[key]
            if state is not None and reports_failure(ex, propagate_interruption):
                self.deferred.done_unsafe(ex)

        fiber.add_observer_unsafe(observer)

    def set[XA, XE](
        self: FiberMap[K, XA, XE],
        key: K,
        fiber: Fiber[XA, XE],
        *,
        only_if_missing: bool = False,
        propagate_interruption: bool = False,
    ) -> Effect[None]:
        return _Sync(
            lambda: self.set_unsafe(
                key,
                fiber,
                only_if_missing=only_if_missing,
                propagate_interruption=propagate_interruption,
            )
        )

    def get_unsafe(self, key: K) -> Fiber[A_co, E_co] | None:
        state = self._state
        entry = None if state is None else state.by_key.get(key)
        return None if entry is None else entry.fiber

    def get(self, key: K) -> Effect[Fiber[A_co, E_co] | None]:
        return _Sync(lambda: self.get_unsafe(key))

    def has_unsafe(self, key: K) -> bool:
        state = self._state
        return state is not None and key in state.by_key

    def has(self, key: K) -> Effect[bool]:
        return _Sync(lambda: self.has_unsafe(key))

    def remove(self, key: K) -> Effect[None]:
        """Interrupt the fiber under ``key``, if any, and wait for it."""

        def body() -> Effect[None]:
            fiber = self.get_unsafe(key)
            return _Succeed(None) if fiber is None else fiber.interrupt_as(INTERNAL_FIBER_ID)

        return _Suspend(body)

    def clear(self) -> Effect[None]:
        """Interrupt every keyed fiber and wait for them."""

        def body() -> Effect[None]:
            if self._state is None:
                return _Succeed(None)
            return Fiber.interrupt_all_as(
                (entry.fiber for _, entry in live_items(self._entries)),
                INTERNAL_FIBER_ID,
            )

        return _Suspend(body)

    def run[XA, XE, R = Never](
        self: FiberMap[K, XA, XE],
        key: K,
        eff: Effect[XA, XE, R],
        *,
        only_if_missing: bool = False,
        propagate_interruption: bool = False,
        start_immediately: bool = True,
    ) -> Effect[Fiber[XA, XE], Never, R]:
        """Fork ``eff`` under ``key``. It starts at once unless
        ``start_immediately=False``. With ``only_if_missing`` and a fiber
        already there, gives back an interrupted fiber that never runs
        ``eff``. Running into a closed map interrupts the caller."""
        require_effect(eff, "eff")

        def body(parent: Fiber[Any, Any]) -> Effect[Fiber[XA, XE]]:
            if self._state is None:
                return interrupt_closed("FiberMap")
            if only_if_missing and self.has_unsafe(key):
                return _Succeed(interrupted_fiber(parent._run_scheduler, parent._context))
            fiber: Fiber[XA, XE] = parent._fork(
                eff, daemon=True, start_immediately=start_immediately
            )
            self.set_unsafe(
                key,
                fiber,
                only_if_missing=only_if_missing,
                propagate_interruption=propagate_interruption,
            )
            return _AfterStarted(fiber)

        return _WithFiber(body)

    def runtime[XA, XE, R = Never](
        self: FiberMap[K, XA, XE], *tags: TagLike[Any, R]
    ) -> Effect[FiberMapRuntime[K, XA, XE, R], Never, R]:
        """A runner that forks effects needing ``tags`` into the map, with
        the services of the fiber calling this."""
        return _WithFiber(lambda fiber: _Succeed(FiberMapRuntime(self, CapturedRuntime(fiber))))

    def runtime_async[XA, XE, R = Never](
        self: FiberMap[K, XA, XE], *tags: TagLike[Any, R]
    ) -> Effect[FiberMapAsyncRuntime[K, XA, XE, R], Never, R]:
        """``runtime``, but the runner returns a future of the value (needs
        a running asyncio loop when called)."""
        return self.runtime(*tags).map(FiberMapAsyncRuntime)

    def size(self) -> Effect[int]:
        return _Sync(lambda: len(self._entries()))

    def join(self) -> Effect[None, E_co]:
        """Wait for the first reported failure and fail with it; succeed
        when the scope closes."""
        return self.deferred.wait()

    def await_empty(self) -> Effect[None]:
        """Wait until no key holds a fiber (or the map is closed)."""

        def loop():
            while entries := self._entries():
                yield from entries[0][1].fiber.await_exit()

        return _Gen(loop)

    def _close(self) -> Effect[None]:
        def body() -> Effect[None]:
            with self._lock:
                state, self._state = self._state, None
                owned = [] if state is None else list(state.owned)
            if state is None:
                return _Succeed(None)
            return self.deferred.into(Fiber.interrupt_all(owned)).as_void()

        return _Suspend(body)


class FiberMapRuntime[K: Hashable, A, E, R]:
    """Forks effects into a ``FiberMap`` from plain code; see
    ``FiberMap.runtime``."""

    __slots__ = ("_map", "_runtime")

    def __init__(self, fiber_map: FiberMap[K, A, E], runtime: CapturedRuntime) -> None:
        self._map = fiber_map
        self._runtime = runtime

    def __call__(
        self,
        key: K,
        eff: Effect[A, E, R],
        /,
        *,
        only_if_missing: bool = False,
        propagate_interruption: bool = False,
        uninterruptible: bool = False,
        scheduler: Scheduler | None = None,
    ) -> Fiber[A, E]:
        """Fork ``eff`` on a root fiber under ``key``. A closed map, or a
        taken key with ``only_if_missing``, gives back an interrupted fiber
        that never runs ``eff``."""
        require_effect(eff, "eff")
        fiber_map = self._map
        if fiber_map._state is None:
            return self._runtime.interrupted(closed("FiberMap"))
        if only_if_missing and fiber_map.has_unsafe(key):
            return self._runtime.interrupted()
        fiber = self._runtime.fork(eff, uninterruptible=uninterruptible, scheduler=scheduler)
        fiber_map.set_unsafe(
            key,
            fiber,
            only_if_missing=only_if_missing,
            propagate_interruption=propagate_interruption,
        )
        return fiber


class FiberMapAsyncRuntime[K: Hashable, A, E, R]:
    """``FiberMapRuntime`` returning a future of the fiber's value."""

    __slots__ = ("_run",)

    def __init__(self, run: FiberMapRuntime[K, A, E, R]) -> None:
        self._run = run

    def __call__(
        self,
        key: K,
        eff: Effect[A, E, R],
        /,
        *,
        only_if_missing: bool = False,
        propagate_interruption: bool = False,
        uninterruptible: bool = False,
        scheduler: Scheduler | None = None,
    ) -> asyncio.Future[A]:
        require_effect(eff, "eff")
        return future_of(
            self._run(
                key,
                eff,
                only_if_missing=only_if_missing,
                propagate_interruption=propagate_interruption,
                uninterruptible=uninterruptible,
                scheduler=scheduler,
            )
        )


__all__ = ["FiberMap", "FiberMapAsyncRuntime", "FiberMapRuntime"]
