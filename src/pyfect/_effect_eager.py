"""``Effect`` methods that apply at once to an effect that is nothing but its
outcome (``known_exit``: ``succeed``, ``fail``, ``fail_cause``, ``from_exit``),
and otherwise build the lazy form (Effect's ``*Eager`` variants)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Never, cast

from pyfect import _core
from pyfect._effect_base import A_co, E_co, EffectBase, R_co, as_effect
from pyfect.cause import Cause, Fail
from pyfect.exit import Success

if TYPE_CHECKING:
    from pyfect._core import Effect


class EagerMethods(EffectBase[A_co, E_co, R_co]):
    __slots__ = ()

    def map_eager[B](self, f: Callable[[A_co], B]) -> Effect[B, E_co, R_co]:
        effect = as_effect(self)
        known = _core.known_exit(effect)
        if known is None:
            return effect.map(f)
        if isinstance(known, Success):
            return _core._Succeed(f(known.value))
        return _core._FailCause(known.cause)

    def map_error_eager[E2](self, f: Callable[[E_co], E2]) -> Effect[A_co, E2, R_co]:
        effect = as_effect(self)
        known = _core.known_exit(effect)
        if known is None:
            return effect.map_error(f)
        if isinstance(known, Success):
            return _core._Succeed(known.value)
        return _core._FailCause(known.cause.map(f))

    def map_both_eager[B, E2](
        self, *, on_failure: Callable[[E_co], E2], on_success: Callable[[A_co], B]
    ) -> Effect[B, E2, R_co]:
        effect = as_effect(self)
        known = _core.known_exit(effect)
        if known is None:
            return effect.map_both(on_failure=on_failure, on_success=on_success)
        if isinstance(known, Success):
            return _core._Succeed(on_success(known.value))
        return _core._FailCause(known.cause.map(on_failure))

    def flat_map_eager[B, E2 = Never, R2 = Never](
        self, f: Callable[[A_co], Effect[B, E2, R2]]
    ) -> Effect[B, E_co | E2, R_co | R2]:
        effect = as_effect(self)
        known = _core.known_exit(effect)
        if known is None:
            return effect.flat_map(f)
        if isinstance(known, Success):
            return f(known.value)
        return cast("Effect[B, E_co, R_co]", effect)

    def catch_eager[B, E2 = Never, R2 = Never](
        self, f: Callable[[E_co], Effect[B, E2, R2]]
    ) -> Effect[A_co | B, E2, R_co | R2]:
        effect = as_effect(self)
        known = _core.known_exit(effect)
        if known is None:
            return effect.catch_all(f)
        if isinstance(known, Success):
            return _core._Succeed(known.value)
        found = known.cause.find_recoverable_error()
        return f(found.error) if isinstance(found, Fail) else _core._FailCause(found)

    def match_eager[B, C](
        self, *, on_failure: Callable[[E_co], B], on_success: Callable[[A_co], C]
    ) -> Effect[B | C, Never, R_co]:
        effect = as_effect(self)
        known = _core.known_exit(effect)
        if known is None:
            return effect.match(on_failure=on_failure, on_success=on_success)
        if isinstance(known, Success):
            return _core._Succeed(on_success(known.value))
        found = known.cause.find_recoverable_error()
        if isinstance(found, Fail):
            return _core._Succeed(on_failure(found.error))
        return _core._FailCause(found)

    def match_cause_eager[B, C](
        self, *, on_failure: Callable[[Cause[E_co]], B], on_success: Callable[[A_co], C]
    ) -> Effect[B | C, Never, R_co]:
        effect = as_effect(self)
        known = _core.known_exit(effect)
        if known is None:
            return effect.match_cause(on_failure=on_failure, on_success=on_success)
        if isinstance(known, Success):
            return _core._Succeed(on_success(known.value))
        return _core._Succeed(on_failure(known.cause))

    def match_cause_effect_eager[B, C, EE = Never, RR = Never](
        self,
        *,
        on_failure: Callable[[Cause[E_co]], Effect[B, EE, RR]],
        on_success: Callable[[A_co], Effect[C, EE, RR]],
    ) -> Effect[B | C, EE, R_co | RR]:
        effect = as_effect(self)
        known = _core.known_exit(effect)
        if known is None:
            return effect.match_cause_effect(on_failure=on_failure, on_success=on_success)
        if isinstance(known, Success):
            return on_success(known.value)
        return on_failure(known.cause)
