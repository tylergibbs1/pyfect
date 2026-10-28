"""Channels that decode or encode each chunk with a schema (Effect's
``ChannelSchema``).

``decode(schema)`` reads chunks of encoded values and writes the decoded
ones; ``encode(schema)`` goes the other way. A value that does not fit fails
the channel with ``SchemaError`` (its path starts at the value's index in
the chunk). ``duplex`` wraps a channel of encoded values so it reads and
writes decoded ones::

    from pyfect import channel_schema
    from pyfect import schema as S

    numbers = text_stream.pipe_through_channel(channel_schema.decode(S.NumberFromString))
"""

from __future__ import annotations

from typing import Any, Never, Unpack, cast, overload

from pyfect._core import Effect
from pyfect.channel import Channel, from_transform
from pyfect.channel._base import require_channel
from pyfect.effect import succeed
from pyfect.schema import Codec, NonEmptyArray, ParseOptions, SchemaError
from pyfect.schema import decode_effect as decode_with
from pyfect.schema import encode_effect as encode_with

__all__ = ["decode", "decode_unknown", "duplex", "duplex_unknown", "encode", "encode_unknown"]


def _chunks(parse: Any) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
    def transform(upstream: Effect[Any, Any], _scope: object) -> Effect[Any]:
        return succeed(upstream.flat_map(parse))

    return cast("Channel[Any, Any, Any, Any, Any, Any, Any]", from_transform(transform))


def decode[T, I, RD, E = Never, D = None](
    schema: Codec[T, I, RD, object], /, **options: Unpack[ParseOptions]
) -> Channel[tuple[T, ...], E | SchemaError, D, tuple[I, ...], E, D, RD]:
    """Decode each chunk of ``schema``'s encoded values, failing with
    ``SchemaError`` at the first chunk that does not decode."""
    return _chunks(decode_with(NonEmptyArray(schema), **options))


def decode_unknown[T, RD, E = Never, D = None](
    schema: Codec[T, object, RD, object], /, **options: Unpack[ParseOptions]
) -> Channel[tuple[T, ...], E | SchemaError, D, tuple[object, ...], E, D, RD]:
    """``decode`` reading chunks of any values."""
    return _chunks(decode_with(NonEmptyArray(schema), **options))


def encode[T, I, RE, E = Never, D = None](
    schema: Codec[T, I, object, RE], /, **options: Unpack[ParseOptions]
) -> Channel[tuple[I, ...], E | SchemaError, D, tuple[T, ...], E, D, RE]:
    """Encode each chunk of ``schema``'s values, failing with
    ``SchemaError`` at the first chunk that does not encode."""
    return _chunks(encode_with(NonEmptyArray(schema), **options))


def encode_unknown[I, RE, E = Never, D = None](
    schema: Codec[object, I, object, RE], /, **options: Unpack[ParseOptions]
) -> Channel[tuple[I, ...], E | SchemaError, D, tuple[object, ...], E, D, RE]:
    """``encode`` reading chunks of any values."""
    return _chunks(encode_with(NonEmptyArray(schema), **options))


# Pyright cannot solve ``IE`` from ``IE | SchemaError`` when the wrapped channel
# reads exactly ``SchemaError``, so that case has an overload of its own.


@overload
def duplex[TI, II, TO, IO, OE, OD, ID, RR, IE = Never](
    channel: Channel[tuple[IO, ...], OE, OD, tuple[II, ...], IE | SchemaError, ID, RR],
    /,
    *,
    input_schema: Codec[TI, II, object, RR],
    output_schema: Codec[TO, IO, RR, object],
) -> Channel[tuple[TO, ...], OE | SchemaError, OD, tuple[TI, ...], IE, ID, RR]: ...
@overload
def duplex[TI, II, TO, IO, OE, OD, ID, RR](
    channel: Channel[tuple[IO, ...], OE, OD, tuple[II, ...], SchemaError, ID, RR],
    /,
    *,
    input_schema: Codec[TI, II, object, RR],
    output_schema: Codec[TO, IO, RR, object],
) -> Channel[tuple[TO, ...], OE | SchemaError, OD, tuple[TI, ...], Never, ID, RR]: ...
def duplex(
    channel: Channel[Any, Any, Any, Any, Any, Any, Any],
    /,
    *,
    input_schema: Codec[Any, Any, Any, Any],
    output_schema: Codec[Any, Any, Any, Any],
) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
    """``channel``, a channel of encoded values, reading values that
    ``input_schema`` encodes for it and writing what ``output_schema``
    decodes from its output."""
    require_channel(channel, "channel")
    outgoing: Channel[Any, Any, Any, Any, Any, Any, Any] = encode(input_schema)
    incoming: Channel[Any, Any, Any, Any, Any, Any, Any] = decode(output_schema)
    return outgoing.pipe_to(channel).pipe_to(incoming)


@overload
def duplex_unknown[TI, TO, OE, OD, ID, RR, IE = Never](
    channel: Channel[tuple[object, ...], OE, OD, tuple[Any, ...], IE | SchemaError, ID, RR],
    /,
    *,
    input_schema: Codec[TI, object, object, RR],
    output_schema: Codec[TO, object, RR, object],
) -> Channel[tuple[TO, ...], OE | SchemaError, OD, tuple[TI, ...], IE, ID, RR]: ...
@overload
def duplex_unknown[TI, TO, OE, OD, ID, RR](
    channel: Channel[tuple[object, ...], OE, OD, tuple[Any, ...], SchemaError, ID, RR],
    /,
    *,
    input_schema: Codec[TI, object, object, RR],
    output_schema: Codec[TO, object, RR, object],
) -> Channel[tuple[TO, ...], OE | SchemaError, OD, tuple[TI, ...], Never, ID, RR]: ...
def duplex_unknown(
    channel: Channel[Any, Any, Any, Any, Any, Any, Any],
    /,
    *,
    input_schema: Codec[Any, Any, Any, Any],
    output_schema: Codec[Any, Any, Any, Any],
) -> Channel[Any, Any, Any, Any, Any, Any, Any]:
    """``duplex`` for a channel that writes values of any type."""
    require_channel(channel, "channel")
    outgoing: Channel[Any, Any, Any, Any, Any, Any, Any] = encode(input_schema)
    incoming: Channel[Any, Any, Any, Any, Any, Any, Any] = decode_unknown(output_schema)
    return outgoing.pipe_to(channel).pipe_to(incoming)
