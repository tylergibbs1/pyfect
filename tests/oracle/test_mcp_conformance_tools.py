"""Ports of Effect's MCP conformance tool titles
(test/ai/McpServer/McpConformance/ToolsTest.ts), run over stdio for every
revision whose test file runs the suite.

Effect runs these over its HTTP conformance harness; the stdio harness
serves the same tools, and the titles check the JSON-RPC results only.
Content tools take base64 ``data`` strings, so the image and audio tools
give ``"AQID"`` / ``"BAUG"`` where Effect builds them from a
``Uint8Array``.

Omitted:
- "should list shared tools and gate modern-only tools by era" checks the
  ``MrtrTool`` too: ``input_required`` round trips are not ported; the
  ``JsonSchema2020Tool`` half is "gates a modern-only tool by revision" here.
- "Tools > Modern request headers": the ``Mcp-Name`` title is in
  test_mcp_http_admission.py; the 3 ``Mcp-Param-*`` mirroring titles are not
  ported.
- "should send a tool list-change notification when the advertised list
  changes" reads ``flushListChanged``: list-change coalescing is not
  ported.
"""

from __future__ import annotations

import json
from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai._mcp.core import ToolEntry
from pyfect.context import Context

from ._mcp import Json, StdioHarness, stdio_harness

ALL = [P.v2024_11_05, P.v2025_03_26, P.v2025_06_18, P.v2025_11_25, P.v2026_07_28]
STATEFUL = [p for p in ALL if not p.is_stateless]
STRUCTURED = [p for p in ALL if p.protocol_version not in ("2024-11-05", "2025-03-26")]
MODERN = [P.v2026_07_28]


def _id(protocol: P.AnyProtocolAdapter) -> str:
    return protocol.protocol_version


class _Value(TypedDict):
    value: str


class _Structured(TypedDict):
    value: str


TestTool = T.make(
    "TestTool", description="A test tool", parameters=S.Struct(_Value), success=S.String
)
StructuredTool = T.make("StructuredTool", success=S.Struct(_Structured))
LogLevelTool = T.make("LogLevelTool", success=S.String)
RequestMetadataTool = T.make(
    "RequestMetadataTool", success=S.String, dependencies=[MS.McpRequestContext]
)
_KIT = K.make(TestTool, StructuredTool, LogLevelTool, RequestMetadataTool)

_JSON_SCHEMA_2020: Json = {
    "$schema": "https://json-schema.org/draft/2020-12/schema",
    "type": "object",
    "$defs": {"identifier": {"type": "string"}},
    "properties": {"value": {"$ref": "#/$defs/identifier"}},
    "allOf": [{"required": ["value"]}],
    "unevaluatedProperties": False,
}


def _content_tool(name: str, result: MS.CallToolResult) -> fx.Effect[None, Any, M.McpServer]:
    entry = ToolEntry(
        {"name": name, "inputSchema": {"type": "object", "properties": {}}},
        Context.empty(),
        lambda _: fx.succeed(result),
    )
    return M.McpServer().flat_map(lambda server: server.add_tool(entry))


def _features(invocations: list[str]) -> tuple[fx.Effect[None, Any, Any], ...]:
    """Effect's ``makeTestToolkitLayer`` and ``makeContentToolsLayer``."""

    def test_tool(params: _Value, _: object) -> fx.Effect[str]:
        return fx.sync(lambda: invocations.append("TestTool")).as_(params["value"])

    toolkit = M.register_toolkit(_KIT).pipe(
        fx.provide(
            _KIT.to_layer(
                TestTool.handler(test_tool),
                StructuredTool.handler(lambda _, __: fx.succeed({"value": "structured"})),
                LogLevelTool.handler(lambda _, __: fx.CurrentLogLevel().map(str)),
                RequestMetadataTool.handler(
                    lambda _, __: MS.McpRequestContext().map(
                        lambda context: json.dumps(context.request_metadata)
                    )
                ),
            )
        )
    )
    defect = ToolEntry(
        {"name": "DefectTool", "inputSchema": {"type": "object", "properties": {}}},
        Context.empty(),
        lambda _: fx.die(RuntimeError("private defect details")),
    )
    modern = ToolEntry(
        {"name": "JsonSchema2020Tool", "inputSchema": _JSON_SCHEMA_2020},
        Context.make(MS.EnabledWhen, lambda client: client.protocol_version == "2026-07-28"),
        lambda _: fx.succeed({"content": []}),
    )
    return (
        toolkit,
        _content_tool(
            "ImageTool", {"content": [{"type": "image", "data": "AQID", "mimeType": "image/png"}]}
        ),
        _content_tool(
            "EmbeddedResourceTool",
            {
                "content": [
                    {
                        "type": "resource",
                        "resource": {
                            "uri": "file:///embedded",
                            "mimeType": "text/plain",
                            "text": "embedded",
                        },
                    }
                ]
            },
        ),
        _content_tool(
            "MultipleContentTool",
            {"content": [{"type": "text", "text": "first"}, {"type": "text", "text": "second"}]},
        ),
        _content_tool(
            "ErrorTool",
            {"content": [{"type": "text", "text": "expected failure"}], "isError": True},
        ),
        M.McpServer().flat_map(lambda server: server.add_tool(defect)),
        M.McpServer().flat_map(lambda server: server.add_tool(modern)),
        _content_tool(
            "AudioTool", {"content": [{"type": "audio", "data": "BAUG", "mimeType": "audio/wav"}]}
        ),
        _content_tool(
            "ResourceLinkTool",
            {
                "content": [
                    {
                        "type": "resource_link",
                        "uri": "file:///test",
                        "name": "TestResource",
                        "mimeType": "text/plain",
                    }
                ]
            },
        ),
    )


def _server(
    protocol: P.AnyProtocolAdapter, invocations: list[str] | None = None
) -> fx.Effect[StdioHarness, Any, Any]:
    @fx.gen
    def run():
        harness = yield from stdio_harness(protocol, None, *_features(invocations or []))
        yield from harness.initialize()
        return harness

    return run


def _capabilities(protocol: P.AnyProtocolAdapter, *, features: bool) -> fx.Effect[Json, Any, Any]:
    @fx.gen
    def run():
        registrations = _features([]) if features else ()
        harness = yield from stdio_harness(protocol, None, *registrations)
        if protocol.is_stateless:
            reply = yield from harness.send_request("server/discover", {})
        else:
            reply = yield from harness.initialize()
        return reply["result"]["capabilities"]

    return run


def _tools(harness: StdioHarness) -> fx.Effect[list[Json]]:
    return harness.send_request("tools/list", {}).map(lambda reply: reply["result"]["tools"])


def _call(
    protocol: P.AnyProtocolAdapter, name: str, arguments: object = None
) -> fx.Effect[Json, Any, Any]:
    params: Json = {"name": name, "arguments": {} if arguments is None else arguments}
    return _server(protocol).flat_map(lambda harness: harness.send_request("tools/call", params))


def _string_content(protocol: P.AnyProtocolAdapter, text: str) -> list[Json]:
    """String results are mirrored as JSON only where they are also
    structured content (2026-07-28)."""
    modern = protocol.protocol_version == "2026-07-28"
    return [{"type": "text", "text": json.dumps(text) if modern else text}]


# --- Capabilities and listing -------------------------------------------------------------


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_advertise_the_tools_capability_when_tools_are_registered(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Tools / Capabilities / MUST advertise the tools capability when tools are registered"""  # noqa: E501
    assert "tools" in (yield from _capabilities(protocol, features=True))


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_not_advertise_the_tools_capability_when_not_supported(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Tools / Capabilities / MUST NOT advertise the tools capability when tools are not supported"""  # noqa: E501
    assert "tools" not in (yield from _capabilities(protocol, features=False))


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_schema_preserves_tool_names_and_descriptions(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools / Listing Tools / SCHEMA preserves tool names and descriptions"""
    tools = yield from _tools((yield from _server(protocol)))
    assert next(t for t in tools if t["name"] == "TestTool")["description"] == "A test tool"


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_return_each_tool_input_schema(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools / Listing Tools / MUST return each tool input schema"""
    tools = yield from _tools((yield from _server(protocol)))
    assert all(t["inputSchema"]["type"] == "object" for t in tools)


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_gates_a_modern_only_tool_by_revision(protocol: P.AnyProtocolAdapter):
    """Not an Effect title: the JsonSchema2020Tool half of "should list shared
    tools and gate modern-only tools by era"."""
    names = {t["name"] for t in (yield from _tools((yield from _server(protocol))))}
    assert {"TestTool", "StructuredTool", "LogLevelTool", "RequestMetadataTool"} <= names
    assert ("JsonSchema2020Tool" in names) == protocol.is_stateless


# --- Calling tools ------------------------------------------------------------------------


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_call_a_registered_tool_with_valid_arguments(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools / Calling Tools / MUST call a registered tool with valid arguments"""
    result = (yield from _call(protocol, "TestTool", {"value": "called"}))["result"]
    assert result.get("isError", False) is False
    assert result["content"] == _string_content(protocol, "called")


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_reject_an_unknown_tool_name_with_a_protocol_error(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools / Calling Tools / MUST reject an unknown tool name with a protocol error"""  # noqa: E501
    invocations: list[str] = []
    harness = yield from _server(protocol, invocations)
    reply = yield from harness.send_request("tools/call", {"name": "UnknownTool", "arguments": {}})
    assert reply["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE
    assert invocations == []


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_schema_returns_text_content(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools / Calling Tools / SCHEMA returns text content"""
    result = (yield from _call(protocol, "TestTool", {"value": "text"}))["result"]
    assert result["content"] == _string_content(protocol, "text")


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_schema_returns_image_content(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools / Calling Tools / SCHEMA returns image content"""
    result = (yield from _call(protocol, "ImageTool"))["result"]
    assert result["content"] == [{"type": "image", "data": "AQID", "mimeType": "image/png"}]


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_schema_returns_embedded_resources(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools / Calling Tools / SCHEMA returns embedded resources"""
    result = (yield from _call(protocol, "EmbeddedResourceTool"))["result"]
    assert result["content"] == [
        {
            "type": "resource",
            "resource": {"uri": "file:///embedded", "mimeType": "text/plain", "text": "embedded"},
        }
    ]


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_return_multiple_content_items_in_order(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools / Calling Tools / MUST return multiple content items in order"""
    result = (yield from _call(protocol, "MultipleContentTool"))["result"]
    assert result["content"] == [
        {"type": "text", "text": "first"},
        {"type": "text", "text": "second"},
    ]


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_return_tool_execution_failures_with_is_error(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools / Calling Tools / MUST return tool execution failures with isError"""
    result = (yield from _call(protocol, "ErrorTool"))["result"]
    assert result["isError"] is True
    assert result["content"] == [{"type": "text", "text": "expected failure"}]


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_must_keep_tool_execution_errors_distinct_from_protocol_errors(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Tools / Calling Tools / MUST keep tool execution errors distinct from protocol errors"""  # noqa: E501
    harness = yield from _server(protocol)
    execution = yield from harness.send_request(
        "tools/call", {"name": "ErrorTool", "arguments": {}}
    )
    error = yield from harness.send_request("tools/call", {"name": "UnknownTool", "arguments": {}})
    assert execution["result"]["isError"] is True
    assert error["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_should_not_expose_defects_or_internal_error_details(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools / Calling Tools / SHOULD not expose defects or internal error details"""  # noqa: E501
    reply = yield from _call(protocol, "DefectTool")
    assert reply["error"]["code"] == MS.INTERNAL_ERROR_CODE
    assert reply["error"]["message"] == "Internal error"
    assert "private defect details" not in json.dumps(reply)


@pytest.mark.parametrize(
    "protocol", [p for p in ALL if p.protocol_version != "2024-11-05"], ids=_id
)
@testing.effect
def test_should_return_base64_audio_content(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools / Calling Tools / should return base64 audio content when an audio tool is called"""  # noqa: E501
    result = (yield from _call(protocol, "AudioTool"))["result"]
    assert result["content"] == [{"type": "audio", "data": "BAUG", "mimeType": "audio/wav"}]


@pytest.mark.parametrize("protocol", STRUCTURED, ids=_id)
@testing.effect
def test_should_advertise_an_object_output_schema(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools / Calling Tools / Structured content / should advertise an object output schema when a tool declares one"""  # noqa: E501
    tools = yield from _tools((yield from _server(protocol)))
    structured = next(t for t in tools if t["name"] == "StructuredTool")
    assert structured["outputSchema"]["type"] == "object"


@pytest.mark.parametrize("protocol", STRUCTURED, ids=_id)
@testing.effect
def test_should_return_a_resource_link(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools / Calling Tools / Structured content / should return a resource link when a resource-link tool is called"""  # noqa: E501
    result = (yield from _call(protocol, "ResourceLinkTool"))["result"]
    assert result["content"] == [
        {
            "type": "resource_link",
            "uri": "file:///test",
            "name": "TestResource",
            "mimeType": "text/plain",
        }
    ]


@pytest.mark.parametrize("protocol", STRUCTURED, ids=_id)
@testing.effect
def test_should_return_structured_content(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools / Calling Tools / Structured content / should return structured content when a structured tool is called"""  # noqa: E501
    result = (yield from _call(protocol, "StructuredTool"))["result"]
    assert result["structuredContent"] == {"value": "structured"}


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_distinguishes_malformed_requests_from_tool_validation_errors(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Tools / Calling Tools / distinguishes malformed requests from tool validation errors by protocol revision"""  # noqa: E501
    invocations: list[str] = []
    harness = yield from _server(protocol, invocations)

    def request(arguments: object) -> fx.Effect[Json]:
        return harness.send_request("tools/call", {"name": "TestTool", "arguments": arguments})

    malformed = yield from request("invalid")
    assert malformed["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE
    reply = yield from request({"value": 123})
    if protocol.protocol_version in ("2024-11-05", "2025-03-26", "2025-06-18"):
        assert reply["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE
        text = reply["error"]["message"]
    else:
        result = reply["result"]
        assert result["isError"] is True
        assert "structuredContent" not in result
        assert len(result["content"]) == 1
        assert result["content"][0]["type"] == "text"
        text = result["content"][0]["text"]
    assert "Invalid parameters for tool 'TestTool'" in text
    assert "Expected string" in text
    for internal in ("AiError", "ToolParameterValidationError", "Toolkit", "TestTool.handle"):
        assert internal not in text
    assert invocations == []


# --- Stateless modern suite ---------------------------------------------------------------


@pytest.mark.parametrize("protocol", MODERN, ids=_id)
@testing.effect
def test_should_preserve_2020_12_keywords_when_listing_an_input_schema(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Tools > JSON Schema 2020-12 / should preserve 2020-12 keywords when listing an input schema"""  # noqa: E501
    tools = yield from _tools((yield from _server(protocol)))
    assert next(t for t in tools if t["name"] == "JsonSchema2020Tool")["inputSchema"] == (
        _JSON_SCHEMA_2020
    )


@pytest.mark.parametrize("protocol", MODERN, ids=_id)
@testing.effect
def test_should_list_a_non_object_output_schema(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools > JSON Schema 2020-12 / should list a non-object output schema when the tool declares one"""  # noqa: E501
    tools = yield from _tools((yield from _server(protocol)))
    assert next(t for t in tools if t["name"] == "TestTool")["outputSchema"] == {"type": "string"}


@pytest.mark.parametrize("protocol", MODERN, ids=_id)
@testing.effect
def test_should_return_primitive_structured_content(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools > JSON Schema 2020-12 / should return primitive structured content when declared by the tool"""  # noqa: E501
    result = (yield from _call(protocol, "TestTool", {"value": "called"}))["result"]
    assert result["structuredContent"] == "called"


@pytest.mark.parametrize("protocol", MODERN, ids=_id)
@testing.effect
def test_should_return_tools_in_the_same_order_when_unchanged(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools > Modern listing / should return tools in the same order when the registered inventory has not changed"""  # noqa: E501
    harness = yield from _server(protocol)
    first = [t["name"] for t in (yield from _tools(harness))]
    second = [t["name"] for t in (yield from _tools(harness))]
    assert first == second


# --- Stateful legacy suite ----------------------------------------------------------------


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_reject_malformed_tool_parameters_without_invoking_a_handler(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Tools > Legacy validation / should reject malformed tool parameters without invoking a handler"""  # noqa: E501
    invocations: list[str] = []
    harness = yield from _server(protocol, invocations)
    reply = yield from harness.send_request("tools/call", {"arguments": {"value": "called"}})
    assert reply["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE
    assert invocations == []


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_advertise_tool_list_change_notifications(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Tools > Legacy notifications / should advertise tool list-change notifications when supported"""  # noqa: E501
    capabilities = yield from _capabilities(protocol, features=True)
    assert capabilities["tools"]["listChanged"] is True
