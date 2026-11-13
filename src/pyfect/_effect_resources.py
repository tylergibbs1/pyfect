"""``Effect`` methods for resource safety: finalizers and interruptibility.

Every user callback runs through ``_call_user``, so a raise becomes a
defect inside the surrounding finalizer or region.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never

from pyfect import _core
from pyfect._cause_election import finalizer_cause
from pyfect._effect_args import require_effect
from pyfect._effect_base import A_co, E_co, EffectBase, R_co, Step, as_effect
from pyfect.cause import Cause
from pyfect.cause import die as die_cause
from pyfect.exit import Exit, Failure, Success
from pyfect.result import Ok, Result

if TYPE_CHECKING:
    from pyfect._core import Effect


class ResourceMethods(EffectBase[A_co, E_co, R_co]):
    __slots__ = ()

    def on_exit[R2 = Never](
        self, f: Callable[[Exit[A_co, E_co]], Effect[object, Never, R2]]
    ) -> Effect[A_co, E_co, R_co | R2]:
        """Run ``f`` after this effect however it ends. ``f`` runs
        uninterruptibly; if it fails, its cause is added to the result."""
        return _on_exit(as_effect(self), f)

    def on_exit_primitive[E2 = Never, R2 = Never](
        self,
        f: Callable[[Exit[A_co, E_co]], Effect[object, E2, R2] | None],
        interruptible: bool = False,
    ) -> Effect[A_co, E_co | E2, R_co | R2]:
        """``on_exit`` whose ``f`` may return ``None``, and may fail, as
        Effect's building block for it. With ``interruptible`` the finalizer
        stays as interruptible as the fiber is: ``f`` is still called, but an
        interrupted fiber does not run the effect it returns."""

        def finish(ex: Exit[A_co, E_co]) -> Step:
            # As Effect's ``OnExit`` frame: no finalizer hands ``ex`` straight on.
            after = _call_user_now(f, ex)
            return _core._FromExit(ex) if after is None else _run_finalizer(after, ex)

        effect = as_effect(self)
        if not interruptible:
            return _core._OnExit(effect, finish)
        return _core._MatchCause(effect, lambda c: finish(Failure(c)), lambda a: finish(Success(a)))

    def ensuring[R2 = Never](
        self, finalizer: Effect[object, Never, R2]
    ) -> Effect[A_co, E_co, R_co | R2]:
        require_effect(finalizer, "finalizer")
        return self.on_exit(lambda _: finalizer)

    def on_error[R2 = Never](
        self, f: Callable[[Cause[E_co]], Effect[object, Never, R2]]
    ) -> Effect[A_co, E_co, R_co | R2]:
        def handle(ex: Exit[A_co, E_co]) -> Effect[object, Never, R2]:
            return f(ex.cause) if isinstance(ex, Failure) else _core._Succeed(None)

        return self.on_exit(handle)

    def on_error_if[E2 = Never, R2 = Never](
        self,
        predicate: Callable[[Cause[E_co]], bool],
        f: Callable[[Cause[E_co]], Effect[object, E2, R2]],
    ) -> Effect[A_co, E_co | E2, R_co | R2]:
        """``on_error`` for the causes ``predicate`` accepts. If ``f``
        fails, its cause is added to the result."""

        def handle(ex: Exit[A_co, E_co]) -> Effect[object, E2, R2]:
            if isinstance(ex, Failure) and predicate(ex.cause):
                return f(ex.cause)
            return _core._Succeed(None)

        return _on_exit(as_effect(self), handle)

    def on_error_filter[B, E2 = Never, R2 = Never](
        self,
        filter: Callable[[Cause[E_co]], Result[B, object]],
        f: Callable[[B, Cause[E_co]], Effect[object, E2, R2]],
    ) -> Effect[A_co, E_co | E2, R_co | R2]:
        """``on_error`` for the causes ``filter`` passes (``Ok(value)``):
        run ``f(value, cause)``."""

        def handle(ex: Exit[A_co, E_co]) -> Effect[object, E2, R2]:
            if isinstance(ex, Failure):
                passed = filter(ex.cause)
                if isinstance(passed, Ok):
                    return f(passed.value, ex.cause)
            return _core._Succeed(None)

        return _on_exit(as_effect(self), handle)

    def on_exit_if[E2 = Never, R2 = Never](
        self,
        predicate: Callable[[Exit[A_co, E_co]], bool],
        f: Callable[[Exit[A_co, E_co]], Effect[object, E2, R2]],
    ) -> Effect[A_co, E_co | E2, R_co | R2]:
        """``on_exit`` for the exits ``predicate`` accepts. If ``f`` fails,
        its cause is added to the result."""

        def handle(ex: Exit[A_co, E_co]) -> Effect[object, E2, R2]:
            return f(ex) if predicate(ex) else _core._Succeed(None)

        return _on_exit(as_effect(self), handle)

    def on_exit_filter[B, E2 = Never, R2 = Never](
        self,
        filter: Callable[[Exit[A_co, E_co]], Result[B, object]],
        f: Callable[[B, Exit[A_co, E_co]], Effect[object, E2, R2]],
    ) -> Effect[A_co, E_co | E2, R_co | R2]:
        """``on_exit`` for the exits ``filter`` passes (``Ok(value)``): run
        ``f(value, exit)``."""

        def handle(ex: Exit[A_co, E_co]) -> Effect[object, E2, R2]:
            passed = filter(ex)
            return f(passed.value, ex) if isinstance(passed, Ok) else _core._Succeed(None)

        return _on_exit(as_effect(self), handle)

    def on_interrupt[R2 = Never](
        self, finalizer: Effect[object, Never, R2]
    ) -> Effect[A_co, E_co, R_co | R2]:
        require_effect(finalizer, "finalizer")

        def handle(ex: Exit[A_co, E_co]) -> Effect[object, Never, R2]:
            if isinstance(ex, Failure) and ex.cause.has_interrupts:
                return finalizer
            return _core._Succeed(None)

        return self.on_exit(handle)

    def uninterruptible(self) -> Effect[A_co, E_co, R_co]:
        return _core._SetInterruptible(as_effect(self), False)

    def interruptible(self) -> Effect[A_co, E_co, R_co]:
        return _core._SetInterruptible(as_effect(self), True)


def _on_exit[A, E, R, E2, R2](
    eff: Effect[A, E, R], f: Callable[[Exit[A, E]], Effect[object, E2, R2]]
) -> Effect[A, E | E2, R | R2]:
    """Run ``f(exit)`` uninterruptibly after ``eff``; a failure of ``f``
    adds its cause to the result."""
    return _core._OnExit(eff, lambda ex: _run_finalizer(_call_user_now(f, ex), ex))


def _call_user[*Ts, A, E, R](f: Callable[[*Ts], Effect[A, E, R]], *args: *Ts) -> Effect[A, E, R]:
    """Call user code when the effect runs, not when it is built. A raise
    then becomes a defect at that point of the program, inside whatever
    finalizer or region surrounds it. Resource and finalizer combinators
    call every user callback through this, or through ``_call_user_now``."""
    return _core._Suspend(lambda: f(*args))


def _call_user_now[*Ts, T](f: Callable[[*Ts], T], *args: *Ts) -> T | Effect[Never, Any]:
    """``_call_user`` for a frame that is already running, which calls user
    code at once, as Effect's frames do (no op of its own): a raise is a
    defect right here. Ctrl-C goes on to the loop (``Fiber._raised``)."""
    try:
        return f(*args)
    except KeyboardInterrupt:
        raise
    except BaseException as exc:
        return _core._FailCause(die_cause(exc))


def _run_finalizer(finalizer: Effect[object, Any, Any], ex: Exit[Any, Any]) -> Step:
    """Run ``finalizer``, then end with ``ex`` (Effect's ``OnExit`` frame:
    ``flatMap(finalizer, () => exit)``, the finalizer's cause combined with
    a failed ``ex``'s by ``combineFinalizerCause``)."""
    if isinstance(ex, Failure):

        def after_failure(fin_cause: Cause[Any]) -> Effect[Any, Any, Any]:
            return _core._FailCause(finalizer_cause(ex, fin_cause))

        finalizer = _core._MatchCause(finalizer, after_failure, None)
    return _core._FlatMap(finalizer, lambda _: _core._FromExit(ex))


__all__ = ["ResourceMethods", "_call_user", "_call_user_now", "_on_exit", "_run_finalizer"]
