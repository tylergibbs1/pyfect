"""Ports of titles of Effect's ``test/ai/McpServer/ProtocolAdapters.test.ts``
(tool failures by revision, duplicate tools) and the result-envelope
titles of ``v2026_07_28.test.ts``, plus cases Effect's tests leave open,
each run under Node first.

Each test's docstring is the Effect test title (with its ``describe``), or
says it is not one.

Omitted, with the reason:

- The other ``ProtocolAdapters.test.ts`` titles (field projection of
  descriptors, binary and embedded content, notifications per revision,
  client profiles, continuation input, log-level isolation, registration
  request context, elicitation gating, malformed modern metadata): not
  ported in this pass; their fixture needs the per-revision HTTP harness.
- The other ``v2026_07_28.test.ts`` titles: they run on Effect's
  ``McpConformance`` suite (routing headers and ``-32020`` header
  mismatches, request metadata validation, ``input_required`` multi
  round-trips), none of which is ported.
- ``v2024_11_05`` / ``v2025_03_26`` / ``v2025_06_18`` / ``v2025_11_25.test.ts``:
  conformance-suite runs (not ported, as above), except their own titles
  ``MUST NOT advertise completions`` (2024-11-05) and ``does not expose
  experimental Tasks without an extension`` (2025-11-25), which are here;
  the 2025-03-26 ones are about JSON-RPC batches, which are not ported.
- ``Workerd.test.ts``: Cloudflare's workerd runtime, inapplicable.
- ``LayerHttpRequestScoped.test.ts``: ``layerHttpRequestScoped`` is not
  ported.
"""

from __future__ import annotations

import json
from typing import Any, TypedDict, cast

import pyfect as fx
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai._mcp.core import ToolEntry
from pyfect.context import Context
from pyfect.http import request as R
from pyfect.http.client import HttpClientService
from pyfect.http.response import HttpClientResponse

from ._mcp import CLIENT_INFO, StdioHarness, in_memory_http, stdio_harness

SERVER_INFO_META = "io.modelcontextprotocol/serverInfo"
SERVER_INFO = {"name": "test-server", "version": "1.0.0"}


def _capabilities_tool(name: str = "capability") -> fx.Effect[None, Any, M.McpServer]:
    """A tool answering with the client capabilities of its request."""

    def handle(_: object) -> fx.Effect[MS.CallToolResult, Any, Any]:
        return MS.McpRequestContext().map(
            lambda request: cast(
                "MS.CallToolResult",
                {"content": [{"type": "text", "text": json.dumps(request.client_capabilities)}]},
            )
        )

    entry = ToolEntry({"name": name, "inputSchema": {"type": "object"}}, Context.empty(), handle)
    return M.McpServer().flat_map(lambda server: server.add_tool(entry))


class Required(TypedDict):
    required: str


_FEATURES: tuple[fx.Effect[None, Any, Any], ...] = (
    _capabilities_tool("TestTool"),
    M.register_prompt(name="NoArgumentPrompt", content=lambda _: fx.succeed("Hello")),
    M.register_prompt(
        name="TestPrompt",
        parameters=S.Struct(Required),
        completion={"required": lambda value, _: fx.succeed([f"{value}oo"])},
        content=lambda p: fx.succeed(p["required"]),
    ),
    M.register_resource(uri="file:///test", name="test", content=fx.succeed("test")),
    M.register_resource_template(
        M.uri_template("file:///docs/", S.String),
        name="docs",
        content=lambda _uri, name: fx.succeed(name),
    ),
)


def _modern(capabilities: dict[str, Any] | None = None) -> dict[str, Any]:
    return {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientInfo": CLIENT_INFO,
        "io.modelcontextprotocol/clientCapabilities": capabilities or {},
    }


def _features() -> fx.Effect[StdioHarness, Any, Any]:
    return stdio_harness(P.v2026_07_28, None, *_FEATURES)


@testing.effect
def test_attaches_cache_metadata_to_every_cacheable_operation():
    """McpServer 2026-07-28 / Result envelopes / should attach modern result and cache metadata to every cacheable operation"""  # noqa: E501
    harness = yield from _features()
    cases: list[tuple[str, dict[str, Any]]] = [
        ("server/discover", {}),
        ("tools/list", {}),
        ("prompts/list", {}),
        ("resources/list", {}),
        ("resources/templates/list", {}),
        ("resources/read", {"uri": "file:///test"}),
    ]
    for method, params in cases:
        result = (yield from harness.send_request(method, params))["result"]
        assert result["resultType"] == "complete", method
        assert isinstance(result["ttlMs"], int), method
        assert result["ttlMs"] >= 0, method
        assert result["cacheScope"] in ("public", "private"), method
        assert result["_meta"][SERVER_INFO_META] == SERVER_INFO, method


@testing.effect
def test_attaches_result_type_and_identity_to_every_non_cacheable_operation():
    """McpServer 2026-07-28 / Result envelopes / should attach a complete result type and server identity to every non-cacheable operation"""  # noqa: E501
    harness = yield from _features()
    cases: list[tuple[str, dict[str, Any]]] = [
        ("tools/call", {"name": "TestTool", "arguments": {"value": "called"}}),
        ("prompts/get", {"name": "NoArgumentPrompt", "arguments": {}}),
        (
            "completion/complete",
            {
                "ref": {"type": "ref/prompt", "name": "TestPrompt"},
                "argument": {"name": "required", "value": "f"},
            },
        ),
    ]
    for method, params in cases:
        result = (yield from harness.send_request(method, params))["result"]
        assert result["resultType"] == "complete", method
        assert result["_meta"][SERVER_INFO_META] == SERVER_INFO, method


def _text(reply: dict[str, Any]) -> str:
    return reply["result"]["content"][0]["text"]


@testing.effect
def test_isolates_interleaved_stateful_and_stateless_contexts_over_stdio():
    """Not an Effect title: ProtocolAdapters' ``should isolate interleaved
    stateful and stateless request contexts`` over one stdio connection,
    where a stateless request must not change the session's client."""
    harness = yield from stdio_harness(
        P.v2025_11_25, [P.v2026_07_28, P.v2025_11_25], _capabilities_tool()
    )
    yield from harness.initialize({"roots": {}})
    assert _text((yield from harness.send_request("tools/call", {"name": "capability"}))) == (
        json.dumps({"roots": {}})
    )
    modern = {"name": "capability", "_meta": _modern({"sampling": {}})}
    assert _text((yield from harness.send_request("tools/call", modern))) == (
        json.dumps({"sampling": {}})
    )
    assert _text((yield from harness.send_request("tools/call", {"name": "capability"}))) == (
        json.dumps({"roots": {}})
    )


@testing.effect
def test_serves_concurrent_stateless_requests_with_their_own_clients():
    """Not an Effect title: two stateless stdio requests sent before either
    is answered each see their own client capabilities."""
    harness = yield from stdio_harness(P.v2026_07_28, None, _capabilities_tool())
    cases: list[tuple[int, dict[str, Any]]] = [(1, {"roots": {}}), (2, {"sampling": {}})]
    for id, capabilities in cases:
        params = {"name": "capability", "_meta": _modern(capabilities)}
        yield from harness.send(
            {"jsonrpc": "2.0", "id": id, "method": "tools/call", "params": params}
        )
    replies = [(yield from harness.receive()), (yield from harness.receive())]
    assert {reply["id"]: _text(reply) for reply in replies} == {
        1: json.dumps({"roots": {}}),
        2: json.dumps({"sampling": {}}),
    }


URL = "http://localhost/mcp"


def _post(
    http: HttpClientService[Any, Any], body: object, headers: dict[str, str] | None = None
) -> fx.Effect[HttpClientResponse, Any]:
    request = (
        R.post(URL)
        .set_headers({"accept": "application/json, text/event-stream", **(headers or {})})
        .body_text(json.dumps(body), "application/json")
    )
    return http.execute(request)


@testing.effect
def test_answers_a_cancelled_http_request_with_an_empty_event_stream():
    """Not an Effect title: a POST whose request the session cancels ends
    with an empty event stream (Effect's ``layerHttp`` comment: "Only fully
    cancelled request POSTs may return an empty SSE response")."""

    def hang(_: object) -> fx.Effect[MS.CallToolResult]:
        return fx.never

    entry = ToolEntry({"name": "hang", "inputSchema": {"type": "object"}}, Context.empty(), hang)
    registration = layer.effect_discard(
        M.McpServer().flat_map(lambda server: server.add_tool(entry))
    ).pipe(layer.provide(M.layer))
    app = layer.merge(
        M.layer_http(name="test-server", version="1.0.0", path="/mcp", protocols=(P.v2025_11_25,)),
        registration,
    )
    http = yield from in_memory_http(app)
    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": CLIENT_INFO},
    }
    session = (yield from _post(http, initialize)).headers.get("mcp-session-id")
    assert session is not None
    headers = {"mcp-session-id": session, "mcp-protocol-version": "2025-11-25"}
    yield from _post(http, {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers)
    call = {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "hang"}}
    pending = yield from _post(http, call, headers).fork()
    for _ in range(10):
        yield from fx.yield_now()
    cancel = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 2}}
    assert (yield from _post(http, cancel, headers)).status == 202
    response = yield from pending.join()
    assert response.status == 200
    assert response.headers.get("content-type", "").startswith("text/event-stream")
    assert (yield from response.text) == ""


def _low_level_tools() -> fx.Effect[None, Any, M.McpServer]:
    """ProtocolAdapters' low-level fixture: a tool failing with an internal
    error and a name registered twice."""

    def failing(_: object) -> fx.Effect[MS.CallToolResult, MS.InternalError]:
        return fx.fail(MS.InternalError("database unavailable"))

    def answer(text: str) -> Any:
        def handle(_: object) -> fx.Effect[MS.CallToolResult]:
            return fx.succeed({"content": [{"type": "text", "text": text}]})

        return handle

    def entry(name: str, handle: Any, description: str | None = None) -> ToolEntry:
        tool: MS.Tool = {"name": name, "inputSchema": {"type": "object", "properties": {}}}
        if description is not None:
            tool["description"] = description
        return ToolEntry(tool, Context.empty(), handle)

    @fx.gen
    def run():
        server = yield from M.McpServer()
        yield from server.add_tool(entry("internal-failure", failing))
        yield from server.add_tool(entry("duplicate", answer("first"), "first descriptor"))
        yield from server.add_tool(entry("duplicate", answer("second"), "second descriptor"))

    return run


def _initialized(protocol: P.AnyProtocolAdapter) -> fx.Effect[StdioHarness, Any, Any]:
    @fx.gen
    def run():
        harness = yield from stdio_harness(protocol, None, _low_level_tools())
        yield from harness.initialize()
        return harness

    return run


@testing.effect
def test_returns_an_error_result_for_tool_execution_failures_on_2025_11_25():
    """McpServer protocol adapters / should return an error result for tool execution failures on 2025-11-25"""  # noqa: E501
    harness = yield from _initialized(P.v2025_11_25)
    result = (yield from harness.send_request("tools/call", {"name": "internal-failure"}))["result"]
    assert result["isError"] is True
    assert result["content"] == [{"type": "text", "text": "database unavailable"}]


@testing.effect
def test_reports_tool_execution_failures_as_internal_errors_on_older_revisions():
    """McpServer protocol adapters / should report tool execution failures as internal errors on older revisions"""  # noqa: E501
    for protocol in (P.v2025_06_18, P.v2025_03_26, P.v2024_11_05):
        harness = yield from _initialized(protocol)
        reply = yield from harness.send_request("tools/call", {"name": "internal-failure"})
        assert reply["error"]["code"] == MS.INTERNAL_ERROR_CODE
        assert reply["error"]["message"] == "database unavailable"


@testing.effect
def test_lists_and_invokes_the_latest_tool_when_a_name_is_registered_twice():
    """McpServer protocol adapters / should list and invoke the latest tool when a name is registered twice"""  # noqa: E501
    for protocol in (P.v2025_06_18, P.v2024_11_05):
        harness = yield from _initialized(protocol)
        listed = (yield from harness.send_request("tools/list", {}))["result"]["tools"]
        duplicates = [tool for tool in listed if tool["name"] == "duplicate"]
        assert [tool["description"] for tool in duplicates] == ["second descriptor"]
        result = (yield from harness.send_request("tools/call", {"name": "duplicate"}))["result"]
        assert result["content"] == [{"type": "text", "text": "second"}]


class Params(TypedDict):
    first: str
    second: float


def _strict_input_tool() -> fx.Effect[None, Any, M.McpServer]:
    tool = T.make("T", parameters=S.Struct(Params), success=S.String)
    kit = K.make(tool)
    handlers = kit.to_layer(tool.handler(lambda _, __: fx.succeed("ok")))
    return M.register_toolkit(kit).pipe(fx.provide(handlers))


INVALID_INPUT = (
    "Invalid parameters for tool 'T': Expected string\n  at [\"first\"]\n"
    'Missing key\n  at ["second"]'
)


@testing.effect
def test_answers_invalid_tool_input_by_revision():
    """Not an Effect title: invalid tool arguments are an ``isError`` result
    from 2025-11-25 on and an invalid-params error before, and an unknown
    tool is an invalid-params error on every revision (Effect under Node)."""
    for protocol in (P.v2024_11_05, P.v2025_06_18, P.v2025_11_25, P.v2026_07_28):
        harness = yield from stdio_harness(protocol, None, _strict_input_tool())
        yield from harness.initialize()
        arguments = {"first": 1, "extra": True}
        invalid = yield from harness.send_request(
            "tools/call", {"name": "T", "arguments": arguments}
        )
        if protocol.reports_tool_errors_as_results:
            assert invalid["result"]["isError"] is True
            assert invalid["result"]["content"] == [{"type": "text", "text": INVALID_INPUT}]
        else:
            assert invalid["error"] == {
                "code": MS.INVALID_PARAMS_ERROR_CODE,
                "message": INVALID_INPUT,
            }
        unknown = yield from harness.send_request("tools/call", {"name": "Nope"})
        assert unknown["error"] == {
            "code": MS.INVALID_PARAMS_ERROR_CODE,
            "message": "Tool 'Nope' not found",
        }


class Answer(TypedDict):
    answer: str


Str = T.make("Str", success=S.String)
Untyped = T.make("Untyped")
Obj = T.make("Obj", success=S.Struct(Answer))
Arr = T.make("Arr", success=S.Array(S.Int))
_outputs = K.make(Str, Untyped, Obj, Arr)
_output_handlers = _outputs.to_layer(
    Str.handler(lambda _, __: fx.succeed("hi")),
    Untyped.handler(lambda _, __: fx.void),
    Obj.handler(lambda _, __: fx.succeed(Answer(answer="a"))),
    Arr.handler(lambda _, __: fx.succeed((1, 2))),
)
OBJECT_SCHEMA = {
    "type": "object",
    "properties": {"answer": {"type": "string"}},
    "required": ["answer"],
    "additionalProperties": True,
}


@testing.effect
def test_projects_non_object_toolkit_outputs_only_for_the_july_protocol():
    """McpServer protocol adapters / should project non-object JSON Toolkit outputs only for the July protocol"""  # noqa: E501
    registration = M.register_toolkit(_outputs).pipe(fx.provide(_output_handlers))
    expected_calls: dict[str, Any] = {
        "Str": ({"content": [{"type": "text", "text": "hi"}], "isError": False}),
        "Untyped": {"content": [], "isError": False},
        "Obj": {
            "content": [{"type": "text", "text": '{"answer":"a"}'}],
            "structuredContent": {"answer": "a"},
            "isError": False,
        },
        # Diverges from Effect, which drops Arr's structured result and output schema
        # here: pyfect wraps them as {"result": ...} (PARITY.md, DOGFOOD atlas #4).
        "Arr": {
            "content": [{"type": "text", "text": "[1,2]"}],
            "structuredContent": {"result": [1, 2]},
            "isError": False,
        },
    }
    wrapped_arr = {
        "type": "object",
        "properties": {"result": {"type": "array", "items": {"type": "integer"}}},
        "required": ["result"],
        "x-fastmcp-wrap-result": True,
    }
    for protocol in (P.v2025_06_18, P.v2025_11_25):
        harness = yield from stdio_harness(protocol, None, registration)
        yield from harness.initialize()
        listed = (yield from harness.send_request("tools/list", {}))["result"]["tools"]
        schemas = {tool["name"]: tool.get("outputSchema") for tool in listed}
        assert schemas == {"Str": None, "Untyped": None, "Obj": OBJECT_SCHEMA, "Arr": wrapped_arr}
        for name, expected in expected_calls.items():
            reply = yield from harness.send_request("tools/call", {"name": name, "arguments": {}})
            assert reply["result"] == expected, name

    harness = yield from stdio_harness(P.v2026_07_28, None, registration)
    listed = (yield from harness.send_request("tools/list", {}))["result"]["tools"]
    schemas = {tool["name"]: tool.get("outputSchema") for tool in listed}
    assert schemas == {
        "Str": {"type": "string"},
        "Untyped": {"type": "null"},
        "Obj": OBJECT_SCHEMA,
        "Arr": {"type": "array", "items": {"type": "integer"}},
    }
    july_calls: dict[str, Any] = {
        "Str": {
            "content": [{"type": "text", "text": '"hi"'}],
            "structuredContent": "hi",
            "isError": False,
        },
        "Untyped": {"content": [], "isError": False},
        "Obj": expected_calls["Obj"],
        "Arr": {
            "content": [{"type": "text", "text": "[1,2]"}],
            "structuredContent": [1, 2],
            "isError": False,
        },
    }
    for name, expected in july_calls.items():
        reply = yield from harness.send_request("tools/call", {"name": name, "arguments": {}})
        result = {k: v for k, v in reply["result"].items() if k not in ("_meta", "resultType")}
        assert result == expected, name


@testing.effect
def test_accepts_cancellation_notifications_without_request_metadata():
    """McpServer 2026-07-28 / Lifecycle / should accept cancellation notifications without request metadata"""  # noqa: E501
    app = M.layer_http(
        name="test-server",
        version="1.0.0",
        path="/mcp",
        protocols=(P.v2026_07_28, P.v2025_11_25),
    )
    http = yield from in_memory_http(app)
    response = yield from _post(
        http,
        {
            "jsonrpc": "2.0",
            "method": "notifications/cancelled",
            "params": {"requestId": "already-complete"},
        },
        {"mcp-protocol-version": "2026-07-28", "mcp-method": "notifications/cancelled"},
    )
    assert response.status == 202
    assert (yield from response.text) == ""


@testing.effect
def test_2024_11_05_does_not_advertise_completions():
    """Mcp Conformance (2024-11-05) / Completion / Capabilities / MUST NOT advertise completions"""
    harness = yield from stdio_harness(P.v2024_11_05, None, *_FEATURES)
    initialized = yield from harness.initialize()
    assert "completions" not in initialized["result"]["capabilities"]


@testing.effect
def test_2025_11_25_does_not_expose_tasks():
    """Mcp Conformance (2025-11-25) / Tools / does not expose experimental Tasks without an extension"""  # noqa: E501
    harness = yield from stdio_harness(P.v2025_11_25, None, *_FEATURES)
    yield from harness.initialize()
    reply = yield from harness.send_request("tasks/get", {"taskId": "task-1"})
    assert reply["error"]["code"] == MS.METHOD_NOT_FOUND_ERROR_CODE
