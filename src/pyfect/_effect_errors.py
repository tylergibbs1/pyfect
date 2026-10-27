"""``Effect`` methods that handle errors: mapping, recovering from and
tapping typed errors, defects and whole causes.

Every handler is a ``_MatchCause``. Typed recovery goes through
``_recovering``, so a defect always wins over a typed error.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, overload

from pyfect import _core
from pyfect._effect_base import A_co, E_co, EffectBase, R_co, as_effect
from pyfect.cause import Cause, Fail, _as_exception
from pyfect.cause import die as die_cause
from pyfect.cause import fail as fail_cause
from pyfect.exit import Success

if TYPE_CHECKING:
    from pyfect._core import Effect


class ErrorMethods(EffectBase[A_co, E_co, R_co]):
    __slots__ = ()

    def map_error[E2](self, f: Callable[[E_co], E2]) -> Effect[A_co, E2, R_co]:
        def on_failure(cause: Cause[E_co]) -> Effect[Never, E2, Never]:
            return _core._FailCause(cause.map(f))

        return _core._MatchCause(as_effect(self), on_failure, None)

    def map_both[B, E2](
        self, *, on_failure: Callable[[E_co], E2], on_success: Callable[[A_co], B]
    ) -> Effect[B, E2, R_co]:
        """``map_error`` and ``map`` at once."""
        return _core._MatchCause(
            as_effect(self),
            lambda c: _core._FailCause(c.map(on_failure)),
            lambda a: Success(on_success(a)),
        )

    def catch_all[B, E2 = Never, R2 = Never](
        self, f: Callable[[E_co], Effect[B, E2, R2]]
    ) -> Effect[A_co | B, E2, R_co | R2]:
        """Recover from every typed error. Defects and interruptions pass
        through. To handle one error class, use ``pipe(catch_tag(...))``."""
        return _core._MatchCause(as_effect(self), _recovering(f), None)

    @overload
    def catch_if[B, E2 = Never, R2 = Never](
        self, predicate: Callable[[E_co], bool], f: Callable[[E_co], Effect[B, E2, R2]]
    ) -> Effect[A_co | B, E_co | E2, R_co | R2]: ...
    @overload
    def catch_if[B, C, EE = Never, RR = Never](
        self,
        predicate: Callable[[E_co], bool],
        f: Callable[[E_co], Effect[B, EE, RR]],
        *,
        or_else: Callable[[E_co], Effect[C, EE, RR]],
    ) -> Effect[A_co | B | C, EE, R_co | RR]: ...
    def catch_if(
        self,
        predicate: Callable[[Any], bool],
        f: Callable[[Any], Effect[Any, Any, Any]],
        *,
        or_else: Callable[[Any], Effect[Any, Any, Any]] | None = None,
    ) -> Effect[Any, Any, Any]:
        """Recover from the typed errors that pass ``predicate``; ``or_else``,
        if given, handles the rest. To remove the caught errors from ``E``,
        use ``pipe(catch_if(refinement, ...))`` with a ``TypeIs`` refinement."""
        return _core._MatchCause(as_effect(self), _catching_if(predicate, f, or_else), None)

    def catch_cause[B, E2 = Never, R2 = Never](
        self, f: Callable[[Cause[E_co]], Effect[B, E2, R2]]
    ) -> Effect[A_co | B, E2, R_co | R2]:
        """Recover from any failure, including defects. Interruption still
        wins: an interrupted fiber skips this handler."""
        return _core._MatchCause(as_effect(self), f, None)

    def catch_cause_if[B, E2 = Never, R2 = Never](
        self,
        predicate: Callable[[Cause[E_co]], bool],
        f: Callable[[Cause[E_co]], Effect[B, E2, R2]],
    ) -> Effect[A_co | B, E_co | E2, R_co | R2]:
        """``catch_cause`` for the causes that pass ``predicate``."""
        return _core._MatchCause(
            as_effect(self), lambda c: f(c) if predicate(c) else _core._FailCause(c), None
        )

    def catch_defect[B, E2 = Never, R2 = Never](
        self, f: Callable[[BaseException], Effect[B, E2, R2]]
    ) -> Effect[A_co | B, E_co | E2, R_co | R2]:
        """Recover from the first defect. Typed errors pass through."""

        def on_failure(cause: Cause[E_co]) -> Effect[Any, Any, Any]:
            defect = cause.find_defect()
            return _core._FailCause(cause) if defect is None else f(defect)

        return _core._MatchCause(as_effect(self), on_failure, None)

    def or_else_succeed[B](self, f: Callable[[E_co], B]) -> Effect[A_co | B, Never, R_co]:
        """Succeed with ``f(error)`` instead of failing."""
        return self.catch_all(lambda e: _core._Sync(lambda: f(e)))

    def eventually(self) -> Effect[A_co, Never, R_co]:
        """Run again after each typed failure, yielding in between, until it
        succeeds."""
        loop: Effect[A_co, Never, R_co] = self.catch_all(
            lambda _: _core._FlatMap(_core._YieldNow(), lambda _: loop)
        )
        return loop

    def flip(self) -> Effect[E_co, A_co, R_co]:
        """Swap the error and the value: fail with the value, succeed with
        the error. Defects and interruptions stay failures."""
        return _core._MatchCause(as_effect(self), _recovering(_core._Succeed), _fail)

    def sandbox(self) -> Effect[A_co, Cause[E_co], R_co]:
        """Fail with the whole ``Cause``, defects and interruptions included,
        as the typed error."""
        return _core._MatchCause(as_effect(self), _fail, None)

    def or_die(self) -> Effect[A_co, Never, R_co]:
        """Die with the first typed error instead of failing with it."""
        return self.catch_all(lambda e: _core._FailCause(die_cause(_as_exception(e))))

    def tap_error[E2 = Never, R2 = Never](
        self, f: Callable[[E_co], Effect[object, E2, R2]]
    ) -> Effect[A_co, E_co | E2, R_co | R2]:
        def on_failure(cause: Cause[E_co]) -> Effect[Any, Any, Any]:
            found = cause.find_fail()
            if not isinstance(found, Fail):
                return _core._FailCause(cause)
            return _core._FlatMap(f(found.error), lambda _: _core._FailCause(cause))

        return _core._MatchCause(as_effect(self), on_failure, None)

    def tap_cause[E2 = Never, R2 = Never](
        self, f: Callable[[Cause[E_co]], Effect[object, E2, R2]]
    ) -> Effect[A_co, E_co | E2, R_co | R2]:
        return _core._MatchCause(
            as_effect(self), lambda c: _core._FlatMap(f(c), lambda _: _core._FailCause(c)), None
        )

    def tap_cause_if[E2 = Never, R2 = Never](
        self,
        predicate: Callable[[Cause[E_co]], bool],
        f: Callable[[Cause[E_co]], Effect[object, E2, R2]],
    ) -> Effect[A_co, E_co | E2, R_co | R2]:
        """``tap_cause`` for the causes that pass ``predicate``."""

        def on_failure(cause: Cause[E_co]) -> Effect[Any, Any, Any]:
            if not predicate(cause):
                return _core._FailCause(cause)
            return _core._FlatMap(f(cause), lambda _: _core._FailCause(cause))

        return _core._MatchCause(as_effect(self), on_failure, None)

    def tap_defect[E2 = Never, R2 = Never](
        self, f: Callable[[BaseException], Effect[object, E2, R2]]
    ) -> Effect[A_co, E_co | E2, R_co | R2]:
        """Run ``f(defect)`` for the first defect, then keep failing."""

        def on_failure(cause: Cause[E_co]) -> Effect[Any, Any, Any]:
            defect = cause.find_defect()
            if defect is None:
                return _core._FailCause(cause)
            return _core._FlatMap(f(defect), lambda _: _core._FailCause(cause))

        return _core._MatchCause(as_effect(self), on_failure, None)

    @overload
    def tap_error_tag[T1, E2 = Never, R2 = Never](
        self, tag: type[T1], f: Callable[[T1], Effect[object, E2, R2]]
    ) -> Effect[A_co, E_co | E2, R_co | R2]: ...
    @overload
    def tap_error_tag[T1, T2, E2 = Never, R2 = Never](
        self, tag: tuple[type[T1], type[T2]], f: Callable[[T1 | T2], Effect[object, E2, R2]]
    ) -> Effect[A_co, E_co | E2, R_co | R2]: ...
    @overload
    def tap_error_tag[T1, T2, T3, E2 = Never, R2 = Never](
        self,
        tag: tuple[type[T1], type[T2], type[T3]],
        f: Callable[[T1 | T2 | T3], Effect[object, E2, R2]],
    ) -> Effect[A_co, E_co | E2, R_co | R2]: ...
    def tap_error_tag(
        self,
        tag: type[Any] | tuple[type[Any], ...],
        f: Callable[[Any], Effect[object, Any, Any]],
    ) -> Effect[Any, Any, Any]:
        """``tap_error`` for the errors that are instances of ``tag`` (a
        class or a tuple of classes)."""
        return self.tap_error(lambda e: f(e) if isinstance(e, tag) else _core._Succeed(None))

    def ignore(self) -> Effect[None, Never, R_co]:
        """Discard the value and any typed error."""
        return _core._MatchCause(as_effect(self), _ignore_failure, _succeed_none)

    def ignore_cause(self) -> Effect[None, Never, R_co]:
        """Discard the value and the whole cause: typed errors, defects and
        interrupts."""
        return _core._MatchCause(as_effect(self), _succeed_none, _succeed_none)


def _fail[E](error: E) -> Effect[Never, E]:
    return _core._FailCause(fail_cause(error))


def _succeed_none(_: object) -> Effect[None]:
    return _core._Succeed(None)


def _recovering(
    f: Callable[[Any], Effect[Any, Any, Any]],
) -> Callable[[Cause[Any]], Effect[Any, Any, Any]]:
    """A failure handler that passes the recoverable typed error to ``f``.
    Every typed recovery goes through this, so a defect always wins: the
    cause is then re-failed with its typed errors elected to defects."""

    def handle(cause: Cause[Any]) -> Effect[Any, Any, Any]:
        found = cause.find_recoverable_error()
        return f(found.error) if isinstance(found, Fail) else _core._FailCause(found)

    return handle


_ignore_failure = _recovering(_succeed_none)


def _catching_if(
    predicate: Callable[[Any], bool],
    f: Callable[[Any], Effect[Any, Any, Any]],
    or_else: Callable[[Any], Effect[Any, Any, Any]] | None,
) -> Callable[[Cause[Any]], Effect[Any, Any, Any]]:
    """The failure handler of ``catch_if`` and ``catch_tag``. An error that
    fails ``predicate`` goes to ``or_else``, or re-fails with the whole cause."""

    def handle(cause: Cause[Any]) -> Effect[Any, Any, Any]:
        found = cause.find_recoverable_error()
        if not isinstance(found, Fail):
            return _core._FailCause(found)
        if predicate(found.error):
            return f(found.error)
        return _core._FailCause(cause) if or_else is None else or_else(found.error)

    return handle
