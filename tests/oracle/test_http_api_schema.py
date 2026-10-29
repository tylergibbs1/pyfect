"""Ports of Effect's ``httpapi/HttpApiSchema.test.ts``. Each test's
docstring is the Effect test title, prefixed by its ``describe`` blocks.

A stream schema's ``mode`` is its class (``isinstance``, Effect's
``isStreamSse`` / ``isStreamUint8Array``); the ``httpApiStatus``
annotation is ``http_api_status``.

Omitted: "supports a fields shorthand for headers" (a pyfect struct is
declared by a ``TypedDict``, so the headers are always a schema).
"""

from typing import Any

import pytest

from pyfect import schema as S
from pyfect.http_api import schema as api_schema
from pyfect.http_api.schema import StreamSseSchema, StreamUint8ArraySchema
from pyfect.schema import Bottom

from ._http_api import struct


def test_stream_sse_stores_default_metadata() -> None:
    """HttpApiSchema / StreamSse / stores default metadata"""
    events = struct({"event": S.Literal("user.created"), "data": S.String})
    error = struct({"reason": S.String})
    stream = api_schema.StreamSse(events=events, error=error)
    assert isinstance(stream, Bottom)
    assert api_schema.is_stream_schema(stream)
    assert isinstance(stream, StreamSseSchema)
    assert not isinstance(stream, StreamUint8ArraySchema)
    assert stream.sse_mode == "events"
    assert stream.content_type == "text/event-stream"
    assert stream.events is events
    assert stream.error is error


def test_stream_sse_stores_custom_content_type() -> None:
    """HttpApiSchema / StreamSse / stores custom content type"""
    events = struct({"event": S.Literal("custom"), "data": S.String})
    stream = api_schema.StreamSse(
        content_type="text/event-stream; charset=utf-8", events=events, error=S.String
    )
    assert stream.content_type == "text/event-stream; charset=utf-8"


def test_defaults_the_stream_error_schema_to_never() -> None:
    """HttpApiSchema / StreamSse / defaults the stream error schema to Never"""
    events = struct({"event": S.Literal("custom"), "data": S.String})
    stream = api_schema.StreamSse(events=events)
    assert isinstance(stream.error.__codec__().ast, S.ast.Never)


def test_creates_an_event_schema_from_a_json_data_schema() -> None:
    """HttpApiSchema / StreamSse / creates an event schema from a JSON data schema"""
    data = struct({"id": S.String})
    stream = api_schema.StreamSse(data=data, error=struct({"reason": S.String}))
    encode = S.encode_unknown_sync(stream.events)
    decode = S.decode_unknown_sync(stream.events)
    assert stream.sse_mode == "data"
    assert encode({"event": "user.created", "data": {"id": "123"}}) == {
        "event": "user.created",
        "data": '{"id":"123"}',
    }
    assert decode({"event": "user.created", "data": '{"id":"123"}'}) == {
        "event": "user.created",
        "data": {"id": "123"},
    }


def test_stream_uint8_array_stores_default_metadata() -> None:
    """HttpApiSchema / StreamUint8Array / stores default metadata"""
    stream = api_schema.StreamUint8Array()
    assert isinstance(stream, Bottom)
    assert api_schema.is_stream_schema(stream)
    assert not isinstance(stream, StreamSseSchema)
    assert isinstance(stream, StreamUint8ArraySchema)
    assert stream.content_type == "application/octet-stream"


def test_stream_uint8_array_stores_custom_content_type() -> None:
    """HttpApiSchema / StreamUint8Array / stores custom content type"""
    stream = api_schema.StreamUint8Array(content_type="application/custom-binary")
    assert stream.content_type == "application/custom-binary"


def _headers(name: str, schema: S.Codec[Any, Any, Any, Any] = S.String) -> Any:
    return struct({name: schema})


def test_stores_the_inner_schema_and_headers_schema() -> None:
    """HttpApiSchema / WithHeaders / stores the inner schema and headers schema"""
    headers = _headers("x-total-count", S.FiniteFromString)
    schema = api_schema.WithHeaders(S.String, headers)
    assert isinstance(schema, Bottom)
    assert api_schema.is_with_headers(schema)
    assert schema.schema is S.String
    assert schema.headers is headers


def test_does_not_identify_other_schemas_as_with_headers() -> None:
    """HttpApiSchema / WithHeaders / does not identify other schemas as WithHeaders"""
    assert not api_schema.is_with_headers(S.String)
    assert not api_schema.is_with_headers(api_schema.StreamUint8Array())


def test_rejects_nested_with_headers_schemas() -> None:
    """HttpApiSchema / WithHeaders / rejects nested WithHeaders schemas"""
    inner = api_schema.WithHeaders(S.String, _headers("x-a"))
    with pytest.raises(ValueError, match="WithHeaders schemas cannot be nested"):
        api_schema.WithHeaders(inner, _headers("x-b"))


def test_accepts_only_branded_values_when_decoding() -> None:
    """HttpApiSchema / WithHeaders / accepts only branded values when decoding"""
    schema = api_schema.WithHeaders(S.String, _headers("x-a"))
    value = api_schema.with_headers("a", {"x-a": "1"})
    assert S.decode_unknown_sync(schema)(value) is value
    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(schema)({"body": "a", "headers": {"x-a": "1"}})


def test_keeps_the_wrapper_intact_through_annotate() -> None:
    """HttpApiSchema / WithHeaders / keeps the wrapper intact through annotate"""
    headers = _headers("x-a")
    schema = api_schema.WithHeaders(S.String, headers).annotate(description="described")
    assert api_schema.is_with_headers(schema)
    assert schema.schema is S.String
    assert schema.headers is headers


def test_resolves_the_status_from_the_wrapper_first() -> None:
    """HttpApiSchema / WithHeaders / resolves the status from the wrapper first, falling through to the inner schema"""  # noqa: E501
    headers = _headers("x-a")
    on_inner = api_schema.WithHeaders(api_schema.status(201)(S.String), headers)
    assert api_schema.get_status_success_schema(on_inner) == 201
    on_wrapper = api_schema.status(202)(api_schema.WithHeaders(S.String, headers))
    assert api_schema.is_with_headers(on_wrapper)
    assert api_schema.get_status_success_schema(on_wrapper) == 202
    on_both = api_schema.status(202)(
        api_schema.WithHeaders(api_schema.status(201)(S.String), headers)
    )
    assert api_schema.get_status_success_schema(on_both) == 202
    assert api_schema.get_status_success_schema(api_schema.WithHeaders(S.String, headers)) == 200
    assert api_schema.get_status_success_schema(api_schema.status(201)(S.String)) == 201


def test_resolves_the_response_encoding_from_the_wrapper_first() -> None:
    """HttpApiSchema / WithHeaders / resolves the response encoding from the wrapper first, falling through to the inner schema"""  # noqa: E501
    headers = _headers("x-a")
    on_inner = api_schema.WithHeaders(api_schema.as_text()(S.String), headers)
    assert api_schema.get_response_encoding_schema(on_inner).tag == "Text"
    on_wrapper = api_schema.as_json(content_type="application/vnd.custom+json")(
        api_schema.WithHeaders(S.String, headers)
    )
    assert api_schema.is_with_headers(on_wrapper)
    encoding = api_schema.get_response_encoding_schema(on_wrapper)
    assert encoding.content_type == "application/vnd.custom+json"
    on_neither = api_schema.WithHeaders(S.String, headers)
    assert api_schema.get_response_encoding_schema(on_neither).tag == "Json"


def test_constructs_a_branded_response_value() -> None:
    """HttpApiSchema / withHeaders / constructs a branded response value"""
    value = api_schema.with_headers("a", {"x-a": "1"})
    assert value.body == "a"
    assert value.headers == {"x-a": "1"}


class UserNotFound(S.TaggedError):
    user_id: int


_WRAPPED_USER_NOT_FOUND = api_schema.encode_to_with_headers(
    UserNotFound,
    body=api_schema.Empty(404),
    headers=struct({"x-user-id": S.Int}),
    decode=lambda pair: UserNotFound(user_id=pair["headers"]["x-user-id"]),
    encode=lambda error: {"headers": {"x-user-id": error.user_id}, "body": None},
)


def test_encodes_to_a_body_and_headers_pair() -> None:
    """HttpApiSchema / encodeToWithHeaders / encodes to a body and headers pair"""
    assert S.encode_sync(_WRAPPED_USER_NOT_FOUND)(UserNotFound(user_id=1)) == {
        "body": None,
        "headers": {"x-user-id": 1},
    }


def test_decodes_a_pair_back_to_the_source_type() -> None:
    """HttpApiSchema / encodeToWithHeaders / decodes a pair back to the source type"""
    decoded = S.decode_unknown_sync(_WRAPPED_USER_NOT_FOUND)(
        {"body": None, "headers": {"x-user-id": 1}}
    )
    assert decoded == UserNotFound(user_id=1)


def test_resolves_the_status_from_the_body_schema() -> None:
    """HttpApiSchema / encodeToWithHeaders / resolves the status from the body schema"""
    assert api_schema.get_status_error(_WRAPPED_USER_NOT_FOUND.ast) == 404


def test_resolves_the_response_encoding_from_the_body_schema() -> None:
    """HttpApiSchema / encodeToWithHeaders / resolves the response encoding from the body schema"""
    schema = api_schema.encode_to_with_headers(
        S.String,
        body=api_schema.as_text()(S.String),
        headers=_headers("x-a"),
        decode=lambda pair: pair["body"],
        encode=lambda value: {"body": value, "headers": {"x-a": "1"}},
    )
    assert api_schema.get_response_encoding(schema.ast).tag == "Text"


def test_defaults_the_response_encoding_to_json() -> None:
    """HttpApiSchema / encodeToWithHeaders / defaults the response encoding to Json"""
    assert api_schema.get_response_encoding(_WRAPPED_USER_NOT_FOUND.ast).tag == "Json"


def test_uses_the_body_defaults_instead_of_source_response_metadata() -> None:
    """HttpApiSchema / encodeToWithHeaders / uses the body defaults instead of source response metadata"""  # noqa: E501
    source = api_schema.as_text()(api_schema.status(429)(S.String))
    schema = api_schema.encode_to_with_headers(
        source,
        body=S.String,
        headers=_headers("x-note"),
        decode=lambda pair: pair["body"],
        encode=lambda body: {"body": body, "headers": {"x-note": "test"}},
    )
    assert api_schema.get_status_error(schema.ast) == 500
    encoding = api_schema.get_response_encoding(schema.ast)
    assert (encoding.tag, encoding.content_type) == ("Json", "application/json")


def test_does_not_identify_buffered_schemas_as_stream_schemas() -> None:
    """HttpApiSchema / does not identify buffered schemas as stream schemas"""
    assert not api_schema.is_stream_schema(S.String)
    assert not api_schema.is_stream_schema(api_schema.as_uint8_array()(S.Bytes))


def test_accepts_status_literals() -> None:
    """HttpApiSchema / status / accepts status literals"""
    created = api_schema.status("Created")(S.String)
    conflict = api_schema.status("Conflict")(S.String)
    assert api_schema.get_status_success(created.ast) == 201
    assert api_schema.get_status_error(conflict.ast) == 409


def test_uses_the_last_of_status_and_the_http_api_status_annotation() -> None:
    """HttpApiSchema / status / uses the last of status and the httpApiStatus annotation"""
    created = api_schema.status(201)(S.String)
    assert api_schema.get_status_success(created.annotate(http_api_status=202).ast) == 202
    assert api_schema.get_status_success(created.annotate(http_api_status=None).ast) == 200
    annotated = S.String.annotate(http_api_status=404).check(S.is_min_length(1))
    assert api_schema.get_status_error(annotated.ast) == 404
    assert api_schema.get_status_error(api_schema.status(409)(annotated).ast) == 409


def test_preserves_the_status_when_adding_checks() -> None:
    """HttpApiSchema / status / preserves the status when adding checks"""
    check = S.is_min_length(1)
    created = api_schema.status(201)(S.String.check(check)).check(check)
    assert api_schema.get_status_success(created.ast) == 201
    annotated = created.annotate(http_api_status=202).check(check)
    assert api_schema.get_status_success(annotated.ast) == 202
    updated = api_schema.status(203)(annotated).check(check)
    assert api_schema.get_status_success(updated.ast) == 203
    cleared = updated.annotate(http_api_status=None).check(check)
    assert api_schema.get_status_success(cleared.ast) == 200
    assert api_schema.get_status_success(api_schema.status(201)(cleared).ast) == 201


def test_resolves_status_annotations_inside_check_groups() -> None:
    """HttpApiSchema / status / resolves status annotations inside check groups"""
    group = S.make_filter_group(
        S.is_min_length(1, http_api_status=201),
        S.make_filter_group(S.is_max_length(100, http_api_status=202)),
    )
    schema = S.String.check(group).check(S.is_trimmed())
    assert api_schema.get_status_success(schema.ast) == 202
    assert api_schema.get_status_success(api_schema.status(203)(schema).ast) == 203
    cleared = S.String.check(S.make_filter_group(*group.checks, http_api_status=None))
    assert api_schema.get_status_success(cleared.ast) == 200
