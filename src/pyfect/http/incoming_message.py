"""What incoming messages (responses here) share, and the schema decoders
of their bodies and headers (Effect's ``HttpIncomingMessage``)."""

from __future__ import annotations

from collections.abc import Callable
from typing import Protocol, Unpack

from pyfect._json_text import Json
from pyfect.byte_size import ByteSize
from pyfect.context import Reference
from pyfect.effect import Effect
from pyfect.http.headers import Headers
from pyfect.http.url_params import UrlParams
from pyfect.schema import (
    Codec,
    SchemaError,
    Unknown,
    decode_effect,
    decode_unknown_effect,
    from_json_string,
    to_codec_json,
)
from pyfect.schema._options import ParseOptions
from pyfect.stream import Stream

type Reviver = Callable[[str, object], object]
"""``JSON.parse``'s reviver: called with each key (``""`` for the root) and
its parsed value, children first; what it returns replaces the value."""


class HttpIncomingMessage[E](Protocol):
    @property
    def headers(self) -> Headers: ...
    @property
    def remote_address(self) -> str | None: ...
    @property
    def json(self) -> Effect[Json, E]: ...
    @property
    def text(self) -> Effect[str, E]: ...
    @property
    def url_params_body(self) -> Effect[UrlParams, E]: ...
    @property
    def bytes_(self) -> Effect[bytes, E]: ...
    @property
    def stream(self) -> Stream[bytes, E]: ...


class MaxBodySize(Reference[ByteSize | None]):
    """The most bytes a body read takes (``None``: no limit); a larger body
    fails as ``BodyTooLarge``."""

    @classmethod
    def default(cls) -> ByteSize | None:
        return None


class MessageDecoder[T, RD](Protocol):
    """Decodes a message, failing with the message's error or a
    ``SchemaError``."""

    def __call__[E](self, message: HttpIncomingMessage[E], /) -> Effect[T, E | SchemaError, RD]: ...


def revive(value: object, reviver: Reviver) -> object:
    """``value`` (parsed JSON) walked as ``JSON.parse`` walks it with
    ``reviver``."""

    def walk(key: str, node: object) -> object:
        if isinstance(node, list):
            items: list[object] = node  # pyright: ignore[reportUnknownVariableType]
            node = [walk(str(i), item) for i, item in enumerate(items)]
        elif isinstance(node, dict):
            entries: dict[str, object] = node  # pyright: ignore[reportUnknownVariableType]
            node = {k: walk(k, v) for k, v in entries.items()}
        return reviver(key, node)

    return walk("", value)


_parse_json = decode_effect(from_json_string(Unknown))


def schema_body_json[T, RD](
    schema: Codec[T, object, RD, object],
    *,
    reviver: Reviver | None = None,
    **options: Unpack[ParseOptions],
) -> MessageDecoder[T, RD]:
    """A decoder of a message's JSON body by ``schema``. With a ``reviver``
    the text is parsed with it; an empty body is ``None`` either way."""
    decode = decode_unknown_effect(to_codec_json(schema), **options)

    def run[E](message: HttpIncomingMessage[E]) -> Effect[T, E | SchemaError, RD]:
        if reviver is None:
            return message.json.flat_map(decode)
        revive_with = reviver

        def from_text(body: str) -> Effect[T, E | SchemaError, RD]:
            if body == "":
                return message.json.flat_map(decode)
            return _parse_json(body).flat_map(lambda parsed: decode(revive(parsed, revive_with)))

        return message.text.flat_map(from_text)

    return run


def schema_body_url_params[T, RD](
    schema: Codec[T, object, RD, object], **options: Unpack[ParseOptions]
) -> MessageDecoder[T, RD]:
    """A decoder of a form-encoded body: ``schema`` gets each name mapped
    to its value, or to its values when repeated."""
    decode = decode_unknown_effect(schema, **options)

    def run[E](message: HttpIncomingMessage[E]) -> Effect[T, E | SchemaError, RD]:
        return message.url_params_body.flat_map(lambda params: decode(params.to_record()))

    return run


def schema_headers[T, RD](
    schema: Codec[T, object, RD, object], **options: Unpack[ParseOptions]
) -> Callable[[HttpIncomingMessage[object]], Effect[T, SchemaError, RD]]:
    """A decoder of a message's headers (lowercased names) by ``schema``."""
    decode = decode_unknown_effect(schema, **options)
    return lambda message: decode(dict(message.headers))


__all__ = [
    "HttpIncomingMessage",
    "MaxBodySize",
    "MessageDecoder",
    "Reviver",
    "revive",
    "schema_body_json",
    "schema_body_url_params",
    "schema_headers",
]
