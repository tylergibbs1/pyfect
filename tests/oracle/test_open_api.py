"""Ports of Effect's ``httpapi/OpenApi.test.ts``.

Each test's docstring is the Effect test title. ``Schema.Struct({...})``
is ``struct({...})`` (``_http_api``); responses are keyed by the status
text, as in the JSON document.

Two schemas compile as pyfect's JSON Schemas do (``test_to_json_schema_document``),
kept as the expected value: ``is_pattern`` takes a Python ``re`` pattern,
which is left out, and an ``int`` has no safe-integer bounds.
"""

import json
import re
from collections.abc import Callable, Mapping
from typing import Any

import pytest

from pyfect import effect
from pyfect import schema as S
from pyfect.http_api import endpoint as ep
from pyfect.http_api import openapi, security
from pyfect.http_api import schema as api_schema
from pyfect.http_api.api import HttpApi
from pyfect.http_api.group import HttpApiGroup
from pyfect.http_api.middleware import HttpApiMiddleware
from pyfect.schema import ast
from pyfect.schema import transformation as T

from ._http_api import struct


class HeaderAuthA(
    HttpApiMiddleware, key="HeaderAuthA", security={"auth": security.api_key(key="x-api-key")}
):
    pass


class HeaderAuthB(
    HttpApiMiddleware, key="HeaderAuthB", security={"auth": security.api_key(key="x-api-key")}
):
    pass


class HeaderAuthUpper(
    HttpApiMiddleware, key="HeaderAuthUpper", security={"auth": security.api_key(key="X-API-Key")}
):
    pass


class QueryAuth(
    HttpApiMiddleware,
    key="QueryAuth",
    security={"auth": security.api_key(key="api_key", in_="query")},
):
    pass


class TokenAuthUpper(
    HttpApiMiddleware, key="TokenAuthUpper", security={"auth": security.http(scheme="Token")}
):
    pass


class TokenAuthLower(
    HttpApiMiddleware, key="TokenAuthLower", security={"auth": security.http(scheme="token")}
):
    pass


class ProtoHeaderAuth(
    HttpApiMiddleware,
    key="ProtoHeaderAuth",
    security={"__proto__": security.api_key(key="x-api-key")},
):
    pass


class ProtoQueryAuth(
    HttpApiMiddleware,
    key="ProtoQueryAuth",
    security={"__proto__": security.api_key(key="api_key", in_="query")},
):
    pass


def _security_api(first: Any, second: Any) -> HttpApi[Any]:
    return HttpApi.make("Api").add(
        HttpApiGroup.make("test").add(
            ep.get("first", "/first").middleware(first),
            ep.get("second", "/second").middleware(second),
        )
    )


def _api(*endpoints: Any, group: str = "test") -> HttpApi[Any]:
    return HttpApi.make("Api").add(HttpApiGroup.make(group).add(*endpoints))


_NUMBER_STRING = {
    "type": "string",
    "pattern": r"^[+-]?(?:\d+(?:\.\d+)?|\.\d+)(?:[Ee][+-]?\d+)?$",
}


def test_preserves_literal_action_suffixes_in_path_templates() -> None:
    """preserves literal action suffixes in path templates"""
    api = _api(
        ep.post("wait", "/operations/:id:wait", params=struct({"id": S.String})),
        group="operations",
    )
    spec = openapi.from_api(api)
    assert list(spec["paths"]) == ["/operations/{id}:wait"]
    assert spec["paths"]["/operations/{id}:wait"]["post"]["parameters"] == [
        {"name": "id", "in": "path", "required": True, "schema": {"type": "string"}}
    ]


def test_omits_regex_constraints_from_path_templates() -> None:
    """omits regex constraints from path templates"""
    api = _api(
        ep.get("get", r"/users/:id(\d+)", params=struct({"id": S.NumberFromString})),
        ep.get(
            "preview", r"/previews/:id(^(?:\d)+)preview", params=struct({"id": S.NumberFromString})
        ),
        group="users",
    )
    assert list(openapi.from_api(api)["paths"]) == ["/users/{id}", "/previews/{id}preview"]


def test_keeps_action_paths_literal_when_no_parameter_schema_is_declared() -> None:
    """keeps action paths literal when no parameter schema is declared"""
    api = _api(ep.post("resolve", "/offers:resolve"), group="offers")
    spec = openapi.from_api(api)
    assert list(spec["paths"]) == ["/offers:resolve"]
    assert spec["paths"]["/offers:resolve"]["post"]["parameters"] == []


def test_preserves_parameter_schemas_when_an_endpoint_transform_reorders_parameters() -> None:
    """preserves parameter schemas when an endpoint transform reorders parameters"""

    def reverse(operation: dict[str, Any]) -> dict[str, Any]:
        return {**operation, "parameters": list(reversed(operation["parameters"]))}

    api = _api(
        ep.get(
            "list",
            "/list",
            query=struct({"first": S.Literal("first"), "second": S.Literal("second")}),
        ).annotate(openapi.Transform, reverse)
    )
    assert openapi.from_api(api)["paths"]["/list"]["get"]["parameters"] == [
        {
            "name": "second",
            "in": "query",
            "required": True,
            "schema": {"type": "string", "enum": ["second"]},
        },
        {
            "name": "first",
            "in": "query",
            "required": True,
            "schema": {"type": "string", "enum": ["first"]},
        },
    ]


def test_derives_parameter_names_optionality_and_schemas_from_the_encoded_object() -> None:
    """derives parameter names, optionality, and schemas from the encoded object representation"""

    def defaulted(value: str) -> Any:
        return S.FiniteFromString.pipe(S.with_decoding_default_key(effect.succeed(value)))

    api = _api(
        ep.get(
            "list",
            "/list/:cursor",
            params=struct({"cursor": defaulted("0")}),
            query=struct(
                {
                    "limit": defaulted("10"),
                    "offset": defaulted("0"),
                    "search": S.String.annotate_key(description="Search text"),
                }
            ),
            headers=struct({"x-page-size": defaulted("10")}),
        )
    )
    assert openapi.from_api(api)["paths"]["/list/{cursor}"]["get"]["parameters"] == [
        {"name": "cursor", "in": "path", "required": True, "schema": {"type": "string"}},
        {"name": "x-page-size", "in": "header", "required": False, "schema": {"type": "string"}},
        {"name": "limit", "in": "query", "required": False, "schema": {"type": "string"}},
        {"name": "offset", "in": "query", "required": False, "schema": {"type": "string"}},
        {
            "name": "search",
            "in": "query",
            "required": True,
            "schema": {"type": "string", "allOf": [{"description": "Search text"}]},
        },
    ]


def _opaque_string(codec: Callable[[tuple[ast.AST, ...]], ast.Link]) -> Any:
    def is_string(value: object) -> Any:
        return isinstance(value, str)

    return S.declare(is_string, to_codec_json=codec)


def test_does_not_apply_json_codecs_to_parameters_when_codecs_are_disabled() -> None:
    """does not apply JSON codecs to parameters when codecs are disabled"""
    same: T.Transformation[str, str] = T.passthrough()
    opaque = _opaque_string(lambda _parameters: ast.Link(S.String.ast, same))
    api = _api(
        ep.get("encoded", "/encoded", query=struct({"value": opaque})),
        ep.get("unencoded", "/unencoded", disable_codecs=True, query=struct({"value": opaque})),
    )
    spec = openapi.from_api(api)
    assert spec["paths"]["/encoded"]["get"]["parameters"] == [
        {"name": "value", "in": "query", "required": True, "schema": {"type": "string"}}
    ]
    assert spec["paths"]["/unencoded"]["get"]["parameters"] == [
        {"name": "value", "in": "query", "required": True, "schema": {}}
    ]


def test_returns_fresh_spec_instances_when_using_the_cache() -> None:
    """returns fresh spec instances when using the cache"""
    api = _api(ep.get("get", "/resource"))
    first = openapi.from_api(api)
    first["info"]["title"] = "mutated"
    first["paths"]["/resource"]["get"]["summary"] = "mutated"
    second = openapi.from_api(api)
    assert first is not second
    assert first["info"] is not second["info"]
    assert first["paths"]["/resource"]["get"] is not second["paths"]["/resource"]["get"]
    assert second["info"]["title"] == "Api"
    assert "summary" not in second["paths"]["/resource"]["get"]
    second["info"]["title"] = "mutated again"
    second["paths"]["/resource"]["get"]["summary"] = "mutated again"
    third = openapi.from_api(api)
    assert third["info"]["title"] == "Api"
    assert "summary" not in third["paths"]["/resource"]["get"]


def test_preserves_json_raw_json_values_when_cloning_cached_specs() -> None:
    """preserves JSON.rawJSON values when cloning cached specs"""
    big = 9223372036854775807
    api = HttpApi.make("Api").annotate(
        openapi.Transform, lambda spec: {**spec, "info": {**spec["info"], "x-raw": big}}
    )
    expected = '{"title":"Api","version":"0.0.1","x-raw":9223372036854775807}'
    assert json.dumps(openapi.from_api(api)["info"], separators=(",", ":")) == expected
    assert json.dumps(openapi.from_api(api)["info"], separators=(",", ":")) == expected


def test_isolates_the_cached_spec_from_external_override_mutations() -> None:
    """isolates the cached spec from external override mutations"""
    info = {"title": "Api", "version": "1.0.0"}
    api = HttpApi.make("Api").annotate(openapi.Override, {"info": info})
    openapi.from_api(api)
    info["title"] = "mutated"
    assert openapi.from_api(api)["info"]["title"] == "Api"


def test_preserves_every_declared_payload_content_type_for_normalized_equivalents() -> None:
    """preserves every declared payload content type for normalized equivalents"""
    profile_a = "Application/Vnd.Effect+JSON; Profile=A"
    profile_b = "application/vnd.effect+json; profile=b"
    api = _api(
        ep.post(
            "create",
            "/create",
            payload=(
                struct({"a": S.String}).pipe(api_schema.as_json(content_type=profile_a)),
                struct({"b": S.String}).pipe(api_schema.as_json(content_type=profile_b)),
            ),
        )
    )
    content = openapi.from_api(api)["paths"]["/create"]["post"]["requestBody"]["content"]
    assert content[profile_a]["schema"] == {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": ["a"],
        "additionalProperties": False,
    }
    assert content[profile_b]["schema"] == {
        "type": "object",
        "properties": {"b": {"type": "string"}},
        "required": ["b"],
        "additionalProperties": False,
    }


def test_preserves_get_and_query_schemas_on_the_same_path() -> None:
    """preserves GET and QUERY schemas on the same path"""

    def transform(operation: dict[str, Any]) -> dict[str, Any]:
        assert operation["requestBody"]["content"]["application/json"]["schema"] == {
            "type": "string"
        }
        return {**operation, "summary": "Search"}

    api = _api(
        ep.get("list", "/search", success=S.Finite),
        ep.query("search", "/search", payload=S.String, success=S.Boolean).annotate(
            openapi.Transform, transform
        ),
        group="search",
    )
    spec = openapi.from_api(api)
    path_item = spec["paths"]["/search"]
    query = path_item["x-oai-additionalOperations"]["QUERY"]
    assert spec["openapi"] == "3.1.0"
    assert list(path_item) == ["get", "x-oai-additionalOperations"]
    assert query["summary"] == "Search"
    assert path_item["get"]["responses"]["200"]["content"]["application/json"]["schema"] == {
        "type": "number"
    }
    assert query["responses"]["200"]["content"]["application/json"]["schema"] == {"type": "boolean"}


def test_emits_buffered_and_stream_successes_with_the_same_status() -> None:
    """emits buffered and stream successes with the same status"""
    api = _api(
        ep.get(
            "chat",
            "/chat",
            success=(
                struct({"message": S.String}),
                api_schema.StreamSse(
                    events=struct({"event": S.String, "data": S.String}),
                    error=struct({"reason": S.String}),
                ),
            ),
        )
    )
    content = openapi.from_api(api)["paths"]["/chat"]["get"]["responses"]["200"]["content"]
    assert "application/json" in content
    assert "text/event-stream" in content
    extension = content["text/event-stream"]["x-effect-stream"]
    assert extension["encoding"] == "sse"
    assert extension["failureEvent"] == "effect/http-api/stream/failure"
    assert "causeSchema" in extension
    assert "errorSchema" in extension


def test_emits_the_encoded_schema_of_text_bodies() -> None:
    """emits the encoded schema of text bodies"""

    class NotFound(S.TaggedError):
        pass

    def decode(_: str) -> Mapping[str, object]:
        return {"_tag": "NotFound"}

    def encode(_: Mapping[str, object]) -> str:
        return "Not Found"

    not_found = S.Literal("Not Found").pipe(
        S.decode_to(NotFound, T.transform(decode=decode, encode=encode))
    )
    api = _api(
        ep.post(
            "create",
            "/create",
            payload=S.String.check(S.is_pattern(re.compile("^[a-z]+$"))).pipe(api_schema.as_text()),
            success=S.Literal("Created").pipe(api_schema.as_text()),
            error=(
                S.Literal("Bad Request").pipe(api_schema.as_text()).pipe(api_schema.status(400)),
                S.Literal("Invalid Cursor").pipe(api_schema.as_text()).pipe(api_schema.status(400)),
                not_found.pipe(api_schema.as_text()).pipe(api_schema.status(404)),
            ),
        )
    )
    spec = openapi.from_api(api)
    operation = spec["paths"]["/create"]["post"]
    # Python: a re pattern is left out of the JSON Schema.
    assert operation["requestBody"]["content"]["text/plain"]["schema"] == {"type": "string"}
    responses = operation["responses"]
    assert responses["200"]["content"]["text/plain"]["schema"] == {
        "type": "string",
        "enum": ["Created"],
    }
    assert responses["400"]["content"]["text/plain"]["schema"] == {
        "type": "string",
        "enum": ["Bad Request", "Invalid Cursor"],
    }
    assert responses["404"]["content"]["text/plain"]["schema"] == {
        "type": "string",
        "$ref": "#/components/schemas/NotFoundEncoded",
    }
    assert spec["components"]["schemas"]["NotFoundEncoded"] == {
        "type": "string",
        "enum": ["Not Found"],
    }


def _is_str(value: object) -> Any:
    return isinstance(value, str)


def test_keeps_opaque_text_bodies_as_strings() -> None:
    """keeps opaque text bodies as strings"""
    text = S.declare(_is_str).pipe(api_schema.as_text())
    api = _api(
        ep.post(
            "create", "/create", payload=text, success=text, error=text.pipe(api_schema.status(400))
        )
    )
    operation = openapi.from_api(api)["paths"]["/create"]["post"]
    assert operation["requestBody"]["content"]["text/plain"]["schema"] == {"type": "string"}
    assert operation["responses"]["200"]["content"]["text/plain"]["schema"] == {"type": "string"}
    assert operation["responses"]["400"]["content"]["text/plain"]["schema"] == {"type": "string"}


def test_constrains_referenced_opaque_text_bodies_without_changing_shared_json_schemas() -> None:
    """constrains referenced opaque text bodies without changing shared JSON schemas"""
    opaque = S.declare(_is_str).annotate(identifier="OpaqueText")
    text = opaque.pipe(api_schema.as_text())
    api = _api(
        ep.post(
            "text", "/text", payload=text, success=text, error=text.pipe(api_schema.status(400))
        ),
        ep.post("json", "/json", payload=opaque, success=opaque),
    )
    spec = openapi.from_api(api)
    text_operation = spec["paths"]["/text"]["post"]
    json_operation = spec["paths"]["/json"]["post"]
    reference = {"$ref": "#/components/schemas/OpaqueTextEncoded"}
    text_schema = {"type": "string"}
    assert text_operation["requestBody"]["content"]["text/plain"]["schema"] == text_schema
    assert text_operation["responses"]["200"]["content"]["text/plain"]["schema"] == text_schema
    assert text_operation["responses"]["400"]["content"]["text/plain"]["schema"] == text_schema
    assert json_operation["requestBody"]["content"]["application/json"]["schema"] == reference
    assert json_operation["responses"]["200"]["content"]["application/json"]["schema"] == reference
    assert spec["components"]["schemas"] == {"OpaqueTextEncoded": {}}


def _value_of(value: dict[str, str]) -> str:
    return value["value"]


def _with_value(value: str) -> dict[str, str]:
    return {"value": value}


def test_uses_encoding_specific_codecs_for_text_json_and_form_bodies() -> None:
    """uses encoding-specific codecs for text, JSON, and form bodies"""
    value_struct = struct({"value": S.String})
    opaque = _opaque_string(
        lambda _parameters: ast.Link(
            value_struct.ast,
            T.transform(decode=_value_of, encode=_with_value),
        )
    )
    schemas = (
        opaque,
        opaque.pipe(api_schema.as_text()),
        opaque.pipe(api_schema.as_form_url_encoded()),
    )
    api = _api(ep.post("create", "/create", payload=schemas, success=schemas))
    operation = openapi.from_api(api)["paths"]["/create"]["post"]
    object_schema = {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
        "additionalProperties": False,
    }
    body = operation["requestBody"]["content"]
    response = operation["responses"]["200"]["content"]
    assert body["text/plain"]["schema"] == {"type": "string"}
    assert response["text/plain"]["schema"] == {"type": "string"}
    assert body["application/json"]["schema"] == object_schema
    assert response["application/json"]["schema"] == object_schema
    assert body["application/x-www-form-urlencoded"]["schema"] == object_schema
    assert response["application/x-www-form-urlencoded"]["schema"] == object_schema


def test_emits_encoded_success_response_headers() -> None:
    """emits encoded success response headers"""
    api = _api(
        ep.get(
            "success",
            "/success",
            success=api_schema.WithHeaders(
                S.String,
                struct(
                    {
                        "X-Count": S.FiniteFromString,
                        "X-Optional": S.FiniteFromString,
                        "Content-Type": S.String,
                    },
                    optional=["X-Optional"],
                ),
            ),
        )
    )
    assert openapi.from_api(api)["paths"]["/success"]["get"]["responses"]["200"]["headers"] == {
        "x-count": {"schema": {"type": "string"}, "required": True},
        "x-optional": {"schema": {"type": "string"}, "required": False},
    }


def test_marks_response_headers_optional_from_their_encoded_object_representation() -> None:
    """marks response headers optional from their encoded object representation"""
    defaulted = S.FiniteFromString.pipe(S.with_decoding_default_key(effect.succeed("0")))
    api = _api(
        ep.get(
            "success",
            "/success",
            success=api_schema.WithHeaders(
                S.String, struct({"X-Total": defaulted, "X-Offset": defaulted})
            ),
        )
    )
    assert openapi.from_api(api)["paths"]["/success"]["get"]["responses"]["200"]["headers"] == {
        "x-total": {"schema": {"type": "string"}, "required": False},
        "x-offset": {"schema": {"type": "string"}, "required": False},
    }


def test_emits_encoded_error_response_headers() -> None:
    """emits encoded error response headers"""

    class NotFound(S.TaggedError):
        id: float

    with_headers = api_schema.encode_to_with_headers(
        NotFound,
        body=api_schema.Empty(404),
        headers=struct({"X-Error-Id": S.FiniteFromString}),
        decode=lambda pair: NotFound(id=pair["headers"]["X-Error-Id"]),
        encode=lambda error: {"body": None, "headers": {"X-Error-Id": error.id}},
    )
    api = _api(ep.get("error", "/error", error=with_headers))
    assert openapi.from_api(api)["paths"]["/error"]["get"]["responses"]["404"]["headers"] == {
        "x-error-id": {"schema": {"type": "string"}, "required": True}
    }


def test_emits_encode_to_with_headers_wire_schemas_according_to_codec_mode() -> None:
    """emits encodeToWithHeaders wire schemas according to codec mode"""
    with_headers = api_schema.encode_to_with_headers(
        S.Number,
        body=api_schema.Empty(404),
        headers=struct({"X-Error-Id": S.Int}),
        decode=lambda pair: pair["headers"]["X-Error-Id"],
        encode=lambda id: {"body": None, "headers": {"X-Error-Id": id}},
    )
    api = _api(
        ep.get("encoded", "/encoded", error=with_headers),
        ep.get("unencoded", "/unencoded", disable_codecs=True, error=with_headers),
    )
    spec = openapi.from_api(api)
    encoded = spec["paths"]["/encoded"]["get"]["responses"]["404"]["headers"]["x-error-id"]
    unencoded = spec["paths"]["/unencoded"]["get"]["responses"]["404"]["headers"]["x-error-id"]
    assert encoded["schema"] == _NUMBER_STRING
    # Python: an int has no safe-integer bounds.
    assert unencoded["schema"] == {"type": "integer"}


def test_emits_headers_for_an_error_wrapped_in_with_headers() -> None:
    """emits headers for an error wrapped in WithHeaders"""
    api = _api(
        ep.get(
            "error",
            "/error",
            error=api_schema.WithHeaders(
                struct({"message": S.String}).pipe(api_schema.status(429)),
                struct({"X-Retry-After": S.Int}),
            ),
        )
    )
    assert openapi.from_api(api)["paths"]["/error"]["get"]["responses"]["429"]["headers"] == {
        "x-retry-after": {"schema": _NUMBER_STRING, "required": True}
    }


def _api_error(identifier: str, field: str = "code") -> Any:
    return struct({field: S.String}).annotate(identifier=identifier)


def test_collapses_a_middleware_error_that_repeats_an_endpoint_error() -> None:
    """collapses a middleware error that repeats an endpoint error"""
    api_error = _api_error("ApiError")

    class SameError(HttpApiMiddleware, key="SameError"):
        error = api_error

    api = _api(ep.get("error", "/error", error=api_error)).middleware(SameError)
    assert openapi.from_api(api)["paths"]["/error"]["get"]["responses"]["500"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/ApiError"}}
    }


def test_collapses_a_repeated_middleware_error_when_the_endpoint_disables_codecs() -> None:
    """collapses a repeated middleware error when the endpoint disables codecs"""
    api_error = _api_error("ApiError")

    class SameError(HttpApiMiddleware, key="SameErrorNoCodecs"):
        error = api_error

    api = _api(ep.get("error", "/error", disable_codecs=True, error=api_error)).middleware(
        SameError
    )
    assert openapi.from_api(api)["paths"]["/error"]["get"]["responses"]["500"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/ApiError"}}
    }


def test_resolves_one_shared_middleware_error_per_endpoint_codec_mode() -> None:
    """resolves one shared middleware error per endpoint codec mode"""
    api_error = _api_error("ApiError")

    class SharedError(HttpApiMiddleware, key="SharedError"):
        error = api_error

    api = _api(
        ep.get("codecs", "/codecs", error=api_error),
        ep.get("raw", "/raw", disable_codecs=True, error=api_error),
    ).middleware(SharedError)
    spec = openapi.from_api(api)
    expected = {"application/json": {"schema": {"$ref": "#/components/schemas/ApiError"}}}
    assert spec["paths"]["/codecs"]["get"]["responses"]["500"]["content"] == expected
    assert spec["paths"]["/raw"]["get"]["responses"]["500"]["content"] == expected


def test_emits_an_any_of_for_a_middleware_error_that_differs_from_the_endpoint_error() -> None:
    """emits an anyOf for a middleware error that differs from the endpoint error"""

    class OtherError(HttpApiMiddleware, key="OtherError"):
        error = _api_error("MiddlewareError", "reason")

    api = _api(ep.get("error", "/error", error=_api_error("EndpointError"))).middleware(OtherError)
    assert openapi.from_api(api)["paths"]["/error"]["get"]["responses"]["500"]["content"] == {
        "application/json": {
            "schema": {
                "anyOf": [
                    {"$ref": "#/components/schemas/EndpointError"},
                    {"$ref": "#/components/schemas/MiddlewareError"},
                ]
            }
        }
    }


def test_emits_an_any_of_for_two_different_endpoint_errors_sharing_a_status() -> None:
    """emits an anyOf for two different endpoint errors sharing a status"""
    api = _api(
        ep.get(
            "error",
            "/error",
            error=(_api_error("FirstError"), _api_error("SecondError", "reason")),
        )
    )
    assert openapi.from_api(api)["paths"]["/error"]["get"]["responses"]["500"]["content"] == {
        "application/json": {
            "schema": {
                "anyOf": [
                    {"$ref": "#/components/schemas/FirstError"},
                    {"$ref": "#/components/schemas/SecondError"},
                ]
            }
        }
    }


def test_documents_a_middleware_error_for_a_status_the_endpoint_does_not_declare() -> None:
    """documents a middleware error for a status the endpoint does not declare"""

    class Auth(HttpApiMiddleware, key="Auth"):
        error = (
            struct({"message": S.String})
            .pipe(api_schema.status(401))
            .annotate(identifier="Unauthorized")
        )

    api = _api(ep.get("error", "/error", error=_api_error("ServerError"))).middleware(Auth)
    responses = openapi.from_api(api)["paths"]["/error"]["get"]["responses"]
    assert responses["401"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/Unauthorized"}}
    }
    assert responses["500"]["content"] == {
        "application/json": {"schema": {"$ref": "#/components/schemas/ServerError"}}
    }


def test_emits_stream_response_headers() -> None:
    """emits stream response headers"""
    api = _api(
        ep.get(
            "stream",
            "/stream",
            success=api_schema.WithHeaders(
                api_schema.StreamUint8Array(), struct({"X-Stream-Id": S.Int})
            ),
        )
    )
    assert openapi.from_api(api)["paths"]["/stream"]["get"]["responses"]["200"]["headers"] == {
        "x-stream-id": {"schema": _NUMBER_STRING, "required": True}
    }


def test_emits_streaming_payloads_and_successes_with_x_effect_stream_and_no_limits() -> None:
    """emits streaming payloads and successes with x-effect-stream and no limits"""
    item = struct({"id": S.Finite})
    item_schema = {
        "type": "object",
        "properties": {"id": {"type": "number"}},
        "required": ["id"],
        "additionalProperties": False,
    }
    api = _api(
        ep.post("upload", "/upload", payload=api_schema.StreamUint8Array(max_bytes="1 MiB")),
        ep.post(
            "ingest",
            "/ingest",
            payload=api_schema.StreamNdjson(item, max_bytes="10 MiB", max_element_bytes="1 KiB"),
        ),
        ep.get("export", "/export", success=api_schema.StreamNdjson(item)),
    )
    spec = openapi.from_api(api)
    assert spec["paths"]["/upload"]["post"]["requestBody"] == {
        "content": {
            "application/octet-stream": {
                "schema": {"type": "string", "format": "binary"},
                "x-effect-stream": {"encoding": "uint8array"},
            }
        },
        "required": True,
    }
    assert spec["paths"]["/ingest"]["post"]["requestBody"] == {
        "content": {
            "application/x-ndjson": {
                "schema": item_schema,
                "x-effect-stream": {"encoding": "ndjson"},
            }
        },
        "required": True,
    }
    assert spec["paths"]["/export"]["get"]["responses"]["200"]["content"] == {
        "application/x-ndjson": {"schema": item_schema, "x-effect-stream": {"encoding": "ndjson"}}
    }


def test_rejects_duplicate_method_and_path_pairs() -> None:
    """rejects duplicate method and path pairs"""
    api = _api(ep.get("first", "/shared"), ep.get("second", "/shared"))
    with pytest.raises(ValueError, match="Duplicate OpenAPI operation for GET /shared"):
        openapi.from_api(api)


def test_rejects_equivalent_templated_method_and_path_pairs() -> None:
    """rejects equivalent templated method and path pairs"""
    api = _api(
        ep.get("first", "/users/:id", params=struct({"id": S.String})),
        ep.get("second", "/users/:userId", params=struct({"userId": S.String})),
    )
    with pytest.raises(ValueError, match=r"Duplicate OpenAPI operation for GET /users/\{userId\}"):
        openapi.from_api(api)


def test_rejects_duplicate_operation_identifiers() -> None:
    """rejects duplicate operation identifiers"""
    api = _api(
        ep.get("first", "/first").annotate(openapi.Identifier, "shared"),
        ep.get("second", "/second").annotate(openapi.Identifier, "shared"),
    )
    with pytest.raises(ValueError, match="Duplicate OpenAPI operationId: shared"):
        openapi.from_api(api)


def test_allows_operations_without_identifiers() -> None:
    """allows operations without identifiers"""

    def remove_operation_id(operation: dict[str, Any]) -> dict[str, Any]:
        return {k: v for k, v in operation.items() if k != "operationId"}

    api = _api(
        ep.get("first", "/first").annotate(openapi.Transform, remove_operation_id),
        ep.get("second", "/second").annotate(openapi.Transform, remove_operation_id),
    )
    spec = openapi.from_api(api)
    assert "operationId" not in spec["paths"]["/first"]["get"]
    assert "operationId" not in spec["paths"]["/second"]["get"]


def test_rejects_incompatible_security_schemes_with_the_same_name() -> None:
    """rejects incompatible security schemes with the same name"""
    with pytest.raises(ValueError, match="Conflicting OpenAPI security scheme: auth"):
        openapi.from_api(_security_api(HeaderAuthA, QueryAuth))


def test_deduplicates_equivalent_security_schemes_with_the_same_name() -> None:
    """deduplicates equivalent security schemes with the same name"""
    spec = openapi.from_api(_security_api(HeaderAuthA, HeaderAuthB))
    assert spec["components"]["securitySchemes"]["auth"] == {
        "type": "apiKey",
        "name": "x-api-key",
        "in": "header",
    }


def test_deduplicates_api_key_header_names_case_insensitively() -> None:
    """deduplicates API key header names case-insensitively"""
    spec = openapi.from_api(_security_api(HeaderAuthUpper, HeaderAuthA))
    assert spec["components"]["securitySchemes"]["auth"] == {
        "type": "apiKey",
        "name": "X-API-Key",
        "in": "header",
    }


def test_deduplicates_http_security_schemes_case_insensitively() -> None:
    """deduplicates HTTP security schemes case-insensitively"""
    spec = openapi.from_api(_security_api(TokenAuthUpper, TokenAuthLower))
    assert spec["components"]["securitySchemes"]["auth"] == {"type": "http", "scheme": "Token"}


def test_stores_proto_security_scheme_names_as_own_properties() -> None:
    """stores __proto__ security scheme names as own properties"""
    api = _api(ep.get("first", "/first").middleware(ProtoHeaderAuth))
    schemes = openapi.from_api(api)["components"]["securitySchemes"]
    assert list(schemes) == ["__proto__"]
    assert schemes["__proto__"] == {"type": "apiKey", "name": "x-api-key", "in": "header"}


def test_rejects_incompatible_proto_security_schemes() -> None:
    """rejects incompatible __proto__ security schemes"""
    with pytest.raises(ValueError, match="Conflicting OpenAPI security scheme: __proto__"):
        openapi.from_api(_security_api(ProtoHeaderAuth, ProtoQueryAuth))
