"""A stateful parser of concatenated SchemaBinary frames."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

from pyfect._core import Effect
from pyfect._primitives import _FailCause, _Succeed, _Suspend  # pyright: ignore[reportPrivateUsage]
from pyfect.cause import fail as fail_cause
from pyfect.encoding.schema_binary import _dictionary as D
from pyfect.encoding.schema_binary import _wire as W
from pyfect.encoding.schema_binary._decode import decode_frame_body
from pyfect.encoding.schema_binary._fingerprint import Mode
from pyfect.encoding.schema_binary._layout import Layout
from pyfect.encoding.schema_binary._reader import Reader
from pyfect.schema import ParseOptions, SchemaError


class Parser[T](Protocol):
    """Values from a stream of chunks holding concatenated frames.

    Values completed before a failure remain observable: the failure is
    raised by the next call. After a failure, the parser rejects further
    calls."""

    def feed_sync(self, chunk: bytes, /) -> list[T]:
        """Feeds a chunk and returns the values it completed."""
        ...

    def end_sync(self) -> None:
        """Finishes; raises ``SchemaError`` for an incomplete frame."""
        ...

    def feed(self, chunk: bytes, /) -> Effect[list[T], SchemaError]:
        """``feed_sync`` as an effect."""
        ...

    @property
    def end(self) -> Effect[None, SchemaError]:
        """``end_sync`` as an effect."""
        ...


def _effect_of[A](f: Callable[[], A]) -> Effect[A, SchemaError]:
    def run() -> Effect[A, SchemaError]:
        try:
            return _Succeed(f())
        except SchemaError as error:
            return _FailCause(fail_cause(error))

    return _Suspend(run)


@dataclass(slots=True, eq=False)
class FrameParser[T]:
    """``decode_encoded`` runs the target schema pass on each framed value;
    ``None`` yields the raw binary-decoded values."""

    layout: Layout
    mode: Mode
    options: ParseOptions
    max_frame_size: int | None
    decode_encoded: Callable[[object], object] | None
    dict_: D.DictRead | None
    buffer: bytearray = field(default_factory=bytearray)
    needed: int = 0
    """The buffered bytes the next frame needs, once its header is read: chunks are only
    appended until then, so a frame trickled in small chunks costs linear time."""
    stashed: SchemaError | None = None
    spent: bool = False

    def _error(self, expected: str, input: object = W.NO_INPUT) -> SchemaError:
        return SchemaError(W.invalid_value(expected, input, self.options))

    def _take_stashed(self) -> None:
        if self.stashed is not None:
            error = self.stashed
            self.stashed = None
            raise error
        if self.spent:
            raise self._error("parser is spent")

    def _fail(self, error: SchemaError, out: list[T]) -> list[T]:
        self.spent = True
        self.buffer = bytearray()
        if not out:
            raise error
        self.stashed = error
        return out

    def _frame_header(self, buf: bytes, pos: int) -> tuple[int, int] | SchemaError | None:
        """The frame length and the header's: ``None`` until it is whole."""
        buffered = len(buf) - pos
        value = 0
        for i in range(min(10, buffered)):
            b = buf[pos + i]
            value |= (b & 0x7F) << (7 * i)
            if b < 0x80:
                if value > W.MAX_SAFE:
                    return self._error("safe integer length", value)
                return value, i + 1
        return self._error("uvarint", buf[pos : pos + 10]) if buffered >= 10 else None

    def _whole(self, chunk: bytes) -> bytes | None:
        """The buffered bytes with ``chunk``, or ``None`` while the next frame is still short
        of them (``chunk`` is then only appended)."""
        if not self.buffer:
            return bytes(chunk)
        self.buffer += chunk
        if len(self.buffer) < self.needed:
            return None
        return bytes(self.buffer)

    def feed_sync(self, chunk: bytes, /) -> list[T]:
        self._take_stashed()
        buf = self._whole(chunk)
        return [] if buf is None else self._frames(buf)

    def _frames(self, buf: bytes) -> list[T]:
        """The frames whole in ``buf``; the rest is buffered."""
        self.needed = 0
        pos = 0
        out: list[T] = []
        while True:
            header = self._frame_header(buf, pos)
            if header is None:
                break
            if isinstance(header, SchemaError):
                return self._fail(header, out)
            length, header_length = header
            if length == 0:
                return self._fail(self._error("nonzero frame length", length), out)
            if self.max_frame_size is not None and length > self.max_frame_size:
                return self._fail(self._error("frame within maxFrameSize", length), out)
            if header_length + length > len(buf) - pos:
                self.needed = header_length + length
                break
            start = pos + header_length
            reader = Reader(
                buf,
                start,
                start + length,
                self.options,
                self.mode.positional,
                self.dict_,
                self.mode.reject_unknown_fields,
            )
            try:
                value = decode_frame_body(self.layout, reader, self.mode)
                decode = self.decode_encoded
                out.append(value if decode is None else decode(value))  # pyright: ignore[reportArgumentType]
            except W.IssueError as error:
                return self._fail(SchemaError(error.issue), out)
            except SchemaError as error:
                return self._fail(error, out)
            pos = start + length
        self.buffer = bytearray(buf[pos:])
        return out

    def end_sync(self) -> None:
        self._take_stashed()
        self.spent = True
        rest = bytes(self.buffer)
        self.buffer = bytearray()
        if rest:
            raise self._error("complete value", rest)

    def feed(self, chunk: bytes, /) -> Effect[list[T], SchemaError]:
        return _effect_of(lambda: self.feed_sync(chunk))

    @property
    def end(self) -> Effect[None, SchemaError]:
        return _effect_of(self.end_sync)


def make_parser(  # noqa: PLR0917
    layout: Layout,
    mode: Mode,
    options: ParseOptions,
    max_frame_size: int | None,
    decode_encoded: Callable[[object], Any] | None,
    dictionary: bool,
) -> FrameParser[Any]:
    return FrameParser(
        layout, mode, options, max_frame_size, decode_encoded, {} if dictionary else None
    )
