"""Reading a request's payload by its content type (Effect's
``HttpApiBuilder`` payload decoders): JSON, a form, text, bytes,
multipart, or a stream handed to the handler unread."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, cast

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._json_text import PARSE_ERRORS, parse
from pyfect.effect import context, fail, provide_context, succeed
from pyfect.encoding import ndjson
from pyfect.http.method import has_body
from pyfect.http.multipart import Limits, limits_context
from pyfect.http.server_request import ServerRequest
from pyfect.http.server_response import HttpServerResponse, empty
from pyfect.http.server_response import text as text_response
from pyfect.http_api import _media_type as media_type
from pyfect.http_api import schema as api_schema
from pyfect.http_api.endpoint import BufferedPayload, PayloadMap
from pyfect.http_api.error import HttpApiPayloadTooLarge, HttpApiSchemaError
from pyfect.schema import ParseOptions, SchemaError
from pyfect.schema import ast as A
from pyfect.schema import issue as I
from pyfect.stream import Stream
from pyfect.stream import provide_context as stream_provide_context
from pyfect.stream import suspend as stream_suspend

type Decode = Callable[[object], Effect[Any, SchemaError, Any]]


@dataclass(frozen=True, slots=True)
class _Buffered:
    tag: Literal["Json", "FormUrlEncoded", "Uint8Array", "Text"]
    decode: Decode
    null_on_empty: bool


@dataclass(frozen=True, slots=True)
class _Multipart:
    mode: Literal["buffered", "stream"]
    limits: Limits | None
    decode: Decode


@dataclass(frozen=True, slots=True)
class _Stream:
    max_bytes: int | None
    decode: Callable[[ServerRequest], Stream[Any, Any, Any]]


type PayloadDecoder = _Buffered | _Multipart | _Stream
type PayloadDecoders = Mapping[str, PayloadDecoder]


def payload_decoders(payload: PayloadMap, options: ParseOptions) -> PayloadDecoders:
    """A decoder for each payload content type."""
    result: dict[str, PayloadDecoder] = {}
    for content_type, entry in payload.items():
        if not isinstance(entry, BufferedPayload):
            max_bytes = entry.schema.max_bytes
            result[content_type] = _Stream(max_bytes, _stream_decoder(entry.schema, options))
            continue
        schemas = entry.schemas
        schema = schemas[0] if len(schemas) == 1 else S.Union(*schemas)
        encoding = entry.encoding
        if isinstance(encoding, api_schema.MultipartEncoding):
            decode = S.decode_unknown_effect(schema, **options)
            result[content_type] = _Multipart(encoding.mode, encoding.limits, decode)
            continue
        if encoding.tag == "FormUrlEncoded":
            schema = S.to_codec_array_from_single(schema)
        result[content_type] = _Buffered(
            encoding.tag,
            S.decode_unknown_effect(schema, **options),
            any(isinstance(A.to_encoded(s.__codec__().ast), A.Null) for s in schemas),
        )
    return result


_PAYLOAD_TOO_LARGE = empty(status=413, headers={"connection": "close"})


def decode_payload(
    decoders: PayloadDecoders, request: ServerRequest, query: Mapping[str, object]
) -> Effect[Any, SchemaError, Any]:
    """The payload, or the response refusing the request."""
    body = has_body(request.method)
    declared = request.headers.get("content-type")
    content_type = (
        media_type.normalize(declared or "application/json")
        if body
        else "application/x-www-form-urlencoded"
    )
    decoder = decoders.get(content_type)
    if decoder is None:
        return succeed(_unsupported(content_type))
    if body and not declared:
        return _undeclared(decoder, request, query)
    match decoder:
        case _Stream():
            length = _content_length(request)
            if decoder.max_bytes is not None and length is not None and length > decoder.max_bytes:
                return succeed(_PAYLOAD_TOO_LARGE)
            # The stream can be read after the handler returns, inside a
            # streaming response, so it carries the services with it.
            stream_decode = decoder.decode
            return context().map(
                lambda services: stream_decode(request).pipe(stream_provide_context(services))
            )
        case _Multipart():
            return _multipart(decoder, request)
        case _Buffered():
            return _buffered(decoder, request, query, body)


def _undeclared(
    decoder: PayloadDecoder, request: ServerRequest, query: Mapping[str, object]
) -> Effect[Any, SchemaError, Any]:
    """A body with no content-type. Effect decodes it as JSON; pyfect takes
    only an empty one, as a cross-site "simple" request may carry a body
    without a content-type and must not reach a JSON endpoint."""
    unsupported = _unsupported("")
    if not isinstance(decoder, _Buffered):
        return succeed(unsupported)
    return request.text.or_die().flat_map(
        lambda text: (
            _buffered(decoder, request, query, True) if text == "" else succeed(unsupported)
        )
    )


def _unsupported(content_type: str) -> HttpServerResponse:
    return text_response(f"Unsupported content-type: {content_type}", status=415)


def _content_length(request: ServerRequest) -> int | None:
    value = request.headers.get("content-length")
    try:
        return None if value is None else int(value)
    except ValueError:
        return None


def _multipart(decoder: _Multipart, request: ServerRequest) -> Effect[Any, SchemaError, Any]:
    limits = decoder.limits
    if decoder.mode == "buffered":
        read: Effect[Any, Any, Any] = request.multipart.or_die()
        if limits:
            read = read.pipe(provide_context(limits_context(**limits)))
        return read.flat_map(decoder.decode)
    parts = request.multipart_stream
    if limits:
        parts = parts.pipe(stream_provide_context(limits_context(**limits)))
    return succeed(parts)


_INVALID_JSON = SchemaError(I.InvalidValue({"message": "Expected a valid JSON body"}))


def _buffered(
    decoder: _Buffered, request: ServerRequest, query: Mapping[str, object], body: bool
) -> Effect[Any, SchemaError, Any]:
    decode = decoder.decode
    match decoder.tag:
        case "Json":

            def json(text: str) -> Effect[Any, SchemaError, Any]:
                if text == "":
                    return decode(None)
                try:
                    value = parse(text)
                except PARSE_ERRORS:
                    return fail(_INVALID_JSON)
                return decode(value)

            return request.text.or_die().flat_map(json)
        case "Text":
            return request.text.or_die().flat_map(decode)
        case "FormUrlEncoded":
            source: Effect[Mapping[str, object], Any, Any] = (
                request.url_params_body.or_die().map(lambda params: params.to_record())
                if body
                else succeed(query)
            )
            return source.flat_map(decode)
        case "Uint8Array":
            return request.bytes_.or_die().flat_map(decode)


# --- streams -------------------------------------------------------------------------


def _stream_decoder(
    schema: api_schema.StreamUint8ArraySchema | api_schema.StreamNdjsonSchema[Any],
    options: ParseOptions,
) -> Callable[[ServerRequest], Stream[Any, Any, Any]]:
    """The handler pulls the body itself, so nothing is read ahead of it;
    a failure to read the body stays a defect, as for buffered payloads."""
    max_bytes = schema.max_bytes

    def read_body(request: ServerRequest) -> Stream[bytes, Any, Any]:
        stream = request.stream.or_die()
        return stream if max_bytes is None else _limit_bytes(stream, max_bytes)

    if isinstance(schema, api_schema.StreamUint8ArraySchema):
        return read_body
    decode_element = S.decode_unknown_effect(S.to_codec_json(schema.schema), **options)
    max_element_bytes = schema.max_element_bytes
    element_too_large = HttpApiPayloadTooLarge("maxElementBytes", max_element_bytes)

    def to_error(error: object) -> object:
        if isinstance(error, HttpApiPayloadTooLarge):
            return error
        if not isinstance(error, ndjson.NdjsonError):
            return HttpApiSchemaError("Payload", cast("SchemaError", error))
        if error.reason == "LineTooLarge":
            return element_too_large
        return HttpApiSchemaError("Payload", _ndjson_schema_error(error))

    def decode(request: ServerRequest) -> Stream[Any, Any, Any]:
        return (
            read_body(request)
            .pipe_through_channel(
                ndjson.decode(ignore_empty_lines=True, max_line_bytes=max_element_bytes)
            )
            .map_effect(decode_element)
            .map_error(to_error)
        )

    return decode


def _ndjson_schema_error(error: ndjson.NdjsonError) -> SchemaError:
    if error.reason == "InvalidUtf8":
        message = "Expected valid UTF-8"
    elif error.unterminated:
        message = "Expected a valid JSON line, got an unterminated final line"
    else:
        message = "Expected a valid JSON line"
    return SchemaError(I.InvalidValue({"message": message}))


def _limit_bytes(stream: Stream[bytes, Any, Any], max_bytes: int) -> Stream[bytes, Any, Any]:
    error = HttpApiPayloadTooLarge("maxBytes", cast("Any", max_bytes))

    def limited() -> Stream[bytes, Any, Any]:
        total = 0

        def count(chunks: tuple[bytes, ...]) -> Effect[tuple[bytes, ...], HttpApiPayloadTooLarge]:
            nonlocal total
            total += sum(len(chunk) for chunk in chunks)
            return fail(error) if total > max_bytes else succeed(chunks)

        return stream.map_array_effect(count)

    return stream_suspend(limited)


__all__ = ["PayloadDecoders", "decode_payload", "payload_decoders"]
