"""``Effect`` methods for resource safety: finalizers and interruptibility.

Every user callback runs through ``_call_user``, so a raise becomes a
defect inside the surrounding finalizer or region.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never

from pyfect import _core
from pyfect._effect_base import A_co, E_co, EffectBase, R_co, Step, as_effect
from pyfect.cause import Cause, merge
from pyfect.exit import Exit, Failure, Success

if TYPE_CHECKING:
    from pyfect._core import Effect


class ResourceMethods(EffectBase[A_co, E_co, R_co]):
    __slots__ = ()

    def on_exit[R2 = Never](
        self, f: Callable[[Exit[A_co, E_co]], Effect[object, Never, R2]]
    ) -> Effect[A_co, E_co, R_co | R2]:
        """Run ``f`` after this effect however it ends. ``f`` runs
        uninterruptibly; if it fails, its cause is added to the result."""
        eff = as_effect(self)
        return _core.uninterruptible_mask(
            lambda restore: _core._MatchCause(
                restore(eff),
                lambda c: _run_finalizer(_call_user(f, Failure(c)), Failure(c)),
                lambda a: _run_finalizer(_call_user(f, Success(a)), Success(a)),
            )
        )

    def ensuring[R2 = Never](
        self, finalizer: Effect[object, Never, R2]
    ) -> Effect[A_co, E_co, R_co | R2]:
        return self.on_exit(lambda _: finalizer)

    def on_error[R2 = Never](
        self, f: Callable[[Cause[E_co]], Effect[object, Never, R2]]
    ) -> Effect[A_co, E_co, R_co | R2]:
        def handle(ex: Exit[A_co, E_co]) -> Effect[object, Never, R2]:
            return f(ex.cause) if isinstance(ex, Failure) else _core._Succeed(None)

        return self.on_exit(handle)

    def on_interrupt[R2 = Never](
        self, finalizer: Effect[object, Never, R2]
    ) -> Effect[A_co, E_co, R_co | R2]:
        def handle(ex: Exit[A_co, E_co]) -> Effect[object, Never, R2]:
            if isinstance(ex, Failure) and ex.cause.has_interrupts:
                return finalizer
            return _core._Succeed(None)

        return self.on_exit(handle)

    def uninterruptible(self) -> Effect[A_co, E_co, R_co]:
        return _core._SetInterruptible(as_effect(self), False)

    def interruptible(self) -> Effect[A_co, E_co, R_co]:
        return _core._SetInterruptible(as_effect(self), True)


def _call_user[*Ts, A, E, R](f: Callable[[*Ts], Effect[A, E, R]], *args: *Ts) -> Effect[A, E, R]:
    """Call user code when the effect runs, not when it is built. A raise
    then becomes a defect at that point of the program, inside whatever
    finalizer or region surrounds it. Resource and finalizer combinators
    call every user callback through this."""
    return _core._Suspend(lambda: f(*args))


def _run_finalizer(finalizer: Effect[object, Never, Any], ex: Exit[Any, Any]) -> Step:
    """Run ``finalizer``, then end with ``ex``. A failing finalizer adds
    its cause to the result."""

    def after_failure(fin_cause: Cause[Any]) -> Effect[Any, Any, Any]:
        base = ex.cause if isinstance(ex, Failure) else Cause(())
        return _core._FailCause(merge(base, fin_cause))

    return _core._MatchCause(finalizer, after_failure, lambda _: _core._FromExit(ex))
