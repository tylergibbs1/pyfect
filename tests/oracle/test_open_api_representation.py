"""Ports of Effect's ``httpapi/OpenApiRepresentation.test.ts``. Each test's
docstring is the Effect test title, prefixed by its ``describe`` blocks.

``Schema.Date`` is ``S.DateTimeUtc`` (a declaration encoded to a JSON
string). Options are the keyword functions of ``from_api``, so "options
identity" is the identity of those functions.
"""

from typing import Any

import pytest

from pyfect import schema as S
from pyfect.http_api import endpoint as ep
from pyfect.http_api import openapi
from pyfect.http_api import schema as api_schema
from pyfect.http_api.api import AdditionalSchemas, HttpApi
from pyfect.http_api.group import HttpApiGroup

from ._http_api import struct


def _api(*endpoints: Any) -> HttpApi[Any]:
    return HttpApi.make("Api").add(HttpApiGroup.make("test").add(*endpoints))


def _object(properties: dict[str, Any], required: list[str]) -> dict[str, Any]:
    return {
        "type": "object",
        "properties": properties,
        "required": required,
        "additionalProperties": False,
    }


def _success(spec: dict[str, Any], path: str, method: str = "get", status: str = "200") -> Any:
    return spec["paths"][path][method]["responses"][status]["content"]["application/json"]["schema"]


_ADDITIONAL_DATE = S.DateTimeUtc.annotate(identifier="AdditionalDate")


def test_uses_canonical_json_codecs_for_additional_declaration_schemas() -> None:
    """OpenApi representation v2 consumer / uses canonical JSON codecs for additional declaration schemas"""  # noqa: E501
    api = HttpApi.make("Api").annotate(AdditionalSchemas, (_ADDITIONAL_DATE,))
    assert openapi.from_api(api)["components"]["schemas"] == {
        "AdditionalDate": {"$ref": "#/components/schemas/AdditionalDateEncoded"},
        "AdditionalDateEncoded": {"type": "string"},
    }


def test_applies_the_reference_policy_without_removing_additional_schema_components() -> None:
    """OpenApi representation v2 consumer / applies the reference policy without removing additional schema components"""  # noqa: E501
    api = (
        HttpApi.make("Api")
        .annotate(AdditionalSchemas, (_ADDITIONAL_DATE,))
        .add(HttpApiGroup.make("test").add(ep.get("date", "/date", success=_ADDITIONAL_DATE)))
    )
    spec = openapi.from_api(api, reference_policy=lambda _candidate: None)
    assert spec["components"]["schemas"] == {"AdditionalDate": {"type": "string"}}
    assert _success(spec, "/date") == {"type": "string"}


def test_includes_selected_custom_annotation_keys() -> None:
    """OpenApi representation v2 consumer / includes selected custom annotation keys"""
    value = S.String.annotate(identifier="Value", **{"x-test-brand": "Value"})
    api = _api(ep.get("value", "/value", success=value))
    included = openapi.from_api(api, include_annotation_key=lambda key: key == "x-test-brand")
    assert included["components"]["schemas"] == {
        "Value": {"type": "string", "x-test-brand": "Value"}
    }
    assert openapi.from_api(api)["components"]["schemas"] == {"Value": {"type": "string"}}


def test_uses_canonical_json_codecs_for_response_declaration_schemas() -> None:
    """OpenApi representation v2 consumer / uses canonical JSON codecs for response declaration schemas"""  # noqa: E501
    api = _api(ep.get("date", "/date", success=S.DateTimeUtc))
    assert _success(openapi.from_api(api), "/date") == {"type": "string"}


def test_includes_definitions_reachable_only_through_sse_content() -> None:
    """OpenApi representation v2 consumer / includes definitions reachable only through SSE content"""  # noqa: E501
    nested = struct({"text": S.String}).annotate(identifier="Nested")
    content = struct({"nested": nested}).annotate(identifier="Content")
    api = _api(ep.get("stream", "/stream", success=api_schema.StreamSse(data=content)))
    assert openapi.from_api(api)["components"]["schemas"] == {
        "Nested": _object({"text": {"type": "string"}}, ["text"]),
        "Content": _object({"nested": {"$ref": "#/components/schemas/Nested"}}, ["nested"]),
        "ContentEncoded": {
            "type": "string",
            "contentMediaType": "application/json",
            "contentSchema": {"$ref": "#/components/schemas/Content"},
        },
    }


def test_shares_content_definitions_across_regular_json_and_sse_responses() -> None:
    """OpenApi representation v2 consumer / shares content definitions across regular JSON and SSE responses"""  # noqa: E501
    content = struct({"text": S.String}).annotate(identifier="Tool.Content")
    api = _api(
        ep.get("content", "/content", success=content),
        ep.get("stream", "/stream", success=api_schema.StreamSse(data=content)),
    )
    spec = openapi.from_api(api)
    assert spec["components"]["schemas"] == {
        "Tool.Content": _object({"text": {"type": "string"}}, ["text"]),
        "Tool.ContentEncoded": {
            "type": "string",
            "contentMediaType": "application/json",
            "contentSchema": {"$ref": "#/components/schemas/Tool.Content"},
        },
    }
    assert _success(spec, "/content") == {"$ref": "#/components/schemas/Tool.Content"}
    stream = spec["paths"]["/stream"]["get"]["responses"]["200"]["content"]["text/event-stream"]
    assert stream["schema"] == _object(
        {
            # Effect's ``optional(String)`` also allows ``undefined`` (null in
            # JSON Schema); a Python ``NotRequired[str]`` key holds a string.
            "id": {"type": "string"},
            "event": {"type": "string"},
            "data": {"$ref": "#/components/schemas/Tool.ContentEncoded"},
        },
        ["event", "data"],
    )


def test_projects_request_and_response_schemas_to_the_encoded_side() -> None:
    """OpenApi representation v2 consumer / projects request and response schemas to the encoded side"""  # noqa: E501
    api = _api(ep.post("create", "/create", payload=S.FiniteFromString, success=S.FiniteFromString))
    spec = openapi.from_api(api)
    body = spec["paths"]["/create"]["post"]["requestBody"]["content"]["application/json"]
    assert body["schema"] == {"type": "string"}
    assert _success(spec, "/create", "post") == {"type": "string"}


def _min_two_characters(_context: S.CheckContext) -> dict[str, int]:
    return {"minLength": 2}


def test_uses_custom_json_schema_compiler_annotations() -> None:
    """OpenApi representation v2 consumer / uses custom JSON Schema compiler annotations"""
    custom = S.String.check(
        S.make_filter(
            lambda value: len(value) >= 2,
            representation={"id": "test/openapi/minTwoCharacters", "payload": None},
            to_json_schema=_min_two_characters,
        )
    )
    api = _api(ep.post("create", "/create", payload=custom))
    body = openapi.from_api(api)["paths"]["/create"]["post"]["requestBody"]["content"]
    assert body["application/json"]["schema"] == {"type": "string", "minLength": 2}


def test_shares_definitions_and_returns_cached_copies_by_api_identity() -> None:
    """OpenApi representation v2 consumer / shares definitions and returns cached copies by API identity"""  # noqa: E501
    shared = struct({"value": S.FiniteFromString}).annotate(identifier="Shared")
    api = _api(
        ep.post(
            "shared", "/shared", payload=struct({"first": shared, "second": shared}), success=shared
        )
    )
    first = openapi.from_api(api)
    second = openapi.from_api(api)
    assert second is not first
    assert second == first
    assert first["components"]["schemas"]["Shared"] == _object(
        {"value": {"type": "string"}}, ["value"]
    )


_BASE = struct({"id": S.String, "metadata": S.Record(S.String, S.Unknown)})


@pytest.mark.parametrize(
    "schema",
    [
        pytest.param(_BASE, id="plain"),
        pytest.param(_BASE.check(S.is_min_properties(1)), id="checked"),
        pytest.param(_BASE.pipe(api_schema.status(200)), id="with key context"),
    ],
)
def test_shares_a_named_schema_across_response_statuses(schema: Any) -> None:
    """OpenApi representation v2 consumer / shares a named schema across response statuses / $name"""  # noqa: E501
    widget = schema.annotate(identifier="Widget")
    api = _api(
        ep.get("get", "/widget", success=widget),
        ep.post("create", "/widget", success=widget.pipe(api_schema.status(201))),
    )
    spec = openapi.from_api(api)
    assert list(spec["components"]["schemas"]) == ["Widget"]
    assert _success(spec, "/widget") == {"$ref": "#/components/schemas/Widget"}
    assert _success(spec, "/widget", "post", "201") == {"$ref": "#/components/schemas/Widget"}


def test_retains_referenced_parameter_schemas_without_emitting_the_parameter_container() -> None:
    """OpenApi representation v2 consumer / retains referenced parameter schemas without emitting the parameter container"""  # noqa: E501
    filter_ = struct({"value": S.String}).annotate(identifier="Filter")
    query = struct({"filter": filter_}).annotate(identifier="Query")
    spec = openapi.from_api(_api(ep.get("list", "/list", query=query)))
    assert spec["paths"]["/list"]["get"]["parameters"] == [
        {
            "name": "filter",
            "in": "query",
            "required": True,
            "schema": {"$ref": "#/components/schemas/Filter"},
        }
    ]
    assert spec["components"]["schemas"] == {
        "Filter": _object({"value": {"type": "string"}}, ["value"])
    }


def test_caches_generated_specs_by_api_and_options_identity() -> None:
    """OpenApi representation v2 consumer / caches generated specs by API and options identity"""
    api = _api(ep.get("value", "/value", success=struct({"value": S.String})))
    calls = 0

    def policy(candidate: S.ReferenceCandidate) -> str | None:
        nonlocal calls
        calls += 1
        return candidate.identifier

    def other_policy(candidate: S.ReferenceCandidate) -> str | None:
        return policy(candidate)

    openapi.from_api(api, reference_policy=policy)
    after_first = calls
    assert after_first > 0
    openapi.from_api(api, reference_policy=policy)
    assert calls == after_first
    openapi.from_api(api, reference_policy=other_policy)
    assert calls > after_first
