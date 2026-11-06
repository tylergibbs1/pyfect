"""SchemaBinary as channels between chunks of values and chunks of frames."""

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false, reportUnknownMemberType=false
from __future__ import annotations

from collections.abc import Sequence
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
from pyfect.encoding.schema_binary._parser import make_parser
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
            out: list[object] = []

            def step() -> AnyPull:
                if len(out) == len(raw):
                    return _Succeed(tuple(out))

                def added(value: object) -> AnyPull:
                    out.append(value)
                    return _Suspend(step)

                return decode_one(raw[len(out)]).flat_map(added)

            def caught(cause: Cause[Any]) -> AnyPull:
                found = cause.find_recoverable_error()
                if out and isinstance(found, Fail) and isinstance(found.error, SchemaError):
                    stashed.append(found.error)
                    return _Succeed(tuple(out))
                return _FailCause(cause)

            return _Suspend(step).catch_cause(caught)

        def feed(chunk: tuple[bytes, ...]) -> AnyPull:
            raw: list[object] = []
            try:
                for part in chunk:
                    raw.extend(frames.feed_sync(part))
            except SchemaError as error:
                if not raw:
                    return _FailCause(fail_cause(error))
                stashed.append(error)
            if not raw:
                return pull
            return _Succeed(tuple(raw)) if decode_target is None else decode_all(raw)

        def done(leftover: object) -> AnyPull:
            try:
                frames.end_sync()
            except SchemaError as error:
                return _FailCause(fail_cause(error))
            return end_with(leftover)

        def failed(cause: Cause[Any]) -> AnyPull:
            return _FailCause(cause)

        def next_pull() -> AnyPull:
            if stashed:
                return _FailCause(fail_cause(stashed[0]))
            return match_effect(upstream, on_success=feed, on_failure=failed, on_done=done)

        pull: AnyPull = _Suspend(next_pull)
        return _Succeed(pull)

    channel: Any = from_transform(transform)
    return channel


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
