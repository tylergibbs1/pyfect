"""Ports of ``platform-node/test/OpenApi.test.ts``: the OpenAPI document
Effect produces, literally. Each test's docstring is the Effect test
title, prefixed by its ``describe`` blocks.

``Schema.optional(X)`` and ``Schema.optionalKey(X)`` are both a
``NotRequired`` key (Python has no ``undefined``).
"""

from typing import Any, Never

from pyfect import schema as S
from pyfect.http import multipart
from pyfect.http_api import endpoint as ep
from pyfect.http_api import error as api_error
from pyfect.http_api import openapi
from pyfect.http_api import schema as api_schema
from pyfect.http_api.api import AdditionalSchemas, HttpApi
from pyfect.http_api.endpoint import AnyEndpoint
from pyfect.http_api.group import HttpApiGroup
from pyfect.http_api.middleware import HttpApiMiddleware

from ._http_api import struct

type Json = dict[str, Any]

_STRING: Json = {"type": "string"}

type _Schema = S.Codec[Any, Any, Never, Never]


def _spec(*endpoints: AnyEndpoint, group: str = "group") -> Json:
    return openapi.from_api(HttpApi.make("api").add(HttpApiGroup.make(group).add(*endpoints)))


def _object(properties: Json, required: list[str]) -> Json:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _json(schema: Json, content_type: str = "application/json") -> Json:
    return {content_type: {"schema": schema}}


def _request_content(spec: Json, path: str = "/a") -> Json:
    return spec["paths"][path]["post"]["requestBody"]["content"]


def _responses(spec: Json, path: str = "/a", method: str = "get") -> Json:
    return spec["paths"][path][method]["responses"]


def _success(content: Json, description: str = "Success") -> Json:
    return {"description": description, "content": content}


# --- api ---------------------------------------------------------------------------


def _check_info(spec: Json) -> None:
    info = spec["info"]
    assert info["title"] == "title"
    assert info["version"] == "version"
    assert info["description"] == "description"
    assert info["license"] == {"name": "license"}
    assert info["summary"] == "summary"
    assert spec["servers"] == [{"url": "https://example.com"}]


def test_api_annotate() -> None:
    """OpenAPI spec / api / annotate"""
    api = (
        HttpApi.make("api")
        .annotate(openapi.Title, "title")
        .annotate(openapi.Version, "version")
        .annotate(openapi.Description, "description")
        .annotate(openapi.License, {"name": "license"})
        .annotate(openapi.Summary, "summary")
        .annotate(openapi.Servers, ({"url": "https://example.com"},))
    )
    _check_info(openapi.from_api(api))


def test_api_annotate_merge() -> None:
    """OpenAPI spec / api / annotateMerge"""
    api = HttpApi.make("api").annotate_merge(
        openapi.annotations(
            title="title",
            version="version",
            description="description",
            license={"name": "license"},
            summary="summary",
            servers=({"url": "https://example.com"},),
        )
    )
    _check_info(openapi.from_api(api))


def test_api_additional_schemas() -> None:
    """OpenAPI spec / api / AdditionalSchemas"""
    api = HttpApi.make("api").annotate(AdditionalSchemas, (S.String.annotate(identifier="A"),))
    assert openapi.from_api(api)["components"]["schemas"] == {"A": _STRING}


def test_api_override() -> None:
    """OpenAPI spec / api / Override"""
    api = HttpApi.make("api").annotate(openapi.Override, {"tags": [{"name": "A"}]})
    assert openapi.from_api(api)["tags"] == [{"name": "A"}]


def test_api_transform() -> None:
    """OpenAPI spec / api / Transform"""
    api = HttpApi.make("api").annotate(
        openapi.Transform, lambda spec: {**spec, "tags": [{"name": "A"}]}
    )
    assert openapi.from_api(api)["tags"] == [{"name": "A"}]


# --- group -------------------------------------------------------------------------


def test_group_annotations() -> None:
    """OpenAPI spec / group / annotations"""
    group = (
        HttpApiGroup.make("group")
        .annotate(openapi.Description, "my description")
        .annotate(openapi.ExternalDocs, {"url": "http://example.com", "description": "example"})
        .annotate(openapi.Override, {"name": "my name"})
        .annotate(openapi.Transform, lambda spec: {**spec, "name": spec["name"] + "-transformed"})
    )
    excluded = HttpApiGroup.make("excluded").annotate(openapi.Exclude, True)
    spec = openapi.from_api(HttpApi.make("api").add(group).add(excluded))
    assert spec == {
        "openapi": "3.1.0",
        "info": {"title": "Api", "version": "0.0.1"},
        "paths": {},
        "components": {"schemas": {}, "securitySchemes": {}},
        "security": [],
        "tags": [
            {
                "name": "my name-transformed",
                "description": "my description",
                "externalDocs": {"url": "http://example.com", "description": "example"},
            }
        ],
    }


def test_top_level_group() -> None:
    """OpenAPI spec / group / top level group"""
    group = HttpApiGroup.make("group", top_level=True).add(ep.get("get", "/", success=S.String))
    spec = openapi.from_api(HttpApi.make("api").add(group))
    assert spec["paths"] == {
        "/": {
            "get": {
                "tags": ["group"],
                "operationId": "get",
                "parameters": [],
                "security": [],
                "responses": {"200": _success(_json(_STRING))},
            }
        }
    }


# --- endpoint ----------------------------------------------------------------------


def test_endpoint_annotations() -> None:
    """OpenAPI spec / endpoint / annotations / endpoint annotations"""
    get = (
        ep.get("get", "/", success=S.String)
        .annotate(openapi.Description, "my description")
        .annotate(openapi.Summary, "my summary")
        .annotate(openapi.Deprecated, True)
        .annotate(openapi.ExternalDocs, {"url": "http://example.com", "description": "example"})
    )
    excluded = ep.get("excluded", "/excluded", success=S.String).annotate(openapi.Exclude, True)
    assert _spec(get, excluded) == {
        "openapi": "3.1.0",
        "info": {"title": "Api", "version": "0.0.1"},
        "paths": {
            "/": {
                "get": {
                    "tags": ["group"],
                    "operationId": "group.get",
                    "parameters": [],
                    "security": [],
                    "responses": {"200": _success(_json(_STRING))},
                    "description": "my description",
                    "summary": "my summary",
                    "deprecated": True,
                    "externalDocs": {"url": "http://example.com", "description": "example"},
                }
            }
        },
        "components": {"schemas": {}, "securitySchemes": {}},
        "security": [],
        "tags": [{"name": "group"}],
    }


def test_success_description() -> None:
    """OpenAPI spec / endpoint / annotations / success description"""
    user = struct({"id": S.Finite, "name": S.String}).annotate(identifier="User")
    spec = _spec(
        ep.get(
            "getUsers",
            "/users",
            success=S.Array(user).annotate(description="Returns an array of users"),
        )
    )
    assert spec["paths"] == {
        "/users": {
            "get": {
                "tags": ["group"],
                "operationId": "group.getUsers",
                "parameters": [],
                "security": [],
                "responses": {
                    "200": _success(
                        _json(
                            {
                                "type": "array",
                                "items": {"$ref": "#/components/schemas/User"},
                                "description": "Returns an array of users",
                            }
                        ),
                        "Returns an array of users",
                    )
                },
            }
        }
    }
    assert spec["components"]["schemas"] == {
        "User": _object({"id": {"type": "number"}, "name": _STRING}, ["id", "name"])
    }


def test_catch_all_path() -> None:
    """OpenAPI spec / endpoint / catch all path"""
    spec = _spec(ep.get("a", "*", success=S.String))
    assert spec["paths"]["*"]["get"]["responses"] == {"200": _success(_json(_STRING))}


def test_middleware_error() -> None:
    """OpenAPI spec / endpoint / middleware error"""

    class M(HttpApiMiddleware[Never, str], key="Http/Logger"):
        error = api_schema.as_text()(api_schema.status(405)(S.String))

    group = HttpApiGroup.make("group").add(ep.get("a", "/a", success=S.Finite)).middleware(M)
    spec = openapi.from_api(HttpApi.make("api").add(group))
    assert _responses(spec) == {
        "200": _success(_json({"type": "number"})),
        "405": {"description": "Error", "content": _json(_STRING, "text/plain")},
    }


def test_params_option_get() -> None:
    """OpenAPI spec / endpoint / params option / GET"""
    spec = _spec(ep.get("a", "/a/:id", params=struct({"id": S.FiniteFromString})))
    assert spec["paths"]["/a/{id}"]["get"]["parameters"] == [
        {"name": "id", "in": "path", "schema": _STRING, "required": True}
    ]


def test_payload_option_get_query_parameters() -> None:
    """OpenAPI spec / endpoint / payload option / GET / query parameters"""
    payload = struct(
        {
            "required": S.FiniteFromString,
            "optionalKey": S.FiniteFromString,
            "optional": S.FiniteFromString,
        },
        optional=["optionalKey", "optional"],
    )
    spec = _spec(ep.get("a", "/a", payload=payload))
    assert spec["paths"]["/a"]["get"]["parameters"] == [
        {"name": "required", "in": "query", "schema": _STRING, "required": True},
        {"name": "optionalKey", "in": "query", "schema": _STRING, "required": False},
        {"name": "optional", "in": "query", "schema": _STRING, "required": False},
    ]


def test_payload_option_post_no_content() -> None:
    """OpenAPI spec / endpoint / payload option / POST / NoContent"""
    spec = _spec(ep.post("a", "/a", payload=api_schema.NoContent))
    assert "requestBody" not in spec["paths"]["/a"]["post"]


def test_payload_option_post_no_content_and_payload() -> None:
    """OpenAPI spec / endpoint / payload option / POST / NoContent + payload"""
    spec = _spec(ep.post("a", "/a", payload=(api_schema.NoContent, S.String)))
    assert _request_content(spec) == _json(_STRING)


def test_payload_option_post_json_default() -> None:
    """OpenAPI spec / endpoint / payload option / POST / Json (default)"""
    assert _request_content(_spec(ep.post("a", "/a", payload=S.String))) == _json(_STRING)


def test_payload_encoding_as_multipart() -> None:
    """OpenAPI spec / endpoint / payload option / POST / encodings / asMultipart"""
    spec = _spec(ep.post("a", "/a", payload=api_schema.as_multipart(S.String)))
    assert _request_content(spec) == _json(_STRING, "multipart/form-data")


def test_payload_encoding_as_multipart_stream() -> None:
    """OpenAPI spec / endpoint / payload option / POST / encodings / asMultipartStream"""
    spec = _spec(ep.post("a", "/a", payload=api_schema.as_multipart_stream(S.String)))
    assert _request_content(spec) == _json(_STRING, "multipart/form-data")


def test_payload_encoding_as_json_with_content_type() -> None:
    """OpenAPI spec / endpoint / payload option / POST / encodings / asJson + contentType"""
    payload = api_schema.as_json(content_type="application/problem+json")(S.String)
    spec = _spec(ep.post("a", "/a", payload=payload))
    assert _request_content(spec) == _json(_STRING, "application/problem+json")


def test_payload_encoding_as_text() -> None:
    """OpenAPI spec / endpoint / payload option / POST / encodings / asText"""
    spec = _spec(ep.post("a", "/a", payload=api_schema.as_text()(S.String)))
    assert _request_content(spec) == _json(_STRING, "text/plain")


_A_STRUCT = _object({"a": _STRING}, ["a"])


def test_payload_encoding_as_form_url_encoded() -> None:
    """OpenAPI spec / endpoint / payload option / POST / encodings / asFormUrlEncoded"""
    payload = api_schema.as_form_url_encoded()(struct({"a": S.String}))
    spec = _spec(ep.post("a", "/a", payload=payload))
    assert _request_content(spec) == _json(_A_STRUCT, "application/x-www-form-urlencoded")


_BINARY: Json = {"type": "string", "format": "binary"}


def test_payload_encoding_as_uint8_array() -> None:
    """OpenAPI spec / endpoint / payload option / POST / encodings / asUint8Array"""
    spec = _spec(ep.post("a", "/a", payload=api_schema.as_uint8_array()(S.Bytes)))
    assert _request_content(spec) == _json(_BINARY, "application/octet-stream")


def test_payload_array_of_schemas_with_different_encodings() -> None:
    """OpenAPI spec / endpoint / payload option / POST / encodings / array of schemas with different encodings"""  # noqa: E501
    payload = (
        struct({"a": S.String}),
        api_schema.as_text()(S.String),
        api_schema.as_uint8_array()(S.Bytes),
    )
    spec = _spec(ep.post("a", "/a", payload=payload))
    assert _request_content(spec) == {
        "application/json": {"schema": _A_STRUCT},
        "text/plain": {"schema": _STRING},
        "application/octet-stream": {"schema": _BINARY},
    }


def test_as_multipart_with_files_schema() -> None:
    """OpenAPI spec / endpoint / payload option / POST / encodings / asMultipart with FilesSchema"""
    spec = _spec(ep.post("a", "/a", payload=api_schema.as_multipart(multipart.FilesSchema)))
    assert _request_content(spec) == _json(
        {"type": "array", "items": _BINARY}, "multipart/form-data"
    )


def test_as_multipart_with_single_file_schema() -> None:
    """OpenAPI spec / endpoint / payload option / POST / encodings / asMultipart with SingleFileSchema"""  # noqa: E501
    spec = _spec(ep.post("a", "/a", payload=api_schema.as_multipart(multipart.SingleFileSchema)))
    assert _request_content(spec) == _json(_BINARY, "multipart/form-data")


def test_as_multipart_with_single_file_schema_in_struct() -> None:
    """OpenAPI spec / endpoint / payload option / POST / encodings / asMultipart with SingleFileSchema in Struct"""  # noqa: E501
    payload = api_schema.as_multipart(struct({"file": multipart.SingleFileSchema}))
    spec = _spec(ep.post("a", "/a", payload=payload))
    assert _request_content(spec) == _json(
        _object({"file": _BINARY}, ["file"]), "multipart/form-data"
    )


def test_files_schema_in_non_multipart_payload_is_not_binary() -> None:
    """OpenAPI spec / endpoint / payload option / POST / encodings / FilesSchema in non-multipart payload should not be converted to binary"""  # noqa: E501
    spec = _spec(ep.post("a", "/a", payload=struct({"files": multipart.FilesSchema})))
    file = _object(
        {
            "key": _STRING,
            "name": _STRING,
            "contentType": {"type": "string", "contentEncoding": "binary"},
            "path": _STRING,
        },
        ["key", "name", "contentType", "path"],
    )
    assert _request_content(spec) == _json(
        _object({"files": {"type": "array", "items": file}}, ["files"])
    )


def test_success_no_content_default() -> None:
    """OpenAPI spec / endpoint / success option / no content (default)"""
    assert _responses(_spec(ep.get("a", "/a")))["204"] == {"description": "<No Content>"}


def test_success_schema() -> None:
    """OpenAPI spec / endpoint / success option / schema"""
    spec = _spec(ep.get("a", "/a", success=S.String))
    assert _responses(spec)["200"]["content"] == _json(_STRING)


def _no_content(success: _Schema, status: str) -> None:
    spec = _spec(ep.get("a", "/a", success=success))
    assert _responses(spec)[status] == {"description": "<No Content>"}


def test_success_empty_204() -> None:
    """OpenAPI spec / endpoint / success option / NoContent / makeNoContent(204)"""
    _no_content(api_schema.Empty(204), "204")


def test_success_no_content() -> None:
    """OpenAPI spec / endpoint / success option / NoContent / NoContent"""
    _no_content(api_schema.NoContent, "204")


def test_success_created() -> None:
    """OpenAPI spec / endpoint / success option / NoContent / Created"""
    _no_content(api_schema.Created, "201")


def test_success_status_created() -> None:
    """OpenAPI spec / endpoint / success option / NoContent / status("Created")"""
    _no_content(api_schema.status("Created")(api_schema.Void), "201")


def test_success_accepted() -> None:
    """OpenAPI spec / endpoint / success option / NoContent / Accepted"""
    _no_content(api_schema.Accepted, "202")


def _success_content(success: _Schema | tuple[_Schema, ...], status: str = "200") -> Json:
    return _responses(_spec(ep.get("a", "/a", success=success)))[status]["content"]


def test_success_encoding_as_json_with_content_type() -> None:
    """OpenAPI spec / endpoint / success option / encodings / asJson + contentType"""
    success = api_schema.as_json(content_type="application/problem+json")(S.String)
    assert _success_content(success) == _json(_STRING, "application/problem+json")


def test_success_encoding_as_text() -> None:
    """OpenAPI spec / endpoint / success option / encodings / asText"""
    assert _success_content(api_schema.as_text()(S.String)) == _json(_STRING, "text/plain")


def test_success_encoding_as_form_url_encoded() -> None:
    """OpenAPI spec / endpoint / success option / encodings / asFormUrlEncoded"""
    success = api_schema.as_form_url_encoded()(struct({"a": S.String}))
    assert _success_content(success) == _json(_A_STRUCT, "application/x-www-form-urlencoded")


def test_success_encoding_as_uint8_array() -> None:
    """OpenAPI spec / endpoint / success option / encodings / asUint8Array"""
    success = api_schema.as_uint8_array()(S.Bytes)
    assert _success_content(success) == _json(_BINARY, "application/octet-stream")


def _message_sse() -> api_schema.StreamSseSchema[Any, Any]:
    return api_schema.StreamSse(
        events=struct({"event": S.Literal("message"), "data": S.String}),
        error=struct({"message": S.String}),
    )


def test_success_encoding_stream_sse() -> None:
    """OpenAPI spec / endpoint / success option / encodings / StreamSse"""
    content = _success_content(_message_sse())
    stream = content["text/event-stream"]["x-effect-stream"]
    assert stream["encoding"] == "sse"
    assert stream["failureEvent"] == "effect/http-api/stream/failure"
    assert isinstance(stream["causeSchema"], dict)
    assert isinstance(stream["errorSchema"], dict)


def test_success_encoding_stream_sse_with_annotated_status() -> None:
    """OpenAPI spec / endpoint / success option / encodings / StreamSse with annotated status"""
    responses = _responses(_spec(ep.get("a", "/a", success=api_schema.status(202)(_message_sse()))))
    assert "200" not in responses
    assert responses["202"]["content"]["text/event-stream"]["x-effect-stream"]["encoding"] == "sse"


_BYTE_STREAM: Json = {
    "application/octet-stream": {"schema": _BINARY, "x-effect-stream": {"encoding": "uint8array"}}
}


def test_success_encoding_stream_uint8_array() -> None:
    """OpenAPI spec / endpoint / success option / encodings / StreamUint8Array"""
    assert _success_content(api_schema.StreamUint8Array()) == _BYTE_STREAM


def test_success_encoding_upgrade() -> None:
    """OpenAPI spec / endpoint / success option / encodings / Upgrade"""
    upgrade = api_schema.Upgrade(
        "tcp", headers=struct({"x-stream": S.Literals("raw", "multiplexed")})
    )
    spec = _spec(ep.post("a", "/a", payload=struct({"tty": S.Boolean}), success=upgrade))
    responses = _responses(spec, method="post")
    assert responses["101"] == {
        "description": "Switching Protocols",
        "headers": {
            "connection": {"schema": {"type": "string", "enum": ["Upgrade"]}, "required": True},
            "upgrade": {"schema": {"type": "string", "enum": ["tcp"]}, "required": True},
            "x-stream": {
                "schema": {"type": "string", "enum": ["raw", "multiplexed"]},
                "required": True,
            },
        },
    }
    assert list(_request_content(spec)) == ["application/json"]
    assert "200" not in responses


def test_success_encoding_upgrade_with_an_ordinary_success() -> None:
    """OpenAPI spec / endpoint / success option / encodings / Upgrade with an ordinary success"""
    success = (api_schema.Upgrade("tcp"), api_schema.Empty(200))
    responses = _responses(_spec(ep.post("a", "/a", success=success)), method="post")
    assert sorted(responses) == ["101", "200"]


def test_success_encoding_stream_uint8_array_with_annotated_status() -> None:
    """OpenAPI spec / endpoint / success option / encodings / StreamUint8Array with annotated status"""  # noqa: E501
    success = api_schema.status(206)(api_schema.StreamUint8Array())
    responses = _responses(_spec(ep.get("a", "/a", success=success)))
    assert "200" not in responses
    assert responses["206"]["content"] == _BYTE_STREAM


def test_success_union_with_top_level_encoding() -> None:
    """OpenAPI spec / endpoint / success option / encodings / union with top level encoding"""
    success = api_schema.as_form_url_encoded()(
        S.Union(struct({"a": S.String}), struct({"b": S.String}))
    )
    assert _success_content(success) == _json(
        {"anyOf": [_A_STRUCT, _object({"b": _STRING}, ["b"])]},
        "application/x-www-form-urlencoded",
    )


def test_success_as_json_and_as_text() -> None:
    """OpenAPI spec / endpoint / success option / encodings / asJson + astText"""
    content = _success_content((S.String, api_schema.as_text()(S.String)))
    assert content == {"application/json": {"schema": _STRING}, "text/plain": {"schema": _STRING}}


# --- error option ------------------------------------------------------------------


def test_should_deduplicate_the_descriptions() -> None:
    """OpenAPI spec / endpoint / error option / should deduplicate the descriptions"""
    spec = _spec(ep.post("a", "/a", error=api_error.BadRequestNoContent), group="users")
    assert _responses(spec, method="post")["400"] == {"description": "BadRequest"}
    assert spec["components"]["schemas"] == {}


def _string_post(path: str, error: _Schema) -> AnyEndpoint:
    return ep.post(path.strip("/"), path, payload=S.String, success=S.String, error=error)


def _error_responses(status: str, description: str, schema: Json) -> Json:
    return {
        "200": _success(_json(_STRING)),
        status: {"description": description, "content": _json(schema)},
    }


def test_one_endpoint_no_identifier_annotation() -> None:
    """OpenAPI spec / endpoint / error option / 1 endopoint / no identifier annotation"""
    spec = _spec(_string_post("/a", S.String), group="users")
    assert _responses(spec, method="post") == _error_responses("500", "Error", _STRING)
    assert spec["components"]["schemas"] == {}


_ID_REF: Json = {"$ref": "#/components/schemas/id"}


def test_one_endpoint_identifier_annotation() -> None:
    """OpenAPI spec / endpoint / error option / 1 endopoint / identifier annotation"""
    spec = _spec(_string_post("/a", S.String.annotate(identifier="id")), group="users")
    assert _responses(spec, method="post") == _error_responses("500", "id", _ID_REF)
    assert spec["components"]["schemas"] == {"id": _STRING}


def test_one_endpoint_http_api_status_annotation() -> None:
    """OpenAPI spec / endpoint / error option / 1 endopoint / httpApiStatus annotation"""
    spec = _spec(_string_post("/a", S.String.annotate(http_api_status=400)), group="users")
    assert _responses(spec, method="post") == _error_responses("400", "Error", _STRING)
    assert spec["components"]["schemas"] == {}


def test_two_endpoints_no_identifier_annotation() -> None:
    """OpenAPI spec / endpoint / error option / 2 endopoints / no identifier annotation"""
    error = S.String
    spec = _spec(_string_post("/a", error), _string_post("/b", error), group="users")
    for path in ("/a", "/b"):
        assert _responses(spec, path, "post") == _error_responses("500", "Error", _STRING)
    assert spec["components"]["schemas"] == {}


def test_two_endpoints_identifier_annotation() -> None:
    """OpenAPI spec / endpoint / error option / 2 endopoints / identifier annotation"""
    error = S.String.annotate(identifier="id")
    spec = _spec(_string_post("/a", error), _string_post("/b", error), group="users")
    for path in ("/a", "/b"):
        assert _responses(spec, path, "post") == _error_responses("500", "id", _ID_REF)
    assert spec["components"]["schemas"] == {"id": _STRING}


def test_two_endpoints_http_api_status_annotation() -> None:
    """OpenAPI spec / endpoint / error option / 2 endopoints / httpApiStatus annotation"""
    error = S.String.annotate(http_api_status=400)
    spec = _spec(_string_post("/a", error), _string_post("/b", error), group="users")
    for path in ("/a", "/b"):
        assert _responses(spec, path, "post") == _error_responses("400", "Error", _STRING)
    assert spec["components"]["schemas"] == {}


def _error_response(error: _Schema, status: str) -> Json:
    return _responses(_spec(ep.get("a", "/a", error=error)))[status]


def test_error_empty_400() -> None:
    """OpenAPI spec / endpoint / error option / No Content / makeNoContent(400)"""
    assert _error_response(api_schema.Empty(400), "400") == {"description": "<No Content>"}


def test_error_empty_401() -> None:
    """OpenAPI spec / endpoint / error option / No Content / Empty(401)"""
    assert _error_response(api_schema.Empty(401), "401") == {"description": "<No Content>"}


def test_error_unauthorized_no_content() -> None:
    """OpenAPI spec / endpoint / error option / No Content / UnauthorizedNoContent"""
    response = _error_response(api_error.UnauthorizedNoContent, "401")
    assert response == {"description": "Unauthorized"}


def test_error_bad_request_no_content() -> None:
    """OpenAPI spec / endpoint / error option / No Content / BadRequestNoContent"""
    response = _error_response(api_error.BadRequestNoContent, "400")
    assert response == {"description": "BadRequest"}
