"""``Effect`` methods that apply at once to an effect already holding its
exit (``succeed``, ``fail``, ``fail_cause``), and otherwise build the lazy
form (Effect's ``*Eager`` variants)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, cast

from pyfect import _core
from pyfect._effect_base import A_co, E_co, EffectBase, R_co, as_effect
from pyfect.cause import Cause, Fail

if TYPE_CHECKING:
    from pyfect._core import Effect


class EagerMethods(EffectBase[A_co, E_co, R_co]):
    __slots__ = ()

    def map_eager[B](self, f: Callable[[A_co], B]) -> Effect[B, E_co, R_co]:
        effect = as_effect(self)
        if isinstance(effect, _core._Succeed):
            return _core._Succeed(f(effect.value))
        return cast("Effect[B, E_co, R_co]", effect) if _failed(effect) else effect.map(f)

    def map_error_eager[E2](self, f: Callable[[E_co], E2]) -> Effect[A_co, E2, R_co]:
        effect = as_effect(self)
        if isinstance(effect, _core._Succeed):
            return cast("Effect[A_co, E2, R_co]", effect)
        if isinstance(effect, _core._FailCause):
            return _core._FailCause(effect.cause.map(f))
        return effect.map_error(f)

    def map_both_eager[B, E2](
        self, *, on_failure: Callable[[E_co], E2], on_success: Callable[[A_co], B]
    ) -> Effect[B, E2, R_co]:
        effect = as_effect(self)
        if isinstance(effect, _core._Succeed):
            return _core._Succeed(on_success(effect.value))
        if isinstance(effect, _core._FailCause):
            return _core._FailCause(effect.cause.map(on_failure))
        return effect.map_both(on_failure=on_failure, on_success=on_success)

    def flat_map_eager[B, E2 = Never, R2 = Never](
        self, f: Callable[[A_co], Effect[B, E2, R2]]
    ) -> Effect[B, E_co | E2, R_co | R2]:
        effect = as_effect(self)
        if isinstance(effect, _core._Succeed):
            return f(effect.value)
        return cast("Effect[B, E_co, R_co]", effect) if _failed(effect) else effect.flat_map(f)

    def catch_eager[B, E2 = Never, R2 = Never](
        self, f: Callable[[E_co], Effect[B, E2, R2]]
    ) -> Effect[A_co | B, E2, R_co | R2]:
        effect = as_effect(self)
        if isinstance(effect, _core._Succeed):
            return cast("Effect[A_co, E2, R_co]", effect)
        if isinstance(effect, _core._FailCause):
            found = effect.cause.find_recoverable_error()
            return f(found.error) if isinstance(found, Fail) else _core._FailCause(found)
        return effect.catch_all(f)

    def match_eager[B, C](
        self, *, on_failure: Callable[[E_co], B], on_success: Callable[[A_co], C]
    ) -> Effect[B | C, Never, R_co]:
        effect = as_effect(self)
        if isinstance(effect, _core._Succeed):
            return _core._Succeed(on_success(effect.value))
        if isinstance(effect, _core._FailCause):
            found = effect.cause.find_recoverable_error()
            if isinstance(found, Fail):
                return _core._Succeed(on_failure(found.error))
            return _core._FailCause(found)
        return effect.match(on_failure=on_failure, on_success=on_success)

    def match_cause_eager[B, C](
        self, *, on_failure: Callable[[Cause[E_co]], B], on_success: Callable[[A_co], C]
    ) -> Effect[B | C, Never, R_co]:
        effect = as_effect(self)
        if isinstance(effect, _core._Succeed):
            return _core._Succeed(on_success(effect.value))
        if isinstance(effect, _core._FailCause):
            return _core._Succeed(on_failure(effect.cause))
        return effect.match_cause(on_failure=on_failure, on_success=on_success)

    def match_cause_effect_eager[B, C, EE = Never, RR = Never](
        self,
        *,
        on_failure: Callable[[Cause[E_co]], Effect[B, EE, RR]],
        on_success: Callable[[A_co], Effect[C, EE, RR]],
    ) -> Effect[B | C, EE, R_co | RR]:
        effect = as_effect(self)
        if isinstance(effect, _core._Succeed):
            return on_success(effect.value)
        if isinstance(effect, _core._FailCause):
            return on_failure(effect.cause)
        return effect.match_cause_effect(on_failure=on_failure, on_success=on_success)


def _failed(effect: Effect[Any, Any, Any]) -> bool:
    return isinstance(effect, _core._FailCause)
