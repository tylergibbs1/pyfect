"""Stand-ins for the Stream operators the core ports use (``take``,
``tap``, ``map``, ``map_effect``, ``chunks``, ``provide_service``), built on
``stream.transform_pull`` and the stream's channel until the Stream
operator cluster of M6 adds them as methods. Each is curried for
``.pipe``, as Effect's are."""

from collections.abc import Callable
from typing import Any

import pyfect as fx
from pyfect import channel, stream
from pyfect.scope import CloseableScope

type _Stream = stream.Stream[Any, Any, Any]


def take(n: int) -> Callable[[_Stream], _Stream]:
    """``Stream.take(n)``: the first ``n`` items, then end without pulling
    again."""

    def apply(source: _Stream) -> _Stream:
        def build(pull: fx.Effect[Any, Any, Any], _scope: CloseableScope) -> Any:
            taken = 0

            def cut(chunk: tuple[Any, ...]) -> tuple[Any, ...]:
                nonlocal taken
                kept = chunk[: n - taken]
                taken += len(kept)
                return kept

            def next_chunk() -> fx.Effect[Any, Any, Any]:
                return fx.fail(fx.Done()) if taken >= n else pull.map(cut)

            return fx.succeed(fx.suspend(next_chunk))

        return stream.transform_pull(source, build)

    return apply


def tap(f: Callable[[Any], fx.Effect[Any, Any, Any]]) -> Callable[[_Stream], _Stream]:
    """``Stream.tap(f)``: run ``f`` on each item as it passes."""
    return _per_chunk(lambda chunk: fx.for_each(chunk, f).as_(chunk))


def map_(f: Callable[[Any], Any]) -> Callable[[_Stream], _Stream]:
    """``Stream.map(f)``."""
    return lambda source: stream.from_channel(
        source.channel.map(lambda chunk: tuple(f(a) for a in chunk))
    )


def map_effect(f: Callable[[Any], fx.Effect[Any, Any, Any]]) -> Callable[[_Stream], _Stream]:
    """``Stream.mapEffect(f)``, one item at a time."""
    return _per_chunk(lambda chunk: fx.for_each(chunk, f).map(tuple))


def chunks(source: _Stream) -> _Stream:
    """``Stream.chunks``: each chunk as one item."""
    return stream.from_channel(source.channel.map(lambda chunk: (chunk,)))


def provide_service(tag: Any, service: object) -> Callable[[_Stream], _Stream]:
    """``Stream.provideService(tag, service)``."""
    return lambda source: stream.from_channel(
        source.channel.pipe(channel.provide_service(tag, service))
    )


def _per_chunk(
    f: Callable[[tuple[Any, ...]], fx.Effect[Any, Any, Any]],
) -> Callable[[_Stream], _Stream]:
    return lambda source: stream.from_channel(source.channel.map_effect(f))
