"""Ports of Effect's ``httpapi/HttpApiEndpoint.test.ts``. Each test's
docstring is the Effect test title, prefixed by its ``describe`` block.

Omitted: "can be extended as a class" (a JavaScript endpoint is a class
constructor; a Python endpoint is a value declared on a group class).
"""

from typing import Any, Never, cast

import pytest

from pyfect import schema as S
from pyfect.http_api import endpoint as ep
from pyfect.http_api import openapi
from pyfect.http_api import schema as api_schema
from pyfect.http_api.endpoint import BufferedPayload

from ._http_api import struct

_EVENTS = struct({"event": S.Literal("user.created"), "data": S.String})
_STREAM_ERROR = struct({"reason": S.String})


def _sse() -> api_schema.StreamSseSchema[Any, Any]:
    return api_schema.StreamSse(events=_EVENTS, error=_STREAM_ERROR)


def _encode(schema: S.Top, value: object) -> object:
    # An endpoint's query schema has no requirements.
    return S.encode_unknown_sync(cast("S.Codec[Any, Any, Never, Never]", schema))(value)


def test_omits_undefined_optional_http_properties() -> None:
    """HttpApiEndpoint / omits undefined optional HTTP properties"""
    endpoint = ep.get("get", "/", query=struct({"search": S.String}, optional=["search"]))
    assert endpoint.query is not None
    assert _encode(endpoint.query, {}) == {}
    assert _encode(endpoint.query, {"search": "value"}) == {"search": "value"}


def test_stores_the_supplied_identifier() -> None:
    """HttpApiEndpoint / stores the supplied identifier"""
    assert ep.get("getUser", "/users/:id").identifier == "getUser"


def test_prefixes_an_endpoint() -> None:
    """HttpApiEndpoint / can be extended as a class (the prefix part)"""
    prefixed = ep.get("getUser", "/users/:id").prefix("/v1")
    assert prefixed.identifier == "getUser"
    assert prefixed.path == "/v1/users/:id"


def test_normalizes_payload_map_keys_while_preserving_the_declared_content_type() -> None:
    """HttpApiEndpoint payload schemas / normalizes payload map keys while preserving the declared content type"""  # noqa: E501
    content_type = "Application/Vnd.Effect+JSON; Charset=UTF-8"
    endpoint = ep.post(
        "create",
        "/",
        payload=api_schema.as_json(content_type=content_type)(struct({"name": S.String})),
    )
    entry = endpoint.payload["application/vnd.effect+json"]
    assert isinstance(entry, BufferedPayload)
    assert entry.encoding.content_type == content_type


def test_rejects_incompatible_encodings_for_equivalent_content_types() -> None:
    """HttpApiEndpoint payload schemas / rejects incompatible encodings for equivalent content types"""  # noqa: E501
    json_payload = api_schema.as_json(content_type="Application/Vnd.Effect+Data; charset=utf-8")(
        struct({"name": S.String})
    )
    text_payload = api_schema.as_text(content_type="application/vnd.effect+data")(S.String)
    with pytest.raises(ValueError, match="Multiple payload encodings"):
        ep.post("create", "/", payload=(json_payload, text_payload))


def test_rejects_two_streaming_payloads() -> None:
    """HttpApiEndpoint streaming payload schemas / rejects two streaming payloads"""
    with pytest.raises(ValueError, match="Multiple streaming payloads"):
        ep.post(
            "upload",
            "/upload",
            payload=(api_schema.StreamNdjson(S.Finite), api_schema.StreamUint8Array()),
        )


def test_rejects_buffered_payloads_and_successes_on_any_listed_stream_content_type() -> None:
    """HttpApiEndpoint streaming payload schemas / rejects buffered payloads and successes on any listed stream content type"""  # noqa: E501
    stream = api_schema.StreamNdjson(
        S.Number, content_type=["application/x-ndjson", "application/json"]
    )
    ok = struct({"ok": S.Boolean})
    with pytest.raises(
        ValueError,
        match="Cannot combine buffered and streaming payloads for content-type: application/json",
    ):
        ep.post("upload", "/upload", payload=(stream, ok))
    with pytest.raises(
        ValueError,
        match="Cannot combine buffered and streaming success responses for status 200 "
        "and content-type: application/json",
    ):
        ep.get("export", "/export", success=(stream, ok))


def test_rejects_streaming_payloads_on_no_body_methods() -> None:
    """HttpApiEndpoint streaming payload schemas / rejects streaming payloads on no-body methods"""
    with pytest.raises(ValueError, match="GET"):
        ep.make("GET", "upload", "/upload", payload=api_schema.StreamUint8Array())


def test_get_endpoint_accepts_stream_sse_success() -> None:
    """HttpApiEndpoint streaming success schemas / GET endpoint accepts StreamSse success"""
    stream = _sse()
    assert stream in ep.get("events", "/events", success=stream).success


def test_get_endpoint_accepts_stream_uint8_array_success() -> None:
    """HttpApiEndpoint streaming success schemas / GET endpoint accepts StreamUint8Array success"""
    stream = api_schema.StreamUint8Array()
    assert stream in ep.get("download", "/download", success=stream).success


def test_streaming_schema_in_error_throws_during_endpoint_construction() -> None:
    """HttpApiEndpoint streaming success schemas / streaming schema in error throws during endpoint construction"""  # noqa: E501
    with pytest.raises(ValueError, match="Streaming schemas are not supported"):
        ep.make("GET", "events", "/events", error=_sse())


def test_head_with_streaming_success_throws() -> None:
    """HttpApiEndpoint streaming success schemas / HEAD with streaming success throws"""
    with pytest.raises(ValueError):
        ep.head("events", "/events", success=_sse())


def test_streaming_success_mixed_with_no_content_at_the_same_status_throws() -> None:
    """HttpApiEndpoint streaming success schemas / streaming success mixed with NoContent at the same status throws"""  # noqa: E501
    with pytest.raises(ValueError):
        ep.get("events", "/events", success=(_sse(), api_schema.status(200)(api_schema.NoContent)))


def test_streaming_and_buffered_success_at_the_same_status_for_distinct_content_types() -> None:
    """HttpApiEndpoint streaming success schemas / streaming success mixed with a buffered success at the same status is allowed for distinct content types"""  # noqa: E501
    stream = _sse()
    endpoint = ep.get("events", "/events", success=(stream, struct({"ok": S.Boolean})))
    assert stream in endpoint.success


def test_streaming_and_buffered_success_at_the_same_content_type_throws() -> None:
    """HttpApiEndpoint streaming success schemas / streaming success mixed with a buffered success at the same content type throws"""  # noqa: E501
    stream = api_schema.StreamSse(
        content_type="application/json", events=_EVENTS, error=_STREAM_ERROR
    )
    with pytest.raises(ValueError):
        ep.get("events", "/events", success=(stream, struct({"ok": S.Boolean})))


def test_streaming_and_buffered_success_at_content_types_differing_by_parameters_throws() -> None:
    """HttpApiEndpoint streaming success schemas / streaming success mixed with a buffered success at content types differing only by parameters throws"""  # noqa: E501
    stream = api_schema.StreamSse(
        content_type="application/json; charset=utf-8", events=_EVENTS, error=_STREAM_ERROR
    )
    with pytest.raises(ValueError):
        ep.get("events", "/events", success=(stream, struct({"ok": S.Boolean})))


def test_streaming_and_buffered_success_at_distinct_statuses_is_allowed() -> None:
    """HttpApiEndpoint streaming success schemas / streaming success mixed with a buffered success at distinct statuses is allowed"""  # noqa: E501
    stream = api_schema.status(206)(_sse())
    endpoint = ep.get("events", "/events", success=(stream, struct({"ok": S.Boolean})))
    assert stream in endpoint.success


def test_streaming_success_and_no_content_at_distinct_statuses_is_allowed() -> None:
    """HttpApiEndpoint streaming success schemas / streaming success mixed with NoContent at distinct statuses is allowed"""  # noqa: E501
    stream = api_schema.status(200)(_sse())
    endpoint = ep.get("events", "/events", success=(stream, api_schema.NoContent))
    assert stream in endpoint.success


def test_two_streaming_successes_for_the_same_status_throw() -> None:
    """HttpApiEndpoint streaming success schemas / two streaming successes for the same status throw"""  # noqa: E501
    with pytest.raises(ValueError):
        ep.get(
            "events",
            "/events",
            success=(_sse(), api_schema.StreamUint8Array(content_type="application/custom-stream")),
        )


def test_two_streaming_successes_for_distinct_statuses_throw() -> None:
    """HttpApiEndpoint streaming success schemas / two streaming successes for distinct statuses throw"""  # noqa: E501
    stream = api_schema.status(206)(_sse())
    stream_bytes = api_schema.status(200)(
        api_schema.StreamUint8Array(content_type="application/custom-stream")
    )
    with pytest.raises(ValueError, match="Multiple streaming success responses are not supported"):
        ep.get("events", "/events", success=(stream, stream_bytes))


def test_statically_detectable_sse_reserved_failure_event_name_throws() -> None:
    """HttpApiEndpoint streaming success schemas / statically detectable SSE reserved failure event name throws"""  # noqa: E501
    stream = api_schema.StreamSse(
        events=struct({"event": S.Literal("effect/http-api/stream/failure"), "data": S.String}),
        error=_STREAM_ERROR,
    )
    with pytest.raises(ValueError):
        ep.get("events", "/events", success=stream)


def test_rejects_a_with_headers_success_sharing_its_status_and_content_type() -> None:
    """HttpApiEndpoint WithHeaders schemas / rejects a WithHeaders success sharing its status and content type"""  # noqa: E501
    with pytest.raises(
        ValueError,
        match="Cannot combine a response with headers with another response for status 200 "
        "and content-type: application/json",
    ):
        ep.get(
            "get",
            "/",
            success=(
                struct({"plain": S.String}),
                api_schema.WithHeaders(
                    struct({"wrapped": S.String}), struct({"x-trace-id": S.String})
                ),
            ),
        )


def test_rejects_an_encode_to_with_headers_error_sharing_its_status_and_content_type() -> None:
    """HttpApiEndpoint WithHeaders schemas / rejects an encodeToWithHeaders error sharing its status and content type"""  # noqa: E501
    error_with_headers = api_schema.encode_to_with_headers(
        S.String,
        body=struct({"wrapped": S.String}),
        headers=struct({"x-trace-id": S.String}),
        decode=lambda pair: pair["body"]["wrapped"],
        encode=lambda message: {"body": {"wrapped": message}, "headers": {"x-trace-id": "trace"}},
    )
    with pytest.raises(
        ValueError,
        match="Cannot combine a response with headers with another response for status 500 "
        "and content-type: application/json",
    ):
        ep.get("get", "/", error=(struct({"plain": S.String}), error_with_headers))


def test_rejects_two_with_headers_successes_sharing_a_status_across_content_types() -> None:
    """HttpApiEndpoint WithHeaders schemas / rejects two WithHeaders successes sharing a status across content types"""  # noqa: E501
    with pytest.raises(
        ValueError, match="Cannot declare multiple responses with headers for status 200"
    ):
        ep.get(
            "get",
            "/",
            success=(
                api_schema.WithHeaders(struct({"value": S.String}), struct({"x-json": S.String})),
                api_schema.WithHeaders(
                    api_schema.as_text()(S.String), struct({"x-text": S.String})
                ),
            ),
        )


def test_rejects_two_encode_to_with_headers_errors_sharing_a_status() -> None:
    """HttpApiEndpoint WithHeaders schemas / rejects two encodeToWithHeaders errors sharing a status"""  # noqa: E501
    json_error = api_schema.encode_to_with_headers(
        S.String,
        body=struct({"message": S.String}),
        headers=struct({"x-json": S.String}),
        decode=lambda pair: pair["body"]["message"],
        encode=lambda message: {"body": {"message": message}, "headers": {"x-json": "json"}},
    )
    text_error = api_schema.encode_to_with_headers(
        S.String,
        body=api_schema.as_text()(S.String),
        headers=struct({"x-text": S.String}),
        decode=lambda pair: pair["body"],
        encode=lambda message: {"body": message, "headers": {"x-text": "text"}},
    )
    with pytest.raises(
        ValueError, match="Cannot declare multiple responses with headers for status 500"
    ):
        ep.get("get", "/", error=(json_error, text_error))


def test_rejects_mixed_with_headers_and_encode_to_with_headers_responses_sharing_a_status() -> None:
    """HttpApiEndpoint WithHeaders schemas / rejects mixed WithHeaders and encodeToWithHeaders responses sharing a status"""  # noqa: E501
    annotated_error = api_schema.encode_to_with_headers(
        S.String,
        body=api_schema.as_text()(api_schema.status(429)(S.String)),
        headers=struct({"retry-after": S.String}),
        decode=lambda pair: pair["body"],
        encode=lambda message: {"body": message, "headers": {"retry-after": "30"}},
    )
    with pytest.raises(
        ValueError, match="Cannot declare multiple responses with headers for status 429"
    ):
        ep.get(
            "get",
            "/",
            error=(
                api_schema.WithHeaders(
                    api_schema.status(429)(struct({"message": S.String})),
                    struct({"x-trace-id": S.String}),
                ),
                annotated_error,
            ),
        )


def test_allows_one_response_with_headers_and_a_plain_response_across_content_types() -> None:
    """HttpApiEndpoint WithHeaders schemas / allows one response with headers and a plain response for the same status across content types"""  # noqa: E501
    endpoint = ep.get(
        "get",
        "/",
        success=(
            api_schema.WithHeaders(struct({"value": S.String}), struct({"x-trace-id": S.String})),
            api_schema.as_text()(S.String),
        ),
    )
    assert len(endpoint.success) == 2


def test_allows_responses_with_headers_on_distinct_statuses() -> None:
    """HttpApiEndpoint WithHeaders schemas / allows responses with headers on distinct statuses"""
    endpoint = ep.get(
        "get",
        "/",
        success=(
            api_schema.WithHeaders(struct({"value": S.String}), struct({"x-trace-id": S.String})),
            api_schema.WithHeaders(
                api_schema.status(201)(struct({"created": S.Boolean})),
                struct({"location": S.String}),
            ),
        ),
    )
    assert len(endpoint.success) == 2


def test_keeps_the_wrapper_in_the_success_set_with_codec_transformed_parts() -> None:
    """HttpApiEndpoint WithHeaders schemas / keeps the wrapper in the success set with codec-transformed parts"""  # noqa: E501
    endpoint = ep.get(
        "list",
        "/users",
        success=api_schema.WithHeaders(struct({"a": S.String}), struct({"x-count": S.Int})),
    )
    (schema,) = endpoint.success
    assert api_schema.is_with_headers(schema)
    assert _encode(schema.headers, {"x-count": 3}) == {"x-count": "3"}


def test_leaves_the_wrapper_untouched_when_codecs_are_disabled() -> None:
    """HttpApiEndpoint WithHeaders schemas / leaves the wrapper untouched when codecs are disabled"""  # noqa: E501
    wrapped = api_schema.WithHeaders(struct({"a": S.String}), struct({"x-count": S.Int}))
    endpoint = ep.get("list", "/users", disable_codecs=True, success=wrapped)
    assert wrapped in endpoint.success


def test_preserves_disable_codecs_through_derived_endpoints() -> None:
    """HttpApiEndpoint WithHeaders schemas / preserves disableCodecs through derived endpoints"""
    endpoint = ep.get("list", "/users", disable_codecs=True, success=struct({"a": S.String}))
    assert endpoint.disable_codecs
    assert endpoint.prefix("/api").disable_codecs
    assert endpoint.annotate(openapi.Title, "Users").disable_codecs
    assert not ep.get("plain", "/plain").disable_codecs


def test_keeps_a_wrapped_stream_schema_as_the_inner_schema() -> None:
    """HttpApiEndpoint WithHeaders schemas / keeps a wrapped stream schema as the inner schema"""
    stream = _sse()
    endpoint = ep.get(
        "events", "/events", success=api_schema.WithHeaders(stream, struct({"x-count": S.Int}))
    )
    (schema,) = endpoint.success
    assert api_schema.is_with_headers(schema)
    assert schema.schema is stream


def test_preserves_wrapper_annotations_through_endpoint_construction() -> None:
    """HttpApiEndpoint WithHeaders schemas / preserves wrapper annotations through endpoint construction"""  # noqa: E501
    endpoint = ep.get(
        "list",
        "/users",
        success=api_schema.status(201)(
            api_schema.WithHeaders(struct({"a": S.String}), struct({"x-count": S.Int}))
        ),
    )
    (schema,) = endpoint.success
    assert api_schema.get_status_success_schema(schema) == 201


def test_validates_a_wrapped_stream_like_a_bare_stream() -> None:
    """HttpApiEndpoint WithHeaders schemas / validates a wrapped stream like a bare stream"""
    with pytest.raises(ValueError):
        ep.get(
            "events",
            "/events",
            success=(
                api_schema.WithHeaders(_sse(), struct({"x-count": S.Int})),
                api_schema.StreamUint8Array(content_type="application/custom-stream"),
            ),
        )
    with pytest.raises(ValueError):
        ep.head(
            "events", "/events", success=api_schema.WithHeaders(_sse(), struct({"x-count": S.Int}))
        )


def test_rejects_wrapped_and_bare_streams_at_distinct_statuses() -> None:
    """HttpApiEndpoint WithHeaders schemas / rejects wrapped and bare streams at distinct statuses"""  # noqa: E501
    message = "Multiple streaming success responses are not supported"
    with pytest.raises(ValueError, match=message):
        ep.get(
            "events",
            "/events",
            success=(
                api_schema.status(206)(
                    api_schema.StreamUint8Array(content_type="application/custom-bytes")
                ),
                api_schema.WithHeaders(
                    api_schema.status(201)(
                        api_schema.StreamUint8Array(content_type="application/other-bytes")
                    ),
                    struct({"x-source": S.String}),
                ),
            ),
        )
    with pytest.raises(ValueError, match=message):
        ep.get(
            "events",
            "/events",
            success=(api_schema.WithHeaders(_sse(), struct({"x-count": S.Int})), _sse()),
        )


def test_keeps_with_headers_in_the_error_set_with_codec_transformed_parts() -> None:
    """HttpApiEndpoint WithHeaders schemas / keeps WithHeaders in the error set with codec-transformed parts"""  # noqa: E501
    endpoint = ep.get(
        "list",
        "/users",
        error=api_schema.WithHeaders(
            api_schema.status(429)(struct({"message": S.String})),
            struct({"retry-after": S.Int}),
        ),
    )
    (schema,) = endpoint.error
    assert api_schema.is_with_headers(schema)
    assert api_schema.get_status_error_schema(schema) == 429
    assert _encode(schema.headers, {"retry-after": 30}) == {"retry-after": "30"}


_UPGRADE = api_schema.Upgrade("tcp")


@pytest.mark.parametrize(
    "success",
    [api_schema.Empty(200), S.String],
    ids=["a no-content response", "a buffered response"],
)
def test_accepts_an_upgrade(success: S.Codec[Any, Any, Never, Never]) -> None:
    """HttpApiEndpoint WithHeaders schemas / Upgrade / accepts an upgrade with $name"""
    endpoint = ep.post("start", "/start", success=(_UPGRADE, success))
    assert [api_schema.is_upgrade(s) for s in endpoint.success] == [True, False]


def _upgrade_with_upgrade() -> object:
    return ep.post("attach", "/attach", success=(_UPGRADE, api_schema.Upgrade("h2c")))


def _upgrade_with_stream() -> object:
    return ep.post("attach", "/attach", success=(_UPGRADE, _sse()))


def _upgrade_with_status_101() -> object:
    return ep.post("attach", "/attach", success=(_UPGRADE, api_schema.status(101)(S.String)))


def _upgrade_in_with_headers() -> object:
    return ep.post(
        "attach", "/attach", success=api_schema.WithHeaders(_UPGRADE, struct({"x-id": S.String}))
    )


def _upgrade_in_encode_to_with_headers() -> object:
    return api_schema.encode_to_with_headers(
        _UPGRADE,
        body=_UPGRADE,
        headers=struct({"x-id": S.String}),
        decode=lambda pair: pair["body"],
        encode=lambda body: {"body": body, "headers": {"x-id": "id"}},
    )


def _upgrade_on_head() -> object:
    return ep.head("attach", "/attach", success=_UPGRADE)


def _upgrade_with_byte_stream_payload() -> object:
    return ep.post("attach", "/attach", payload=api_schema.StreamUint8Array(), success=_UPGRADE)


def _upgrade_with_multipart_stream_payload() -> object:
    return ep.post(
        "attach",
        "/attach",
        payload=api_schema.as_multipart_stream(struct({"file": S.String})),
        success=_UPGRADE,
    )


def _upgrade_as_error() -> object:
    return ep.make("POST", "attach", "/attach", error=_UPGRADE)


def _upgrade_to_web_socket() -> object:
    return api_schema.Upgrade("WebSocket")


@pytest.mark.parametrize(
    ("make", "message"),
    [
        (_upgrade_with_upgrade, "Cannot declare more than one upgrade"),
        (_upgrade_with_stream, "Cannot combine an upgrade with a streaming success response"),
        (
            _upgrade_with_status_101,
            "Cannot combine an upgrade with another success response for status: 101",
        ),
        (_upgrade_in_with_headers, "WithHeaders cannot wrap an upgrade"),
        (_upgrade_in_encode_to_with_headers, "encodeToWithHeaders cannot wrap an upgrade"),
        (_upgrade_on_head, "HEAD endpoints cannot declare an upgrade"),
        (_upgrade_with_byte_stream_payload, "Upgrade endpoints cannot declare a streaming payload"),
        (
            _upgrade_with_multipart_stream_payload,
            "Upgrade endpoints cannot declare a streaming payload",
        ),
        (_upgrade_as_error, "Upgrade schemas are not supported in error responses"),
        (_upgrade_to_web_socket, "Upgrade does not support WebSocket"),
    ],
    ids=[
        "with another upgrade",
        "with a streaming success",
        "with another success at status 101",
        "wrapped in WithHeaders",
        "wrapped by encodeToWithHeaders",
        "on HEAD",
        "with a byte stream payload",
        "with a multipart stream payload",
        "as an error",
        "to WebSocket",
    ],
)
def test_rejects_an_upgrade(make: Any, message: str) -> None:
    """HttpApiEndpoint WithHeaders schemas / Upgrade / rejects an upgrade $name"""
    with pytest.raises(ValueError, match=message):
        make()
