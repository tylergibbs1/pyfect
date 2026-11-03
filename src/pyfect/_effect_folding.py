"""``Effect`` methods that fold both outcomes into a value or a next effect:
``match*``, ``option``, ``as_some``, ``is_failure`` / ``is_success``,
``exit`` and ``result``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Never

from pyfect import _core
from pyfect._effect_base import A_co, E_co, EffectBase, R_co, as_effect
from pyfect._effect_errors import _recovering, _succeed_none
from pyfect.cause import Cause
from pyfect.exit import Exit, Failure, Success
from pyfect.result import Err, Ok

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect.option import Option, Some


class FoldingMethods(EffectBase[A_co, E_co, R_co]):
    __slots__ = ()

    def match[B, C](
        self, *, on_failure: Callable[[E_co], B], on_success: Callable[[A_co], C]
    ) -> Effect[B | C, Never, R_co]:
        return _core._MatchCause(
            as_effect(self),
            _recovering(lambda e: _core._Succeed(on_failure(e))),
            lambda a: _core._Succeed(on_success(a)),
        )

    def match_cause[B, C](
        self, *, on_failure: Callable[[Cause[E_co]], B], on_success: Callable[[A_co], C]
    ) -> Effect[B | C, Never, R_co]:
        """``match`` over the whole ``Cause``: defects reach ``on_failure``
        too. Interruption still propagates."""
        return _core._MatchCause(
            as_effect(self),
            lambda c: _core._Succeed(on_failure(c)),
            lambda a: _core._Succeed(on_success(a)),
        )

    def option(self) -> Effect[Option[A_co], Never, R_co]:
        """Succeed with ``Some(value)``, or ``None`` on a typed error.
        Defects and interruptions still propagate."""
        from pyfect.option import Some

        return _core._MatchCause(
            as_effect(self), _recovering(_succeed_none), lambda a: _core._Succeed(Some(a))
        )

    def as_some(self) -> Effect[Some[A_co], E_co, R_co]:
        """Succeed with ``Some(value)``."""
        from pyfect.option import Some

        return _core._Map(as_effect(self), Some)

    def is_failure(self) -> Effect[bool, Never, R_co]:
        """Whether it fails with a typed error. Defects and interruptions
        still propagate."""
        return self.match(on_failure=_true, on_success=_false)

    def is_success(self) -> Effect[bool, Never, R_co]:
        """Whether it succeeds. Defects and interruptions still propagate."""
        return self.match(on_failure=_false, on_success=_true)

    def match_effect[B, C, EE = Never, RR = Never](
        self,
        *,
        on_failure: Callable[[E_co], Effect[B, EE, RR]],
        on_success: Callable[[A_co], Effect[C, EE, RR]],
    ) -> Effect[B | C, EE, R_co | RR]:
        return _core._MatchCause(as_effect(self), _recovering(on_failure), on_success)

    def match_cause_effect[B, C, EE = Never, RR = Never](
        self,
        *,
        on_failure: Callable[[Cause[E_co]], Effect[B, EE, RR]],
        on_success: Callable[[A_co], Effect[C, EE, RR]],
    ) -> Effect[B | C, EE, R_co | RR]:
        return _core._MatchCause(as_effect(self), on_failure, on_success)

    def exit(self) -> Effect[Exit[A_co, E_co], Never, R_co]:
        """Succeed with the outcome as a value. Interruption still
        propagates; it is not something a fiber can catch."""
        return _core._MatchCause(
            as_effect(self),
            lambda c: _core._Succeed(Failure(c)),
            lambda a: _core._Succeed(Success(a)),
        )

    def result(self) -> Effect[Ok[A_co] | Err[E_co], Never, R_co]:
        """Succeed with ``Ok(value)`` or ``Err(error)``. Defects and
        interruptions still propagate."""
        return _core._MatchCause(
            as_effect(self),
            _recovering(lambda e: _core._Succeed(Err(e))),
            lambda a: _core._Succeed(Ok(a)),
        )


def _true(_: object) -> bool:
    return True


def _false(_: object) -> bool:
    return False
