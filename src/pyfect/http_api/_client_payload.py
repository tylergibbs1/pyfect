"""How a derived client sends a payload (Effect's ``HttpApiClient``
payload encoders): a body of the payload's encoding, URL parameters for a
method without a body, or a streamed body."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from functools import cache
from typing import Any, TypeIs, cast

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._json_text import STRINGIFY_ERRORS, stringify
from pyfect.effect import fail, succeed
from pyfect.encoding import ndjson
from pyfect.http import body as http_body
from pyfect.http.method import has_body
from pyfect.http_api import schema as api_schema
from pyfect.http_api.endpoint import HttpMethod
from pyfect.option import Some
from pyfect.schema import ParseOptions, Top
from pyfect.schema import issue as I
from pyfect.schema import transformation as T
from pyfect.stream import Stream
from pyfect.stream import die as stream_die

_BODY_TYPES = (
    http_body.Empty,
    http_body.Raw,
    http_body.Bytes,
    http_body.FormData,
    http_body.Stream,
)


def _is_http_body(value: object) -> TypeIs[http_body.HttpBody]:
    return isinstance(value, _BODY_TYPES)


_HTTP_BODY: S.Bottom[http_body.HttpBody] = S.declare(_is_http_body, expected="HttpBody")

type _Encode = Callable[[object, str], Effect[http_body.HttpBody, I.Issue]]


def _invalid(message: str, input: object) -> Effect[Any, I.Issue]:
    return fail(I.InvalidValue({"message": message}, Some(input)))


def _json(value: object, content_type: str) -> Effect[http_body.HttpBody, I.Issue]:
    try:
        return succeed(http_body.text(stringify(value), content_type))
    except STRINGIFY_ERRORS:
        return fail(I.InvalidValue({"expected": "a JSON-serializable request body"}, Some(value)))


def _text(value: object, content_type: str) -> Effect[http_body.HttpBody, I.Issue]:
    if not isinstance(value, str):
        return _invalid("Expected a string", value)
    return succeed(http_body.text(value, content_type))


def _form(value: object, content_type: str) -> Effect[http_body.HttpBody, I.Issue]:
    if not isinstance(value, Mapping):
        return _invalid("Expected a record", value)
    record = cast("Mapping[str, Any]", value)
    return succeed(http_body.url_params(record, content_type))


def _bytes(value: object, content_type: str) -> Effect[http_body.HttpBody, I.Issue]:
    if not isinstance(value, bytes):
        return _invalid("Expected a Uint8Array", value)
    return succeed(http_body.bytes_(value, content_type))


_ENCODERS: Mapping[str, _Encode] = {
    "Json": _json,
    "Text": _text,
    "FormUrlEncoded": _form,
    "Uint8Array": _bytes,
}


def _body_encoder(
    encoding: api_schema.PayloadEncoding,
) -> Callable[[object, ParseOptions], Effect[http_body.HttpBody, I.Issue]]:
    if isinstance(encoding, api_schema.MultipartEncoding):
        return lambda value, _options: fail(
            I.Forbidden({"message": "Payload must be a FormData"}, Some(value))
        )
    encode = _ENCODERS[encoding.tag]
    content_type = encoding.content_type
    return lambda value, _options: encode(value, content_type)


def _forbidden(input: object, _options: ParseOptions) -> Effect[Any, I.Issue]:
    return fail(I.Forbidden({"message": "Encode only schema"}, Some(input)))


@cache
def _body_schema(schema: Top, method: HttpMethod) -> Top:
    encoding = api_schema.get_payload_encoding(schema.__codec__().ast, method)
    transformation = T.transform_effect(decode=_forbidden, encode=_body_encoder(encoding))
    return _HTTP_BODY.pipe(S.decode_to(schema, transformation))


def payload_encoder(
    schemas: list[Top], method: HttpMethod, options: ParseOptions
) -> Callable[[object], Effect[Any, S.SchemaError, Any]] | None:
    """Encodes a payload to an ``HttpBody`` (or, for a method without a
    body, the URL parameters)."""
    if not schemas:
        return None
    if has_body(method):
        schema = S.Union(*(_body_schema(s, method) for s in schemas))
    else:
        schema = schemas[0] if len(schemas) == 1 else S.Union(*schemas)
    return S.encode_unknown_effect(schema, **options)


def stream_payload_encoder(
    schema: api_schema.StreamUint8ArraySchema | api_schema.StreamNdjsonSchema[Any],
    options: ParseOptions,
) -> Callable[[Stream[Any, Any, Any]], Stream[bytes, Any, Any]]:
    if isinstance(schema, api_schema.StreamUint8ArraySchema):
        return lambda stream: stream
    encode_elements = S.encode_unknown_effect(
        S.NonEmptyArray(S.to_codec_json(schema.schema)), **options
    )

    def encode(stream: Stream[Any, Any, Any]) -> Stream[bytes, Any, Any]:
        return (
            stream.map_array_effect(lambda elements: encode_elements(elements).map(tuple))
            .pipe_through_channel(ndjson.encode())
            .catch_if(_is_pack_error, stream_die)
        )

    return encode


def _is_pack_error(error: object) -> TypeIs[ndjson.NdjsonError]:
    return isinstance(error, ndjson.NdjsonError) and error.kind == "Pack"


__all__ = ["payload_encoder", "stream_payload_encoder"]
