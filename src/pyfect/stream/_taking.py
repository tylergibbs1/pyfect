"""The work behind ``Stream``'s filtering, taking, dropping and ``changes``
methods. Each keeps its state in the pull a run builds, so every run
starts afresh."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections import deque
from collections.abc import Callable, Generator, Iterable
from typing import Any

from pyfect._core import Effect, _FlatMap, _Gen, _Succeed, _Suspend
from pyfect.channel import transform_pull
from pyfect.channel._base import end_with
from pyfect.result import Ok, Result
from pyfect.stream._base import AnyStream
from pyfect.stream._mapping import map_array_effect, map_chunks
from pyfect.stream._stream import Stream

type AnyEffect = Effect[Any, Any, Any]
type Chunk = tuple[Any, ...]
type AnyStream_ = Stream[Any, Any, Any]

_ENDED: AnyEffect = end_with(None)


def count_of(n: int) -> int:
    """Effect's ``Count.normalize`` for an ``int``: below zero is zero."""
    return max(0, n)


def _pulling(self: AnyStream, build: Callable[[AnyEffect], AnyEffect]) -> AnyStream_:
    return Stream(transform_pull(self._channel, lambda pull, _: _Succeed(build(pull))))


# --- filtering ----------------------------------------------------------------


def _passed(results: Iterable[Result[Any, object]]) -> Chunk:
    return tuple(r.value for r in results if isinstance(r, Ok))


def filter_map(self: AnyStream, f: Callable[[Any], Result[Any, object]]) -> AnyStream_:
    return map_chunks(self, lambda: lambda chunk: _passed(map(f, chunk)))


def filter_map_effect(self: AnyStream, f: Callable[[Any], AnyEffect]) -> AnyStream_:
    def each(chunk: Chunk) -> AnyEffect:
        def body() -> Generator[AnyEffect, Any, Chunk]:
            results: list[Any] = []
            for item in chunk:
                results.append((yield f(item)))  # noqa: PERF401 (no yield in comprehensions)
            return _passed(results)

        return _Gen(body)

    return map_array_effect(self, each)


# --- taking -------------------------------------------------------------------


def take(self: AnyStream, n: int) -> AnyStream_:
    from pyfect.stream._constructors import empty

    count = count_of(n)
    if count == 0:
        return empty

    def build(pull: AnyEffect) -> AnyEffect:
        taken = 0

        def cut(chunk: Chunk) -> AnyEffect:
            nonlocal taken
            kept = chunk[: count - taken]
            taken += len(kept)
            return _Succeed(kept)

        return _Suspend(lambda: _ENDED if taken >= count else _FlatMap(pull, cut))

    return _pulling(self, build)


def take_right(self: AnyStream, n: int) -> AnyStream_:
    from pyfect.stream._constructors import empty

    count = count_of(n)
    if count == 0:
        return empty

    def keep(last: deque[Any], chunk: Chunk) -> tuple[deque[Any], tuple[()]]:
        last.extend(chunk)
        return last, ()

    def on_halt(last: deque[Any]) -> list[Chunk]:
        return [tuple(last)] if last else []

    return Stream(self._channel.map_accum(lambda: deque[Any](maxlen=count), keep, on_halt=on_halt))


def take_until(self: AnyStream, predicate: Callable[[Any], bool], exclude_last: bool) -> AnyStream_:
    def build(pull: AnyEffect) -> AnyEffect:
        done = False

        def cut(chunk: Chunk) -> AnyEffect:
            nonlocal done
            for index, item in enumerate(chunk):
                if predicate(item):
                    done = True
                    kept = chunk[: index if exclude_last else index + 1]
                    return _Succeed(kept) if kept else _ENDED
            return _Succeed(chunk)

        return _Suspend(lambda: _ENDED if done else _FlatMap(pull, cut))

    return _pulling(self, build)


def take_until_effect(
    self: AnyStream, predicate: Callable[[Any], AnyEffect], exclude_last: bool
) -> AnyStream_:
    def build(pull: AnyEffect) -> AnyEffect:
        done = False

        def body() -> Generator[AnyEffect, Any, Chunk]:
            nonlocal done
            if done:
                return (yield _ENDED)
            chunk: Chunk = yield pull
            for index, item in enumerate(chunk):
                if (yield predicate(item)):
                    done = True
                    kept = chunk[: index if exclude_last else index + 1]
                    return kept if kept else (yield _ENDED)
            return chunk

        return _Gen(body)

    return _pulling(self, build)


def take_while(self: AnyStream, predicate: Callable[[Any], bool]) -> AnyStream_:
    def build(pull: AnyEffect) -> AnyEffect:
        done = False

        def cut(chunk: Chunk) -> AnyEffect:
            nonlocal done
            for index, item in enumerate(chunk):
                if not predicate(item):
                    done = True
                    kept = chunk[:index]
                    return _Succeed(kept) if kept else _ENDED
            return _Succeed(chunk)

        return _Suspend(lambda: _ENDED if done else _FlatMap(pull, cut))

    return _pulling(self, build)


def take_while_filter(self: AnyStream, f: Callable[[Any], Result[Any, object]]) -> AnyStream_:
    def build(pull: AnyEffect) -> AnyEffect:
        done = False

        def cut(chunk: Chunk) -> AnyEffect:
            nonlocal done
            out: list[Any] = []
            for item in chunk:
                result = f(item)
                if not isinstance(result, Ok):
                    done = True
                    return _Succeed(tuple(out)) if out else _ENDED
                out.append(result.value)
            return _Succeed(tuple(out))

        return _Suspend(lambda: _ENDED if done else _FlatMap(pull, cut))

    return _pulling(self, build)


def limit_bytes(
    self: AnyStream, limit: int, on_limit_reached: Callable[[], AnyStream]
) -> AnyStream_:
    from pyfect.stream._concat import concat
    from pyfect.stream._constructors import empty, suspend

    def make() -> AnyStream_:
        size = 0
        reached = False

        def within(chunk: bytes) -> bool:
            nonlocal size, reached
            if size + len(chunk) > limit:
                reached = True
                return False
            size += len(chunk)
            return True

        return concat(
            take_while(self, within), suspend(lambda: on_limit_reached() if reached else empty)
        )

    return suspend(make)


# --- dropping -----------------------------------------------------------------


def drop(self: AnyStream, n: int) -> AnyStream_:
    count = count_of(n)
    if count == 0:
        return Stream(self._channel)

    def build(pull: AnyEffect) -> AnyEffect:
        dropped = 0

        def skip(chunk: Chunk) -> AnyEffect:
            nonlocal dropped
            if dropped >= count:
                return _Succeed(chunk)
            before = dropped
            dropped += len(chunk)
            if dropped <= count:
                return pump
            return _Succeed(chunk[count - before :])

        pump = _FlatMap(pull, skip)
        return pump

    return _pulling(self, build)


def drop_right(self: AnyStream, n: int) -> AnyStream_:
    count = count_of(n)
    if count == 0:
        return Stream(self._channel)

    def build(pull: AnyEffect) -> AnyEffect:
        held: deque[Any] = deque()

        def emit(chunk: Chunk) -> AnyEffect:
            held.extend(chunk)
            ready = len(held) - count
            if ready <= 0:
                return pump
            return _Succeed(tuple(held.popleft() for _ in range(ready)))

        pump = _FlatMap(pull, emit)
        return pump

    return _pulling(self, build)


def drop_while(self: AnyStream, predicate: Callable[[Any], bool]) -> AnyStream_:
    def build(pull: AnyEffect) -> AnyEffect:
        dropping = True

        def skip(chunk: Chunk) -> AnyEffect:
            nonlocal dropping
            for index, item in enumerate(chunk):
                if not predicate(item):
                    dropping = False
                    return _Succeed(chunk[index:])
            return filtered

        filtered = _FlatMap(pull, skip)
        return _Suspend(lambda: filtered if dropping else pull)

    return _pulling(self, build)


def drop_while_effect(self: AnyStream, predicate: Callable[[Any], AnyEffect]) -> AnyStream_:
    def build(pull: AnyEffect) -> AnyEffect:
        dropping = True

        def body() -> Generator[AnyEffect, Any, Chunk]:
            nonlocal dropping
            while True:
                chunk: Chunk = yield pull
                for index, item in enumerate(chunk):
                    if (yield predicate(item)):
                        continue
                    dropping = False
                    return chunk[index:]

        filtered = _Gen(body)
        return _Suspend(lambda: filtered if dropping else pull)

    return _pulling(self, build)


# --- repeats ------------------------------------------------------------------


def changes_with(self: AnyStream, f: Callable[[Any, Any], bool]) -> AnyStream_:
    def make() -> Callable[[Chunk], Chunk]:
        last: list[Any] = []

        def keep(chunk: Chunk) -> Chunk:
            out: list[Any] = []
            for item in chunk:
                if last and f(item, last[0]):
                    continue
                last[:] = [item]
                out.append(item)
            return tuple(out)

        return keep

    return map_chunks(self, make)


def changes_with_effect(self: AnyStream, f: Callable[[Any, Any], AnyEffect]) -> AnyStream_:
    def build(pull: AnyEffect) -> AnyEffect:
        last: list[Any] = []

        def body() -> Generator[AnyEffect, Any, Chunk]:
            while True:
                chunk: Chunk = yield pull
                out: list[Any] = []
                for item in chunk:
                    if last and (yield f(item, last[0])):
                        continue
                    last[:] = [item]
                    out.append(item)
                if out:
                    return tuple(out)

        return _Gen(body)

    return _pulling(self, build)
