"""SchemaBinary as channels between chunks of values and chunks of frames."""

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false
from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Never, Unpack

from pyfect import schema as S
from pyfect._primitives import _FailCause, _Succeed, _Suspend  # pyright: ignore[reportPrivateUsage]
from pyfect.cause import Cause, Fail
from pyfect.cause import die as die_cause
from pyfect.cause import fail as fail_cause
from pyfect.channel import Channel, from_transform
from pyfect.channel._base import AnyPull, end_with, require_channel
from pyfect.encoding.schema_binary import _encode
from pyfect.encoding.schema_binary._fingerprint import compile_mode
from pyfect.encoding.schema_binary._parser import Parser, make_parser
from pyfect.encoding.schema_binary._target import (
    compile_target,
    excess_is_error,
    is_success_exit,
)
from pyfect.encoding.schema_binary._wire import IssueError
from pyfect.pull import match_effect
from pyfect.schema import Codec, ParseOptions, SchemaError
from pyfect.scope import CloseableScope


def encode[A, RE, E = Never, D = None](
    schema: Codec[A, Any, object, RE],
    /,
    *,
    fingerprint: bool = False,
    **options: Unpack[ParseOptions],
) -> Channel[tuple[bytes, ...], E | SchemaError, D, tuple[A, ...], E, D, RE]:
    """Encodes chunks of values into frames: each input chunk gives one
    ``bytes`` of concatenated frames, written in one pass. A schema with
    transformations first runs one schema pass per chunk, which may be
    asynchronous and use services."""
    compiled = compile_target(schema)
    mode = compile_mode(compiled.layout, fingerprint)

    def write(values: Sequence[object]) -> AnyPull:
        try:
            return _Succeed((_encode.encode_frames(compiled.layout, values, options, mode),))
        except IssueError as error:
            return _FailCause(fail_cause(SchemaError(error.issue)))
        except Exception as defect:
            return _FailCause(die_cause(defect))

    if compiled.exact and not excess_is_error(options):

        def direct(upstream: AnyPull, _: CloseableScope) -> Any:
            return _Succeed(upstream.flat_map(write))

        channel: Any = from_transform(direct)
        return channel

    encode_values = S.encode_unknown_effect(S.NonEmptyArray(compiled.target), **options)

    def through_schema(upstream: AnyPull, _: CloseableScope) -> Any:
        return _Succeed(upstream.flat_map(lambda chunk: encode_values(chunk).flat_map(write)))

    passed: Any = from_transform(through_schema)
    return passed


def decode[A, RD, E = Never, D = None](
    schema: Codec[A, Any, RD, object],
    /,
    *,
    fingerprint: bool = False,
    max_frame_size: int | None = None,
    **options: Unpack[ParseOptions],
) -> Channel[tuple[A, ...], E | SchemaError, D, tuple[bytes, ...], E, D, RD]:
    """Decodes chunks of frames into values, with one frame parser per run:
    frames may be fragmented across chunks or concatenated within one, values
    completed before a failure are written first, and an incomplete frame
    left at the end fails. A schema with transformations runs the schema pass
    per value, which may be asynchronous and use services."""
    compiled = compile_target(schema)
    mode = compile_mode(compiled.layout, fingerprint)
    decode_target = None if compiled.exact else S.decode_unknown_effect(compiled.target, **options)

    def decode_one(value: object) -> Any:
        if compiled.exit_success and is_success_exit(value):
            return _Succeed(value)
        assert decode_target is not None
        return decode_target(value)

    def transform(upstream: AnyPull, _: CloseableScope) -> Any:
        frames = make_parser(compiled.layout, mode, options, max_frame_size, None, False)
        stashed: list[SchemaError] = []

        def decode_all(raw: list[object]) -> AnyPull:
            step = _DecodeAll(raw, decode_one)
            out = step.out

            def caught(cause: Cause[Any]) -> AnyPull:
                found = cause.find_recoverable_error()
                if out and isinstance(found, Fail) and isinstance(found.error, SchemaError):
                    stashed.append(found.error)
                    return _Succeed(tuple(out))
                return _FailCause(cause)

            return _Suspend(step).catch_cause(caught)

        def done(leftover: object) -> AnyPull:
            try:
                frames.end_sync()
            except SchemaError as error:
                return _FailCause(fail_cause(error))
            return end_with(leftover)

        decode = None if decode_target is None else decode_all
        return _Succeed(_Suspend(_FramesPull(upstream, frames, stashed, decode, done).next))

    channel: Any = from_transform(transform)
    return channel


class _FramesPull:
    """``decode``'s pull: a state object rather than closures over the pull
    itself, so a finished run does not keep its input alive."""

    __slots__ = ("decode_all", "done", "frames", "stashed", "upstream")

    def __init__(
        self,
        upstream: AnyPull,
        frames: Parser[Any],
        stashed: list[SchemaError],
        decode_all: Callable[[list[object]], AnyPull] | None,
        done: Callable[[object], AnyPull],
    ) -> None:
        self.upstream = upstream
        self.frames = frames
        self.stashed = stashed
        self.decode_all = decode_all
        self.done = done

    def next(self) -> AnyPull:
        if self.stashed:
            return _FailCause(fail_cause(self.stashed[0]))
        return match_effect(
            self.upstream, on_success=self, on_failure=_FailCause, on_done=self.done
        )

    def __call__(self, chunk: tuple[bytes, ...]) -> AnyPull:
        raw: list[object] = []
        try:
            for part in chunk:
                raw.extend(self.frames.feed_sync(part))
        except SchemaError as error:
            if not raw:
                return _FailCause(fail_cause(error))
            self.stashed.append(error)
        if not raw:
            return _Suspend(self.next)
        return _Succeed(tuple(raw)) if self.decode_all is None else self.decode_all(raw)


class _DecodeAll:
    """Decode each of ``raw`` in turn into ``out``: a loop on a state object,
    so a finished run does not keep its values alive."""

    __slots__ = ("decode_one", "out", "raw")

    def __init__(self, raw: list[object], decode_one: Callable[[object], Any]) -> None:
        self.raw = raw
        self.decode_one = decode_one
        self.out: list[object] = []

    def __call__(self) -> AnyPull:
        if len(self.out) == len(self.raw):
            return _Succeed(tuple(self.out))
        return self.decode_one(self.raw[len(self.out)]).flat_map(self.added)

    def added(self, value: object) -> AnyPull:
        self.out.append(value)
        return _Suspend(self)


def duplex[TI, TO, OE, OD, IE, ID, R, RD, RE](
    channel: Channel[tuple[bytes, ...], OE, OD, tuple[bytes, ...], SchemaError | IE, ID, R],
    /,
    *,
    input_schema: Codec[TI, Any, object, RE],
    output_schema: Codec[TO, Any, RD, object],
    fingerprint: bool = False,
    max_frame_size: int | None = None,
    **options: Unpack[ParseOptions],
) -> Channel[tuple[TO, ...], SchemaError | OE, OD, tuple[TI, ...], IE, ID, R | RD | RE]:
    """``channel``, a channel of binary frames, reading values that
    ``input_schema`` encodes and writing what ``output_schema`` decodes."""
    require_channel(channel, "channel")
    outgoing: Channel[Any, Any, Any, Any, Any, Any, Any] = encode(
        input_schema, fingerprint=fingerprint, **options
    )
    incoming: Channel[Any, Any, Any, Any, Any, Any, Any] = decode(
        output_schema, fingerprint=fingerprint, max_frame_size=max_frame_size, **options
    )
    wired: Any = outgoing.pipe_to(channel).pipe_to(incoming)
    return wired
