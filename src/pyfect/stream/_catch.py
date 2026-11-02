"""Stream recovery that removes the caught errors from the stream's type:
use with ``.pipe``, as ``pyfect.catch_tag`` / ``catch_if`` for effects::

    numbers.pipe(stream.catch_tag(NotFound, lambda e: stream.succeed(0)))
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, TypeIs, overload

from pyfect.channel import _errors
from pyfect.stream._base import AnyStream, StreamBase
from pyfect.stream._stream import Stream

type Handler = Callable[[Any], AnyStream]


def catch_if(
    self: AnyStream, predicate: Callable[[Any], bool], f: Handler, or_else: Handler | None
) -> Stream[Any, Any, Any]:
    return Stream(
        _errors.catch_if(self._channel, predicate, _on_channel(f), _on_channel_or_none(or_else))
    )


def _on_channel(f: Handler) -> Callable[[Any], Any]:
    return lambda error: f(error)._channel


def _on_channel_or_none(f: Handler | None) -> Callable[[Any], Any] | None:
    return None if f is None else _on_channel(f)


class _CatchSome[EC, A2, E2, R2]:
    """Removes ``EC`` from a stream's errors."""

    __slots__ = ("f", "predicate")

    def __init__(self, predicate: Callable[[Any], bool], f: Handler) -> None:
        self.predicate = predicate
        self.f = f

    @overload
    def __call__[A, R](self, stream: StreamBase[A, EC, R]) -> Stream[A | A2, E2, R | R2]: ...
    @overload
    def __call__[A, R, ER](
        self, stream: StreamBase[A, EC | ER, R]
    ) -> Stream[A | A2, ER | E2, R | R2]: ...
    def __call__(self, stream: AnyStream) -> Stream[Any, Any, Any]:
        return catch_if(stream, self.predicate, self.f, None)


class _CatchAll[EC, EO, A2, A3, EE, RR]:
    """Handles ``EC`` with one handler and ``EO``, which must be every other
    error of the stream, with another."""

    __slots__ = ("f", "or_else", "predicate")

    def __init__(self, predicate: Callable[[Any], bool], f: Handler, or_else: Handler) -> None:
        self.predicate = predicate
        self.f = f
        self.or_else = or_else

    def __call__[A, R](self, stream: StreamBase[A, EC | EO, R]) -> Stream[A | A2 | A3, EE, R | RR]:
        return catch_if(stream, self.predicate, self.f, self.or_else)


type _S[A, E, R] = StreamBase[A, E, R]


class _CatchEvery[E, A2, E2, R2]:
    """Handles every typed error ``E`` of a stream."""

    __slots__ = ("f",)

    def __init__(self, f: Callable[[E], _S[A2, E2, R2]]) -> None:
        self.f = f

    def __call__[A, R = Never](self, stream: StreamBase[A, E, R]) -> Stream[A | A2, E2, R | R2]:
        f = self.f
        return Stream(stream._channel.catch_all(lambda error: f(error)._channel))


def catch_all[E, A2, E2 = Never, R2 = Never](
    f: Callable[[E], _S[A2, E2, R2]],
) -> _CatchEvery[E, A2, E2, R2]:
    """``stream.catch_all(f)`` for ``.pipe`` (Effect's ``Stream.catch``):
    go on with ``f(error)`` after any typed failure. Annotate ``f``'s
    parameter (a ``def``): pyright checks it covers every error."""
    return _CatchEvery(f)


@overload
def catch_if_refinement[EB, A2, E2 = Never, R2 = Never](
    refinement: Callable[[Any], TypeIs[EB]], f: Callable[[EB], _S[A2, E2, R2]]
) -> _CatchSome[EB, A2, E2, R2]: ...
@overload
def catch_if_refinement[EB, EO, A2, A3, EE = Never, RR = Never](
    refinement: Callable[[Any], TypeIs[EB]],
    f: Callable[[EB], _S[A2, EE, RR]],
    *,
    or_else: Callable[[EO], _S[A3, EE, RR]],
) -> _CatchAll[EB, EO, A2, A3, EE, RR]: ...
def catch_if_refinement(
    refinement: Callable[[Any], bool], f: Handler, *, or_else: Handler | None = None
) -> Any:
    """Recover from the typed errors ``refinement`` accepts and remove them
    from the stream's errors. For a plain ``bool`` predicate, use the
    ``catch_if`` method."""
    if or_else is None:
        return _CatchSome[Any, Any, Any, Any](refinement, f)
    return _CatchAll[Any, Any, Any, Any, Any, Any](refinement, f, or_else)


@overload
def catch_tag[T1, A2, E2 = Never, R2 = Never](
    tag: type[T1], f: Callable[[T1], _S[A2, E2, R2]]
) -> _CatchSome[T1, A2, E2, R2]: ...
@overload
def catch_tag[T1, T2, A2, E2 = Never, R2 = Never](
    tag: tuple[type[T1], type[T2]], f: Callable[[T1 | T2], _S[A2, E2, R2]]
) -> _CatchSome[T1 | T2, A2, E2, R2]: ...
@overload
def catch_tag[T1, T2, T3, A2, E2 = Never, R2 = Never](
    tag: tuple[type[T1], type[T2], type[T3]], f: Callable[[T1 | T2 | T3], _S[A2, E2, R2]]
) -> _CatchSome[T1 | T2 | T3, A2, E2, R2]: ...
@overload
def catch_tag[T1, EO, A2, A3, EE = Never, RR = Never](
    tag: type[T1],
    f: Callable[[T1], _S[A2, EE, RR]],
    *,
    or_else: Callable[[EO], _S[A3, EE, RR]],
) -> _CatchAll[T1, EO, A2, A3, EE, RR]: ...
def catch_tag(
    tag: type[Any] | tuple[type[Any], ...], f: Handler, *, or_else: Handler | None = None
) -> Any:
    """Recover from the errors that are instances of ``tag`` (a class or a
    tuple of up to three) and remove them from the stream's errors."""
    predicate: Callable[[Any], bool] = lambda e: isinstance(e, tag)  # noqa: E731
    if or_else is None:
        return _CatchSome[Any, Any, Any, Any](predicate, f)
    return _CatchAll[Any, Any, Any, Any, Any, Any](predicate, f, or_else)
