"""Running a stream: its channel's runs, item by item over each chunk."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from typing import Any

from pyfect._core import Effect, _Gen
from pyfect.option import Option, Some
from pyfect.stream._base import AnyStream

type AnyEffect = Effect[Any, Any, Any]
type Chunk = tuple[Any, ...]


def _extend(acc: list[Any], chunk: Chunk) -> list[Any]:
    acc.extend(chunk)
    return acc


def run_collect(self: AnyStream) -> AnyEffect:
    return self._channel.run_fold(list, _extend)


def run_count(self: AnyStream) -> AnyEffect:
    return self._channel.run_fold(int, lambda n, chunk: n + len(chunk))


def run_sum(self: AnyStream) -> AnyEffect:
    return self._channel.run_fold(int, lambda total, chunk: total + sum(chunk))


def run_string(self: AnyStream) -> AnyEffect:
    return self._channel.run_fold(list, _extend).map("".join)


def run_bytes(self: AnyStream) -> AnyEffect:
    return self._channel.run_fold(list, _extend).map(b"".join)


def run_fold(
    self: AnyStream, initial: Callable[[], Any], f: Callable[[Any, Any], Any]
) -> AnyEffect:
    def fold_chunk(acc: Any, chunk: Chunk) -> Any:
        for item in chunk:
            acc = f(acc, item)
        return acc

    return self._channel.run_fold(initial, fold_chunk)


def run_fold_effect(
    self: AnyStream, initial: Callable[[], Any], f: Callable[[Any, Any], AnyEffect]
) -> AnyEffect:
    def fold_chunk(acc: Any, chunk: Chunk) -> AnyEffect:
        if len(chunk) == 1:
            return f(acc, chunk[0])

        def body() -> Generator[AnyEffect, Any, Any]:
            state = acc
            for item in chunk:
                state = yield f(state, item)
            return state

        return _Gen(body)

    return self._channel.run_fold_effect(initial, fold_chunk)


def run_for_each(self: AnyStream, f: Callable[[Any], AnyEffect]) -> AnyEffect:
    def each(chunk: Chunk) -> AnyEffect:
        if len(chunk) == 1:
            return f(chunk[0])

        def body() -> Generator[AnyEffect, Any]:
            for item in chunk:
                yield f(item)

        return _Gen(body)

    return self._channel.run_for_each(each)


def run_for_each_while(self: AnyStream, f: Callable[[Any], Effect[bool, Any, Any]]) -> AnyEffect:
    def each(chunk: Chunk) -> Effect[bool, Any, Any]:
        if len(chunk) == 1:
            return f(chunk[0])

        def body() -> Generator[AnyEffect, Any, bool]:
            for item in chunk:
                if not (yield f(item)):
                    return False
            return True

        return _Gen(body)

    return self._channel.run_for_each_while(each)


def _first(chunk: Option[Chunk]) -> Option[Any]:
    return None if chunk is None else Some(chunk.value[0])


def _last(chunk: Option[Chunk]) -> Option[Any]:
    return None if chunk is None else Some(chunk.value[-1])


def run_head(self: AnyStream) -> AnyEffect:
    return self._channel.run_head().map(_first)


def run_last(self: AnyStream) -> AnyEffect:
    return self._channel.run_last().map(_last)
