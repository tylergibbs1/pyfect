"""Stream recovery from reason errors, as ``pyfect.catch_reason`` /
``catch_reasons`` / ``unwrap_reason`` for effects: use with ``.pipe``::

    s.pipe(stream.catch_reason(AiError, RateLimitError, lambda r, e: stream.succeed(0)))

Handlers get ``(reason, error)`` and return a stream. Without ``or_else``
the parent error stays in the stream's errors; with it (a ``def`` whose
first parameter covers the other reasons), it leaves them.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, overload

from pyfect._reasons import HasReason, ReasonCatch, ReasonHandler
from pyfect.stream._base import AnyStream, StreamBase
from pyfect.stream._catch import catch_if
from pyfect.stream._constructors import fail
from pyfect.stream._stream import Stream

type _S[A, E, R] = StreamBase[A, E, R]
type _Run = Callable[[AnyStream], Stream[Any, Any, Any]]


def _reason_catch(
    tag: type[Any],
    cases: tuple[tuple[type[Any], ReasonHandler[AnyStream]], ...],
    or_else: ReasonHandler[AnyStream] | None,
) -> _Run:
    catch = ReasonCatch(tag, cases, or_else, fail)
    return lambda s: catch_if(s, catch.accepts, catch, None)


class _CatchReason[A2, E2, R2]:
    """Handles some reasons; the parent error stays in the stream's errors."""

    __slots__ = ("run",)

    def __init__(self, run: _Run) -> None:
        self.run = run

    def __call__[A, E, R](self, stream: _S[A, E, R]) -> Stream[A | A2, E | E2, R | R2]:
        return self.run(stream)


class _CatchReasonAll[T, P, RK, EO, A2, A3, EE, RR]:
    """Handles every instance of ``T`` and removes it; binding ``self``
    checks that ``RK`` and ``or_else``'s ``EO`` cover ``T``'s reason."""

    __slots__ = ("run",)

    def __init__(self, run: _Run) -> None:
        self.run = run

    @overload
    def __call__[A, R](
        self: _CatchReasonAll[T, HasReason[RK | EO], RK, EO, A2, A3, EE, RR], stream: _S[A, T, R]
    ) -> Stream[A | A2 | A3, EE, R | RR]: ...
    @overload
    def __call__[A, R, ER](
        self: _CatchReasonAll[T, HasReason[RK | EO], RK, EO, A2, A3, EE, RR],
        stream: _S[A, T | ER, R],
    ) -> Stream[A | A2 | A3, ER | EE, R | RR]: ...
    def __call__(self, stream: AnyStream) -> Stream[Any, Any, Any]:
        return self.run(stream)


@overload
def catch_reason[T: HasReason[Any], RK, A2, E2 = Never, R2 = Never](
    tag: type[T], reason: type[RK], f: Callable[[RK, T], _S[A2, E2, R2]]
) -> _CatchReason[A2, E2, R2]: ...
@overload
def catch_reason[T: HasReason[Any], RK, EO, A2, A3, EE = Never, RR = Never](
    tag: type[T],
    reason: type[RK],
    f: Callable[[RK, T], _S[A2, EE, RR]],
    *,
    or_else: Callable[[EO, T], _S[A3, EE, RR]],
) -> _CatchReasonAll[T, T, RK, EO, A2, A3, EE, RR]: ...
def catch_reason(
    tag: type[Any],
    reason: type[Any],
    f: ReasonHandler[AnyStream],
    *,
    or_else: ReasonHandler[AnyStream] | None = None,
) -> Any:
    """Switch to ``f(reason, error)`` when the stream fails with a ``tag``
    error whose ``reason`` is an instance of ``reason``; with ``or_else``,
    other ``tag`` errors switch to ``or_else(reason, error)``."""
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
    A1,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    /,
) -> _CatchReason[A1, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    A1,
    A2,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _S[A2, EE, RR]]],
    /,
) -> _CatchReason[A1 | A2, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    A1,
    A2,
    A3,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _S[A2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _S[A3, EE, RR]]],
    /,
) -> _CatchReason[A1 | A2 | A3, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    A1,
    A2,
    A3,
    A4,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _S[A2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _S[A3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _S[A4, EE, RR]]],
    /,
) -> _CatchReason[A1 | A2 | A3 | A4, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    K5,
    A1,
    A2,
    A3,
    A4,
    A5,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _S[A2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _S[A3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _S[A4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _S[A5, EE, RR]]],
    /,
) -> _CatchReason[A1 | A2 | A3 | A4 | A5, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    K5,
    K6,
    A1,
    A2,
    A3,
    A4,
    A5,
    A6,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _S[A2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _S[A3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _S[A4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _S[A5, EE, RR]]],
    case6: tuple[type[K6], Callable[[K6, T], _S[A6, EE, RR]]],
    /,
) -> _CatchReason[A1 | A2 | A3 | A4 | A5 | A6, EE, RR]: ...
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
    A1,
    A2,
    A3,
    A4,
    A5,
    A6,
    A7,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _S[A2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _S[A3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _S[A4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _S[A5, EE, RR]]],
    case6: tuple[type[K6], Callable[[K6, T], _S[A6, EE, RR]]],
    case7: tuple[type[K7], Callable[[K7, T], _S[A7, EE, RR]]],
    /,
) -> _CatchReason[A1 | A2 | A3 | A4 | A5 | A6 | A7, EE, RR]: ...
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
    A1,
    A2,
    A3,
    A4,
    A5,
    A6,
    A7,
    A8,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _S[A2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _S[A3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _S[A4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _S[A5, EE, RR]]],
    case6: tuple[type[K6], Callable[[K6, T], _S[A6, EE, RR]]],
    case7: tuple[type[K7], Callable[[K7, T], _S[A7, EE, RR]]],
    case8: tuple[type[K8], Callable[[K8, T], _S[A8, EE, RR]]],
    /,
) -> _CatchReason[A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    EO,
    A1,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _S[C, EE, RR]],
) -> _CatchReasonAll[T, T, K1, EO, A1, C, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    EO,
    A1,
    A2,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _S[A2, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _S[C, EE, RR]],
) -> _CatchReasonAll[T, T, K1 | K2, EO, A1 | A2, C, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    EO,
    A1,
    A2,
    A3,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _S[A2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _S[A3, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _S[C, EE, RR]],
) -> _CatchReasonAll[T, T, K1 | K2 | K3, EO, A1 | A2 | A3, C, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    EO,
    A1,
    A2,
    A3,
    A4,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _S[A2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _S[A3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _S[A4, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _S[C, EE, RR]],
) -> _CatchReasonAll[T, T, K1 | K2 | K3 | K4, EO, A1 | A2 | A3 | A4, C, EE, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    K5,
    EO,
    A1,
    A2,
    A3,
    A4,
    A5,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _S[A2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _S[A3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _S[A4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _S[A5, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _S[C, EE, RR]],
) -> _CatchReasonAll[T, T, K1 | K2 | K3 | K4 | K5, EO, A1 | A2 | A3 | A4 | A5, C, EE, RR]: ...
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
    A1,
    A2,
    A3,
    A4,
    A5,
    A6,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _S[A2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _S[A3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _S[A4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _S[A5, EE, RR]]],
    case6: tuple[type[K6], Callable[[K6, T], _S[A6, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _S[C, EE, RR]],
) -> _CatchReasonAll[
    T,
    T,
    K1 | K2 | K3 | K4 | K5 | K6,
    EO,
    A1 | A2 | A3 | A4 | A5 | A6,
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
    A1,
    A2,
    A3,
    A4,
    A5,
    A6,
    A7,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _S[A2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _S[A3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _S[A4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _S[A5, EE, RR]]],
    case6: tuple[type[K6], Callable[[K6, T], _S[A6, EE, RR]]],
    case7: tuple[type[K7], Callable[[K7, T], _S[A7, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _S[C, EE, RR]],
) -> _CatchReasonAll[
    T,
    T,
    K1 | K2 | K3 | K4 | K5 | K6 | K7,
    EO,
    A1 | A2 | A3 | A4 | A5 | A6 | A7,
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
    A1,
    A2,
    A3,
    A4,
    A5,
    A6,
    A7,
    A8,
    C,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: tuple[type[K1], Callable[[K1, T], _S[A1, EE, RR]]],
    case2: tuple[type[K2], Callable[[K2, T], _S[A2, EE, RR]]],
    case3: tuple[type[K3], Callable[[K3, T], _S[A3, EE, RR]]],
    case4: tuple[type[K4], Callable[[K4, T], _S[A4, EE, RR]]],
    case5: tuple[type[K5], Callable[[K5, T], _S[A5, EE, RR]]],
    case6: tuple[type[K6], Callable[[K6, T], _S[A6, EE, RR]]],
    case7: tuple[type[K7], Callable[[K7, T], _S[A7, EE, RR]]],
    case8: tuple[type[K8], Callable[[K8, T], _S[A8, EE, RR]]],
    /,
    *,
    or_else: Callable[[EO, T], _S[C, EE, RR]],
) -> _CatchReasonAll[
    T,
    T,
    K1 | K2 | K3 | K4 | K5 | K6 | K7 | K8,
    EO,
    A1 | A2 | A3 | A4 | A5 | A6 | A7 | A8,
    C,
    EE,
    RR,
]: ...
# --- end generated catch_reasons overloads ---
def catch_reasons(
    tag: type[Any],
    *cases: tuple[type[Any], ReasonHandler[AnyStream]],
    or_else: ReasonHandler[AnyStream] | None = None,
) -> Any:
    """``catch_reason`` with a ``(reason_class, handler)`` pair per reason,
    tried in order."""
    run = _reason_catch(tag, cases, or_else)
    return (
        _CatchReason[Any, Any, Any](run)
        if or_else is None
        else _CatchReasonAll[Any, Any, Any, Any, Any, Any, Any, Any](run)
    )


class _UnwrapReason[T, P]:
    """Replaces ``T`` in the stream's errors with its reason."""

    __slots__ = ("run",)

    def __init__(self, run: _Run) -> None:
        self.run = run

    @overload
    def __call__[A, RE, R](
        self: _UnwrapReason[T, HasReason[RE]], stream: _S[A, T, R]
    ) -> Stream[A, RE, R]: ...
    @overload
    def __call__[A, RE, R, ER](
        self: _UnwrapReason[T, HasReason[RE]], stream: _S[A, T | ER, R]
    ) -> Stream[A, ER | RE, R]: ...
    def __call__(self, stream: AnyStream) -> Stream[Any, Any, Any]:
        return self.run(stream)


def unwrap_reason[T: HasReason[Any]](tag: type[T]) -> _UnwrapReason[T, T]:
    """Fail with the ``reason`` of a ``tag`` error instead of the error."""
    return _UnwrapReason(_reason_catch(tag, (), lambda reason, _: fail(reason)))
