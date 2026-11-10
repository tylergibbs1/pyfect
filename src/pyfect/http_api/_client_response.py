"""How a derived client reads a response (Effect's ``HttpApiClient``
response decoders): a decoder for each declared status, choosing among
content types, and the streaming success decoders."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict, cast

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._json_text import PARSE_ERRORS, parse
from pyfect._primitives import Restore, uninterruptible_mask
from pyfect.cause import Cause
from pyfect.cause import fail as cause_fail
from pyfect.cause import merge as cause_merge
from pyfect.effect import context, fail, fail_cause, succeed, suspend
from pyfect.encoding import ndjson, sse
from pyfect.http import url_params
from pyfect.http.error import DecodeError, HttpClientError, StatusCodeError
from pyfect.http.response import HttpClientResponse
from pyfect.http_api import _media_type as media_type
from pyfect.http_api import schema as api_schema
from pyfect.http_api._client_method import SseOptions
from pyfect.option import Some
from pyfect.schema import ParseOptions, SchemaError, Top
from pyfect.schema import issue as I
from pyfect.schema import transformation as T
from pyfect.scope import scoped
from pyfect.socket import SocketService
from pyfect.stream import Stream, transform_pull
from pyfect.stream import provide_context as stream_provide_context

type ResponseDecoder = Callable[[HttpClientResponse, SseOptions | None], Effect[Any, Any, Any]]


@dataclass(frozen=True, slots=True)
class _Alternative:
    content_type: str
    decode: ResponseDecoder


def decoders(
    errors: Mapping[int, tuple[Top, ...]],
    successes: Mapping[int, tuple[Top, ...]],
    streams: Sequence[tuple[Top, api_schema.StreamSchema]],
    options: Any,
) -> Mapping[int, ResponseDecoder]:
    """The decoder of each declared status; ``options`` are the slot
    parse options. A declared error is decoded then failed with."""
    result: dict[int, ResponseDecoder] = {}
    for status, alternatives in _alternatives(errors, options.error, options.headers).items():
        result[status] = _fail_with(_choose(alternatives))
    success = _alternatives(successes, options.success, options.headers)
    for schema, body in streams:
        status = api_schema.get_status_success_schema(schema)
        decode = _stream_response(schema, body, options.success, options.headers)
        for content_type in body.content_types:
            success.setdefault(status, []).append(
                _Alternative(media_type.normalize(content_type), decode)
            )
    for status, alternatives in success.items():
        result[status] = _choose(alternatives)
    return result


def _alternatives(
    schemas: Mapping[int, tuple[Top, ...]], options: ParseOptions, headers_options: ParseOptions
) -> dict[int, list[_Alternative]]:
    result: dict[int, list[_Alternative]] = {}
    for status, by_status in schemas.items():
        for content_type, grouped in _by_content_type(by_status).items():
            result.setdefault(status, []).append(
                _Alternative(content_type, _schemas_response(grouped, options, headers_options))
            )
    return result


def _by_content_type(schemas: tuple[Top, ...]) -> dict[str, list[Top]]:
    grouped: dict[str, list[Top]] = {}
    for schema in schemas:
        body = api_schema.body_of(schema)
        content_type = (
            ""
            if api_schema.is_no_content(body.__codec__().ast)
            else media_type.normalize(api_schema.get_response_encoding_schema(schema).content_type)
        )
        grouped.setdefault(content_type, []).append(schema)
    return grouped


def _fail_with(decode: ResponseDecoder) -> ResponseDecoder:
    def decode_error(
        response: HttpClientResponse, sse_options: SseOptions | None
    ) -> Effect[Any, Any, Any]:
        status_error = HttpClientError(StatusCodeError(response.request, response))

        def on_cause(cause: Cause[Any]) -> Effect[Any, Any, Any]:
            return fail_cause(cause_merge(cause_fail(status_error), cause))

        return decode(response, sse_options).catch_cause(on_cause).flat_map(fail)

    return decode_error


def _choose(alternatives: list[_Alternative]) -> ResponseDecoder:
    first = alternatives[0].decode
    if all(alternative.decode is first for alternative in alternatives):
        # One schema (a stream under several media types) needs no choice.
        return first

    def decode(response: HttpClientResponse, sse_options: SseOptions | None) -> Any:
        content_type = media_type.normalize(response.headers.get("content-type") or "")
        for alternative in alternatives:
            if alternative.content_type == content_type:
                return alternative.decode(response, sse_options)
        expected = ", ".join(dict.fromkeys(a.content_type for a in alternatives))
        return fail(
            decode_error(
                response,
                f"Unsupported response content-type for status {response.status}: "
                f"{content_type or '<missing>'}. Expected one of: {expected}",
            )
        )

    return decode


def decode_error(response: HttpClientResponse, description: str) -> HttpClientError:
    return HttpClientError(DecodeError(response.request, response, description=description))


def undeclared_status(response: HttpClientResponse, _: SseOptions | None) -> Effect[Any, Any]:
    return fail(decode_error(response, "undeclared status code"))


# --- buffered bodies -------------------------------------------------------------------


def _forbidden_decode(input: object, options: ParseOptions) -> Effect[Any, I.Issue]:
    del options
    return fail(I.Forbidden({"message": "Decode only schema"}, Some(input)))


def _forbidden_encode(input: object, options: ParseOptions) -> Effect[Any, I.Issue]:
    del options
    return fail(I.Forbidden({"message": "Encode only schema"}, Some(input)))


def _text(data: bytes) -> str:
    return data.decode("utf-8", "replace")


def _json(data: object, options: ParseOptions) -> Effect[object, I.Issue]:
    del options
    text = _text(cast("bytes", data))
    if text == "":
        return succeed(None)
    try:
        return succeed(parse(text))
    except PARSE_ERRORS as error:
        return fail(I.InvalidValue({"message": str(error)}, Some(text)))


def _from_bytes(
    decode: Callable[[object, ParseOptions], Effect[object, I.Issue]],
) -> S.Bottom[object, Any]:
    return S.Bytes.pipe(
        S.decode_to(S.Unknown, T.transform_effect(decode=decode, encode=_forbidden_encode))
    )


def _sync(
    f: Callable[[bytes], object],
) -> Callable[[object, ParseOptions], Effect[object, I.Issue]]:
    return lambda data, _options: succeed(f(data))  # pyright: ignore[reportArgumentType]


_BODIES: Mapping[str, S.Bottom[object, Any]] = {
    "Json": _from_bytes(_json),
    "Text": _from_bytes(_sync(_text)),
    "Uint8Array": _from_bytes(_sync(lambda data: data)),
    "FormUrlEncoded": _from_bytes(_sync(lambda data: url_params.parse(_text(data)).to_record())),
}


def _from_body(schema: Top) -> Top:
    """``schema``'s values from the bytes of a response body."""
    body = _BODIES[api_schema.get_response_encoding(schema.__codec__().ast).tag]
    return body.pipe(S.decode_to(schema))


def _schemas_response(
    schemas: list[Top], options: ParseOptions, headers_options: ParseOptions
) -> ResponseDecoder:
    with_headers = any(
        api_schema.is_with_headers(s)
        or api_schema.get_with_headers_annotation(s.__codec__().ast) is not None
        for s in schemas
    )
    if not with_headers:
        decode = S.decode_unknown_effect(S.Union(*(_from_body(s) for s in schemas)), **options)
        return lambda response, _: response.bytes_.flat_map(decode)
    codec = S.Union(*(_with_headers_body(s, options, headers_options) for s in schemas))
    decode_pair = S.decode_unknown_effect(codec, **options)
    return lambda response, _: response.bytes_.flat_map(
        lambda data: decode_pair({"body": data, "headers": response.headers})
    )


class _Pair(TypedDict):
    body: object
    headers: object


_PAIR = S.Struct(_Pair)


def _with_headers_body(schema: Top, options: ParseOptions, headers_options: ParseOptions) -> Top:
    """A ``{"body", "headers"}`` pair decoded into ``schema``'s value: the
    body with ``options`` and the headers with ``headers_options``."""
    annotation = api_schema.get_with_headers_annotation(schema.__codec__().ast)
    if annotation is not None:
        body, headers = annotation.body_codec, annotation.headers_codec
        to_value: Callable[[Mapping[str, Any]], object] = annotation.decode
    elif api_schema.is_with_headers(schema):
        body, headers = schema.schema, schema.headers
        to_value = lambda pair: api_schema.with_headers(pair["body"], pair["headers"])  # noqa: E731
    else:
        body, headers = schema, S.Unknown
        to_value = lambda pair: pair["body"]  # noqa: E731
    decode_body = S.decode_unknown_effect(_from_body(body), **options)
    decode_headers = S.decode_unknown_effect(headers, **headers_options)

    def decode(pair: Mapping[str, Any], _options: ParseOptions) -> Effect[object, I.Issue, Any]:
        both = decode_body(pair["body"]).zip(decode_headers(pair["headers"]))
        return both.map(lambda parts: to_value({"body": parts[0], "headers": parts[1]})).map_error(
            lambda error: error.issue
        )

    target = schema if api_schema.is_with_headers(schema) else S.to_type(schema)
    return _PAIR.pipe(
        S.decode_to(target, T.transform_effect(decode=decode, encode=_forbidden_decode))
    )


# --- streams ---------------------------------------------------------------------------


def _stream_response(
    schema: Top,
    body: api_schema.StreamSchema,
    options: ParseOptions,
    headers_options: ParseOptions,
) -> ResponseDecoder:
    decode_body = _stream_body(body, options)

    def to_stream(
        response: HttpClientResponse, sse_options: SseOptions | None
    ) -> Effect[Stream[Any, Any, Any]]:
        return context().map(
            lambda services: decode_body(response, sse_options).pipe(
                stream_provide_context(services)
            )
        )

    if not api_schema.is_with_headers(schema):
        return to_stream
    decode_headers = S.decode_unknown_effect(schema.headers, **headers_options)
    return lambda response, sse_options: decode_headers(response.headers).flat_map(
        lambda headers: to_stream(response, sse_options).map(
            lambda stream: api_schema.with_headers(stream, headers)
        )
    )


type _BodyDecoder = Callable[[HttpClientResponse, SseOptions | None], Stream[Any, Any, Any]]


def _stream_body(schema: api_schema.StreamSchema, options: ParseOptions) -> _BodyDecoder:
    if isinstance(schema, api_schema.StreamUint8ArraySchema):
        return lambda response, _: response.stream
    if isinstance(schema, api_schema.StreamNdjsonSchema):
        return _ndjson_body(schema, options)
    return _sse_body(schema, options)


def _ndjson_body(schema: api_schema.StreamNdjsonSchema[Any], options: ParseOptions) -> _BodyDecoder:
    decode_element = S.decode_unknown_effect(S.to_codec_json(schema.schema), **options)
    max_element_bytes = int(schema.max_element_bytes)

    def decode(response: HttpClientResponse, _: SseOptions | None) -> Stream[Any, Any, Any]:
        def to_error(error: object) -> object:
            if not isinstance(error, ndjson.NdjsonError):
                return error
            if error.reason != "LineTooLarge":
                return ndjson_schema_error(error)
            return decode_error(
                response, f"NDJSON line exceeds maxElementBytes of {max_element_bytes} bytes"
            )

        return (
            response.stream.pipe_through_channel(
                ndjson.decode(ignore_empty_lines=True, max_line_bytes=max_element_bytes)
            )
            .map_error(to_error)
            .map_effect(decode_element)
        )

    return decode


def ndjson_schema_error(error: ndjson.NdjsonError) -> SchemaError:
    if error.reason == "InvalidUtf8":
        message = "Expected valid UTF-8"
    elif error.unterminated:
        message = "Expected a valid JSON line, got an unterminated final line"
    else:
        message = "Expected a valid JSON line"
    return SchemaError(I.InvalidValue({"message": message}))


class _FailureEvent(TypedDict):
    event: str
    data: object
    id: NotRequired[str]


def _sse_body(schema: api_schema.StreamSseSchema[Any, Any], options: ParseOptions) -> _BodyDecoder:
    cause = S.from_json_string(S.to_codec_json(S.Cause(schema.error, S.Defect())))
    failure = S.Struct(
        _FailureEvent, event=S.Literal(api_schema.RESERVED_STREAM_FAILURE_EVENT), data=cause
    )
    event = S.Union(failure, schema.events)
    data_mode = schema.sse_mode == "data"

    def decode(
        response: HttpClientResponse, sse_options: SseOptions | None
    ) -> Stream[Any, Any, Any]:
        max_event_size = (sse_options or {}).get("max_event_size", sse.DEFAULT_MAX_EVENT_SIZE)
        decoder: Any = sse.decode_schema(event, max_event_size=max_event_size, **options)
        events = transform_pull(
            response.stream.decode_text().pipe_through_channel(decoder), _until_failure
        )
        return events.map(lambda e: e["data"]) if data_mode else events

    return decode


def _until_failure(pull: Effect[tuple[Any, ...], Any], _scope: object) -> Effect[Any]:
    """The events up to a reserved failure event, then its cause."""
    pending: list[Cause[Any]] = []

    def next_events() -> Effect[tuple[Any, ...], Any]:
        if pending:
            return fail_cause(pending[0])
        return pull.flat_map(split)

    def split(events: tuple[Any, ...]) -> Effect[tuple[Any, ...], Any]:
        for index, event in enumerate(cast("tuple[Mapping[str, object], ...]", events)):
            data = event.get("data")
            is_failure = event.get("event") == api_schema.RESERVED_STREAM_FAILURE_EVENT
            if is_failure and isinstance(data, Cause):
                data = cast("Cause[Any]", data)
                if index == 0:
                    return fail_cause(data)
                pending.append(data)
                return succeed(events[:index])
        return succeed(events)

    return succeed(suspend(next_events))


__all__ = [
    "ResponseDecoder",
    "decode_error",
    "decoders",
    "ndjson_schema_error",
    "undeclared_status",
]


def upgrade_decoder(
    schema: api_schema.UpgradeSchema[Any], headers_options: ParseOptions
) -> ResponseDecoder:
    """Decodes a ``101`` into an ``Upgraded``: the connection and its headers,
    decoded with the upgrade's ``headers`` schema when it declares one. A
    failure or an interrupt after the connection is taken closes it."""
    headers_schema = schema.headers
    decode_headers: Callable[[object], Effect[Any, SchemaError, Any]] = (
        succeed
        if headers_schema is None
        else S.decode_unknown_effect(headers_schema, **headers_options)
    )

    def decode(response: HttpClientResponse, _: SseOptions | None) -> Effect[Any, Any, Any]:
        def taken(restore: Restore, socket: SocketService) -> Effect[Any, Any, Any]:
            # Nothing takes the connection on failure: releasing the reader's
            # scope closes it.
            close = scoped(socket.reader).ignore()
            return (
                restore(decode_headers(response.headers))
                .map(lambda headers: api_schema.Upgraded(headers, socket))
                .on_error(lambda _cause: close)
            )

        # The cleanup must be in place before an interruption can be observed.
        return uninterruptible_mask(
            lambda restore: response.upgrade.flat_map(lambda socket: taken(restore, socket))
        )

    return decode
