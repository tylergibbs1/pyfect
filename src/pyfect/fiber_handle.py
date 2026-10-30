"""``FiberHandle[A, E]``: at most one fiber at a time, inside one scope.

Running or setting a new fiber interrupts the current one
(``only_if_missing=True`` keeps it and interrupts the newcomer instead).
Replaced fibers stay owned until they finish interrupting, so closing the
scope waits for their cleanup too. ``join`` fails with the first failure;
interrupts only count with ``propagate_interruption=True``, and never those
the handle sends itself (replacing, ``clear``, closing).

``runtime(*tags)`` returns a runner that forks root fibers into the handle
from plain code, as Effect's ``FiberHandle.runtime``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from typing import Any, Never

from pyfect._core import (
    Effect,
    Restore,
    _AfterStarted,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
    uninterruptible_mask,
)
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect._fiber_collections import (
    INTERNAL_FIBER_ID,
    CapturedRuntime,
    future_of,
    interrupted_fiber,
    reports_failure,
)
from pyfect.context import TagLike
from pyfect.deferred import Deferred
from pyfect.effect import interrupt
from pyfect.exit import Exit
from pyfect.scheduler import Scheduler
from pyfect.scope import Scope, acquire_release


class _Open[A, E]:
    __slots__ = ("current", "owned")

    def __init__(self) -> None:
        self.current: Fiber[A, E] | None = None
        # Every fiber the handle still owns: the current one, plus replaced
        # fibers that are still interrupting.
        self.owned: dict[Fiber[A, E], None] = {}


class FiberHandle[A = object, E = object]:
    """Make one with ``FiberHandle[A, E].make()`` inside a scope."""

    __slots__ = ("_state", "deferred")

    def __init__(self) -> None:
        self._state: _Open[A, E] | None = _Open()  # None once the scope has closed
        # Completed by the first reported failure, or when the scope closes.
        self.deferred: Deferred[None, E] = Deferred()

    @classmethod
    def make(cls) -> Effect[FiberHandle[A, E], Never, Scope]:
        """A handle whose fibers are interrupted when the current scope
        closes."""
        return acquire_release(_Sync(cls), lambda h, _: h._close())

    @classmethod
    def make_runtime[R = Never](
        cls, *tags: TagLike[Any, R]
    ) -> Effect[FiberHandleRuntime[A, E, R], Never, Scope | R]:
        """``make`` and ``runtime`` in one."""
        return cls.make().flat_map(lambda h: h.runtime(*tags))

    @classmethod
    def make_runtime_async[R = Never](
        cls, *tags: TagLike[Any, R]
    ) -> Effect[FiberHandleAsyncRuntime[A, E, R], Never, Scope | R]:
        """``make`` and ``runtime_async`` in one."""
        return cls.make().flat_map(lambda h: h.runtime_async(*tags))

    def __repr__(self) -> str:
        if self._state is None:
            return "FiberHandle(closed)"
        return f"FiberHandle({self._state.current!r})"

    def set_unsafe(
        self,
        fiber: Fiber[A, E],
        *,
        only_if_missing: bool = False,
        propagate_interruption: bool = False,
    ) -> None:
        """Make a running fiber the current one, interrupting the one there
        (or, with ``only_if_missing``, interrupting ``fiber`` instead). Into
        a closed handle the fiber is interrupted. Call on the scheduler
        thread."""
        state = self._state
        if state is None:
            fiber.interrupt_as_unsafe(INTERNAL_FIBER_ID)
            return
        previous = state.current
        if previous is fiber:
            return
        if previous is not None and only_if_missing:
            fiber.interrupt_as_unsafe(INTERNAL_FIBER_ID)
            return
        # Install the replacement before the interrupt can re-enter the
        # handle through a finalizer.
        state.current = fiber
        state.owned[fiber] = None
        if previous is not None:
            previous.interrupt_as_unsafe(INTERNAL_FIBER_ID)

        def observer(ex: Exit[A, E]) -> None:
            state = self._state
            if state is not None:
                state.owned.pop(fiber, None)
                if state.current is fiber:
                    state.current = None
            if reports_failure(ex, propagate_interruption):
                self.deferred.done_unsafe(ex)

        fiber.add_observer_unsafe(observer)

    def set(
        self,
        fiber: Fiber[A, E],
        *,
        only_if_missing: bool = False,
        propagate_interruption: bool = False,
    ) -> Effect[None]:
        return _Sync(
            lambda: self.set_unsafe(
                fiber,
                only_if_missing=only_if_missing,
                propagate_interruption=propagate_interruption,
            )
        )

    def get_unsafe(self) -> Fiber[A, E] | None:
        return None if self._state is None else self._state.current

    def get(self) -> Effect[Fiber[A, E] | None]:
        return _Sync(self.get_unsafe)

    def clear(self) -> Effect[None]:
        """Interrupt the current fiber, if any, and wait for it. A fiber set
        meanwhile stays current."""

        def body(restore: Restore) -> Effect[None]:
            fiber = self.get_unsafe()
            if fiber is None:
                return _Succeed(None)

            def forget() -> None:
                if self._state is not None and self._state.current is fiber:
                    self._state.current = None

            return restore(fiber.interrupt_as(INTERNAL_FIBER_ID)).and_then(_Sync(forget))

        return uninterruptible_mask(body)

    def run[R = Never](
        self,
        eff: Effect[A, E, R],
        *,
        only_if_missing: bool = False,
        propagate_interruption: bool = False,
        start_immediately: bool = True,
    ) -> Effect[Fiber[A, E], Never, R]:
        """Fork ``eff`` as the current fiber. It starts at once unless
        ``start_immediately=False``. With ``only_if_missing`` and a current
        fiber, gives back an interrupted fiber that never runs ``eff``.
        Running into a closed handle interrupts the caller."""
        require_effect(eff, "eff")

        def body(parent: Fiber[Any, Any]) -> Effect[Fiber[A, E]]:
            state = self._state
            if state is None:
                return interrupt()
            if only_if_missing and state.current is not None:
                return _Succeed(interrupted_fiber(parent._run_scheduler, parent._context))
            fiber: Fiber[A, E] = parent._fork(eff, daemon=True, start_immediately=start_immediately)
            self.set_unsafe(
                fiber,
                only_if_missing=only_if_missing,
                propagate_interruption=propagate_interruption,
            )
            return _AfterStarted(fiber)

        return _WithFiber(body)

    def runtime[R = Never](
        self, *tags: TagLike[Any, R]
    ) -> Effect[FiberHandleRuntime[A, E, R], Never, R]:
        """A runner that forks effects needing ``tags`` into the handle,
        with the services of the fiber calling this."""
        return _WithFiber(lambda fiber: _Succeed(FiberHandleRuntime(self, CapturedRuntime(fiber))))

    def runtime_async[R = Never](
        self, *tags: TagLike[Any, R]
    ) -> Effect[FiberHandleAsyncRuntime[A, E, R], Never, R]:
        """``runtime``, but the runner returns a future of the value (needs
        a running asyncio loop when called)."""
        return self.runtime(*tags).map(FiberHandleAsyncRuntime)

    def join(self) -> Effect[None, E]:
        """Wait for the first reported failure and fail with it; succeed
        when the scope closes."""
        return self.deferred.wait()

    def await_empty(self) -> Effect[None]:
        """Wait for the current fiber, if any."""

        def body() -> Effect[None]:
            fiber = self.get_unsafe()
            return _Succeed(None) if fiber is None else fiber.await_exit().as_void()

        return _Suspend(body)

    def _close(self) -> Effect[None]:
        def body() -> Effect[None]:
            state = self._state
            if state is None:
                return _Succeed(None)
            self._state = None
            interrupting = Fiber.interrupt_all_as(list(state.owned), INTERNAL_FIBER_ID)
            return self.deferred.into(interrupting).as_void()

        return _Suspend(body)


class FiberHandleRuntime[A, E, R]:
    """Forks effects into a ``FiberHandle`` from plain code; see
    ``FiberHandle.runtime``."""

    __slots__ = ("_handle", "_runtime")

    def __init__(self, handle: FiberHandle[A, E], runtime: CapturedRuntime) -> None:
        self._handle = handle
        self._runtime = runtime

    def __call__(
        self,
        eff: Effect[A, E, R],
        /,
        *,
        only_if_missing: bool = False,
        propagate_interruption: bool = False,
        uninterruptible: bool = False,
        scheduler: Scheduler | None = None,
    ) -> Fiber[A, E]:
        """Fork ``eff`` on a root fiber and make it current. A closed
        handle, or a current fiber with ``only_if_missing``, gives back an
        interrupted fiber that never runs ``eff``."""
        require_effect(eff, "eff")
        handle = self._handle
        if handle._state is None or (only_if_missing and handle._state.current is not None):
            return self._runtime.interrupted()
        fiber = self._runtime.fork(eff, uninterruptible=uninterruptible, scheduler=scheduler)
        handle.set_unsafe(
            fiber, only_if_missing=only_if_missing, propagate_interruption=propagate_interruption
        )
        return fiber


class FiberHandleAsyncRuntime[A, E, R]:
    """``FiberHandleRuntime`` returning a future of the fiber's value."""

    __slots__ = ("_run",)

    def __init__(self, run: FiberHandleRuntime[A, E, R]) -> None:
        self._run = run

    def __call__(
        self,
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
                eff,
                only_if_missing=only_if_missing,
                propagate_interruption=propagate_interruption,
                uninterruptible=uninterruptible,
                scheduler=scheduler,
            )
        )


__all__ = ["FiberHandle", "FiberHandleAsyncRuntime", "FiberHandleRuntime"]
