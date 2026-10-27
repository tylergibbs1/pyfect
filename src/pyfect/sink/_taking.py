"""Sinks that take items: ``take``, the ``take_while`` family and the
``take_until`` family.

``take_while`` reads the first item that fails its predicate and drops
it, as Effect's does; ``take_until`` keeps the item that matches. What
follows in the same chunk is left over.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Never, TypeIs, overload

from pyfect._core import Effect, _Gen, _Succeed
from pyfect.result import Err, Ok, Result
from pyfect.scope import CloseableScope
from pyfect.sink._sink import Sink, Upstream
from pyfect.sink._steps import ENDED, VOID, read_until_done

type AnyEffect = Effect[Any, Any, Any]
type Chunk = tuple[Any, ...]


_REJECTED: Result[Never, None] = Err(None)
"""What a predicate that fails gives the shared ``take_while`` loop."""


def _rest(chunk: Chunk, start: int) -> Chunk | None:
    return chunk[start:] or None


def take[In](n: int) -> Sink[list[In], In, In]:
    """A sink taking the first ``n`` items (none for ``n`` 0 or less); the
    rest of the chunk that reaches ``n`` is left over."""
    count = max(n, 0)

    def transform(upstream: Upstream[In], _scope: CloseableScope) -> AnyEffect:
        taken: list[In] = []
        if count == 0:
            return _Succeed((taken, None))
        leftover: Chunk | None = None

        def step(chunk: tuple[In, ...]) -> AnyEffect:
            nonlocal leftover
            room = count - len(taken)
            if len(chunk) < room:
                taken.extend(chunk)
                return VOID
            taken.extend(chunk[:room])
            leftover = _rest(chunk, room)
            return ENDED

        return read_until_done(upstream.flat_map(step), lambda: (taken, leftover))

    return Sink(transform)


def _taking_while[In](
    keep: Callable[[In], Result[Any, object]],
) -> Sink[list[Any], In, In]:
    def transform(upstream: Upstream[In], _scope: CloseableScope) -> AnyEffect:
        taken: list[Any] = []
        leftover: Chunk | None = None

        def step(chunk: tuple[In, ...]) -> AnyEffect:
            nonlocal leftover
            for i, item in enumerate(chunk):
                kept = keep(item)
                if not isinstance(kept, Ok):
                    leftover = _rest(chunk, i + 1)
                    return ENDED
                taken.append(kept.value)
            return VOID

        return read_until_done(upstream.flat_map(step), lambda: (taken, leftover))

    return Sink(transform)


@overload
def take_while[In, B](predicate: Callable[[In], TypeIs[B]]) -> Sink[list[B], In, In]: ...
@overload
def take_while[In](predicate: Callable[[In], bool]) -> Sink[list[In], In, In]: ...
def take_while(predicate: Callable[[Any], bool]) -> Sink[list[Any], Any, Any]:
    """A sink taking items while ``predicate`` holds."""
    return _taking_while(lambda item: Ok(item) if predicate(item) else _REJECTED)


def take_while_filter[In, B](f: Callable[[In], Result[B, object]]) -> Sink[list[B], In, In]:
    """A sink taking the ``Ok`` values of ``f(item)`` until it gives an
    ``Err``."""
    return _taking_while(f)


def _taking_while_effect[In](
    keep: Callable[[In], Effect[Result[Any, object], Any, Any]],
) -> Sink[list[Any], In, In, Any, Any]:
    def transform(upstream: Upstream[In], _scope: CloseableScope) -> AnyEffect:
        taken: list[Any] = []
        leftover: Chunk | None = None

        def step(chunk: tuple[In, ...]) -> AnyEffect:
            def body() -> Generator[AnyEffect, Any, AnyEffect]:
                nonlocal leftover
                for i, item in enumerate(chunk):
                    kept: Result[Any, object] = yield keep(item)
                    if not isinstance(kept, Ok):
                        leftover = _rest(chunk, i + 1)
                        return ENDED
                    taken.append(kept.value)
                return VOID

            return _Gen(body).flatten()

        return read_until_done(upstream.flat_map(step), lambda: (taken, leftover))

    return Sink(transform)


def take_while_effect[In, E = Never, R = Never](
    predicate: Callable[[In], Effect[bool, E, R]],
) -> Sink[list[In], In, In, E, R]:
    """``take_while`` with an effectful ``predicate``."""
    return _taking_while_effect(
        lambda item: predicate(item).map(lambda ok: Ok(item) if ok else _REJECTED)
    )


def take_while_filter_effect[In, B, E = Never, R = Never](
    f: Callable[[In], Effect[Result[B, object], E, R]],
) -> Sink[list[B], In, In, E, R]:
    """``take_while_filter`` with an effectful ``f``."""
    return _taking_while_effect(f)


def take_until[In](predicate: Callable[[In], bool]) -> Sink[list[In], In, In]:
    """A sink taking items up to and including the first one
    ``predicate`` holds for."""

    def transform(upstream: Upstream[In], _scope: CloseableScope) -> AnyEffect:
        taken: list[In] = []
        leftover: Chunk | None = None

        def step(chunk: tuple[In, ...]) -> AnyEffect:
            nonlocal leftover
            for i, item in enumerate(chunk):
                taken.append(item)
                if predicate(item):
                    leftover = _rest(chunk, i + 1)
                    return ENDED
            return VOID

        return read_until_done(upstream.flat_map(step), lambda: (taken, leftover))

    return Sink(transform)


def take_until_effect[In, E = Never, R = Never](
    predicate: Callable[[In], Effect[bool, E, R]],
) -> Sink[list[In], In, In, E, R]:
    """``take_until`` with an effectful ``predicate``."""

    def transform(upstream: Upstream[In], _scope: CloseableScope) -> AnyEffect:
        taken: list[In] = []
        leftover: Chunk | None = None

        def step(chunk: tuple[In, ...]) -> AnyEffect:
            def body() -> Generator[AnyEffect, Any, AnyEffect]:
                nonlocal leftover
                for i, item in enumerate(chunk):
                    matched = yield predicate(item)
                    taken.append(item)
                    if matched:
                        leftover = _rest(chunk, i + 1)
                        return ENDED
                return VOID

            return _Gen(body).flatten()

        return read_until_done(upstream.flat_map(step), lambda: (taken, leftover))

    return Sink(transform)
