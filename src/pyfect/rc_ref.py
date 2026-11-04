"""``RcRef[A, E]``: a resource acquired on first use and shared while in use.

``get`` acquires the resource the first time (or joins an acquisition in
progress) and holds a reference until the caller's ``Scope`` closes. The
last reference to go releases the resource, at once or after
``idle_time_to_live``; the next ``get`` acquires afresh. Closing the scope
that made the ref releases the resource and interrupts a pending
acquisition; a ``get`` after that is interrupted.

The acquisition runs on a fiber of its own, so callers can leave without
killing it while others still wait; it is interrupted once every waiting
caller has left.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
from typing import Any, Final, Generic, Literal, Never, TypeVar, overload

from pyfect._core import (
    Effect,
    Restore,
    _Locally,
    _Succeed,
    _Suspend,
    _Sync,
    _WithFiber,
    uninterruptible_mask,
)
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect._root import new_root, start_root
from pyfect._unsubscripted import Unsubscripted
from pyfect.clock import sleep
from pyfect.context import Context
from pyfect.duration import Duration, Seconds, to_seconds
from pyfect.effect import interrupt
from pyfect.exit import Exit, Failure, Success
from pyfect.scope import CloseableScope, Scope

_VOID: Final[Effect[None]] = _Succeed(None)
_DONE: Final[Exit[None, Never]] = Success(None)

A_co = TypeVar("A_co", covariant=True, default=Unsubscripted)
E_co = TypeVar("E_co", covariant=True, default=Never)


class _Acquiring[A]:
    """An acquisition in progress and the callers waiting on it. ``acquired``
    is set when the references are handed out, which can be before the
    acquisition's fiber exits."""

    __slots__ = ("acquired", "awaiters", "fiber")

    def __init__(self, fiber: Fiber[_Acquired[A], Any]) -> None:
        self.fiber = fiber
        self.awaiters = 1  # the caller that starts it
        self.acquired: _Acquired[A] | None = None


class _Acquired[A]:
    __slots__ = ("fiber", "invalidated", "ref_count", "scope", "value")

    def __init__(self, value: A, scope: CloseableScope, ref_count: int) -> None:
        self.value = value
        self.scope = scope
        self.ref_count = ref_count
        self.invalidated = False
        self.fiber: Fiber[None, Never] | None = None  # the idle timer


type _State[A] = _Acquiring[A] | _Acquired[A] | Literal["empty", "closed"]


class RcRef(Generic[A_co, E_co]):
    """Make one with ``RcRef.make(acquire)`` inside a scope. Covariant, as
    in Effect: the resource is only read."""

    __slots__ = ("_acquire", "_context", "_idle_time_to_live", "_scope", "_state")

    def __init__(
        self,
        acquire: Effect[A_co, E_co, Any],
        context: Context,
        scope: CloseableScope,
        idle_time_to_live: Seconds | None,
    ) -> None:
        self._acquire = acquire
        self._context = context
        self._scope = scope
        self._idle_time_to_live = idle_time_to_live
        self._state: _State[A_co] = "empty"

    @overload
    @classmethod
    def make[T, X = Never, R = Never](
        cls: type[RcRef[Unsubscripted, Any]],
        acquire: Effect[T, X, R],
        *,
        idle_time_to_live: Duration | None = None,
    ) -> Effect[RcRef[T, X], Never, Scope | R]: ...
    @overload
    @classmethod
    def make[R = Never](
        cls, acquire: Effect[A_co, E_co, R], *, idle_time_to_live: Duration | None = None
    ) -> Effect[RcRef[A_co, E_co], Never, Scope | R]: ...
    @classmethod
    def make[T, X = Never, R = Never](
        cls, acquire: Effect[T, X, R], *, idle_time_to_live: Duration | None = None
    ) -> Effect[RcRef[T, X], Never, Scope | R]:
        """A ref that runs ``acquire`` (with the services in scope now, and
        a scope of its own) when first used. Without ``idle_time_to_live``
        the resource is released as soon as the last reference goes."""
        require_effect(acquire, "acquire")
        ttl = None if idle_time_to_live is None else to_seconds(idle_time_to_live)

        def body(fiber: Fiber[Any, Any]) -> Effect[RcRef[T, X]]:
            context = fiber._context
            scope = context.get_unsafe(Scope)
            ref = RcRef(acquire, context, scope, ttl)
            return scope.add_finalizer(lambda _: ref._close()).as_(ref)

        return _WithFiber(body)

    def get(self) -> Effect[A_co, E_co, Scope]:
        """The resource, held until the current scope closes."""

        def body(restore: Restore) -> Effect[A_co, E_co, Scope]:
            def with_fiber(fiber: Fiber[Any, Any]) -> Effect[A_co, E_co]:
                scope = fiber._context.get_unsafe(Scope)
                return self._get_state(fiber, restore).flat_map(
                    lambda state: scope.add_finalizer(lambda _: self._release(state)).as_(
                        state.value
                    )
                )

            return _WithFiber(with_fiber)

        return uninterruptible_mask(body)

    def invalidate(self) -> Effect[None]:
        """Forget the resource, so the next ``get`` acquires afresh. It is
        released now if nobody holds it, else when the last holder lets go."""

        def body() -> Effect[None]:
            state = self._state
            if not isinstance(state, _Acquired):
                return _VOID
            self._state = "empty"
            state.invalidated = True
            if state.ref_count > 0:
                return _VOID
            if state.fiber is not None:
                state.fiber.interrupt_as_unsafe(None)
            return state.scope.close(_DONE)

        return _Suspend(body).uninterruptible()

    def __repr__(self) -> str:
        state = self._state
        if isinstance(state, _Acquired):
            return f"RcRef(acquired, refs={state.ref_count})"
        return f"RcRef({'acquiring' if isinstance(state, _Acquiring) else state})"

    def _get_state(self, fiber: Fiber[Any, Any], restore: Restore) -> Effect[_Acquired[A_co], E_co]:
        state = self._state
        if state == "closed":
            return interrupt()
        if isinstance(state, _Acquired):
            state.ref_count += 1
            idle = state.fiber
            return _Succeed(state) if idle is None else idle.interrupt().as_(state)
        if isinstance(state, _Acquiring):
            state.awaiters += 1
            return self._await_acquiring(state, restore)
        return self._start_acquiring(fiber, restore)

    def _start_acquiring(
        self, parent: Fiber[Any, Any], restore: Restore
    ) -> Effect[_Acquired[A_co], E_co]:
        scope = CloseableScope()
        context = self._context.add(Scope, scope)
        acquiring: _Acquiring[A_co] = _Acquiring(new_root(parent._run_scheduler, parent._context))

        def publish(value: A_co) -> Effect[_Acquired[A_co]]:
            if self._state is not acquiring:  # closed, or abandoned
                return interrupt()
            # Every caller still waiting holds a reference.
            acquired = _Acquired(value, scope, acquiring.awaiters)
            self._state = acquiring.acquired = acquired
            return _Succeed(acquired)

        def settle(ex: Exit[_Acquired[A_co], E_co]) -> Effect[None]:
            if isinstance(ex, Success):
                return _VOID
            if self._state is acquiring:
                self._state = "empty"
            return scope.close(ex)

        self._state = acquiring
        acquire: Effect[A_co, E_co] = _Locally(
            self._acquire, lambda current: current.merge(context)
        )
        start_root(acquiring.fiber, acquire.flat_map(publish).on_exit(settle))
        return self._await_acquiring(acquiring, restore)

    def _await_acquiring(
        self, acquiring: _Acquiring[A_co], restore: Restore
    ) -> Effect[_Acquired[A_co], E_co]:
        def leave(ex: Exit[_Acquired[A_co], E_co]) -> Effect[None]:
            acquired = acquiring.acquired
            if acquired is not None:
                # Counted as a reference, maybe before the fiber exited:
                # give it back if this caller was interrupted before it
                # could register its release.
                return self._release(acquired) if isinstance(ex, Failure) else _VOID
            acquiring.awaiters -= 1
            if acquiring.awaiters > 0 or self._state is not acquiring:
                return _VOID
            # Detach it first, so a new caller starts afresh rather than
            # joining an acquisition being interrupted.
            self._state = "empty"
            return acquiring.fiber.interrupt()

        return restore(acquiring.fiber.join()).on_exit(leave)

    def _release(self, state: _Acquired[A_co]) -> Effect[None]:
        return _WithFiber(lambda fiber: self._release_now(fiber, state))

    def _release_now(self, fiber: Fiber[Any, Any], state: _Acquired[A_co]) -> Effect[None]:
        state.ref_count -= 1
        if state.ref_count > 0:
            return _VOID
        ttl = self._idle_time_to_live
        if ttl is None or state.invalidated:
            if self._state is state:
                self._state = "empty"
            return state.scope.close(_DONE)
        if math.isinf(ttl):
            return _VOID

        def expire(_: None) -> Effect[None]:
            if self._state is state and state.ref_count == 0:
                self._state = "empty"
                return state.scope.close(_DONE)
            return _VOID

        def forget() -> None:
            state.fiber = None

        idle = uninterruptible_mask(lambda restore: restore(sleep(ttl)).flat_map(expire)).ensuring(
            _Sync(forget)
        )
        timer: Fiber[None, Never] = new_root(fiber._run_scheduler, self._context)
        state.fiber = timer
        start_root(timer, idle)
        timer.run_in(self._scope)
        return _VOID

    def _close(self) -> Effect[None]:
        state = self._state
        self._state = "closed"
        if isinstance(state, _Acquired):
            return state.scope.close(_DONE)
        if isinstance(state, _Acquiring):
            return state.fiber.interrupt()
        return _VOID


__all__ = ["RcRef"]
