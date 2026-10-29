"""How RPC messages are written (Effect's ``RpcSerialization``).

A serialization gives a ``Parser`` per connection: ``decode`` turns the
bytes or text received into messages, ``encode`` turns a message (or a
list of them) into what to send, ``None`` for nothing. ``codec_for`` gives
the codec of the values inside messages (payloads, chunks, exits).

- ``json``: one JSON value per frame (a batch is an array);
- ``ndjson`` / ``make_ndjson``: one JSON value per line, frames of any size;
- ``json_rpc`` / ``nd_json_rpc``: JSON-RPC 2.0, unframed or per line.

Effect's ``SchemaBinary`` serialization is not ported yet.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol, cast

from pyfect import schema as S
from pyfect._js import text_decoder, text_encode
from pyfect._json_text import parse, stringify
from pyfect.context import Tag
from pyfect.errors import TaggedError
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.rpc._json_rpc import Batches, decode_json_rpc, encode_json_rpc

type CodecFor = Callable[[S.Top], S.Codec[Any, Any, Any, Any]]
"""The codec of a value schema in the messages: ``S.to_codec_json`` for
the text serializations."""

type Frame = bytes | str


class Parser(Protocol):
    """A connection's reader and writer of messages."""

    def decode(self, data: Frame, /) -> list[object]: ...
    def encode(self, response: object, /) -> Frame | None: ...


@dataclass(frozen=True, slots=True)
class RpcSerializationService:
    """A serialization: ``make_unsafe`` makes a parser per connection;
    ``content_type`` is its HTTP content type; ``includes_framing`` says
    whether a frame can hold part of a message (so a stream can be split
    anywhere); ``codec_for`` gives the codecs of the values inside
    messages."""

    make_unsafe: Callable[[], Parser]
    content_type: str
    includes_framing: bool
    codec_for: CodecFor


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
    __slots__ = ("_batches",)

    def __init__(self) -> None:
        self._batches: Batches = {}

    def decode(self, data: Frame, /) -> list[object]:
        return decode_json_rpc(parse(_text(data)), self._batches)

    def encode(self, response: object, /) -> Frame | None:
        encoded = encode_json_rpc(response, self._batches)
        return None if encoded is None else stringify(encoded)


def json_rpc(*, content_type: str = "application/json") -> RpcSerializationService:
    """JSON-RPC 2.0, one JSON value per frame: a request batch (an array)
    is answered with one array once each of its requests is done."""
    return RpcSerializationService(
        make_unsafe=_JsonRpcParser,
        content_type=content_type,
        includes_framing=False,
        codec_for=_codec_for_json,
    )


class _NdJsonRpcParser:
    __slots__ = ("_batches", "_parser")

    def __init__(self, max_buffer_size: MaxBufferSize) -> None:
        self._parser = _NdjsonParser(max_buffer_size)
        self._batches: Batches = {}

    def decode(self, data: Frame, /) -> list[object]:
        frames = self._parser.decode(data)
        messages: list[object] = []
        for frame in frames:
            messages.extend(decode_json_rpc(frame, self._batches))
        return messages

    def encode(self, response: object, /) -> Frame | None:
        encoded = encode_json_rpc(response, self._batches)
        return None if encoded is None else self._parser.encode(encoded)


def nd_json_rpc(
    *,
    content_type: str = "application/json-rpc",
    max_buffer_size: MaxBufferSize = DEFAULT_MAX_BUFFER_SIZE,
) -> RpcSerializationService:
    """JSON-RPC 2.0, one JSON value per line."""
    return RpcSerializationService(
        make_unsafe=lambda: _NdJsonRpcParser(max_buffer_size),
        content_type=content_type,
        includes_framing=True,
        codec_for=_codec_for_json,
    )


def with_codec_for(
    service: RpcSerializationService, codec_for: CodecFor
) -> RpcSerializationService:
    """``service`` with other value codecs."""
    return replace(service, codec_for=codec_for)


layer_json: Layer[RpcSerialization] = layer_succeed(RpcSerialization, json)
layer_ndjson: Layer[RpcSerialization] = layer_succeed(RpcSerialization, ndjson)


def layer_ndjson_with(
    *, max_buffer_size: MaxBufferSize = DEFAULT_MAX_BUFFER_SIZE
) -> Layer[RpcSerialization]:
    return layer_succeed(RpcSerialization, make_ndjson(max_buffer_size=max_buffer_size))


def layer_json_rpc(*, content_type: str = "application/json") -> Layer[RpcSerialization]:
    return layer_succeed(RpcSerialization, json_rpc(content_type=content_type))


def layer_nd_json_rpc(
    *,
    content_type: str = "application/json-rpc",
    max_buffer_size: MaxBufferSize = DEFAULT_MAX_BUFFER_SIZE,
) -> Layer[RpcSerialization]:
    return layer_succeed(
        RpcSerialization, nd_json_rpc(content_type=content_type, max_buffer_size=max_buffer_size)
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
    "make_ndjson",
    "nd_json_rpc",
    "ndjson",
    "with_codec_for",
]
