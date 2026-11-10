"""What the streaming archive codecs (``tar``, ``zip``) share: a queue of input
chunks, and the channel that runs a pull-driven decoder."""
# pyright: reportPrivateUsage=false, reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false

from __future__ import annotations

import enum
from collections import deque
from collections.abc import Callable
from typing import Any, Final, Literal, Protocol

from pyfect._primitives import _Succeed, _Suspend, _Sync
from pyfect.channel import from_transform
from pyfect.channel._base import AnyPull, end_with
from pyfect.exit import Success
from pyfect.exit import fail as fail_exit
from pyfect.pull import catch_done
from pyfect.scope import CloseableScope
from pyfect.semaphore import Semaphore
from pyfect.stream import from_pull


class _NeedInput(enum.Enum):
    NEED_INPUT = enum.auto()


NEED_INPUT: Final = _NeedInput.NEED_INPUT
"""What a decoder returns when the buffered input is not enough to continue."""
type NeedInput = Literal[_NeedInput.NEED_INPUT]


class ByteQueue:
    """Input chunks, handed out whole where possible. Consumed chunks are
    released right away."""

    __slots__ = ("_chunks", "_offset", "consumed", "length")

    def __init__(self) -> None:
        self._chunks: deque[bytes] = deque()
        self._offset = 0
        self.length = 0
        self.consumed = 0

    def push(self, chunk: bytes) -> None:
        if chunk:
            self._chunks.append(chunk)
            self.length += len(chunk)

    def take_some(self, most: int) -> bytes:
        """At most ``most`` (> 0) bytes of the first chunk; the queue must not be empty."""
        chunk = self._chunks[0]
        available = len(chunk) - self._offset
        if most < available:
            out = chunk[self._offset : self._offset + most]
            self._offset += most
            self.length -= most
            self.consumed += most
            return out
        out = chunk if self._offset == 0 else chunk[self._offset :]
        self._chunks.popleft()
        self._offset = 0
        self.length -= available
        self.consumed += available
        return out

    def take(self, n: int) -> bytes:
        """Exactly ``n`` bytes; the queue must hold at least ``n``."""
        if n == 0:
            return b""
        first = self.take_some(n)
        if len(first) == n:
            return first
        parts = [first]
        filled = len(first)
        while filled < n:
            part = self.take_some(n - filled)
            parts.append(part)
            filled += len(part)
        return b"".join(parts)

    def peek(self, n: int) -> bytes:
        """The first ``n`` bytes without consuming them; the queue must hold at
        least ``n``."""
        parts: list[bytes] = []
        filled = 0
        offset = self._offset
        for chunk in self._chunks:
            if filled == n:
                break
            part = chunk[offset : offset + n - filled]
            parts.append(part)
            filled += len(part)
            offset = 0
        return b"".join(parts)

    def skip(self, n: int) -> None:
        while n > 0:
            n -= len(self.take_some(n))

    def unread(self, data: bytes) -> None:
        """Puts back ``data``, the last bytes taken."""
        if self._offset >= len(data):
            self._offset -= len(data)
        else:
            # The first chunk holds the end of ``data`` already
            self._chunks.appendleft(data[: len(data) - self._offset])
            self._offset = 0
        self.length += len(data)
        self.consumed -= len(data)

    def clear(self) -> None:
        self._chunks.clear()
        self._offset = 0
        self.length = 0


class Decoder[H](Protocol):
    """A decoder the channel drives. ``next`` skips the rest of the current body
    and ``read`` consumes it; both keep their progress across ``NEED_INPUT``."""

    generation: int

    def push(self, chunk: bytes) -> None: ...

    def end(self) -> None: ...

    def close(self) -> None: ...

    def next(self) -> H | NeedInput | None: ...

    def read(self, generation: int) -> tuple[bytes, ...] | NeedInput | None: ...


def decode_channel[H](
    make_decoder: Callable[[], Decoder[H]],
    make_entry: Callable[[H, Any], object],
    error_type: type[Exception],
) -> Any:
    """The channel of a decoder: each output chunk holds one entry, whose body is
    a stream reading the decoder while the channel runs."""

    def transform(upstream: AnyPull, scope: CloseableScope) -> AnyPull:
        decoder = make_decoder()
        done: tuple[Any] | None = None
        pulls = 0

        def pushed(chunks: tuple[bytes, ...]) -> None:
            nonlocal pulls
            pulls += 1
            for chunk in chunks:
                decoder.push(chunk)

        def ended(value: object) -> AnyPull:
            nonlocal done, pulls
            pulls += 1
            done = (value,)
            decoder.end()
            return _Succeed(None)

        pull_upstream = catch_done(upstream.map(pushed), ended)

        # Serialize entry and body pulls; reuse input pulled while waiting for the lock.
        lock = Semaphore(1)

        def pull_input(seen: int) -> AnyPull:
            return lock.with_permits(
                _Suspend(lambda: pull_upstream if pulls == seen else _Succeed(None))
            )

        def run(read: Callable[[], Any], end: Callable[[], object]) -> AnyPull:
            def loop() -> Any:
                seen = pulls
                try:
                    result = read()
                except error_type as error:
                    return fail_exit(error)
                if result is NEED_INPUT:
                    return pull_input(seen).flat_map(lambda _: _Suspend(loop))
                return end_with(end()) if result is None else Success(result)

            return _Suspend(loop)

        def body(generation: int) -> Any:
            return from_pull(_Succeed(run(lambda: decoder.read(generation), lambda: None)))

        def next_entry() -> Any:
            header = decoder.next()
            if header is NEED_INPUT or header is None:
                return header
            return (make_entry(header, body(decoder.generation)),)

        def leftover() -> object:
            assert done is not None
            return done[0]

        pull = run(next_entry, leftover)
        return scope.add_finalizer(lambda _: _Sync(decoder.close)).map(lambda _: pull)

    return from_transform(lambda upstream, scope: _Suspend(lambda: transform(upstream, scope)))
