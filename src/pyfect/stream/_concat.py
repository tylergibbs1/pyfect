"""``concat`` chains that run as one flat sequence.

A ``concat`` result remembers its two parts, and ``suspend`` remembers its
thunk, so running a chain walks it with a stack: each plain part's channel
runs in turn, and a suspended part is evaluated when it is reached and
joins the chain. A chain of thousands of ``concat`` calls, nested to the
left, to the right, or built through ``suspend``, costs the same per part
as a short one (Effect's ``concatChannels``).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Iterator
from typing import Any

from pyfect import channel
from pyfect.channel import Channel
from pyfect.stream._base import AnyStream, StreamBase
from pyfect.stream._stream import Stream

type AnyChannel = Channel[Any, Any, Any, Any, Any, Any, Any]


class ConcatStream(Stream[Any, Any, Any]):
    """A ``concat`` result: its channel walks the chain of its parts."""

    __slots__ = ("parts",)

    def __init__(self, first: AnyStream, second: AnyStream) -> None:
        self.parts = (first, second)
        super().__init__(channel.from_iterator(lambda: _channels(first, second)).flatten())


class SuspendedStream(Stream[Any, Any, Any]):
    """A ``suspend`` result: ``thunk`` builds the stream each time it runs."""

    __slots__ = ("thunk",)

    def __init__(self, thunk: Callable[[], StreamBase[Any, Any, Any]]) -> None:
        self.thunk = thunk
        super().__init__(channel.suspend(lambda: thunk()._channel))


def concat(first: AnyStream, second: AnyStream) -> Stream[Any, Any, Any]:
    return ConcatStream(first, second)


def _channels(first: AnyStream, second: AnyStream) -> Iterator[AnyChannel]:
    stack: list[AnyStream] = [second, first]
    while stack:
        stream = stack.pop()
        if isinstance(stream, ConcatStream):
            stack.extend(reversed(stream.parts))
            continue
        if not isinstance(stream, SuspendedStream):
            yield stream._channel
            continue
        # Evaluated here, not in an effect, so a retried pull cannot
        # evaluate it twice; the empty channel keeps a yield point.
        try:
            stack.append(stream.thunk())
        except Exception as defect:
            stack.append(Stream(channel.die(defect)))
        yield channel.empty
