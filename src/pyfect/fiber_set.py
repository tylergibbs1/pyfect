"""``FiberSet[A, E]``: fibers managed together inside one scope.

Each fiber leaves the set when it completes, and the fibers still running
are interrupted when the set's scope closes. ``join`` fails with the first
member failure; interrupts only count with ``propagate_interruption=True``,
and never those the set sends itself (``clear``).

``runtime(*tags)`` captures the calling fiber's services (the tags name
what the runner's effects need) and returns a runner that forks root
fibers into the set from plain code, as Effect's ``FiberSet.runtime``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from collections.abc import Iterator
from typing import Any, Generic, Never, TypeVar

from pyfect._core import Effect, _AfterStarted, _Gen, _Succeed, _Suspend, _Sync, _WithFiber
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
from pyfect._interrupt_reason import closed
from pyfect.context import TagLike
from pyfect.deferred import Deferred
from pyfect.exit import Exit
from pyfect.scheduler import Scheduler
from pyfect.scope import Scope, acquire_release

A_co = TypeVar("A_co", covariant=True, default=object)
E_co = TypeVar("E_co", covariant=True, default=object)


class FiberSet(Generic[A_co, E_co]):
    """Make one with ``FiberSet[A, E].make()`` inside a scope."""

    __slots__ = ("_fibers", "deferred")

    def __init__(self) -> None:
        # None once the scope has closed. A dict keeps insertion order.
        self._fibers: dict[Fiber[A_co, E_co], None] | None = {}
        # Completed by the first reported failure, or when the scope closes.
        # Typed as Effect's ``Deferred<void, unknown>``, so the class stays covariant.
        self.deferred: Deferred[None, Any] = Deferred()

    @classmethod
    def make(cls) -> Effect[FiberSet[A_co, E_co], Never, Scope]:
        """A set whose fibers are interrupted when the current scope closes."""
        return acquire_release(_Sync(cls), lambda s, _: s._close())

    @classmethod
    def make_runtime[XA, XE, R = Never](
        cls: type[FiberSet[XA, XE]], *tags: TagLike[Any, R]
    ) -> Effect[FiberSetRuntime[XA, XE, R], Never, Scope | R]:
        """``make`` and ``runtime`` in one."""
        return cls.make().flat_map(lambda s: s.runtime(*tags))

    @classmethod
    def make_runtime_async[XA, XE, R = Never](
        cls: type[FiberSet[XA, XE]], *tags: TagLike[Any, R]
    ) -> Effect[FiberSetAsyncRuntime[XA, XE, R], Never, Scope | R]:
        """``make`` and ``runtime_async`` in one."""
        return cls.make().flat_map(lambda s: s.runtime_async(*tags))

    def __iter__(self) -> Iterator[Fiber[A_co, E_co]]:
        return iter(() if self._fibers is None else list(self._fibers))

    def __repr__(self) -> str:
        return "FiberSet(closed)" if self._fibers is None else f"FiberSet(size={len(self._fibers)})"

    def add_unsafe[XA, XE](
        self: FiberSet[XA, XE], fiber: Fiber[XA, XE], *, propagate_interruption: bool = False
    ) -> None:
        """Add a running fiber; it leaves the set when it completes. Into a
        closed set the fiber is interrupted. Call on the scheduler thread."""
        fibers = self._fibers
        if fibers is None:
            fiber.interrupt_as_unsafe(INTERNAL_FIBER_ID, closed("FiberSet"))
            return
        if fiber in fibers:
            return
        fibers[fiber] = None

        def observer(ex: Exit[XA, XE]) -> None:
            if self._fibers is None:
                return
            self._fibers.pop(fiber, None)
            if reports_failure(ex, propagate_interruption):
                self.deferred.done_unsafe(ex)

        fiber.add_observer_unsafe(observer)

    def add[XA, XE](
        self: FiberSet[XA, XE], fiber: Fiber[XA, XE], *, propagate_interruption: bool = False
    ) -> Effect[None]:
        return _Sync(lambda: self.add_unsafe(fiber, propagate_interruption=propagate_interruption))

    def run[XA, XE, R = Never](
        self: FiberSet[XA, XE],
        eff: Effect[XA, XE, R],
        *,
        propagate_interruption: bool = False,
        start_immediately: bool = True,
    ) -> Effect[Fiber[XA, XE], Never, R]:
        """Fork ``eff`` into the set. It starts at once unless
        ``start_immediately=False``. A closed set gives back an interrupted
        fiber that never runs ``eff``."""
        require_effect(eff, "eff")

        def body(parent: Fiber[Any, Any]) -> Effect[Fiber[XA, XE]]:
            if self._fibers is None:
                return _Succeed(
                    interrupted_fiber(parent._run_scheduler, parent._context, closed("FiberSet"))
                )
            fiber: Fiber[XA, XE] = parent._fork(
                eff, daemon=True, start_immediately=start_immediately
            )
            self.add_unsafe(fiber, propagate_interruption=propagate_interruption)
            return _AfterStarted(fiber)

        return _WithFiber(body)

    def runtime[XA, XE, R = Never](
        self: FiberSet[XA, XE], *tags: TagLike[Any, R]
    ) -> Effect[FiberSetRuntime[XA, XE, R], Never, R]:
        """A runner that forks effects needing ``tags`` into the set, with
        the services of the fiber calling this."""
        return _WithFiber(lambda fiber: _Succeed(FiberSetRuntime(self, CapturedRuntime(fiber))))

    def runtime_async[XA, XE, R = Never](
        self: FiberSet[XA, XE], *tags: TagLike[Any, R]
    ) -> Effect[FiberSetAsyncRuntime[XA, XE, R], Never, R]:
        """``runtime``, but the runner returns a future of the value (needs
        a running asyncio loop when called)."""
        return self.runtime(*tags).map(FiberSetAsyncRuntime)

    def clear(self) -> Effect[None]:
        """Interrupt every fiber in the set and wait for them."""

        def body() -> Effect[None]:
            if self._fibers is None:
                return _Succeed(None)
            return Fiber.interrupt_all_as(
                (fiber for fiber, _ in live_items(self._fibers)), INTERNAL_FIBER_ID
            )

        return _Suspend(body)

    def size(self) -> Effect[int]:
        return _Sync(lambda: 0 if self._fibers is None else len(self._fibers))

    def join(self) -> Effect[None, E_co]:
        """Wait for the first reported failure and fail with it; succeed
        when the scope closes."""
        return self.deferred.wait()

    def await_empty(self) -> Effect[None]:
        """Wait until the set is empty (or closed)."""

        def loop():
            while self._fibers:
                yield from next(iter(self._fibers)).await_exit()

        return _Gen(loop)

    def _close(self) -> Effect[None]:
        def body() -> Effect[None]:
            fibers = self._fibers
            if fibers is None:
                return _Succeed(None)
            self._fibers = None
            return self.deferred.into(Fiber.interrupt_all(list(fibers))).as_void()

        return _Suspend(body)


class FiberSetRuntime[A, E, R]:
    """Forks effects into a ``FiberSet`` from plain code; see
    ``FiberSet.runtime``."""

    __slots__ = ("_runtime", "_set")

    def __init__(self, fiber_set: FiberSet[A, E], runtime: CapturedRuntime) -> None:
        self._set = fiber_set
        self._runtime = runtime

    def __call__(
        self,
        eff: Effect[A, E, R],
        /,
        *,
        propagate_interruption: bool = False,
        uninterruptible: bool = False,
        scheduler: Scheduler | None = None,
    ) -> Fiber[A, E]:
        """Fork ``eff`` on a root fiber and add it to the set. A closed set
        gives back an interrupted fiber that never runs ``eff``."""
        require_effect(eff, "eff")
        if self._set._fibers is None:
            return self._runtime.interrupted(closed("FiberSet"))
        fiber = self._runtime.fork(eff, uninterruptible=uninterruptible, scheduler=scheduler)
        self._set.add_unsafe(fiber, propagate_interruption=propagate_interruption)
        return fiber


class FiberSetAsyncRuntime[A, E, R]:
    """``FiberSetRuntime`` returning a future of the fiber's value."""

    __slots__ = ("_run",)

    def __init__(self, run: FiberSetRuntime[A, E, R]) -> None:
        self._run = run

    def __call__(
        self,
        eff: Effect[A, E, R],
        /,
        *,
        propagate_interruption: bool = False,
        uninterruptible: bool = False,
        scheduler: Scheduler | None = None,
    ) -> asyncio.Future[A]:
        require_effect(eff, "eff")
        return future_of(
            self._run(
                eff,
                propagate_interruption=propagate_interruption,
                uninterruptible=uninterruptible,
                scheduler=scheduler,
            )
        )


__all__ = ["FiberSet", "FiberSetAsyncRuntime", "FiberSetRuntime"]
