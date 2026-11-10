"""Newline-delimited JSON channels (Effect's ``encoding/Ndjson``).

NDJSON holds one JSON value per line. The decoders read chunks of bytes
(``decode``) or text (``decode_string``) and write the parsed values; the
encoders write each chunk of values as lines. Lines may span chunks, and
``\\n``, ``\\r\\n`` and a bare ``\\r`` end a line. Use them with
``Stream.pipe_through_channel``::

    values = byte_stream.pipe_through_channel(ndjson.decode())

The schema variants (``decode_schema``, ``encode_schema``, ``duplex_schema``
and their ``_string`` forms) decode each parsed value with a schema, or
encode each value before writing it, failing with ``SchemaError``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Never, Unpack, overload

from pyfect import channel_schema
from pyfect._js import text_encode
from pyfect._json_text import PARSE_ERRORS, STRINGIFY_ERRORS, Json, parse, stringify
from pyfect._primitives import _FailCause, _Succeed, _Suspend, _Sync
from pyfect.cause import Cause
from pyfect.cause import fail as fail_cause
from pyfect.channel import Channel, from_transform, split_lines
from pyfect.channel._base import AnyPull, end_with, require_channel
from pyfect.errors import TaggedError
from pyfect.pull import match_effect
from pyfect.schema import Codec, ParseOptions, SchemaError
from pyfect.scope import CloseableScope

__all__ = [
    "NdjsonError",
    "NdjsonErrorReason",
    "decode",
    "decode_schema",
    "decode_schema_string",
    "decode_string",
    "duplex",
    "duplex_schema",
    "duplex_schema_string",
    "duplex_string",
    "encode",
    "encode_schema",
    "encode_schema_string",
    "encode_string",
]

type NdjsonErrorReason = Literal["InvalidJson", "InvalidUtf8", "LineTooLarge"]
"""Why a decoder rejected a line: not JSON, not UTF-8 (byte decoders), or
longer than ``max_line_bytes`` (byte decoders)."""


@dataclass(eq=False)
class NdjsonError(TaggedError):
    """Encoding (``"Pack"``) or decoding (``"Unpack"``) failed. Decoders set
    ``reason``, and ``unterminated`` when the rejected line is the input's
    last and has no line break."""

    kind: Literal["Pack", "Unpack"]
    cause: Exception
    reason: NdjsonErrorReason | None = None
    unterminated: bool = False

    @property
    def message(self) -> str:
        return self.kind


# --- encoding ---------------------------------------------------------------------


def encode_string[E = Never, D = None]() -> Channel[
    tuple[str, ...], E | NdjsonError, D, tuple[object, ...], E, D
]:
    """Write each chunk of values as one string of lines, each ending with
    ``\\n``. A value with no JSON form (a set, an object, ``NaN``) fails
    with a ``"Pack"`` error."""

    def encoded(chunk: tuple[object, ...]) -> AnyPull:
        try:
            text = "\n".join(map(stringify, chunk)) + "\n"
        except STRINGIFY_ERRORS as cause:
            return _FailCause(fail_cause(NdjsonError("Pack", cause)))
        return _Succeed((text,))

    channel: Channel[tuple[str, ...], E | NdjsonError, D, tuple[object, ...], E, D] = (
        from_transform(lambda upstream, _scope: _Succeed(upstream.flat_map(encoded)))
    )
    return channel


def encode[E = Never, D = None]() -> Channel[
    tuple[bytes, ...], E | NdjsonError, D, tuple[object, ...], E, D
]:
    """``encode_string`` as UTF-8 bytes."""
    strings: Channel[tuple[str, ...], E | NdjsonError, D, tuple[object, ...], E, D] = (
        encode_string()
    )
    return strings.map(lambda chunk: tuple(text_encode(text) for text in chunk))


# --- decoding ---------------------------------------------------------------------

type _Step = Callable[[Any, list[Json]], NdjsonError | None]
"""Parses one input chunk's lines into the list; the first failure stops
the chunk, and the values before it are still written."""


def _decode_pull(
    upstream: AnyPull, step: _Step, flush: Callable[[list[Json]], NdjsonError | None]
) -> AnyPull:
    failure: NdjsonError | None = None
    ended: list[object] = []

    def emit(out: list[Json], error: NdjsonError | None) -> AnyPull | None:
        nonlocal failure
        failure = error
        if out:
            return _Succeed(tuple(out))
        return None if error is None else _FailCause(fail_cause(error))

    def written(chunk: object) -> AnyPull:
        out: list[Json] = []
        result = emit(out, step(chunk, out))
        return pull if result is None else result

    def failed(cause: Cause[Any]) -> AnyPull:
        return _FailCause(cause)

    def done(leftover: object) -> AnyPull:
        ended.append(leftover)
        out: list[Json] = []
        result = emit(out, flush(out))
        return end_with(leftover) if result is None else result

    def next_pull() -> AnyPull:
        if failure is not None:
            return _FailCause(fail_cause(failure))
        if ended:
            return end_with(ended[0])
        return match_effect(upstream, on_success=written, on_failure=failed, on_done=done)

    pull: AnyPull = _Suspend(next_pull)
    return pull


def _parse_line(
    line: str, out: list[Json], ignore_empty_lines: bool, unterminated: bool
) -> NdjsonError | None:
    if ignore_empty_lines and not line.strip(" \t"):
        return None
    try:
        out.append(parse(line))
    except PARSE_ERRORS as cause:
        return NdjsonError("Unpack", cause, reason="InvalidJson", unterminated=unterminated)
    return None


def _flush_nothing(_out: list[Json]) -> None:
    return None


def decode_string[E = Never, D = None](
    *, ignore_empty_lines: bool = False
) -> Channel[tuple[Json, ...], E | NdjsonError, D, tuple[str, ...], E, D]:
    """Parse chunks of text as NDJSON. The first line that is not JSON fails
    the channel (``"InvalidJson"``) after the values before it are written;
    blank lines (empty, or only spaces and tabs) fail too unless
    ``ignore_empty_lines``."""

    def transform(upstream: AnyPull, scope: CloseableScope) -> Any:
        # ``split_lines`` writes a line after its input has ended only when
        # that line has no line break.
        ended = False

        def done(leftover: object) -> AnyPull:
            nonlocal ended
            ended = True
            return end_with(leftover)

        def failed(cause: Cause[Any]) -> AnyPull:
            return _FailCause(cause)

        source = match_effect(upstream, on_success=_Succeed, on_failure=failed, on_done=done)

        def step(lines: tuple[str, ...], out: list[Json]) -> NdjsonError | None:
            for line in lines:
                error = _parse_line(line, out, ignore_empty_lines, ended)
                if error is not None:
                    return error
            return None

        return (
            split_lines()
            ._transform(source, scope)
            .map(lambda lines: _decode_pull(lines, step, _flush_nothing))
        )

    channel: Channel[tuple[Json, ...], E | NdjsonError, D, tuple[str, ...], E, D] = from_transform(
        transform
    )
    return channel


_LF = 0x0A
_CR = 0x0D


class _ByteLines:
    """Splits UTF-8 bytes into lines and parses each, carrying an unfinished
    line (and a ``\\r`` that may start a ``\\r\\n``) across chunks."""

    __slots__ = ("after_cr", "first", "ignore_empty_lines", "max_line_bytes", "pending", "size")

    def __init__(self, ignore_empty_lines: bool, max_line_bytes: float) -> None:
        self.ignore_empty_lines = ignore_empty_lines
        self.max_line_bytes = max_line_bytes
        self.first = True  # the first line may start with a byte-order mark
        self.pending: list[bytes] = []
        self.size = 0
        self.after_cr = False

    def take_line(self, chunk: bytes, start: int, end: int) -> bytes:
        if not self.pending:
            return chunk[start:end]
        self.pending.append(chunk[start:end])
        line = b"".join(self.pending)
        self.pending = []
        self.size = 0
        return line

    def decode_line(self, data: bytes, out: list[Json], unterminated: bool) -> NdjsonError | None:
        first = self.first
        try:
            line = data.decode("utf-8-sig" if first else "utf-8")
        except UnicodeDecodeError as cause:
            return NdjsonError("Unpack", cause, reason="InvalidUtf8", unterminated=unterminated)
        self.first = False
        if first and unterminated and not line:
            return None  # a byte-order mark alone is not a record
        return _parse_line(line, out, self.ignore_empty_lines, unterminated)

    def too_large(self) -> NdjsonError:
        cause = ValueError(f"NDJSON line exceeds max_line_bytes of {self.max_line_bytes}")
        return NdjsonError("Unpack", cause, reason="LineTooLarge")

    def step(self, chunks: tuple[bytes, ...], out: list[Json]) -> NdjsonError | None:
        for chunk in chunks:
            n = len(chunk)
            start = 0
            lf = chunk.find(b"\n")
            cr = chunk.find(b"\r")
            while start < n:
                if self.after_cr:
                    self.after_cr = False
                    if chunk[start] == _LF:
                        start += 1
                        continue
                if 0 <= lf < start:
                    lf = chunk.find(b"\n", start)
                if 0 <= cr < start:
                    cr = chunk.find(b"\r", start)
                end = cr if lf == -1 or 0 <= cr < lf else lf
                length = (n if end == -1 else end) - start
                if length and self.size + length > self.max_line_bytes:
                    return self.too_large()
                if end == -1:
                    self.pending.append(chunk[start:])
                    self.size += length
                    break
                error = self.decode_line(self.take_line(chunk, start, end), out, False)
                if error is not None:
                    return error
                self.after_cr = chunk[end] == _CR
                start = end + 1
        return None

    def flush(self, out: list[Json]) -> NdjsonError | None:
        if not self.size:
            return None
        return self.decode_line(self.take_line(b"", 0, 0), out, True)


def decode[E = Never, D = None](
    *, ignore_empty_lines: bool = False, max_line_bytes: int | None = None
) -> Channel[tuple[Json, ...], E | NdjsonError, D, tuple[bytes, ...], E, D]:
    """Parse chunks of UTF-8 bytes as NDJSON; a leading byte-order mark is
    skipped. The first bad line fails the channel after the values before
    it are written: ``"InvalidUtf8"``, ``"InvalidJson"``, or
    ``"LineTooLarge"`` as soon as a line passes ``max_line_bytes`` (its
    bytes without the line break; ``None``, the default, is unbounded),
    without reading the rest of it."""
    limit = math.inf if max_line_bytes is None else max_line_bytes

    def build(upstream: AnyPull) -> AnyPull:
        lines = _ByteLines(ignore_empty_lines, limit)
        return _decode_pull(upstream, lines.step, lines.flush)

    channel: Channel[tuple[Json, ...], E | NdjsonError, D, tuple[bytes, ...], E, D] = (
        from_transform(lambda upstream, _scope: _Sync(lambda: build(upstream)))
    )
    return channel


# --- duplex -----------------------------------------------------------------------
#
# The wrapped channel reads the encoder's output, which fails with the outer
# upstream's ``IE`` or ``NdjsonError``. Pyright cannot solve ``IE`` from
# ``IE | NdjsonError`` when the channel reads exactly ``NdjsonError``, so
# that case has an overload of its own.

type _Bytes = tuple[bytes, ...]
type _Strings = tuple[str, ...]
type _Values = tuple[Json, ...]
type _Inputs = tuple[object, ...]


@overload
def duplex[OE, OD, ID, R, IE = Never](
    channel: Channel[_Bytes, OE, OD, _Bytes, IE | NdjsonError, ID, R],
    *,
    ignore_empty_lines: bool = False,
    max_line_bytes: int | None = None,
) -> Channel[_Values, NdjsonError | OE, OD, _Inputs, IE, ID, R]: ...
@overload
def duplex[OE, OD, ID, R](
    channel: Channel[_Bytes, OE, OD, _Bytes, NdjsonError, ID, R],
    *,
    ignore_empty_lines: bool = False,
    max_line_bytes: int | None = None,
) -> Channel[_Values, NdjsonError | OE, OD, _Inputs, Never, ID, R]: ...
def duplex(
    channel: Channel[Any, Any, Any, Any, Any, Any, Any],
    *,
    ignore_empty_lines: bool = False,
    max_line_bytes: int | None = None,
) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
    """Wrap a channel of bytes both ways: the values written to it go out as
    NDJSON bytes, and the bytes it writes come back parsed (``decode``)."""
    require_channel(channel, "channel")
    outgoing: Channel[Any, Any, Any, Any, Any, Any, Any] = encode()
    incoming: Channel[Any, Any, Any, Any, Any, Any, Any] = decode(
        ignore_empty_lines=ignore_empty_lines, max_line_bytes=max_line_bytes
    )
    return outgoing.pipe_to(channel).pipe_to(incoming)


@overload
def duplex_string[OE, OD, ID, R, IE = Never](
    channel: Channel[_Strings, OE, OD, _Strings, IE | NdjsonError, ID, R],
    *,
    ignore_empty_lines: bool = False,
) -> Channel[_Values, NdjsonError | OE, OD, _Inputs, IE, ID, R]: ...
@overload
def duplex_string[OE, OD, ID, R](
    channel: Channel[_Strings, OE, OD, _Strings, NdjsonError, ID, R],
    *,
    ignore_empty_lines: bool = False,
) -> Channel[_Values, NdjsonError | OE, OD, _Inputs, Never, ID, R]: ...
def duplex_string(
    channel: Channel[Any, Any, Any, Any, Any, Any, Any],
    *,
    ignore_empty_lines: bool = False,
) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
    """``duplex`` for a channel of text."""
    require_channel(channel, "channel")
    outgoing: Channel[Any, Any, Any, Any, Any, Any, Any] = encode_string()
    incoming: Channel[Any, Any, Any, Any, Any, Any, Any] = decode_string(
        ignore_empty_lines=ignore_empty_lines
    )
    return outgoing.pipe_to(channel).pipe_to(incoming)


# --- schemas ----------------------------------------------------------------------

type _AnyChannel = Channel[Any, Any, Any, Any, Any, Any, Any]


def encode_schema[T, I, RE, E = Never, D = None](
    schema: Codec[T, I, object, RE], /
) -> Channel[tuple[bytes, ...], E | NdjsonError | SchemaError, D, tuple[T, ...], E, D, RE]:
    """``encode`` of each value encoded with ``schema`` first."""
    encoded: _AnyChannel = channel_schema.encode(schema)
    return encoded.pipe_to(encode())


def encode_schema_string[T, I, RE, E = Never, D = None](
    schema: Codec[T, I, object, RE], /
) -> Channel[tuple[str, ...], E | NdjsonError | SchemaError, D, tuple[T, ...], E, D, RE]:
    """``encode_string`` of each value encoded with ``schema`` first."""
    encoded: _AnyChannel = channel_schema.encode(schema)
    return encoded.pipe_to(encode_string())


def decode_schema[T, RD, E = Never, D = None](
    schema: Codec[T, object, RD, object],
    /,
    *,
    ignore_empty_lines: bool = False,
    max_line_bytes: int | None = None,
    **options: Unpack[ParseOptions],
) -> Channel[tuple[T, ...], E | NdjsonError | SchemaError, D, tuple[bytes, ...], E, D, RD]:
    """``decode``, each parsed value then decoded with ``schema``."""
    lines: _AnyChannel = decode(
        ignore_empty_lines=ignore_empty_lines, max_line_bytes=max_line_bytes
    )
    return lines.pipe_to(channel_schema.decode_unknown(schema, **options))


def decode_schema_string[T, RD, E = Never, D = None](
    schema: Codec[T, object, RD, object],
    /,
    *,
    ignore_empty_lines: bool = False,
    **options: Unpack[ParseOptions],
) -> Channel[tuple[T, ...], E | NdjsonError | SchemaError, D, tuple[str, ...], E, D, RD]:
    """``decode_string``, each parsed value then decoded with ``schema``."""
    lines: _AnyChannel = decode_string(ignore_empty_lines=ignore_empty_lines)
    return lines.pipe_to(channel_schema.decode_unknown(schema, **options))


def duplex_schema[TI, TO, OE, OD, ID, RR, IE = Never](
    channel: Channel[_Bytes, OE, OD, _Bytes, IE | NdjsonError | SchemaError, ID, RR],
    /,
    *,
    input_schema: Codec[TI, object, object, RR],
    output_schema: Codec[TO, object, RR, object],
    ignore_empty_lines: bool = False,
    max_line_bytes: int | None = None,
) -> Channel[tuple[TO, ...], NdjsonError | SchemaError | OE, OD, tuple[TI, ...], IE, ID, RR]:
    """``duplex`` with values encoded by ``input_schema`` on the way in and
    decoded by ``output_schema`` on the way out."""
    require_channel(channel, "channel")
    framed: _AnyChannel = duplex(
        channel, ignore_empty_lines=ignore_empty_lines, max_line_bytes=max_line_bytes
    )
    return channel_schema.duplex_unknown(
        framed, input_schema=input_schema, output_schema=output_schema
    )


def duplex_schema_string[TI, TO, OE, OD, ID, RR, IE = Never](
    channel: Channel[_Strings, OE, OD, _Strings, IE | NdjsonError | SchemaError, ID, RR],
    /,
    *,
    input_schema: Codec[TI, object, object, RR],
    output_schema: Codec[TO, object, RR, object],
    ignore_empty_lines: bool = False,
) -> Channel[tuple[TO, ...], NdjsonError | SchemaError | OE, OD, tuple[TI, ...], IE, ID, RR]:
    """``duplex_string`` with values encoded by ``input_schema`` on the way
    in and decoded by ``output_schema`` on the way out."""
    require_channel(channel, "channel")
    framed: _AnyChannel = duplex_string(channel, ignore_empty_lines=ignore_empty_lines)
    return channel_schema.duplex_unknown(
        framed, input_schema=input_schema, output_schema=output_schema
    )
