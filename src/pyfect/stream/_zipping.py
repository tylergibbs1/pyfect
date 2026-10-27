"""The work behind zipping, ``zip_latest_all``, interleaving and racing
streams."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import itertools
from collections.abc import Callable, Generator
from typing import Any

from pyfect import channel
from pyfect._core import Effect, _Gen, _Succeed, _Suspend, _Sync
from pyfect._fiber_all import join_all
from pyfect.channel import Channel
from pyfect.channel._base import end_with
from pyfect.exit import Exit, Success
from pyfect.latch import Latch
from pyfect.pull import catch_done
from pyfect.scope import CloseableScope
from pyfect.stream._base import AnyStream
from pyfect.stream._stream import Stream

type AnyEffect = Effect[Any, Any, Any]
type Chunk = tuple[Any, ...]
type AnyStream_ = Stream[Any, Any, Any]
type AnyChannel = Channel[Any, Any, Any, Any, Any, Any, Any]

_ENDED: AnyEffect = end_with(None)


# --- zipping ------------------------------------------------------------------


def zip_with_array(
    left: AnyStream,
    right: AnyStream,
    f: Callable[[Chunk, Chunk], tuple[Chunk, Chunk, Chunk]],
) -> AnyStream_:
    def transform(_up: AnyEffect, scope: CloseableScope, _forked: CloseableScope) -> AnyEffect:
        def body() -> Generator[AnyEffect, Any, AnyEffect]:
            pull_left: AnyEffect = yield left._channel.to_pull_scoped(scope)
            pull_right: AnyEffect = yield right._channel.to_pull_scoped(scope)

            def both() -> Generator[AnyEffect, Any, list[Chunk]]:
                fiber_left = yield pull_left.fork_in(scope)
                fiber_right = yield pull_right.fork_in(scope)
                return (yield join_all([fiber_left, fiber_right]))

            pull_both = _Gen(both)
            held_left: Chunk = ()
            held_right: Chunk = ()

            def pull() -> Generator[AnyEffect, Any, Chunk]:
                nonlocal held_left, held_right
                if held_left:
                    pair = (held_left, held_right or (yield pull_right))
                elif held_right:
                    pair = ((yield pull_left), held_right)
                else:
                    pair = tuple((yield pull_both))
                output, held_left, held_right = f(*pair)
                return output

            return _Gen(pull)

        return _Gen(body)

    return Stream(channel.from_transform_bracket(transform))


def zip_with(left: AnyStream, right: AnyStream, f: Callable[[Any, Any], Any]) -> AnyStream_:
    from pyfect.stream._constructors import suspend

    def make() -> AnyStream_:
        # Cursors into the current chunks, so a long chunk is not copied on
        # every pull.
        left_index = 0
        right_index = 0

        def step(lefts: Chunk, rights: Chunk) -> tuple[Chunk, Chunk, Chunk]:
            nonlocal left_index, right_index
            length = min(len(lefts) - left_index, len(rights) - right_index)
            output = tuple(f(lefts[left_index + i], rights[right_index + i]) for i in range(length))
            left_index += length
            right_index += length
            left_done = left_index == len(lefts)
            right_done = right_index == len(rights)
            if left_done:
                left_index = 0
            if right_done:
                right_index = 0
            return output, () if left_done else lefts, () if right_done else rights

        return zip_with_array(left, right, step)

    return suspend(make)


_NOTHING: Any = object()


def zip_latest_all(*streams: AnyStream) -> AnyStream_:
    def make() -> AnyChannel:
        count = len(streams)
        latest: list[Any] = [None] * count
        emitted: set[int] = set()
        ready = Latch()
        empty = Latch()

        def side(index: int, stream: AnyStream) -> AnyChannel:
            def on_item(item: Any) -> AnyEffect:
                latest[index] = item
                if index in emitted:
                    return _Succeed((tuple(latest),))
                emitted.add(index)
                if len(emitted) < count:
                    return ready.wait().as_(_NOTHING)
                return ready.open().as_((tuple(latest),))

            # A side ending without an item makes a full tuple impossible.
            return (
                stream._channel.flatten_array()
                .map_effect(on_item)
                .filter(lambda chunk: chunk is not _NOTHING)
                .map_done_effect(lambda _: _Succeed(None) if index in emitted else empty.open())
            )

        sides = channel.from_iterable([side(i, s) for i, s in enumerate(streams)])
        merged = sides.merge_all(concurrency="unbounded", buffer_size=0)
        return merged.interrupt_when(empty.wait())

    return Stream(channel.suspend(make))


# --- interleaving -------------------------------------------------------------


def alternating() -> AnyStream_:
    from pyfect.stream._constructors import from_iterable

    return from_iterable(itertools.cycle((True, False)))


_RETRY: Any = object()


def interleave_with(left: AnyStream, right: AnyStream, decider: AnyStream) -> AnyStream_:
    def transform(_up: AnyEffect, scope: CloseableScope) -> AnyEffect:
        def body() -> Generator[AnyEffect, Any, AnyEffect]:
            pull_decider: AnyEffect = yield decider._channel.flatten_array().to_pull_scoped(scope)
            pull_left: AnyEffect = yield left._channel.flatten_array().to_pull_scoped(scope)
            pull_right: AnyEffect = yield right._channel.flatten_array().to_pull_scoped(scope)
            done = [False, False]

            def ending(index: int) -> Callable[[object], AnyEffect]:
                def end(_: object) -> AnyEffect:
                    done[index] = True
                    return _Succeed(_RETRY)

                return end

            sides = (catch_done(pull_left, ending(0)), catch_done(pull_right, ending(1)))

            def pull() -> Generator[AnyEffect, Any, Chunk]:
                while True:
                    if done[0] and done[1]:
                        return (yield _ENDED)
                    use_left: bool = yield pull_decider
                    index = 0 if use_left else 1
                    if done[index]:
                        continue
                    item = yield sides[index]
                    if item is _RETRY:
                        continue
                    return (item,)

            return _Gen(pull)

        return _Gen(body)

    return Stream(channel.from_transform(transform))


# --- racing -------------------------------------------------------------------


def race_all(*streams: AnyStream) -> AnyStream_:
    from pyfect._concurrency import race_all as race_effects

    def transform(_up: AnyEffect, scope: CloseableScope) -> AnyEffect:
        def make() -> AnyEffect:
            winner: list[AnyEffect] = []

            def contender(stream: AnyStream) -> AnyEffect:
                child = scope._fork_now()

                def settle(ex: Exit[Any, Any]) -> AnyEffect:
                    if isinstance(ex, Success) and not winner:
                        winner.append(ex.value[0])
                        return _Succeed(None)
                    return child.close(ex)

                started = stream._channel.to_pull_scoped(child).flat_map(
                    lambda pull: pull.map(lambda chunk: (pull, chunk))
                )
                return started.on_exit(settle).map(lambda pair: pair[1])

            race = race_effects(*(contender(s) for s in streams))
            return _Suspend(lambda: winner[0] if winner else race)

        return _Sync(make)

    return Stream(channel.from_transform(transform))
