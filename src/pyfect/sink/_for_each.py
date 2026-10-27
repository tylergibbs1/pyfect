"""Sinks that run an effect on their input: ``for_each``,
``for_each_array``, ``for_each_while`` and ``for_each_while_array``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Never

from pyfect._core import Effect, _Gen
from pyfect.scope import CloseableScope
from pyfect.sink._sink import End, Sink, Upstream
from pyfect.sink._steps import ENDED, VOID, read_until_done

type AnyEffect = Effect[Any, Any, Any]
type Chunk = tuple[Any, ...]


def _no_value() -> End[None]:
    return (None, None)


def _until_done(step: AnyEffect) -> Effect[End[None], Any, Any]:
    return read_until_done(step, _no_value)


def for_each_array[In, E = Never, R = Never](
    f: Callable[[tuple[In, ...]], Effect[object, E, R]],
) -> Sink[None, In, Never, E, R]:
    """A sink that runs ``f`` on each chunk of its input, in order."""

    def transform(upstream: Upstream[In], _scope: CloseableScope) -> AnyEffect:
        return _until_done(upstream.flat_map(f))

    return Sink(transform)


def for_each[In, E = Never, R = Never](
    f: Callable[[In], Effect[object, E, R]],
) -> Sink[None, In, Never, E, R]:
    """A sink that runs ``f`` on each item of its input, in order."""

    def each(chunk: Chunk) -> AnyEffect:
        if len(chunk) == 1:
            return f(chunk[0])

        def body() -> Generator[AnyEffect, Any]:
            for item in chunk:
                yield f(item)

        return _Gen(body)

    return for_each_array(each)


def _go_on(more: bool) -> AnyEffect:
    return VOID if more else ENDED


def for_each_while_array[In, E = Never, R = Never](
    f: Callable[[tuple[In, ...]], Effect[bool, E, R]],
) -> Sink[None, In, Never, E, R]:
    """A sink that runs ``f`` on each chunk until it succeeds with
    ``False``; the sink stops reading there."""

    def transform(upstream: Upstream[In], _scope: CloseableScope) -> AnyEffect:
        return _until_done(upstream.flat_map(f).flat_map(_go_on))

    return Sink(transform)


def for_each_while[In, E = Never, R = Never](
    f: Callable[[In], Effect[bool, E, R]],
) -> Sink[None, In, Never, E, R]:
    """A sink that runs ``f`` on each item until it succeeds with
    ``False``; the sink stops reading there."""

    def each(chunk: Chunk) -> Effect[bool, Any, Any]:
        def body() -> Generator[AnyEffect, Any, bool]:
            for item in chunk:
                if not (yield f(item)):
                    return False
            return True

        return _Gen(body)

    return for_each_while_array(each)
