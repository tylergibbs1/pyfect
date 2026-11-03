"""``Walker``: a repeatable iteration over ``(index, data)`` pairs."""

from __future__ import annotations

from collections.abc import Callable, Iterable, Iterator
from typing import Protocol

from pyfect.graph._records import Edge


class Visit[T, N](Protocol):
    """Calls ``f`` on each ``(index, data)`` and yields the results."""

    def __call__[U](self, f: Callable[[T, N], U], /) -> Iterable[U]: ...


class Walker[T, N]:
    """What ``dfs``, ``bfs``, ``topo``, ``nodes``, ``edges`` and the other
    traversals return. Every ``iter(...)`` starts over: a graph walker
    looks at the graph as it is then (and checks its start nodes), and an
    iterator already running keeps the graph it started on."""

    __slots__ = ("_visit",)

    def __init__(self, visit: Visit[T, N]) -> None:
        self._visit = visit

    def visit[U](self, f: Callable[[T, N], U]) -> Iterable[U]:
        return self._visit(f)

    def __iter__(self) -> Iterator[tuple[T, N]]:
        return iter(self._visit(_pair))

    def indices(self) -> Iterable[T]:
        return self._visit(_index)

    def values(self) -> Iterable[N]:
        return self._visit(_data)

    def entries(self) -> Iterable[tuple[T, N]]:
        return self._visit(_pair)


def _pair[T, N](index: T, data: N) -> tuple[T, N]:
    return (index, data)


def _index[T](index: T, _data: object) -> T:
    return index


def _data[N](_index: object, data: N) -> N:
    return data


type NodeWalker[N] = Walker[int, N]
type EdgeWalker[E] = Walker[int, Edge[E]]


class Fresh[A]:
    """An iterable whose every ``iter`` calls ``start`` (which may raise
    there, before the first item)."""

    __slots__ = ("_start",)

    def __init__(self, start: Callable[[], Iterator[A]]) -> None:
        self._start = start

    def __iter__(self) -> Iterator[A]:
        return self._start()
