"""The work behind ``Stream``'s mapping, flat-mapping and flattening
methods, and ``map_chunks``, the chunk-by-chunk loop most stateful
operators share."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect._concurrency import Concurrency
from pyfect._core import Effect, _FlatMap, _Succeed
from pyfect.channel import transform_pull
from pyfect.result import Err, Ok
from pyfect.stream._base import AnyStream
from pyfect.stream._stream import Stream

type AnyEffect = Effect[Any, Any, Any]
type Chunk = tuple[Any, ...]
type AnyStream_ = Stream[Any, Any, Any]


def one[A](value: A) -> tuple[A]:
    return (value,)


def map_chunks(self: AnyStream, make: Callable[[], Callable[[Chunk], Chunk]]) -> AnyStream_:
    """A stream writing ``f(chunk)`` for each chunk, where ``f = make()``
    is built once per run (so it may keep state); an empty result pulls
    the next chunk instead of writing."""

    def build(pull: AnyEffect, _scope: object) -> AnyEffect:
        return _Succeed(_FlatMap(pull, _MapChunks(pull, make()).loop))

    return Stream(transform_pull(self._channel, build))


class _MapChunks:
    """One run of ``map_chunks``: a loop on a state object, not a closure that
    calls itself (that cycle would keep the pull alive after the run)."""

    __slots__ = ("f", "pull")

    def __init__(self, pull: AnyEffect, f: Callable[[Chunk], Chunk]) -> None:
        self.pull = pull
        self.f = f

    def loop(self, chunk: Chunk) -> AnyEffect:
        out = self.f(chunk)
        return _Succeed(out) if out else _FlatMap(self.pull, self.loop)


def map_(self: AnyStream, f: Callable[[Any], Any]) -> AnyStream_:
    return Stream(self._channel.map(lambda chunk: tuple(map(f, chunk))))


def map_array(self: AnyStream, f: Callable[[Chunk], Chunk]) -> AnyStream_:
    return map_chunks(self, lambda: f)


def map_effect(
    self: AnyStream,
    f: Callable[[Any], AnyEffect],
    concurrency: Concurrency,
    unordered: bool,
) -> AnyStream_:
    mapped = self._channel.flatten_array().map_effect(
        f, concurrency=concurrency, unordered=unordered
    )
    return Stream(mapped.map(one))


def map_array_effect(self: AnyStream, f: Callable[[Chunk], AnyEffect]) -> AnyStream_:
    def build(pull: AnyEffect, _scope: object) -> AnyEffect:
        return _Succeed(_FlatMap(pull, _MapArrayEffect(pull, f).loop))

    return Stream(transform_pull(self._channel, build))


class _MapArrayEffect:
    __slots__ = ("f", "pull")

    def __init__(self, pull: AnyEffect, f: Callable[[Chunk], AnyEffect]) -> None:
        self.pull = pull
        self.f = f

    def loop(self, chunk: Chunk) -> AnyEffect:
        return _FlatMap(self.f(chunk), self.mapped)

    def mapped(self, out: Chunk) -> AnyEffect:
        return _Succeed(out) if out else _FlatMap(self.pull, self.loop)


def result(self: AnyStream) -> AnyStream_:
    from pyfect.stream import _constructors

    oks = map_(self, Ok)
    return oks.catch_all(lambda error: _constructors.succeed(Err(error)))


def flat_map(
    self: AnyStream,
    f: Callable[[Any], AnyStream],
    concurrency: Concurrency,
    buffer_size: int,
    *,
    switch: bool,
) -> AnyStream_:
    items = self._channel.flatten_array()
    if switch:
        return Stream(
            items.switch_map(
                lambda a: f(a)._channel, concurrency=concurrency or 1, buffer_size=buffer_size
            )
        )
    return Stream(
        items.flat_map(lambda a: f(a)._channel, concurrency=concurrency, buffer_size=buffer_size)
    )


def flatten_array(self: AnyStream) -> AnyStream_:
    return Stream(self._channel.flatten_array().filter(bool))


def flatten_take(self: AnyStream) -> AnyStream_:
    taken: Any = self._channel.flatten_array().flatten_take()
    return Stream(taken)


def intersperse(self: AnyStream, element: Any) -> AnyStream_:
    def make() -> Callable[[Chunk], Chunk]:
        first = True

        def f(chunk: Chunk) -> Chunk:
            nonlocal first
            out: list[Any] = [] if first else [element]
            first = False
            for item in chunk:
                out.append(item)
                out.append(element)
            out.pop()
            return tuple(out)

        return f

    return map_chunks(self, make)
