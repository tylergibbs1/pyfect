"""Channel recovery from reason errors, as ``pyfect.catch_reason`` /
``catch_reasons`` / ``unwrap_reason`` for effects: use with ``.pipe``.

Handlers get ``(reason, error)`` and return a channel reading the same
upstream. Without ``or_else`` the parent error stays in ``OutErr``; with it
(a ``def`` whose first parameter covers the other reasons), it leaves.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, overload

from pyfect._reasons import HasReason, ReasonCatch, ReasonHandler
from pyfect.channel._base import AnyChannel, ChannelBase
from pyfect.channel._channel import Channel

type _Ch[O, E, D, I, IE, ID, R] = Channel[O, E, D, I, IE, ID, R]
type _AnyCh = Channel[Any, Any, Any, Any, Any, Any, Any]
type _Run = Callable[[AnyChannel], _AnyCh]
type _Case[K, T, O, E, D, I, IE, ID, R] = tuple[
    type[K], Callable[[K, T], _Ch[O, E, D, I, IE, ID, R]]
]


def _reason_catch(
    tag: type[Any],
    cases: tuple[tuple[type[Any], ReasonHandler[AnyChannel]], ...],
    or_else: ReasonHandler[AnyChannel] | None,
) -> _Run:
    from pyfect.channel import _errors
    from pyfect.channel._constructors import fail

    catch = ReasonCatch(tag, cases, or_else, fail)
    return lambda ch: _errors.catch_if(ch, catch.accepts, catch, None)


class _CatchReason[O2, E2, D2, I, IE, ID, R2]:
    """Handles some reasons; the parent error stays in ``OutErr``."""

    __slots__ = ("run",)

    def __init__(self, run: _Run) -> None:
        self.run = run

    def __call__[O, E, D, R](
        self, channel: ChannelBase[O, E, D, I, IE, ID, R]
    ) -> Channel[O | O2, E | E2, D | D2, I, IE, ID, R | R2]:
        return self.run(channel)


class _CatchReasonAll[T, P, RK, EO, O2, EE, D2, I, IE, ID, RR]:
    """Handles every instance of ``T`` and removes it; binding ``self``
    checks that ``RK`` and ``or_else``'s ``EO`` cover ``T``'s reason."""

    __slots__ = ("run",)

    def __init__(self, run: _Run) -> None:
        self.run = run

    @overload
    def __call__[O, D, R](
        self: _CatchReasonAll[T, HasReason[RK | EO], RK, EO, O2, EE, D2, I, IE, ID, RR],
        channel: ChannelBase[O, T, D, I, IE, ID, R],
    ) -> Channel[O | O2, EE, D | D2, I, IE, ID, R | RR]: ...
    @overload
    def __call__[O, D, R, ER](
        self: _CatchReasonAll[T, HasReason[RK | EO], RK, EO, O2, EE, D2, I, IE, ID, RR],
        channel: ChannelBase[O, T | ER, D, I, IE, ID, R],
    ) -> Channel[O | O2, ER | EE, D | D2, I, IE, ID, R | RR]: ...
    def __call__(self, channel: AnyChannel) -> _AnyCh:
        return self.run(channel)


@overload
def catch_reason[
    T: HasReason[Any],
    RK,
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    E2 = Never,
    R2 = Never,
](
    tag: type[T], reason: type[RK], f: Callable[[RK, T], _Ch[O2, E2, D2, I, IE, ID, R2]]
) -> _CatchReason[O2, E2, D2, I, IE, ID, R2]: ...
@overload
def catch_reason[
    T: HasReason[Any],
    RK,
    EO,
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    reason: type[RK],
    f: Callable[[RK, T], _Ch[O2, EE, D2, I, IE, ID, RR]],
    *,
    or_else: Callable[[EO, T], _Ch[O2, EE, D2, I, IE, ID, RR]],
) -> _CatchReasonAll[T, T, RK, EO, O2, EE, D2, I, IE, ID, RR]: ...
def catch_reason(
    tag: type[Any],
    reason: type[Any],
    f: ReasonHandler[AnyChannel],
    *,
    or_else: ReasonHandler[AnyChannel] | None = None,
) -> Any:
    """Switch to ``f(reason, error)`` when the channel fails with a ``tag``
    error whose ``reason`` is an instance of ``reason``; with ``or_else``,
    other ``tag`` errors switch to ``or_else(reason, error)``."""
    run = _reason_catch(tag, ((reason, f),), or_else)
    return (
        _CatchReason[Any, Any, Any, Any, Any, Any, Any](run)
        if or_else is None
        else _CatchReasonAll[Any, Any, Any, Any, Any, Any, Any, Any, Any, Any, Any](run)
    )


# --- generated catch_reasons overloads (tests/test_catch_reasons_overloads.py) ---
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    /,
) -> _CatchReason[O2, EE, D2, I, IE, ID, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    case2: _Case[K2, T, O2, EE, D2, I, IE, ID, RR],
    /,
) -> _CatchReason[O2, EE, D2, I, IE, ID, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    case2: _Case[K2, T, O2, EE, D2, I, IE, ID, RR],
    case3: _Case[K3, T, O2, EE, D2, I, IE, ID, RR],
    /,
) -> _CatchReason[O2, EE, D2, I, IE, ID, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    case2: _Case[K2, T, O2, EE, D2, I, IE, ID, RR],
    case3: _Case[K3, T, O2, EE, D2, I, IE, ID, RR],
    case4: _Case[K4, T, O2, EE, D2, I, IE, ID, RR],
    /,
) -> _CatchReason[O2, EE, D2, I, IE, ID, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    K5,
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    case2: _Case[K2, T, O2, EE, D2, I, IE, ID, RR],
    case3: _Case[K3, T, O2, EE, D2, I, IE, ID, RR],
    case4: _Case[K4, T, O2, EE, D2, I, IE, ID, RR],
    case5: _Case[K5, T, O2, EE, D2, I, IE, ID, RR],
    /,
) -> _CatchReason[O2, EE, D2, I, IE, ID, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    K5,
    K6,
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    case2: _Case[K2, T, O2, EE, D2, I, IE, ID, RR],
    case3: _Case[K3, T, O2, EE, D2, I, IE, ID, RR],
    case4: _Case[K4, T, O2, EE, D2, I, IE, ID, RR],
    case5: _Case[K5, T, O2, EE, D2, I, IE, ID, RR],
    case6: _Case[K6, T, O2, EE, D2, I, IE, ID, RR],
    /,
) -> _CatchReason[O2, EE, D2, I, IE, ID, RR]: ...
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
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    case2: _Case[K2, T, O2, EE, D2, I, IE, ID, RR],
    case3: _Case[K3, T, O2, EE, D2, I, IE, ID, RR],
    case4: _Case[K4, T, O2, EE, D2, I, IE, ID, RR],
    case5: _Case[K5, T, O2, EE, D2, I, IE, ID, RR],
    case6: _Case[K6, T, O2, EE, D2, I, IE, ID, RR],
    case7: _Case[K7, T, O2, EE, D2, I, IE, ID, RR],
    /,
) -> _CatchReason[O2, EE, D2, I, IE, ID, RR]: ...
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
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    case2: _Case[K2, T, O2, EE, D2, I, IE, ID, RR],
    case3: _Case[K3, T, O2, EE, D2, I, IE, ID, RR],
    case4: _Case[K4, T, O2, EE, D2, I, IE, ID, RR],
    case5: _Case[K5, T, O2, EE, D2, I, IE, ID, RR],
    case6: _Case[K6, T, O2, EE, D2, I, IE, ID, RR],
    case7: _Case[K7, T, O2, EE, D2, I, IE, ID, RR],
    case8: _Case[K8, T, O2, EE, D2, I, IE, ID, RR],
    /,
) -> _CatchReason[O2, EE, D2, I, IE, ID, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    EO,
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    /,
    *,
    or_else: Callable[[EO, T], _Ch[O2, EE, D2, I, IE, ID, RR]],
) -> _CatchReasonAll[T, T, K1, EO, O2, EE, D2, I, IE, ID, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    EO,
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    case2: _Case[K2, T, O2, EE, D2, I, IE, ID, RR],
    /,
    *,
    or_else: Callable[[EO, T], _Ch[O2, EE, D2, I, IE, ID, RR]],
) -> _CatchReasonAll[T, T, K1 | K2, EO, O2, EE, D2, I, IE, ID, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    EO,
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    case2: _Case[K2, T, O2, EE, D2, I, IE, ID, RR],
    case3: _Case[K3, T, O2, EE, D2, I, IE, ID, RR],
    /,
    *,
    or_else: Callable[[EO, T], _Ch[O2, EE, D2, I, IE, ID, RR]],
) -> _CatchReasonAll[T, T, K1 | K2 | K3, EO, O2, EE, D2, I, IE, ID, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    EO,
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    case2: _Case[K2, T, O2, EE, D2, I, IE, ID, RR],
    case3: _Case[K3, T, O2, EE, D2, I, IE, ID, RR],
    case4: _Case[K4, T, O2, EE, D2, I, IE, ID, RR],
    /,
    *,
    or_else: Callable[[EO, T], _Ch[O2, EE, D2, I, IE, ID, RR]],
) -> _CatchReasonAll[T, T, K1 | K2 | K3 | K4, EO, O2, EE, D2, I, IE, ID, RR]: ...
@overload
def catch_reasons[
    T: HasReason[Any],
    K1,
    K2,
    K3,
    K4,
    K5,
    EO,
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    case2: _Case[K2, T, O2, EE, D2, I, IE, ID, RR],
    case3: _Case[K3, T, O2, EE, D2, I, IE, ID, RR],
    case4: _Case[K4, T, O2, EE, D2, I, IE, ID, RR],
    case5: _Case[K5, T, O2, EE, D2, I, IE, ID, RR],
    /,
    *,
    or_else: Callable[[EO, T], _Ch[O2, EE, D2, I, IE, ID, RR]],
) -> _CatchReasonAll[T, T, K1 | K2 | K3 | K4 | K5, EO, O2, EE, D2, I, IE, ID, RR]: ...
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
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    case2: _Case[K2, T, O2, EE, D2, I, IE, ID, RR],
    case3: _Case[K3, T, O2, EE, D2, I, IE, ID, RR],
    case4: _Case[K4, T, O2, EE, D2, I, IE, ID, RR],
    case5: _Case[K5, T, O2, EE, D2, I, IE, ID, RR],
    case6: _Case[K6, T, O2, EE, D2, I, IE, ID, RR],
    /,
    *,
    or_else: Callable[[EO, T], _Ch[O2, EE, D2, I, IE, ID, RR]],
) -> _CatchReasonAll[T, T, K1 | K2 | K3 | K4 | K5 | K6, EO, O2, EE, D2, I, IE, ID, RR]: ...
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
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    case2: _Case[K2, T, O2, EE, D2, I, IE, ID, RR],
    case3: _Case[K3, T, O2, EE, D2, I, IE, ID, RR],
    case4: _Case[K4, T, O2, EE, D2, I, IE, ID, RR],
    case5: _Case[K5, T, O2, EE, D2, I, IE, ID, RR],
    case6: _Case[K6, T, O2, EE, D2, I, IE, ID, RR],
    case7: _Case[K7, T, O2, EE, D2, I, IE, ID, RR],
    /,
    *,
    or_else: Callable[[EO, T], _Ch[O2, EE, D2, I, IE, ID, RR]],
) -> _CatchReasonAll[T, T, K1 | K2 | K3 | K4 | K5 | K6 | K7, EO, O2, EE, D2, I, IE, ID, RR]: ...
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
    O2,
    D2 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: type[T],
    case1: _Case[K1, T, O2, EE, D2, I, IE, ID, RR],
    case2: _Case[K2, T, O2, EE, D2, I, IE, ID, RR],
    case3: _Case[K3, T, O2, EE, D2, I, IE, ID, RR],
    case4: _Case[K4, T, O2, EE, D2, I, IE, ID, RR],
    case5: _Case[K5, T, O2, EE, D2, I, IE, ID, RR],
    case6: _Case[K6, T, O2, EE, D2, I, IE, ID, RR],
    case7: _Case[K7, T, O2, EE, D2, I, IE, ID, RR],
    case8: _Case[K8, T, O2, EE, D2, I, IE, ID, RR],
    /,
    *,
    or_else: Callable[[EO, T], _Ch[O2, EE, D2, I, IE, ID, RR]],
) -> _CatchReasonAll[
    T,
    T,
    K1 | K2 | K3 | K4 | K5 | K6 | K7 | K8,
    EO,
    O2,
    EE,
    D2,
    I,
    IE,
    ID,
    RR,
]: ...
# --- end generated catch_reasons overloads ---
def catch_reasons(
    tag: type[Any],
    *cases: tuple[type[Any], ReasonHandler[AnyChannel]],
    or_else: ReasonHandler[AnyChannel] | None = None,
) -> Any:
    """``catch_reason`` with a ``(reason_class, handler)`` pair per reason,
    tried in order."""
    run = _reason_catch(tag, cases, or_else)
    return (
        _CatchReason[Any, Any, Any, Any, Any, Any, Any](run)
        if or_else is None
        else _CatchReasonAll[Any, Any, Any, Any, Any, Any, Any, Any, Any, Any, Any](run)
    )


class _UnwrapReason[T, P]:
    """Replaces ``T`` in ``OutErr`` with its reason."""

    __slots__ = ("run",)

    def __init__(self, run: _Run) -> None:
        self.run = run

    @overload
    def __call__[O, RE, D, I, IE, ID, R](
        self: _UnwrapReason[T, HasReason[RE]], channel: ChannelBase[O, T, D, I, IE, ID, R]
    ) -> Channel[O, RE, D, I, IE, ID, R]: ...
    @overload
    def __call__[O, RE, D, I, IE, ID, R, ER](
        self: _UnwrapReason[T, HasReason[RE]], channel: ChannelBase[O, T | ER, D, I, IE, ID, R]
    ) -> Channel[O, ER | RE, D, I, IE, ID, R]: ...
    def __call__(self, channel: AnyChannel) -> _AnyCh:
        return self.run(channel)


def unwrap_reason[T: HasReason[Any]](tag: type[T]) -> _UnwrapReason[T, T]:
    """Fail with the ``reason`` of a ``tag`` error instead of the error."""
    from pyfect.channel._constructors import fail

    return _UnwrapReason(_reason_catch(tag, (), lambda reason, _: fail(reason)))
