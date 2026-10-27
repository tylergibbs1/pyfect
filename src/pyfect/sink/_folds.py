"""Sinks that fold their input into a state: ``fold``, the ``reduce``
family, and the folds with a fixed answer (``sum``, ``count``,
``collect``, ``head``, ``last``, ``find``, ``every``, ``some``).

The ``*_while`` folds stop reading as soon as the state fails the
predicate; the item-by-item ones leave the rest of that chunk over.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any, Never, TypeIs, overload

from pyfect._core import Effect, _Gen, _Succeed, _Sync
from pyfect.option import Option, Some
from pyfect.pull import catch_done
from pyfect.scope import CloseableScope
from pyfect.sink._constructors import sync
from pyfect.sink._sink import End, Sink, Upstream
from pyfect.sink._steps import ENDED, VOID, read_until_done

type AnyEffect = Effect[Any, Any, Any]
type Chunk = tuple[Any, ...]


def _rest(chunk: Chunk, start: int) -> Chunk | None:
    return chunk[start:] or None


# --- folds with an effect per item ---------------------------------------------


def fold[S, In, E = Never, R = Never](
    initial: Callable[[], S],
    cont: Callable[[S], bool],
    f: Callable[[S, In], Effect[S, E, R]],
) -> Sink[S, In, In, E, R]:
    """Fold each item into ``initial()`` with ``f`` while ``cont(state)``
    holds; once it fails, end with the state and the rest of the chunk as
    leftovers. ``cont`` is first asked after the first item."""

    def transform(upstream: Upstream[In], _scope: CloseableScope) -> AnyEffect:
        state = initial()

        def body() -> Generator[AnyEffect, Any, End[S, In]]:
            nonlocal state
            while True:
                chunk = yield upstream
                for i, item in enumerate(chunk):
                    state = yield f(state, item)
                    if not cont(state):
                        return (state, _rest(chunk, i + 1))

        return catch_done(_Gen(body), lambda _: _Sync(lambda: (state, None)))

    return Sink(transform)


def fold_array[S, In, E = Never, R = Never](
    initial: Callable[[], S],
    cont: Callable[[S], bool],
    f: Callable[[S, tuple[In, ...]], Effect[S, E, R]],
) -> Sink[S, In, Never, E, R]:
    """``fold`` a chunk at a time; nothing is left over."""

    def transform(upstream: Upstream[In], _scope: CloseableScope) -> AnyEffect:
        state = initial()

        def step(chunk: tuple[In, ...]) -> AnyEffect:
            def keep(next_state: S) -> AnyEffect:
                nonlocal state
                state = next_state
                return VOID if cont(state) else ENDED

            return f(state, chunk).flat_map(keep)

        return read_until_done(upstream.flat_map(step), lambda: (state, None))

    return Sink(transform)


def fold_until[S, In, E = Never, R = Never](
    initial: Callable[[], S], max: int, f: Callable[[S, In], Effect[S, E, R]]
) -> Sink[S, In, In, E, R]:
    """Fold at most ``max`` items into ``initial()`` with ``f``. With
    ``max`` 0 or less the sink reads nothing."""
    if max <= 0:
        return sync(initial)

    def start() -> tuple[S, int]:
        return (initial(), 0)

    def below_max(pair: tuple[S, int]) -> bool:
        return pair[1] < max

    def step(pair: tuple[S, int], item: In) -> Effect[tuple[S, int], E, R]:
        return f(pair[0], item).map(lambda state: (state, pair[1] + 1))

    return fold(start, below_max, step).map(lambda pair: pair[0])


def _fold_bool[In](start: bool, predicate: Callable[[In], bool]) -> Sink[bool, In, In]:
    """Fold to ``predicate(item)`` until it differs from ``start``."""

    def step(_: bool, item: In) -> Effect[bool]:
        return _Succeed(predicate(item))

    return fold(lambda: start, lambda found: found == start, step)


def every[In](predicate: Callable[[In], bool]) -> Sink[bool, In, In]:
    """``True`` if ``predicate`` holds for every item; stops at the first
    item it fails for."""
    return _fold_bool(True, predicate)


def some[In](predicate: Callable[[In], bool]) -> Sink[bool, In, In]:
    """``True`` if ``predicate`` holds for some item; stops at the first
    item it holds for."""
    return _fold_bool(False, predicate)


def reduce_while_effect[S, In, E = Never, R = Never](
    initial: Callable[[], S],
    predicate: Callable[[S], bool],
    f: Callable[[S, In], Effect[S, E, R]],
) -> Sink[S, In, In, E, R]:
    """Reduce each item into ``initial()`` with ``f`` while
    ``predicate(state)`` holds, asking it of ``initial()`` first; the rest
    of the chunk is left over."""

    def transform(upstream: Upstream[In], _scope: CloseableScope) -> AnyEffect:
        state = initial()
        leftover: Chunk | None = None
        if not predicate(state):
            return _Succeed((state, None))

        def step(chunk: Chunk) -> AnyEffect:
            def body() -> Generator[AnyEffect, Any, AnyEffect]:
                nonlocal state, leftover
                for i, item in enumerate(chunk):
                    state = yield f(state, item)
                    if not predicate(state):
                        leftover = _rest(chunk, i + 1)
                        return ENDED
                return VOID

            return _Gen(body).flatten()

        return read_until_done(upstream.flat_map(step), lambda: (state, leftover))

    return Sink(transform)


def reduce_effect[S, In, E = Never, R = Never](
    initial: Callable[[], S], f: Callable[[S, In], Effect[S, E, R]]
) -> Sink[S, In, Never, E, R]:
    """Reduce every item into ``initial()`` with ``f``."""
    reduced: Sink[S, In, Any, E, R] = reduce_while_effect(initial, lambda _: True, f)
    return reduced


def reduce_while_array_effect[S, In, E = Never, R = Never](
    initial: Callable[[], S],
    predicate: Callable[[S], bool],
    f: Callable[[S, tuple[In, ...]], Effect[S, E, R]],
) -> Sink[S, In, Never, E, R]:
    """``reduce_while_effect`` a chunk at a time; nothing is left over."""

    def transform(upstream: Upstream[In], scope: CloseableScope) -> AnyEffect:
        state = initial()
        if not predicate(state):
            return _Succeed((state, None))
        return fold_array(lambda: state, predicate, f)._transform(upstream, scope)

    return Sink(transform)


# --- pure folds -------------------------------------------------------------------


def reduce_while[S, In](
    initial: Callable[[], S], predicate: Callable[[S], bool], f: Callable[[S, In], S]
) -> Sink[S, In, In]:
    """Reduce each item into ``initial()`` with ``f`` while
    ``predicate(state)`` holds, asking it of ``initial()`` first; the rest
    of the chunk is left over."""

    def transform(upstream: Upstream[In], _scope: CloseableScope) -> AnyEffect:
        state = initial()
        leftover: Chunk | None = None
        if not predicate(state):
            return _Succeed((state, None))

        def step(chunk: Chunk) -> AnyEffect:
            nonlocal state, leftover
            for i, item in enumerate(chunk):
                state = f(state, item)
                if not predicate(state):
                    leftover = _rest(chunk, i + 1)
                    return ENDED
            return VOID

        return read_until_done(upstream.flat_map(step), lambda: (state, leftover))

    return Sink(transform)


def reduce_while_array[S, In](
    initial: Callable[[], S], predicate: Callable[[S], bool], f: Callable[[S, tuple[In, ...]], S]
) -> Sink[S, In]:
    """``reduce_while`` a chunk at a time; nothing is left over."""

    def transform(upstream: Upstream[In], _scope: CloseableScope) -> AnyEffect:
        state = initial()
        if not predicate(state):
            return _Succeed((state, None))

        def step(chunk: tuple[In, ...]) -> AnyEffect:
            nonlocal state
            state = f(state, chunk)
            return VOID if predicate(state) else ENDED

        return read_until_done(upstream.flat_map(step), lambda: (state, None))

    return Sink(transform)


def reduce_array[S, In](
    initial: Callable[[], S], f: Callable[[S, tuple[In, ...]], S]
) -> Sink[S, In]:
    """Reduce every chunk into ``initial()`` with ``f``."""

    def transform(upstream: Upstream[In], _scope: CloseableScope) -> AnyEffect:
        state = initial()

        def step(chunk: tuple[In, ...]) -> None:
            nonlocal state
            state = f(state, chunk)

        return read_until_done(upstream.map(step), lambda: (state, None))

    return Sink(transform)


def reduce[S, In](initial: Callable[[], S], f: Callable[[S, In], S]) -> Sink[S, In]:
    """Reduce every item into ``initial()`` with ``f``."""

    def reduce_chunk(state: S, chunk: tuple[In, ...]) -> S:
        for item in chunk:
            state = f(state, item)
        return state

    return reduce_array(initial, reduce_chunk)


def _add_up(total: Any, chunk: Chunk) -> Any:
    return total + sum(chunk)


def sum_[N: (int, float)]() -> Sink[N, N]:
    """A sink adding up its input (``0`` for none). Effect's ``Sink.sum``,
    a function here so the result has the input's type."""
    summed: Sink[Any, Any] = reduce_array(int, _add_up)
    return summed


def _count(n: int, chunk: Chunk) -> int:
    return n + len(chunk)


count: Sink[int] = reduce_array(int, _count)
"""A sink counting its input."""


def _extend(items: list[Any], chunk: Chunk) -> list[Any]:
    items.extend(chunk)
    return items


def collect[In]() -> Sink[list[In], In]:
    """A sink collecting its input in a list."""
    return reduce_array(list, _extend)


def _nothing() -> Option[Any]:
    return None


def _not_found(found: Option[Any]) -> bool:
    return found is None


def _first(_: Option[Any], item: Any) -> Option[Any]:
    return Some(item)


def _last(_: Option[Any], chunk: Chunk) -> Option[Any]:
    return Some(chunk[-1])


def head[In]() -> Sink[Option[In], In, In]:
    """``Some`` of the first item (the rest of its chunk is left over), or
    ``None`` if there is none."""
    return reduce_while(_nothing, _not_found, _first)


def last[In]() -> Sink[Option[In], In]:
    """``Some`` of the last item, or ``None`` if there is none."""
    return reduce_array(_nothing, _last)


@overload
def find[In, B](refinement: Callable[[In], TypeIs[B]]) -> Sink[Option[B], In, In]: ...
@overload
def find[In](refinement: Callable[[In], bool]) -> Sink[Option[In], In, In]: ...
def find(refinement: Callable[[Any], bool]) -> Sink[Option[Any], Any, Any]:
    """``Some`` of the first item ``predicate`` holds for (the rest of its
    chunk is left over), or ``None``."""

    def check(found: Option[Any], item: Any) -> Option[Any]:
        return Some(item) if refinement(item) else found

    return reduce_while(_nothing, _not_found, check)


def find_effect[In, E = Never, R = Never](
    predicate: Callable[[In], Effect[bool, E, R]],
) -> Sink[Option[In], In, In, E, R]:
    """``find`` with an effectful ``predicate``."""

    def check(found: Option[In], item: In) -> Effect[Option[In], E, R]:
        return predicate(item).map(lambda ok: Some(item) if ok else found)

    return reduce_while_effect(_nothing, _not_found, check)
