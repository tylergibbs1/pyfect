"""Ports of Effect's ``test/ai/McpServer/McpServer.test.ts``.

Each test's docstring is the Effect test title (with its ``describe``).
Stdio tests run the server over an in-memory stdio (``stdio_harness``);
HTTP tests send raw requests to ``McpServer.layer_http`` through an
in-memory router; direct-service tests call ``McpServerService`` with a
``McpServerClient`` provided.

Omitted, with the reason:

- URL elicitation ordering, cross-connection reverse responses, custom
  transports, slow-reader isolation and mixed-protocol HTTP notification
  isolation: they drive Effect's RpcServer internals and custom
  transports, which pyfect's transports do not expose.
- Resource subscriptions and their backlogs, list-change notification
  scheduling, ``subscriptions/listen``, ``layerHttpRequestScoped`` and
  ``allowSubscriptions``: not ported (see PARITY.md, M10e mcp).
- Disconnect interrupting in-flight HTTP tools, DELETE interrupting a
  pending POST (pyfect ends that POST's stream instead of answering 404) and
  closing a started elicitation stream: the in-memory router buffers whole
  responses and has no client disconnect.
- ``June wire transcript``: covered by the lifecycle tests.

Ported elsewhere: the direct-service and ``registerToolkit`` titles
(strict mode, identified schemas, failure modes, registration context) in
test_mcp_server_registrations.py; POST and DELETE protocol-version checks
and legacy batches in test_mcp_http_admission.py; HTTP batch SSE framing in
test_mcp_batch_cancellation.py.
"""

from __future__ import annotations

import json
from typing import Any, TypedDict, cast

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
from pyfect.http import request as R
from pyfect.http.client import HttpClientService
from pyfect.http.response import HttpClientResponse

from ._mcp import CLIENT_INFO, in_memory_http, stdio_harness

ALL = [P.v2026_07_28, P.v2025_11_25, P.v2025_06_18, P.v2025_03_26, P.v2024_11_05]


def _direct_client(protocol_version: str = "2025-06-18") -> MS.ServerClient:
    return MS.ServerClient(
        client_id=0,
        protocol_version=protocol_version,
        client_capabilities={},
        client_info=None,
        initialize_payload={},
        get_client=fx.die(RuntimeError("no reverse client")),
    )


def _direct[A, E](effect: fx.Effect[A, E, MS.McpServerClient]) -> fx.Effect[A, E]:
    return effect.pipe(fx.provide_service(MS.McpServerClient, _direct_client()))


# --- stdio ---------------------------------------------------------------------------------


LEGACY = [P.v2024_11_05, P.v2025_03_26, P.v2025_06_18, P.v2025_11_25]
PING_CASES = [
    (protocol, protocols)
    for protocol in LEGACY
    for protocols in ((protocol,), (P.v2026_07_28, protocol), (protocol, P.v2026_07_28))
]


@pytest.mark.parametrize(
    ("protocol", "protocols"),
    PING_CASES,
    ids=[",".join(p.protocol_version for p in ps) for _, ps in PING_CASES],
)
@testing.effect
def test_answers_stdio_pings_throughout_initialization(
    protocol: P.AnyProtocolAdapter, protocols: tuple[P.AnyProtocolAdapter, ...]
):
    """McpServer / answers stdio pings throughout initialization with <protocols>"""
    harness = yield from stdio_harness(protocol, protocols)
    assert (yield from harness.send_request("ping", None, 0)) == {
        "jsonrpc": "2.0",
        "id": 0,
        "result": {},
    }
    assert "error" in (yield from harness.send_request("tools/list"))
    initialized = yield from harness.send_request(
        "initialize",
        {
            "protocolVersion": protocol.protocol_version,
            "capabilities": {},
            "clientInfo": {"name": "ping-client", "version": "1.0.0"},
        },
    )
    assert initialized["result"]["protocolVersion"] == protocol.protocol_version
    before = yield from harness.send_request("ping", {}, "before-initialized")
    assert before == {"jsonrpc": "2.0", "id": "before-initialized", "result": {}}
    yield from harness.send_notification("notifications/initialized")
    after = yield from harness.send_request("ping", None, "after-initialized")
    assert after == {"jsonrpc": "2.0", "id": "after-initialized", "result": {}}


@testing.effect
def test_does_not_route_explicitly_stateless_pings_to_a_stateful_adapter():
    """McpServer / does not route explicitly stateless pings to a stateful adapter"""
    harness = yield from stdio_harness(P.v2026_07_28, [P.v2026_07_28, P.v2025_11_25])
    reply = yield from harness.send_request("ping")
    assert reply["error"]["code"] == -32601


@testing.effect
def test_returns_from_completion_notification_when_the_target_is_absent():
    """McpServer / should return from completion notification when the target client is absent"""
    harness = yield from stdio_harness(P.v2025_11_25)
    yield from harness.server.notify_elicitation_complete(999, "elicitation-1")


@testing.effect
def test_initialize_negotiates_and_lists_tools_over_stdio():
    """Not an Effect title: initialize over stdio, then list a toolkit's tools."""
    harness = yield from stdio_harness(
        P.v2025_11_25, None, M.register_toolkit(_toolkit).pipe(fx.provide(_handlers))
    )
    reply = yield from harness.initialize()
    assert reply["result"]["protocolVersion"] == "2025-11-25"
    assert reply["result"]["serverInfo"]["name"] == "test-server"
    listed = yield from harness.send_request("tools/list", {})
    assert [t["name"] for t in listed["result"]["tools"]] == [
        "Structured",
        "Untyped",
        "PublicFailure",
        "StructuredFailure",
        "Defect",
    ]


@testing.effect
def test_rejects_requests_before_initialize():
    """Not an Effect title: a request before initialize is an invalid request."""
    harness = yield from stdio_harness(P.v2025_11_25)
    reply = yield from harness.send_request("tools/list", {})
    assert reply["error"]["code"] == -32600
    assert reply["error"]["message"] == "Server not initialized"


@testing.effect
def test_answers_parse_errors_over_stdio():
    """Not an Effect title: a malformed stdio line is answered with a parse error."""
    harness = yield from stdio_harness(P.v2025_11_25)
    yield from harness.send_raw("{not json")
    reply = yield from harness.receive()
    assert reply["error"]["code"] == -32700


@testing.effect
def test_selects_june_when_an_unsupported_version_is_offered():
    """McpServer / protocol selection / should select June when an unsupported version is offered"""
    harness = yield from stdio_harness(P.v2025_06_18, [P.v2025_06_18, P.v2025_03_26])
    reply = yield from harness.send_request(
        "initialize",
        {"protocolVersion": "1999-01-01", "capabilities": {}, "clientInfo": CLIENT_INFO},
    )
    assert reply["result"]["protocolVersion"] == "2025-06-18"


# --- toolkit -------------------------------------------------------------------------------


class Answer(TypedDict):
    answer: str


Structured = T.make("Structured", success=S.Struct(Answer))
Untyped = T.make("Untyped")


class Busy(TypedDict):
    reason: str
    retryAfter: str


PublicFailure = T.make("PublicFailure", success=S.String, failure=S.ErrorInstance)
StructuredFailure = T.make("StructuredFailure", success=S.String, failure=S.Struct(Busy))
Defect = T.make("Defect", success=S.String)
_toolkit = K.make(Structured, Untyped, PublicFailure, StructuredFailure, Defect)
_handlers = _toolkit.to_layer(
    Structured.handler(lambda _, __: fx.succeed(Answer(answer="result"))),
    Untyped.handler(lambda _, __: fx.void),
    PublicFailure.handler(lambda _, __: fx.fail(Exception("Public failure"))),
    StructuredFailure.handler(lambda _, __: fx.fail(Busy(reason="busy", retryAfter="5"))),
    Defect.handler(lambda _, __: fx.die(RuntimeError("private defect"))),
)


def _registered() -> fx.Effect[M.McpServerService]:
    @fx.gen
    def run():
        server = yield from M.make()
        yield from (
            M.register_toolkit(_toolkit)
            .pipe(fx.provide_service(M.McpServer, server))
            .pipe(fx.provide(_handlers))
        )
        return server

    return run


def _text(result: MS.CallToolResult) -> str:
    [block] = result["content"]
    return cast("Any", block)["text"]


@testing.effect
def test_lists_output_schemas_only_for_structured_results():
    """McpServer / registerToolkit / lists output schemas only for structured tool results"""
    harness = yield from stdio_harness(
        P.v2025_11_25, None, M.register_toolkit(_toolkit).pipe(fx.provide(_handlers))
    )
    yield from harness.initialize()
    listed = (yield from harness.send_request("tools/list", {}))["result"]["tools"]
    tools = {tool["name"]: tool for tool in listed}
    assert tools["Structured"]["outputSchema"] == {
        "type": "object",
        "properties": {"answer": {"type": "string"}},
        "required": ["answer"],
        "additionalProperties": True,
    }
    assert "outputSchema" not in tools["Untyped"]
    assert "outputSchema" not in tools["PublicFailure"]


@testing.effect
def test_keeps_void_tool_results_successful():
    """McpServer / registerToolkit / keeps void tool results successful"""
    server = yield from _registered()
    result = yield from _direct(server.call_tool({"name": "Untyped", "arguments": {}}))
    assert result == {"isError": False, "content": []}


@testing.effect
def test_carries_object_tool_results_as_structured_content():
    """McpServer / registerToolkit / carries object tool results as structured content"""
    server = yield from _registered()
    result = yield from _direct(server.call_tool({"name": "Structured", "arguments": {}}))
    assert result.get("structuredContent") == {"answer": "result"}
    assert result["content"] == [
        {"type": "text", "text": json.dumps({"answer": "result"}, separators=(",", ":"))}
    ]


@testing.effect
def test_returns_messages_for_declared_handler_failures():
    """McpServer / registerToolkit / returns schema-validated messages for declared handler failures"""  # noqa: E501
    server = yield from _registered()
    result = yield from _direct(server.call_tool({"name": "PublicFailure", "arguments": {}}))
    assert result.get("isError") is True
    assert _text(result) == "Public failure"
    assert "structuredContent" not in result


@testing.effect
def test_encodes_declared_non_error_failures():
    """McpServer / registerToolkit / encodes declared non-Error failures without structured content or internal diagnostics"""  # noqa: E501
    server = yield from _registered()
    result = yield from _direct(server.call_tool({"name": "StructuredFailure"}))
    assert result.get("isError") is True
    assert "structuredContent" not in result
    assert json.loads(_text(result)) == {"reason": "busy", "retryAfter": "5"}


@testing.effect
def test_scrubs_handler_defects():
    """McpServer / registerToolkit / logs handler defects with reportErrors=true and scrubs the client message"""  # noqa: E501
    server = yield from _registered()
    result = yield from _direct(server.call_tool({"name": "Defect", "arguments": {}}))
    assert result.get("isError") is True
    assert _text(result) == M.INTERNAL_TOOL_ERROR_MESSAGE
    assert "structuredContent" not in result


@testing.effect
def test_keeps_unknown_tools_as_protocol_errors():
    """McpServer / registerToolkit / keeps unknown tools as protocol errors"""
    server = yield from _registered()
    error = yield from _direct(server.call_tool({"name": "UnknownTool", "arguments": {}})).flip()
    assert error.code == MS.InvalidParams.CODE
    assert str(error) == "Tool 'UnknownTool' not found"


class Params(TypedDict):
    first: str
    second: float


@testing.effect
def test_reports_parameter_errors_without_invoking_the_handler():
    """McpServer / registerToolkit / reports all non-strict parameter errors while ignoring unknown keys"""  # noqa: E501
    invoked: list[bool] = []
    tool = T.make("NonStrictTool", parameters=S.Struct(Params), success=S.String)
    kit = K.make(tool)
    server = yield from M.make()
    yield from (
        M.register_toolkit(kit)
        .pipe(fx.provide_service(M.McpServer, server))
        .pipe(
            fx.provide(
                kit.to_layer(
                    tool.handler(lambda _, __: fx.sync(lambda: invoked.append(True)).as_("ok"))
                )
            )
        )
    )
    cases: list[MS.JsonObject] = [{"first": 1, "second": "invalid", "extra": True}, {"extra": True}]
    for arguments in cases:
        error = yield from _direct(
            server.call_tool({"name": "NonStrictTool", "arguments": arguments})
        ).flip()
        assert error.code == MS.InvalidParams.CODE
        assert '["first"]' in str(error)
        assert '["second"]' in str(error)
        assert '["extra"]' not in str(error)
        assert invoked == []


@testing.effect
def test_dies_when_parameters_are_not_object_rooted():
    """McpServer / registerToolkit / dies with a message naming the tool when parameters are not object-rooted / union of structs"""  # noqa: E501

    class Start(TypedDict):
        id: str

    class Stop(TypedDict):
        reason: str

    class EchoParams(TypedDict):
        text: str

    echo = T.make("echo", parameters=S.Struct(EchoParams), success=S.String)
    act = T.make("act", parameters=S.Union(S.Struct(Start), S.Struct(Stop)), success=S.String)
    kit = K.make(echo, act)
    handlers = kit.to_layer(
        echo.handler(lambda p, _: fx.succeed(p["text"])),
        act.handler(lambda _, __: fx.succeed("ok")),
    )
    server = yield from M.make()
    exit = yield from (
        M.register_toolkit(kit)
        .pipe(fx.provide_service(M.McpServer, server))
        .pipe(fx.provide(handlers))
        .exit()
    )
    assert isinstance(exit, fx.Failure)
    assert "cannot register tool 'act'" in str(exit.cause.squash())
    assert server.tools == ()


# --- direct service ------------------------------------------------------------------------


@testing.effect
def test_returns_from_completion_notification_without_a_transport():
    """McpServer / direct service / should return from completion notification when no transport is running"""  # noqa: E501
    server = yield from M.make()
    yield from server.notify_elicitation_complete(1, "elicitation-1")


@testing.effect
def test_completes_notification_emitting_tools_without_a_transport():
    """McpServer / direct service / should complete notification-emitting tools without a running transport"""  # noqa: E501
    server = yield from M.make()
    yield from server.add_tool(
        ToolEntry(
            {"name": "Emit", "inputSchema": {"type": "object"}},
            Context.empty(),
            lambda _: server.notify("notifications/message", {"level": "error", "data": "x"}).as_(
                cast("MS.CallToolResult", {"content": []})
            ),
        )
    )
    result = yield from _direct(server.call_tool({"name": "Emit"}))
    assert result["content"] == []


@testing.effect
def test_fails_when_a_resource_uri_is_unknown():
    """McpServer / direct service / should fail when a resource URI is unknown"""
    server = yield from M.make()
    error = yield from _direct(server.find_resource("file:///unknown")).flip()
    assert isinstance(error, MS.InvalidParams)
    assert str(error) == "Resource 'file:///unknown' not found"


@testing.effect
def test_resolves_an_http_resource_template():
    """McpServer / direct service / should resolve an HTTP resource template"""
    server = yield from M.make()
    yield from M.register_resource_template(
        M.uri_template("https://example.test/docs/", S.String),
        name="document",
        content=lambda _uri, name: fx.succeed(name),
    ).pipe(fx.provide_service(M.McpServer, server))
    uri = "https://example.test/docs/alice"
    result = yield from _direct(server.find_resource(uri))
    assert result["contents"] == [{"uri": uri, "text": "alice"}]


class CountParams(TypedDict):
    count: float


@testing.effect
def test_passes_decoded_values_to_prompt_handlers():
    """McpServer / direct service / should pass decoded values to prompt handlers"""
    server = yield from M.make()
    yield from M.register_prompt(
        name="count",
        parameters=S.Struct(CountParams, count=S.FiniteFromString),
        completion={"count": lambda _value, _context: fx.succeed([13])},
        content=lambda p: fx.succeed(f"{p['count']:.0f}"),
    ).pipe(fx.provide_service(M.McpServer, server))
    result = yield from _direct(server.get_prompt_result("count", {"count": "12"}))
    completion = yield from _direct(
        server.completion(
            {
                "ref": {"type": "ref/prompt", "name": "count"},
                "argument": {"name": "count", "value": "1"},
            }
        )
    )
    assert result["messages"] == [{"role": "user", "content": {"type": "text", "text": "12"}}]
    assert completion["completion"]["values"] == ["13"]


@testing.effect
def test_passes_none_to_a_low_level_tool_handler_without_arguments():
    """McpServer / direct service / should pass undefined to a low-level tool handler when arguments are omitted"""  # noqa: E501
    received: list[object] = []
    server = yield from M.make()

    def handle(payload: object) -> fx.Effect[MS.CallToolResult]:
        received.append(payload)
        return fx.succeed(cast("MS.CallToolResult", {"content": []}))

    yield from server.add_tool(
        ToolEntry(
            {"name": "omitted", "inputSchema": {"type": "object", "properties": {}}},
            Context.empty(),
            handle,
        )
    )
    yield from _direct(server.call_tool({"name": "omitted"}))
    assert received == [None]


@testing.effect
def test_provides_the_request_context_to_handlers():
    """McpServer / direct service / should provide the neutral request service to handlers"""
    received: list[str] = []
    server = yield from M.make()

    def handle(_: object) -> fx.Effect[MS.CallToolResult, Any, Any]:
        return MS.McpRequestContext().map(
            lambda request: (
                received.append(request.protocol_version),
                cast("MS.CallToolResult", {"content": []}),
            )[1]
        )

    yield from server.add_tool(
        ToolEntry(
            {"name": "request-services", "inputSchema": {"type": "object"}}, Context.empty(), handle
        )
    )
    yield from _direct(server.call_tool({"name": "request-services"}))
    assert received == ["2025-06-18"]


# --- HTTP ----------------------------------------------------------------------------------

URL = "http://localhost/mcp"
ACCEPT = "application/json, text/event-stream"


def _initialize(protocol_version: str = "2025-11-25") -> dict[str, Any]:
    params = {"protocolVersion": protocol_version, "capabilities": {}, "clientInfo": CLIENT_INFO}
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params}


INITIALIZE = _initialize()


def _http(
    protocols: tuple[P.AnyProtocolAdapter, ...] = (P.v2025_11_25,),
    *,
    allow_session_termination: bool = False,
) -> fx.Effect[HttpClientService[Any, Any], Any, Any]:
    app = M.layer_http(
        name="test-server",
        version="1.0.0",
        path="/mcp",
        protocols=protocols,
        allow_session_termination=allow_session_termination,
    )
    return in_memory_http(app)


def _post(
    http: HttpClientService[Any, Any], body: object, headers: dict[str, str] | None = None
) -> fx.Effect[HttpClientResponse, Any]:
    request = (
        R.post(URL)
        .set_headers({"accept": ACCEPT, **(headers or {})})
        .body_text(json.dumps(body), "application/json")
    )
    return http.execute(request)


@testing.effect
def test_rejects_browser_origins_by_default():
    """McpServer / should reject browser Origins by default while accepting Origin-less clients"""
    http = yield from _http()
    assert (yield from _post(http, INITIALIZE)).status == 200
    rejected = yield from _post(
        http, {**INITIALIZE, "id": 2}, {"origin": "https://browser.example"}
    )
    assert rejected.status == 403


@testing.effect
def test_replays_the_selected_protocol_header():
    """McpServer / should replay the selected protocol header when a session is initialized"""
    http = yield from _http((P.v2025_06_18,))
    response = yield from _post(http, _initialize("2025-03-26"))
    assert response.headers.get("mcp-protocol-version") == "2025-06-18"
    session = response.headers.get("mcp-session-id")
    assert session is not None
    ping = yield from _post(
        http,
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        {"mcp-session-id": session, "mcp-protocol-version": "2025-06-18"},
    )
    assert ping.headers.get("mcp-protocol-version") == "2025-06-18"


@testing.effect
def test_returns_400_when_a_request_omits_the_session_id():
    """McpServer / should return 400 when a non-initialize request omits the MCP session id"""
    http = yield from _http()
    response = yield from _post(
        http, {"jsonrpc": "2.0", "id": 0, "method": "tools/list", "params": {}}
    )
    assert response.status == 400


@testing.effect
def test_negotiates_initialize_on_an_unsupported_protocol_version():
    """McpServer / negotiates an initialize request from a client on an unsupported protocol version"""  # noqa: E501
    http = yield from _http((P.v2025_11_25,))
    response = yield from _post(
        http, _initialize("2025-06-18"), {"mcp-protocol-version": "2025-06-18"}
    )
    assert response.status == 200
    assert response.headers.get("mcp-protocol-version") == "2025-11-25"
    assert response.headers.get("mcp-session-id") is not None


@testing.effect
def test_rejects_unsupported_http_methods():
    """McpServer / rejects unsupported HTTP methods without disturbing an initialized session"""
    http = yield from _http()
    initialized = yield from _post(http, INITIALIZE)
    session = initialized.headers.get("mcp-session-id")
    assert session is not None
    rejected = yield from http.execute(R.put(URL).set_headers({"mcp-session-id": session}))
    assert rejected.status == 405
    assert rejected.headers.get("allow") == "POST"
    ping = yield from _post(
        http,
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        {"mcp-session-id": session, "mcp-protocol-version": "2025-11-25"},
    )
    assert ping.status == 200


@testing.effect
def test_advertises_delete_when_termination_is_enabled():
    """McpServer / advertises DELETE on unsupported methods when stateful termination is enabled"""
    http = yield from _http(allow_session_termination=True)
    rejected = yield from http.execute(R.put(URL))
    assert rejected.status == 405
    assert rejected.headers.get("allow") == "POST, DELETE"


@testing.effect
def test_terminates_a_session_on_delete():
    """McpServer / terminates an HTTP session on DELETE without a protocol header when allowSessionTermination is set"""  # noqa: E501
    http = yield from _http(allow_session_termination=True)
    session = (yield from _post(http, INITIALIZE)).headers.get("mcp-session-id")
    assert session is not None
    deleted = yield from http.execute(R.delete(URL).set_headers({"mcp-session-id": session}))
    assert deleted.status == 204
    after = yield from _post(
        http,
        {"jsonrpc": "2.0", "id": 2, "method": "ping"},
        {"mcp-session-id": session, "mcp-protocol-version": "2025-11-25"},
    )
    assert after.status == 404


@testing.effect
def test_rejects_delete_with_a_missing_or_unknown_session():
    """McpServer / rejects DELETE with a missing or unknown session id when termination is enabled"""  # noqa: E501
    http = yield from _http(allow_session_termination=True)
    missing = yield from http.execute(R.delete(URL))
    unknown = yield from http.execute(R.delete(URL).set_headers({"mcp-session-id": "unknown"}))
    assert missing.status == 400
    assert unknown.status == 404


@testing.effect
def test_returns_an_empty_202_for_notifications():
    """McpServer / returns an empty 202 for notifications and responses and remains successful for request POSTs"""  # noqa: E501
    http = yield from _http()
    session = (yield from _post(http, INITIALIZE)).headers.get("mcp-session-id")
    assert session is not None
    headers = {"mcp-session-id": session, "mcp-protocol-version": "2025-11-25"}
    notified = yield from _post(
        http, {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers
    )
    assert notified.status == 202
    assert (yield from notified.text) == ""
    listed = yield from _post(http, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}, headers)
    assert listed.status == 200
    assert json.loads((yield from listed.text))["result"]["tools"] == []
