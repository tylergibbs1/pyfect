"""Recovery from reason errors (Effect's ``catchReason``, ``catchReasons`` and
``unwrapReason``): use with ``.pipe``.

The parent error's class is the tag, and its ``reason`` field's classes are
the reason tags; matching is by ``isinstance``, as in ``catch_tag``::

    eff.pipe(fx.catch_reason(AiError, RateLimitError, lambda r, e: fx.succeed(r.retry_after)))
    eff.pipe(fx.catch_reasons(AiError, (RateLimitError, on_rate), (QuotaExceededError, on_quota)))
    eff.pipe(fx.unwrap_reason(AiError))  # fails with the reason instead of AiError

Handlers get ``(reason, error)``. Without ``or_else`` the parent error stays
in ``E``, because an error with another reason passes through. With
``or_else`` (a ``def`` whose first parameter is annotated with the other
reasons; pyright checks it covers them) every instance of the parent class
is handled, so it leaves ``E``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, overload

from pyfect._core import Effect, _catching_if, _FailCause, _MatchCause
from pyfect._reasons import HasReason, ReasonCatch, ReasonHandler
from pyfect.cause import fail as fail_cause


def _fail(error: object) -> Effect[Never, Any]:
    return _FailCause(fail_cause(error))


type _Eff[A, E, R] = Effect[A, E, R]


def _reason_catch(
    tag: type[Any],
    cases: tuple[tuple[type[Any], ReasonHandler[Effect[Any, Any, Any]]], ...],
    or_else: ReasonHandler[Effect[Any, Any, Any]] | None,
) -> Callable[[Effect[Any, Any, Any]], Effect[Any, Any, Any]]:
    catch = ReasonCatch(tag, cases, or_else, _fail)
    handle = _catching_if(catch.accepts, catch, None)
    return lambda eff: _MatchCause(eff, handle, None)


class _CatchReason[B, E2, R2]:
    """Handles some reasons; the parent error stays in ``E``."""

    __slots__ = ("run",)

    def __init__(self, run: Callable[[Effect[Any, Any, Any]], Effect[Any, Any, Any]]) -> None:
        self.run = run

    def __call__[A, E, R = Never](self, eff: Effect[A, E, R]) -> Effect[A | B, E | E2, R | R2]:
        return self.run(eff)


class _CatchReasonAll[T, P, RK, EO, B, C, EE, RR]:
    """Handles every instance of ``T`` and removes it from ``E``. ``P`` is
    ``T`` again: binding ``self`` checks that the handled reasons ``RK`` and
    ``or_else``'s ``EO`` cover ``T``'s reason."""

    __slots__ = ("run",)

    def __init__(self, run: Callable[[Effect[Any, Any, Any]], Effect[Any, Any, Any]]) -> None:
        self.run = run

    @overload
    def __call__[A, R = Never](
        self: _CatchReasonAll[T, HasReason[RK | EO], RK, EO, B, C, EE, RR], eff: _Eff[A, T, R]
    ) -> Effect[A | B | C, EE, R | RR]: ...
    @overload
    def __call__[A, R = Never, ER = Never](
        self: _CatchReasonAll[T, HasReason[RK | EO], RK, EO, B, C, EE, RR],
        eff: _Eff[A, T | ER, R],
    ) -> Effect[A | B | C, ER | EE, R | RR]: ...
    def __call__(self, eff: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
        return self.run(eff)


@overload
def catch_reason[T: HasReason[Any], RK, B, E2 = Never, R2 = Never](
    tag: type[T], reason: type[RK], f: Callable[[RK, T], _Eff[B, E2, R2]]
) -> _CatchReason[B, E2, R2]: ...
@overload
def catch_reason[T: HasReason[Any], RK, EO, B, C, EE = Never, RR = Never](
    tag: type[T],
    reason: type[RK],
    f: Callable[[RK, T], _Eff[B, EE, RR]],
    *,
    or_else: Callable[[EO, T], _Eff[C, EE, RR]],
) -> _CatchReasonAll[T, T, RK, EO, B, C, EE, RR]: ...
def catch_reason(
    tag: type[Any],
    reason: type[Any],
    f: ReasonHandler[Effect[Any, Any, Any]],
    *,
    or_else: ReasonHandler[Effect[Any, Any, Any]] | None = None,
) -> Any:
    """Recover from a ``tag`` error whose ``reason`` is an instance of
    ``reason``: ``f(reason, error)``. With ``or_else``, the ``tag`` errors
    with any other reason go to ``or_else(reason, error)``. Defects win,
    as in every typed recovery."""
    run = _reason_catch(tag, ((reason, f),), or_else)
    return (
        _CatchReason[Any, Any, Any](run)
        if or_else is None
        else _CatchReasonAll[Any, Any, Any, Any, Any, Any, Any, Any](run)
    )


# --- generated catch_reasons overloads (tests/test_catch_reasons_overloads.py) ---
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    B1,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    /,
) -> _CatchReason[B1, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    B1,
    B2,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _Eff[B2, EE, RR]]],
    /,
) -> _CatchReason[B1 | B2, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    B1,
    B2,
    B3,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _Eff[B2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _Eff[B3, EE, RR]]],
    /,
) -> _CatchReason[B1 | B2 | B3, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    B1,
    B2,
    B3,
    B4,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _Eff[B2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _Eff[B3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _Eff[B4, EE, RR]]],
    /,
) -> _CatchReason[B1 | B2 | B3 | B4, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    K5,
    B1,
    B2,
    B3,
    B4,
    B5,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _Eff[B2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _Eff[B3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _Eff[B4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _Eff[B5, EE, RR]]],
    /,
) -> _CatchReason[B1 | B2 | B3 | B4 | B5, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    K5,
    K6,
    B1,
    B2,
    B3,
    B4,
    B5,
    B6,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _Eff[B2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _Eff[B3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _Eff[B4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _Eff[B5, EE, RR]]],
    case6: tuple[type[K6], Callable[[K6, T], _Eff[B6, EE, RR]]],
    /,
) -> _CatchReason[B1 | B2 | B3 | B4 | B5 | B6, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    K5,
    K6,
    K7,
    B1,
    B2,
    B3,
    B4,
    B5,
    B6,
    B7,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _Eff[B2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _Eff[B3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _Eff[B4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _Eff[B5, EE, RR]]],
    case6: tuple[type[K6], Callable[[K6, T], _Eff[B6, EE, RR]]],
    case7: tuple[type[K7], Callable[[K7, T], _Eff[B7, EE, RR]]],
    /,
) -> _CatchReason[B1 | B2 | B3 | B4 | B5 | B6 | B7, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    K5,
    K6,
    K7,
    K8,
    B1,
    B2,
    B3,
    B4,
    B5,
    B6,
    B7,
    B8,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _Eff[B2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _Eff[B3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _Eff[B4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _Eff[B5, EE, RR]]],
    case6: tuple[type[K6], Callable[[K6, T], _Eff[B6, EE, RR]]],
    case7: tuple[type[K7], Callable[[K7, T], _Eff[B7, EE, RR]]],
    case8: tuple[type[K8], Callable[[K8, T], _Eff[B8, EE, RR]]],
    /,
) -> _CatchReason[B1 | B2 | B3 | B4 | B5 | B6 | B7 | B8, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    EO,
    B1,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _Eff[C, EE, RR]],
) -> _CatchReasonAll[T, T, K1, EO, B1, C, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    EO,
    B1,
    B2,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _Eff[B2, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _Eff[C, EE, RR]],
) -> _CatchReasonAll[T, T, K1 | K2, EO, B1 | B2, C, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    EO,
    B1,
    B2,
    B3,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _Eff[B2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _Eff[B3, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _Eff[C, EE, RR]],
) -> _CatchReasonAll[T, T, K1 | K2 | K3, EO, B1 | B2 | B3, C, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    EO,
    B1,
    B2,
    B3,
    B4,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _Eff[B2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _Eff[B3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _Eff[B4, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _Eff[C, EE, RR]],
) -> _CatchReasonAll[T, T, K1 | K2 | K3 | K4, EO, B1 | B2 | B3 | B4, C, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    K5,
    EO,
    B1,
    B2,
    B3,
    B4,
    B5,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _Eff[B2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _Eff[B3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _Eff[B4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _Eff[B5, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _Eff[C, EE, RR]],
) -> _CatchReasonAll[T, T, K1 | K2 | K3 | K4 | K5, EO, B1 | B2 | B3 | B4 | B5, C, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    K5,
    K6,
    EO,
    B1,
    B2,
    B3,
    B4,
    B5,
    B6,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _Eff[B2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _Eff[B3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _Eff[B4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _Eff[B5, EE, RR]]],
    case6: tuple[type[K6], Callable[[K6, T], _Eff[B6, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _Eff[C, EE, RR]],
) -> _CatchReasonAll[
    T,
    T,
    K1 | K2 | K3 | K4 | K5 | K6,
    EO,
    B1 | B2 | B3 | B4 | B5 | B6,
    C,
    EE,
    RR,
]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    K5,
    K6,
    K7,
    EO,
    B1,
    B2,
    B3,
    B4,
    B5,
    B6,
    B7,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _Eff[B2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _Eff[B3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _Eff[B4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _Eff[B5, EE, RR]]],
    case6: tuple[type[K6], Callable[[K6, T], _Eff[B6, EE, RR]]],
    case7: tuple[type[K7], Callable[[K7, T], _Eff[B7, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _Eff[C, EE, RR]],
) -> _CatchReasonAll[
    T,
    T,
    K1 | K2 | K3 | K4 | K5 | K6 | K7,
    EO,
    B1 | B2 | B3 | B4 | B5 | B6 | B7,
    C,
    EE,
    RR,
]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    K5,
    K6,
    K7,
    K8,
    EO,
    B1,
    B2,
    B3,
    B4,
    B5,
    B6,
    B7,
    B8,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _Eff[B1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _Eff[B2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _Eff[B3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _Eff[B4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _Eff[B5, EE, RR]]],
    case6: tuple[type[K6], Callable[[K6, T], _Eff[B6, EE, RR]]],
    case7: tuple[type[K7], Callable[[K7, T], _Eff[B7, EE, RR]]],
    case8: tuple[type[K8], Callable[[K8, T], _Eff[B8, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _Eff[C, EE, RR]],
) -> _CatchReasonAll[
    T,
    T,
    K1 | K2 | K3 | K4 | K5 | K6 | K7 | K8,
    EO,
    B1 | B2 | B3 | B4 | B5 | B6 | B7 | B8,
    C,
    EE,
    RR,
]: ...
# --- end generated catch_reasons overloads ---
def catch_reasons(
    tag: type[Any],
    *cases: tuple[type[Any], ReasonHandler[Effect[Any, Any, Any]]],
    or_else: ReasonHandler[Effect[Any, Any, Any]] | None = None,
) -> Any:
    """``catch_reason`` with one handler per reason class: each case is a
    ``(reason_class, handler)`` pair, tried in order (Effect's
    ``catchReasons`` object of handlers)."""
    run = _reason_catch(tag, cases, or_else)
    return (
        _CatchReason[Any, Any, Any](run)
        if or_else is None
        else _CatchReasonAll[Any, Any, Any, Any, Any, Any, Any, Any](run)
    )


class _UnwrapReason[T, P]:
    """Replaces ``T`` in ``E`` with its reason. ``P`` is ``T`` again, read
    as ``HasReason[RE]`` to find the reason's type."""

    __slots__ = ("run",)

    def __init__(self, run: Callable[[Effect[Any, Any, Any]], Effect[Any, Any, Any]]) -> None:
        self.run = run

    @overload
    def __call__[A, RE, R = Never](
        self: _UnwrapReason[T, HasReason[RE]], eff: _Eff[A, T, R]
    ) -> Effect[A, RE, R]: ...
    @overload
    def __call__[A, RE, R = Never, ER = Never](
        self: _UnwrapReason[T, HasReason[RE]], eff: _Eff[A, T | ER, R]
    ) -> Effect[A, ER | RE, R]: ...
    def __call__(self, eff: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
        return self.run(eff)


def unwrap_reason[T: HasReason[Any]](tag: type[T]) -> _UnwrapReason[T, T]:
    """Fail with the ``reason`` of a ``tag`` error instead of the error
    itself, promoting the reasons into ``E``."""
    run = _reason_catch(tag, (), lambda reason, _: _fail(reason))
    return _UnwrapReason(run)
