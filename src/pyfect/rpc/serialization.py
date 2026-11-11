"""How RPC messages are written (Effect's ``RpcSerialization``).

A serialization gives a ``Parser`` per connection: ``decode`` turns the
bytes or text received into messages, ``encode`` turns a message (or a
list of them) into what to send, ``None`` for nothing. ``codec_for`` gives
the codec of the values inside messages (payloads, chunks, exits).

- ``json``: one JSON value per frame (a batch is an array);
- ``ndjson`` / ``make_ndjson``: one JSON value per line, frames of any size;
- ``json_rpc`` / ``nd_json_rpc``: JSON-RPC 2.0, unframed or per line;
- ``make_schema_binary``: ``encoding.schema_binary`` frames. Envelopes are in
  fingerprint mode, values in the schema-evolving default mode.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol, Self, cast

from pyfect import schema as S
from pyfect._js import text_decoder, text_encode
from pyfect._json_text import parse, stringify
from pyfect._service_copy import replaced
from pyfect.context import Tag
from pyfect.encoding import schema_binary
from pyfect.errors import TaggedError
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.rpc._encoded_schema import EncodedSchema
from pyfect.rpc._json_rpc import Batches, decode_json_rpc, encode_json_rpc

type CodecFor = Callable[[S.Top], S.Codec[Any, Any, Any, Any]]
"""The codec of a value schema in the messages: ``S.to_codec_json`` for
the text serializations."""

type Frame = bytes | str


class Parser(Protocol):
    """A connection's reader and writer of messages."""

    def decode(self, data: Frame, /) -> list[object]: ...
    def encode(self, response: object, /) -> Frame | None: ...


class RpcSerializationService:
    """A wire format of RPC messages (Effect's ``RpcSerialization``):
    ``make_unsafe`` makes a parser per connection and ``codec_for`` the
    codecs of the values inside messages."""

    __slots__ = ("_codec_for", "_make_unsafe", "content_type", "includes_framing")

    content_type: str
    """The HTTP content type of the frames."""
    includes_framing: bool
    """Whether a frame can hold part of a message (so a stream can be
    split anywhere)."""

    def __replace__(self, **changes: Any) -> Self:
        """A copy with ``changes`` to the constructor's arguments (``copy.replace``)."""
        return replaced(self, changes)

    def __init__(
        self,
        make_unsafe: Callable[[], Parser],
        content_type: str,
        includes_framing: bool,
        codec_for: CodecFor,
    ) -> None:
        self._make_unsafe = make_unsafe
        self.content_type = content_type
        self.includes_framing = includes_framing
        self._codec_for = codec_for

    def make_unsafe(self) -> Parser:
        """A new parser, holding the state of one connection (a partly
        received frame, say). Its ``decode`` raises on malformed data, or
        ``MaxBufferSizeExceeded`` when a framed format holds more than its
        buffer limit of an unfinished message."""
        return self._make_unsafe()

    @property
    def codec_for(self) -> CodecFor:
        """``codec_for(schema)``: the codec of ``schema``'s values inside
        messages (``S.to_codec_json`` for the text formats). The same
        function for every serialization sharing it, since encode caches
        compare it by identity."""
        return self._codec_for


class RpcSerialization(Tag[RpcSerializationService], key="effect/rpc/RpcSerialization"):
    """The serialization of a client's or server's protocol."""


@dataclass(eq=False)
class MaxBufferSizeExceeded(TaggedError):
    """An ndjson frame grew past ``max_buffer_size`` characters."""

    max_buffer_size: int

    @property
    def message(self) -> str:
        return f"RPC serialization buffer exceeded the maximum size of {self.max_buffer_size}"


@dataclass(eq=False)
class NdjsonDecodeError(TaggedError):
    """A line of an ndjson stream is not JSON."""

    cause: object


type MaxBufferSize = int | Literal["unbounded"]

DEFAULT_MAX_BUFFER_SIZE = 16 * 1024 * 1024


def _codec_for_json(schema: S.Top) -> S.Codec[Any, Any, Any, Any]:
    return S.to_codec_json(schema)


def _text(data: Frame) -> str:
    return data if isinstance(data, str) else data.decode("utf-8", "replace")


class _JsonParser:
    __slots__ = ()

    def decode(self, data: Frame, /) -> list[object]:
        decoded = parse(_text(data))
        return list(decoded) if isinstance(decoded, list) else [decoded]

    def encode(self, response: object, /) -> Frame | None:
        return stringify(response)


json = RpcSerializationService(
    make_unsafe=_JsonParser,
    content_type="application/json",
    includes_framing=False,
    codec_for=_codec_for_json,
)
"""One JSON value per frame; a list of messages is one array."""


class _NdjsonParser:
    __slots__ = ("_buffer", "_decoder", "_max")

    def __init__(self, max_buffer_size: MaxBufferSize) -> None:
        self._max = max_buffer_size
        self._buffer = ""
        self._decoder = text_decoder()

    def _exceeded(self, size: int) -> bool:
        return isinstance(self._max, int) and size > self._max

    def _fail_max(self) -> MaxBufferSizeExceeded:
        self._buffer = ""
        return MaxBufferSizeExceeded(cast("int", self._max))

    def decode(self, data: Frame, /) -> list[object]:
        self._buffer += data if isinstance(data, str) else self._decoder.decode(data)
        buffer = self._buffer
        position = 0
        items: list[object] = []
        newline = buffer.find("\n", position)
        while newline != -1:
            if self._exceeded(newline - position):
                raise self._fail_max()
            end = newline - 1 if newline > 0 and buffer[newline - 1] == "\r" else newline
            line = buffer[position:end] if end >= position else ""
            position = newline + 1
            if line:
                try:
                    items.append(parse(line))
                except ValueError as cause:
                    self._buffer = ""
                    raise NdjsonDecodeError(cause) from cause
            newline = buffer.find("\n", position)
        self._buffer = buffer[position:]
        if self._exceeded(len(self._buffer)):
            raise self._fail_max()
        return items

    def encode(self, response: object, /) -> Frame | None:
        if isinstance(response, list):
            messages = cast("list[object]", response)
            if not messages:
                return None
            return "".join(stringify(message) + "\n" for message in messages)
        return stringify(response) + "\n"


def make_ndjson(
    *, max_buffer_size: MaxBufferSize = DEFAULT_MAX_BUFFER_SIZE
) -> RpcSerializationService:
    """One JSON value per line. A line longer than ``max_buffer_size``
    characters (16 MiB by default; ``"unbounded"`` for no limit) fails the
    decode with ``MaxBufferSizeExceeded``; a line that is not JSON with
    ``NdjsonDecodeError``. Blank lines are skipped."""
    return RpcSerializationService(
        make_unsafe=lambda: _NdjsonParser(max_buffer_size),
        content_type="application/x-ndjson",
        includes_framing=True,
        codec_for=_codec_for_json,
    )


ndjson = make_ndjson()


class _JsonRpcParser:
    __slots__ = ("_batches", "_control_messages")

    def __init__(self, control_messages: bool) -> None:
        self._batches: Batches = {}
        self._control_messages = control_messages

    def decode(self, data: Frame, /) -> list[object]:
        return decode_json_rpc(
            parse(_text(data)), self._batches, control_messages=self._control_messages
        )

    def encode(self, response: object, /) -> Frame | None:
        encoded = encode_json_rpc(response, self._batches)
        return None if encoded is None else stringify(encoded)


def json_rpc(
    *, content_type: str = "application/json", control_messages: bool = True
) -> RpcSerializationService:
    """JSON-RPC 2.0, one JSON value per frame: a request batch (an array)
    is answered with one array once each of its requests is done. Set
    ``control_messages=False`` for plain JSON-RPC peers, so ``@effect/rpc/*``
    methods are not read as RPC control messages."""
    return RpcSerializationService(
        make_unsafe=lambda: _JsonRpcParser(control_messages),
        content_type=content_type,
        includes_framing=False,
        codec_for=_codec_for_json,
    )


class _NdJsonRpcParser:
    __slots__ = ("_batches", "_control_messages", "_parser")

    def __init__(self, max_buffer_size: MaxBufferSize, control_messages: bool) -> None:
        self._parser = _NdjsonParser(max_buffer_size)
        self._batches: Batches = {}
        self._control_messages = control_messages

    def decode(self, data: Frame, /) -> list[object]:
        frames = self._parser.decode(data)
        messages: list[object] = []
        for frame in frames:
            messages.extend(
                decode_json_rpc(frame, self._batches, control_messages=self._control_messages)
            )
        return messages

    def encode(self, response: object, /) -> Frame | None:
        encoded = encode_json_rpc(response, self._batches)
        return None if encoded is None else self._parser.encode(encoded)


def nd_json_rpc(
    *,
    content_type: str = "application/json-rpc",
    max_buffer_size: MaxBufferSize = DEFAULT_MAX_BUFFER_SIZE,
    control_messages: bool = True,
) -> RpcSerializationService:
    """JSON-RPC 2.0, one JSON value per line (``control_messages`` as in
    ``json_rpc``)."""
    return RpcSerializationService(
        make_unsafe=lambda: _NdJsonRpcParser(max_buffer_size, control_messages),
        content_type=content_type,
        includes_framing=True,
        codec_for=_codec_for_json,
    )


_SCHEMA_BINARY_MAX_FRAME_SIZE = 16 * 1024 * 1024
"""Effect's default ``max_frame_size`` for ``make_schema_binary``."""

type MaxFrameSize = int | Literal["unbounded"]


def _schema_binary_parser(max_frame_size: int | None) -> Parser:
    reader = schema_binary.parser(EncodedSchema, fingerprint=True, max_frame_size=max_frame_size)
    writer = schema_binary.encoder(EncodedSchema, fingerprint=True)

    class _SchemaBinaryParser:
        def decode(self, data: Frame, /) -> list[object]:
            return reader.feed_sync(text_encode(data) if isinstance(data, str) else data)

        def encode(self, response: object, /) -> Frame | None:
            if not isinstance(response, list):
                return writer.encode(response)
            messages = cast("list[object]", response)
            return writer.encode_many(messages) if messages else None

    return _SchemaBinaryParser()


def make_schema_binary(
    *,
    max_frame_size: MaxFrameSize = _SCHEMA_BINARY_MAX_FRAME_SIZE,
    fingerprint_payloads: bool = False,
) -> RpcSerializationService:
    """``encoding.schema_binary`` over RPC, with Effect's wire format.
    ``max_frame_size`` limits a frame a parser buffers. Values are written in
    the default mode, whose schemas can evolve compatibly; with
    ``fingerprint_payloads`` they also carry their layout hash, and a peer with
    a different layout fails."""
    limit = None if max_frame_size == "unbounded" else max_frame_size

    def codec_for(schema: S.Top) -> S.Codec[Any, Any, Any, Any]:
        return schema_binary.to_codec_direct(
            cast("S.Codec[Any, Any, Any, Any]", schema), fingerprint=fingerprint_payloads
        )

    return RpcSerializationService(
        make_unsafe=lambda: _schema_binary_parser(limit),
        content_type="application/vnd.effect.rpc+schema-binary",
        includes_framing=True,
        codec_for=codec_for,
    )


def with_codec_for(
    service: RpcSerializationService, codec_for: CodecFor
) -> RpcSerializationService:
    """``service`` with other value codecs."""
    return RpcSerializationService(
        service.make_unsafe, service.content_type, service.includes_framing, codec_for
    )


layer_json: Layer[RpcSerialization] = layer_succeed(RpcSerialization, json)
"""``RpcSerialization`` as JSON (``json``)."""
layer_ndjson: Layer[RpcSerialization] = layer_succeed(RpcSerialization, ndjson)
"""``RpcSerialization`` as newline-delimited JSON (``ndjson``)."""


def layer_ndjson_with(
    *, max_buffer_size: MaxBufferSize = DEFAULT_MAX_BUFFER_SIZE
) -> Layer[RpcSerialization]:
    return layer_succeed(RpcSerialization, make_ndjson(max_buffer_size=max_buffer_size))


def layer_schema_binary(
    *,
    max_frame_size: MaxFrameSize = _SCHEMA_BINARY_MAX_FRAME_SIZE,
    fingerprint_payloads: bool = False,
) -> Layer[RpcSerialization]:
    return layer_succeed(
        RpcSerialization,
        make_schema_binary(
            max_frame_size=max_frame_size, fingerprint_payloads=fingerprint_payloads
        ),
    )


def layer_json_rpc(
    *, content_type: str = "application/json", control_messages: bool = True
) -> Layer[RpcSerialization]:
    return layer_succeed(
        RpcSerialization, json_rpc(content_type=content_type, control_messages=control_messages)
    )


def layer_nd_json_rpc(
    *,
    content_type: str = "application/json-rpc",
    max_buffer_size: MaxBufferSize = DEFAULT_MAX_BUFFER_SIZE,
    control_messages: bool = True,
) -> Layer[RpcSerialization]:
    return layer_succeed(
        RpcSerialization,
        nd_json_rpc(
            content_type=content_type,
            max_buffer_size=max_buffer_size,
            control_messages=control_messages,
        ),
    )


def is_binary(service: RpcSerializationService) -> bool:
    """Whether the serialization writes bytes rather than text."""
    return "json" not in service.content_type


def encode_text(frame: Frame) -> bytes:
    return frame if isinstance(frame, bytes) else text_encode(frame)


__all__ = [
    "DEFAULT_MAX_BUFFER_SIZE",
    "CodecFor",
    "Frame",
    "MaxBufferSize",
    "MaxBufferSizeExceeded",
    "MaxFrameSize",
    "NdjsonDecodeError",
    "Parser",
    "RpcSerialization",
    "RpcSerializationService",
    "encode_text",
    "is_binary",
    "json",
    "json_rpc",
    "layer_json",
    "layer_json_rpc",
    "layer_nd_json_rpc",
    "layer_ndjson",
    "layer_ndjson_with",
    "layer_schema_binary",
    "make_ndjson",
    "make_schema_binary",
    "nd_json_rpc",
    "ndjson",
    "with_codec_for",
]
