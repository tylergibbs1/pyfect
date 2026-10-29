"""How a handler's value becomes the response (Effect's ``HttpApiBuilder``
response schemas): each declared success or error schema is a schema
from ``HttpServerResponse`` to its values, and the union of an
endpoint's encodes the value, choosing the first member that takes it.
A stream success is sent as a streaming body."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, TypeIs, cast

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._json_text import STRINGIFY_ERRORS, stringify
from pyfect.cause import Cause
from pyfect.context import Context
from pyfect.effect import fail, succeed
from pyfect.encoding import ndjson, sse
from pyfect.http.server_response import (
    HttpServerResponse,
    bytes_,
    empty,
    is_http_server_response,
    text,
    url_params,
)
from pyfect.http.server_response import stream as stream_response
from pyfect.http_api import schema as api_schema
from pyfect.http_api.endpoint import AnyEndpoint, error_schemas, success_schemas
from pyfect.option import Some
from pyfect.schema import ParseOptions, SchemaError, Top
from pyfect.schema import issue as I
from pyfect.schema import transformation as T
from pyfect.stream import Stream
from pyfect.stream import die as stream_die
from pyfect.stream import from_effect as stream_from_effect
from pyfect.stream import provide_context as stream_provide_context

_RESPONSE: S.Bottom[HttpServerResponse] = S.declare(
    cast("Any", is_http_server_response), expected="HttpServerResponse"
)

type Encode = Callable[[object], Effect[HttpServerResponse, SchemaError, Any]]


def _forbidden(input: object, options: ParseOptions) -> Effect[Any, I.Issue]:
    del options
    return fail(I.Forbidden({"message": "Encode only schema"}, Some(input)))


def response_encode(
    status: int, encoding: api_schema.ResponseEncoding, no_content: bool
) -> Callable[[object, ParseOptions], Effect[HttpServerResponse, I.Issue]]:
    """The response of an encoded body (Effect's ``getResponseEncode``)."""
    content_type = encoding.content_type
    match encoding.tag:
        case "Json":

            def json_body(
                body: object, options: ParseOptions
            ) -> Effect[HttpServerResponse, I.Issue]:
                if no_content:
                    return succeed(empty(status=status))
                try:
                    encoded = stringify(body)
                except STRINGIFY_ERRORS:
                    return fail(
                        I.InvalidValue(
                            {"expected": "a JSON-serializable response body"},
                            Some(body),
                        )
                    )
                return succeed(text(encoded, status=status, content_type=content_type))

            return json_body
        case "Text":
            return lambda body, _: succeed(
                text(cast("str", body), status=status, content_type=content_type)
            )
        case "Uint8Array":
            return lambda body, _: succeed(
                bytes_(cast("bytes", body), status=status, content_type=content_type)
            )
        case "FormUrlEncoded":
            return lambda body, _: succeed(
                url_params(cast("Any", body), status=status).set_header(
                    "content-type", content_type
                )
            )


def _body_response(schema: Top, get_status: Callable[[Top], int]) -> Top:
    """``schema``'s values encoded as their response."""
    body = schema.schema if api_schema.is_with_headers(schema) else schema
    encode = response_encode(
        get_status(schema),
        api_schema.get_response_encoding_schema(schema),
        api_schema.is_no_content(body.__codec__().ast),
    )
    return _RESPONSE.pipe(S.decode_to(body, T.transform_effect(decode=_forbidden, encode=encode)))


def _with_headers_response(
    *,
    schema: Top,
    status: int,
    encoding: api_schema.ResponseEncoding,
    body: Top,
    headers: Top,
    headers_options: ParseOptions,
    to_pair: Callable[[Any], tuple[object, object]],
) -> Top:
    """A response with headers: the body is encoded with the options of
    the encoding, the headers with the headers slot's."""
    encode_body = S.encode_unknown_effect(body)
    encode_headers = S.encode_unknown_effect(headers, **headers_options)
    encode_response = response_encode(
        status, encoding, api_schema.is_no_content(body.__codec__().ast)
    )

    def encode(value: object, options: ParseOptions) -> Effect[HttpServerResponse, I.Issue, Any]:
        body_value, headers_value = to_pair(value)
        return (
            encode_body(body_value, **options)
            .map_error(lambda error: error.issue)
            .flat_map(lambda encoded: encode_response(encoded, options))
            .flat_map(
                lambda response: (
                    encode_headers(headers_value)
                    .map_error(lambda error: error.issue)
                    .map(lambda encoded: response.set_headers(cast("Any", encoded)))
                )
            )
        )

    return _RESPONSE.pipe(S.decode_to(schema, T.transform_effect(decode=_forbidden, encode=encode)))


def _response_schema(
    schema: Top, get_status: Callable[[Top], int], headers_options: ParseOptions
) -> Top:
    annotation = api_schema.get_with_headers_annotation(schema.__codec__().ast)
    if annotation is not None:
        split = annotation.encode
        return _with_headers_response(
            schema=S.to_type(schema),
            status=get_status(annotation.body),
            encoding=api_schema.get_response_encoding(annotation.body.__codec__().ast),
            body=annotation.body_codec,
            headers=annotation.headers_codec,
            headers_options=headers_options,
            to_pair=lambda value: _pair(split(value)),
        )
    return _body_response(schema, get_status)


def _pair(value: Mapping[str, Any]) -> tuple[object, object]:
    return value["body"], value["headers"]


def _error_response(schema: Top, headers_options: ParseOptions) -> Top:
    if not api_schema.is_with_headers(schema):
        return _response_schema(schema, api_schema.get_status_error_schema, headers_options)
    return _with_headers_response(
        schema=schema,
        status=api_schema.get_status_error_schema(schema),
        encoding=api_schema.get_response_encoding_schema(schema),
        body=schema.schema,
        headers=schema.headers,
        headers_options=headers_options,
        to_pair=_value_pair,
    )


def _value_pair(value: api_schema.WithHeadersValue[Any, Any]) -> tuple[object, object]:
    return value.body, value.headers


def _union(schemas: list[Top]) -> Top:
    if not schemas:
        return S.Never
    return schemas[0] if len(schemas) == 1 else S.Union(*schemas)


def success_schema(endpoint: AnyEndpoint, headers_options: ParseOptions) -> Top:
    return _union(
        [
            _response_schema(s, api_schema.get_status_success_schema, headers_options)
            for s in success_schemas(endpoint)
        ]
    )


def error_schema(endpoint: AnyEndpoint, headers_options: ParseOptions) -> Top:
    return _union([_error_response(s, headers_options) for s in error_schemas(endpoint)])


# --- explicit response headers ---------------------------------------------------------


@dataclass(frozen=True, slots=True)
class WithHeadersEncoders:
    """The bodies of ``WithHeaders`` successes, and their headers' encoders
    by status."""

    encode_body: Encode
    encode_headers: Mapping[int, Callable[[object], Effect[Any, SchemaError, Any]]]


def with_headers_encoders(
    endpoint: AnyEndpoint, options: ParseOptions, headers_options: ParseOptions
) -> WithHeadersEncoders | None:
    encode_headers: dict[int, Callable[[object], Effect[Any, SchemaError, Any]]] = {}
    bodies: list[Top] = []
    for schema in endpoint.success:
        if not api_schema.is_with_headers(schema):
            continue
        encode_headers[api_schema.get_status_success_schema(schema)] = S.encode_unknown_effect(
            schema.headers, **headers_options
        )
        if not api_schema.is_stream_schema(schema.schema):
            bodies.append(
                _response_schema(schema, api_schema.get_status_success_schema, headers_options)
            )
    if not encode_headers:
        return None
    # Bodies sent with headers encode against those members only, so the
    # encoded status always has a headers encoder.
    return WithHeadersEncoders(
        S.encode_unknown_effect(cast("Any", _union(bodies)), **options), encode_headers
    )


# --- streams ---------------------------------------------------------------------------

type StreamEncode = Callable[
    [object, Context[Any]], Effect[HttpServerResponse, SchemaError, Any] | None
]


def stream_encoder(endpoint: AnyEndpoint, options: ParseOptions) -> StreamEncode | None:
    """Sends a stream success as a streaming body; ``None`` when the
    endpoint has none. A value that is not a stream is left to the
    buffered successes, or fails when there are none."""
    found = _stream_success(endpoint)
    if found is None:
        return None
    schema, stream_schema = found
    has_buffered = _has_buffered_success(endpoint)
    status = api_schema.get_status_success_schema(schema)
    content_type = stream_schema.content_type
    encode_body = _stream_body_encoder(stream_schema, options)

    def encode(
        response: object, context: Context[Any]
    ) -> Effect[HttpServerResponse, SchemaError, Any] | None:
        if not isinstance(response, Stream):
            if has_buffered:
                return None
            return fail(SchemaError(I.InvalidValue({"message": "Expected a streaming response"})))
        body = encode_body(cast("Stream[Any, Any, Any]", response)).pipe(
            stream_provide_context(context)
        )
        return succeed(stream_response(body, status=status, content_type=content_type))

    return encode


def _stream_success(endpoint: AnyEndpoint) -> tuple[Top, api_schema.StreamSchema] | None:
    for schema in endpoint.success:
        body = api_schema.body_of(schema)
        if api_schema.is_stream_schema(body):
            return schema, body
    return None


def _has_buffered_success(endpoint: AnyEndpoint) -> bool:
    for schema in endpoint.success:
        if not api_schema.is_stream_schema(api_schema.body_of(schema)):
            return True
    return not endpoint.success


def _stream_body_encoder(
    schema: api_schema.StreamSchema, options: ParseOptions
) -> Callable[[Stream[Any, Any, Any]], Stream[bytes, Any, Any]]:
    if isinstance(schema, api_schema.StreamUint8ArraySchema):
        return lambda stream: stream
    if isinstance(schema, api_schema.StreamNdjsonSchema):
        encode_elements = S.encode_unknown_effect(
            S.NonEmptyArray(S.to_codec_json(schema.schema)), **options
        )
        # There is no error schema: a bad element aborts the response.
        return lambda stream: (
            stream.map_array_effect(lambda elements: encode_elements(elements).or_die().map(tuple))
            .pipe_through_channel(ndjson.encode())
            .catch_if(_is_pack_error, _die_stream)
        )
    return _sse_body_encoder(schema, options)


def _is_pack_error(error: object) -> TypeIs[ndjson.NdjsonError]:
    return isinstance(error, ndjson.NdjsonError) and error.kind == "Pack"


def _die_stream(error: ndjson.NdjsonError) -> Stream[Any, Any, Any]:
    return stream_die(error)


def _mappings(events: Sequence[object]) -> tuple[Mapping[str, Any], ...]:
    return cast("tuple[Mapping[str, Any], ...]", tuple(events))


def _sse_body_encoder(
    schema: api_schema.StreamSseSchema[Any, Any], options: ParseOptions
) -> Callable[[Stream[Any, Any, Any]], Stream[bytes, Any, Any]]:
    encode_events = S.encode_unknown_effect(S.Array(schema.events), **options)
    cause_schema = S.to_codec_json(S.Cause(schema.error, S.Defect()))
    encode_cause = S.encode_unknown_effect(S.from_json_string(cause_schema), **options)
    data_mode = schema.sse_mode == "data"

    def failure_event(cause: Cause[Any]) -> Stream[Mapping[str, Any], Any, Any]:
        return stream_from_effect(
            encode_cause(cause)
            .or_die()
            .map(
                lambda data: {
                    "event": api_schema.RESERVED_STREAM_FAILURE_EVENT,
                    "data": data,
                }
            )
        )

    def encode(stream: Stream[Any, Any, Any]) -> Stream[bytes, Any, Any]:
        values = (
            stream.map(lambda value: {"event": "message", "data": value}) if data_mode else stream
        )
        return (
            values.map_array_effect(lambda chunk: encode_events(chunk).or_die().map(_mappings))
            .catch_cause(failure_event)
            .map(_render_event)
            .encode_text()
        )

    return encode


def _render_event(event: Mapping[str, Any]) -> str:
    return sse.write(
        sse.Event(event=event.get("event", "message"), id=event.get("id"), data=event["data"])
    )


__all__ = [
    "StreamEncode",
    "WithHeadersEncoders",
    "error_schema",
    "response_encode",
    "stream_encoder",
    "success_schema",
    "with_headers_encoders",
]
