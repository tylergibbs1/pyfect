"""Channel recovery that removes the caught errors from ``OutErr``: use with
``.pipe``, as ``pyfect.catch_tag`` / ``catch_if`` for effects::

    channel.pipe(catch_tag(NotFound, lambda e: channel.succeed(0)))

The handler's channel reads the same upstream as the channel it
recovers, so both have the same input types.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, TypeIs, overload

from pyfect._tags import Tags
from pyfect.channel import _errors
from pyfect.channel._base import AnyChannel, ChannelBase
from pyfect.channel._channel import Channel

type Handler = Callable[[Any], AnyChannel]


class _CatchSome[EC, O2, E2, D2, I, IE, ID, R2]:
    """Removes ``EC`` from a channel's errors."""

    __slots__ = ("f", "or_else", "predicate")

    def __init__(
        self, predicate: Callable[[Any], bool], f: Handler, or_else: Handler | None
    ) -> None:
        self.predicate = predicate
        self.f = f
        self.or_else = or_else

    @overload
    def __call__[O, D, R](
        self, channel: ChannelBase[O, EC, D, I, IE, ID, R]
    ) -> Channel[O | O2, E2, D | D2, I, IE, ID, R | R2]: ...
    @overload
    def __call__[O, D, R, ER](
        self, channel: ChannelBase[O, EC | ER, D, I, IE, ID, R]
    ) -> Channel[O | O2, ER | E2, D | D2, I, IE, ID, R | R2]: ...
    def __call__(self, channel: AnyChannel) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
        from pyfect.channel import _errors

        return _errors.catch_if(channel, self.predicate, self.f, self.or_else)


class _CatchAll[EC, EO, O2, O3, EE, D2, D3, I, IE, ID, RR]:
    """Handles ``EC`` with one handler and ``EO``, which must be every other
    error of the channel, with another."""

    __slots__ = ("f", "or_else", "predicate")

    def __init__(self, predicate: Callable[[Any], bool], f: Handler, or_else: Handler) -> None:
        self.predicate = predicate
        self.f = f
        self.or_else = or_else

    def __call__[O, D, R](
        self, channel: ChannelBase[O, EC | EO, D, I, IE, ID, R]
    ) -> Channel[O | O2 | O3, EE, D | D2 | D3, I, IE, ID, R | RR]:
        from pyfect.channel import _errors

        return _errors.catch_if(channel, self.predicate, self.f, self.or_else)


type _Ch[O, E, D, I, IE, ID, R] = Channel[O, E, D, I, IE, ID, R]


@overload
def catch_if[EB, O2, D2 = None, I = object, IE = object, ID = object, E2 = Never, R2 = Never](
    refinement: Callable[[Any], TypeIs[EB]], f: Callable[[EB], _Ch[O2, E2, D2, I, IE, ID, R2]]
) -> _CatchSome[EB, O2, E2, D2, I, IE, ID, R2]: ...
@overload
def catch_if[
    EB,
    EO,
    O2,
    O3,
    D2 = None,
    D3 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    refinement: Callable[[Any], TypeIs[EB]],
    f: Callable[[EB], _Ch[O2, EE, D2, I, IE, ID, RR]],
    *,
    or_else: Callable[[EO], _Ch[O3, EE, D3, I, IE, ID, RR]],
) -> _CatchAll[EB, EO, O2, O3, EE, D2, D3, I, IE, ID, RR]: ...
def catch_if(
    refinement: Callable[[Any], bool], f: Handler, *, or_else: Handler | None = None
) -> Any:
    """Recover from the typed errors ``refinement`` accepts and remove them
    from ``OutErr``. For a plain ``bool`` predicate, use the ``catch_if``
    method."""
    if or_else is None:
        return _CatchSome[Any, Any, Any, Any, Any, Any, Any, Any](refinement, f, None)
    return _CatchAll[Any, Any, Any, Any, Any, Any, Any, Any, Any, Any, Any](refinement, f, or_else)


@overload
def catch_tag[T, O2, D2 = None, I = object, IE = object, ID = object, E2 = Never, R2 = Never](
    tag: Tags[T], f: Callable[[T], _Ch[O2, E2, D2, I, IE, ID, R2]]
) -> _CatchSome[T, O2, E2, D2, I, IE, ID, R2]: ...
@overload
def catch_tag[
    T,
    EO,
    O2,
    O3,
    D2 = None,
    D3 = None,
    I = object,
    IE = object,
    ID = object,
    EE = Never,
    RR = Never,
](
    tag: Tags[T],
    f: Callable[[T], _Ch[O2, EE, D2, I, IE, ID, RR]],
    *,
    or_else: Callable[[EO], _Ch[O3, EE, D3, I, IE, ID, RR]],
) -> _CatchAll[T, EO, O2, O3, EE, D2, D3, I, IE, ID, RR]: ...
def catch_tag(tag: Tags[Any], f: Handler, *, or_else: Handler | None = None) -> Any:
    """Recover from the errors that are instances of ``tag`` (a class or a
    tuple of any number) and remove them from ``OutErr``."""
    predicate: Callable[[Any], bool] = lambda e: isinstance(e, tag)  # noqa: E731
    if or_else is None:
        return _CatchSome[Any, Any, Any, Any, Any, Any, Any, Any](predicate, f, None)
    return _CatchAll[Any, Any, Any, Any, Any, Any, Any, Any, Any, Any, Any](predicate, f, or_else)


class _CatchEvery[E, O2, E2, D2, I, IE, ID, R2]:
    """Handles every typed error ``E`` of a channel."""

    __slots__ = ("f",)

    def __init__(self, f: Callable[[E], _Ch[O2, E2, D2, I, IE, ID, R2]]) -> None:
        self.f = f

    def __call__[O, D, R = Never](
        self, channel: ChannelBase[O, E, D, I, IE, ID, R]
    ) -> Channel[O | O2, E2, D | D2, I, IE, ID, R | R2]:
        return _errors.catch_all(channel, self.f)


def catch_all[E, O2, D2 = None, I = object, IE = object, ID = object, E2 = Never, R2 = Never](
    f: Callable[[E], _Ch[O2, E2, D2, I, IE, ID, R2]],
) -> _CatchEvery[E, O2, E2, D2, I, IE, ID, R2]:
    """``channel.catch_all(f)`` for ``.pipe`` (Effect's ``Channel.catch``):
    go on with ``f(error)`` after any typed failure. Annotate ``f``'s
    parameter (a ``def``): pyright checks it covers every error."""
    return _CatchEvery(f)
