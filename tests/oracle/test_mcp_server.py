"""Ports of Effect's ``test/ai/McpServer/McpServer.test.ts``.

Each test's docstring is the Effect test title (with its ``describe``).
Stdio tests run the server over an in-memory stdio (``stdio_harness``);
HTTP tests send raw requests to ``McpServer.layer_http`` through
``router.in_memory_client``, reading event streams as they arrive;
direct-service tests call ``McpServerService`` with a ``McpServerClient``
provided.

Omitted, with the reason:

- ``should release request metadata when HTTP requests complete without
  server notifications``: a Python dict takes no weak reference; a stateless
  POST's connection is never registered, so nothing keeps it.

Ported elsewhere: the custom-transport titles (``McpServer.layer`` over an
``RpcServer.Protocol``) and ``drops server notifications from buffered
JSON-RPC responses`` in test_mcp_rpc_protocol.py; resource subscriptions,
their backlogs, list-change scheduling, ``allowSubscriptions`` and the
mixed-protocol isolation title in test_mcp_conformance_subscriptions.py;
``layerHttpRequestScoped`` in test_mcp_request_scoped.py; the direct-service
and ``registerToolkit`` titles (strict mode, identified schemas, failure modes,
registration context) in test_mcp_server_registrations.py; POST and DELETE protocol-version checks
and legacy batches in test_mcp_http_admission.py; HTTP batch SSE framing in
test_mcp_batch_cancellation.py.
"""

from __future__ import annotations

import json
from typing import Any, TypedDict, cast

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import sink, stdio, stream, testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai._mcp.core import PromptEntry, ToolEntry
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.errors import Done
from pyfect.http import request as R
from pyfect.http.client import HttpClientService
from pyfect.http.response import HttpClientResponse
from pyfect.queue import Queue

from ._mcp import CLIENT_INFO, in_memory_http, stdio_harness
from ._mcp_http import http_harness, initialize_session, read_message, server_layer, sse_reader

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


# --- HTTP streams read as they arrive -------------------------------------------------------


def _blocking_tool(name: str, handle: Any) -> fx.Effect[None, Any, M.McpServer]:
    entry = ToolEntry({"name": name, "inputSchema": {"type": "object"}}, Context.empty(), handle)
    return M.McpServer().flat_map(lambda server: server.add_tool(entry))


def _blocking_tool_entry(tool: Any) -> fx.Effect[None, Any, M.McpServer]:
    entry = ToolEntry(tool, Context.empty(), lambda _: fx.succeed({"content": []}))
    return M.McpServer().flat_map(lambda server: server.add_tool(entry))


@testing.effect
def test_should_interrupt_tool_work_when_its_non_resumable_http_response_is_disconnected():
    """McpServer / should interrupt tool work when its non-resumable HTTP response is disconnected"""  # noqa: E501
    interrupted = Deferred[None]()
    protocol = P.v2025_03_26

    @fx.gen
    def registration():
        server = yield from M.McpServer()

        def wait(_: object) -> fx.Effect[Any]:
            return (
                server.notify("notifications/message", {"level": "error", "data": "running"})
                .and_then(fx.never)
                .on_interrupt(interrupted.succeed(None))
            )

        yield from _blocking_tool("Wait", wait)

    harness = yield from http_harness(server_layer("HttpDisconnect", (protocol,), registration))
    headers = yield from initialize_session(harness, protocol)
    response = yield from harness.post(
        {
            "jsonrpc": "2.0",
            "id": "wait",
            "method": "tools/call",
            "params": {"name": "Wait", "arguments": {}},
        },
        headers,
    )
    stream = yield from sse_reader(response)
    assert (yield from stream.take())["method"] == "notifications/message"
    yield from stream.cancel
    yield from interrupted.wait()


@testing.effect
def test_interrupts_an_in_flight_tool_on_delete_and_returns_404_for_its_pending_post():
    """McpServer / interrupts an in-flight tool on DELETE and returns 404 for its pending POST"""
    started, interrupted = Deferred[None](), Deferred[None]()
    protocol = P.v2025_11_25

    def blocked(_: object) -> fx.Effect[Any]:
        return started.succeed(None).and_then(fx.never).on_interrupt(interrupted.succeed(None))

    harness = yield from http_harness(
        server_layer(
            "SessionDelete",
            (protocol,),
            _blocking_tool("Blocked", blocked),
            allow_session_termination=True,
        )
    )
    headers = yield from initialize_session(harness, protocol)
    pending = yield from harness.post(
        {
            "jsonrpc": "2.0",
            "id": "blocked-tool",
            "method": "tools/call",
            "params": {"name": "Blocked", "arguments": {}},
        },
        headers,
    ).fork_scoped()
    yield from started.wait()
    assert (yield from harness.request("DELETE", None, headers)).status == 204
    yield from interrupted.wait()
    assert (yield from pending.join()).status == 404


@testing.effect
def test_closes_an_already_started_elicitation_stream_on_delete():
    """McpServer / closes an already-started elicitation stream on DELETE"""
    interrupted = Deferred[None]()
    protocol = P.v2025_11_25
    request: Any = {
        "mode": "url",
        "message": "Authorize access",
        "url": "https://example.com/authorize",
        "elicitationId": "authorization-1",
    }

    def authorize(_: object) -> fx.Effect[Any, Any, Any]:
        return (
            MS.McpServerClient()
            .flat_map(lambda client: client.get_client)
            .flat_map(lambda reverse: reverse.elicit(request))
            .as_(cast("MS.CallToolResult", {"content": []}))
            .or_die()
            .on_interrupt(interrupted.succeed(None))
        )

    harness = yield from http_harness(
        server_layer(
            "SessionDelete",
            (protocol,),
            _blocking_tool("Authorize", authorize),
            allow_session_termination=True,
        )
    )
    headers = yield from initialize_session(harness, protocol, {"elicitation": {"url": {}}})
    response = yield from harness.post(
        {
            "jsonrpc": "2.0",
            "id": "authorize-tool",
            "method": "tools/call",
            "params": {"name": "Authorize", "arguments": {}},
        },
        headers,
    )
    stream = yield from sse_reader(response)
    elicitation = yield from stream.take()
    assert elicitation["method"] == "elicitation/create"
    assert "id" in elicitation
    assert (yield from harness.request("DELETE", None, headers)).status == 204
    yield from interrupted.wait()
    remaining = yield from stream.drain()
    assert not any(message.get("id") == "authorize-tool" for message in remaining)


@testing.effect
def test_should_deliver_url_elicitation_completion_before_the_tool_result():
    """McpServer / should deliver URL elicitation completion before the tool result when the tool awaits notification delivery"""  # noqa: E501
    completed = Deferred[None]()
    protocol = P.v2025_11_25
    request: Any = {
        "mode": "url",
        "message": "Authorize access",
        "url": "https://example.com/authorize",
        "elicitationId": "authorization-1",
    }

    @fx.gen
    def registration():
        server = yield from M.McpServer()

        def authorize(_: object) -> fx.Effect[Any, Any, Any]:
            @fx.gen
            def run():
                client = yield from MS.McpServerClient()
                reverse = yield from client.get_client
                yield from reverse.elicit(request)
                yield from completed.wait()
                yield from server.notify_elicitation_complete(client.client_id, "authorization-1")
                return {"content": [{"type": "text", "text": "Authorized"}]}

            return run.or_die()

        yield from server.add_tool(
            ToolEntry(
                {"name": "Authorize", "inputSchema": {"type": "object"}}, Context.empty(), authorize
            )
        )

    harness = yield from http_harness(
        server_layer("UrlElicitationCompletion", (protocol,), registration)
    )
    headers = yield from initialize_session(harness, protocol, {"elicitation": {"url": {}}})
    response = yield from harness.post(
        {
            "jsonrpc": "2.0",
            "id": "authorize-tool",
            "method": "tools/call",
            "params": {"name": "Authorize", "arguments": {}},
        },
        headers,
    )
    stream = yield from sse_reader(response)
    elicitation = yield from stream.take()
    assert elicitation["method"] == "elicitation/create"
    assert "id" in elicitation
    accepted = yield from harness.post(
        {"jsonrpc": "2.0", "id": elicitation["id"], "result": {"action": "accept"}}, headers
    )
    assert accepted.status == 202
    yield from completed.succeed(None)
    complete = yield from stream.take()
    assert complete["method"] == "notifications/elicitation/complete"
    assert complete["params"] == {"elicitationId": "authorization-1"}
    result = yield from stream.take()
    assert result["id"] == "authorize-tool"
    assert result["result"] == {"content": [{"type": "text", "text": "Authorized"}]}
    assert (yield from stream.drain()) == []


@testing.effect
def test_should_honor_the_legacy_http_session_log_level_when_delivering_notifications():
    """McpServer / should honor the legacy HTTP session log level when delivering notifications"""
    protocol = P.v2025_11_25

    @fx.gen
    def registration():
        server = yield from M.McpServer()

        @fx.gen
        def emit():
            for level, data in (("warning", "filtered"), ("error", "delivered")):
                yield from server.notify("notifications/message", {"level": level, "data": data})
            return cast("MS.CallToolResult", {"content": []})

        yield from server.add_tool(
            ToolEntry(
                {"name": "Emit", "inputSchema": {"type": "object"}}, Context.empty(), lambda _: emit
            )
        )

    harness = yield from http_harness(server_layer("SessionLogLevel", (protocol,), registration))
    headers = yield from initialize_session(harness, protocol)
    configured = yield from harness.post(
        {"jsonrpc": "2.0", "id": 2, "method": "logging/setLevel", "params": {"level": "error"}},
        headers,
    )
    assert configured.status == 200
    response = yield from harness.post(
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "Emit"}}, headers
    )
    stream = yield from sse_reader(response)
    messages = yield from stream.drain()
    logs = [m["params"] for m in messages if m.get("method") == "notifications/message"]
    assert logs == [{"level": "error", "data": "delivered"}]
    assert messages[-1]["id"] == 3
    assert messages[-1]["result"] == {"content": []}


@testing.effect
def test_should_deliver_stateless_request_notifications_over_stdio():
    """McpServer / should deliver stateless request notifications over stdio"""

    @fx.gen
    def registration():
        server = yield from M.McpServer()

        @fx.gen
        def emit():
            for level, data in (("info", "filtered"), ("error", "delivered")):
                yield from server.notify("notifications/message", {"level": level, "data": data})
            yield from server.notify(
                "notifications/progress", {"progressToken": "token", "progress": 1}
            )
            return cast("MS.CallToolResult", {"content": []})

        yield from server.add_tool(
            ToolEntry(
                {"name": "Emit", "inputSchema": {"type": "object"}}, Context.empty(), lambda _: emit
            )
        )

    harness = yield from stdio_harness(P.v2026_07_28, None, registration)
    meta = {"io.modelcontextprotocol/logLevel": "warning", "progressToken": "token"}
    params = harness.with_metadata({"name": "Emit", "_meta": meta})
    yield from harness.send({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": params})
    logged = yield from harness.receive()
    assert logged["method"] == "notifications/message"
    assert logged["params"] == {"level": "error", "data": "delivered"}
    progress = yield from harness.receive()
    assert progress["method"] == "notifications/progress"
    assert progress["params"] == {"progressToken": "token", "progress": 1}
    assert (yield from harness.receive())["id"] == 2


@testing.effect
def test_should_accept_batches_after_falling_back_to_a_stateful_protocol():
    """McpServer / should accept batches after falling back to a stateful protocol"""
    harness = yield from stdio_harness(P.v2025_03_26, [P.v2026_07_28, P.v2025_03_26])
    initialized = yield from harness.send_request(
        "initialize",
        {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "fallback-client", "version": "1.0.0"},
        },
        1,
    )
    assert initialized["result"]["protocolVersion"] == "2025-03-26"
    yield from harness.send_notification("notifications/initialized")
    yield from harness.send_raw(
        json.dumps(
            [
                {"jsonrpc": "2.0", "id": 2, "method": "ping"},
                {"jsonrpc": "2.0", "id": 3, "method": "ping"},
            ]
        )
    )
    batch: Any = yield from harness.receive()
    assert sorted(batch, key=lambda reply: reply["id"]) == [
        {"jsonrpc": "2.0", "id": 2, "result": {}},
        {"jsonrpc": "2.0", "id": 3, "result": {}},
    ]


_WAIT_CALL: dict[str, Any] = {
    "jsonrpc": "2.0",
    "id": "wait",
    "method": "tools/call",
    "params": {"name": "Wait", "arguments": {}},
}


def _waiting_tool(
    interrupted: Deferred[None], started: Deferred[None] | None = None
) -> fx.Effect[None, Any, M.McpServer]:
    """``Wait``: logs (when no one waits on ``started``), then runs until interrupted."""

    @fx.gen
    def registration():
        server = yield from M.McpServer()

        def wait(_: object) -> fx.Effect[Any]:
            before = (
                server.notify("notifications/message", {"level": "error", "data": "running"})
                if started is None
                else started.succeed(None)
            )
            return before.and_then(fx.never).on_interrupt(interrupted.succeed(None))

        yield from _blocking_tool("Wait", wait)

    return registration


@testing.effect
def test_a_caller_leaving_before_any_message_interrupts_the_request():
    """Not an Effect title; aborting the POST under Effect's harness interrupts
    the handler, with no event written yet."""
    started, interrupted = Deferred[None](), Deferred[None]()
    protocol = P.v2025_03_26
    harness = yield from http_harness(
        server_layer("Abort", (protocol,), _waiting_tool(interrupted, started))
    )
    headers = yield from initialize_session(harness, protocol)
    pending = yield from harness.post(_WAIT_CALL, headers).fork()
    yield from started.wait()
    yield from pending.interrupt()
    yield from interrupted.wait()


@testing.effect
def test_a_reader_leaving_a_batch_stream_interrupts_its_requests():
    """Not an Effect title; cancelling a batch's event stream under Effect's
    harness interrupts its requests, as for one request."""
    interrupted = Deferred[None]()
    protocol = P.v2025_03_26
    harness = yield from http_harness(
        server_layer("BatchDisconnect", (protocol,), _waiting_tool(interrupted))
    )
    headers = yield from initialize_session(harness, protocol)
    reader = yield from sse_reader((yield from harness.post([_WAIT_CALL], headers)))
    assert (yield from reader.take())["method"] == "notifications/message"
    yield from reader.cancel
    yield from interrupted.wait()


@testing.effect
def test_a_batch_pending_when_its_session_is_deleted_gets_404():
    """Not an Effect title; under Effect's harness a pending batch POST gets
    404 when DELETE ends its session, as one request does."""
    started, interrupted = Deferred[None](), Deferred[None]()
    protocol = P.v2025_03_26
    harness = yield from http_harness(
        server_layer(
            "BatchDelete",
            (protocol,),
            _waiting_tool(interrupted, started),
            allow_session_termination=True,
        )
    )
    headers = yield from initialize_session(harness, protocol)
    pending = yield from harness.post([_WAIT_CALL], headers).fork()
    yield from started.wait()
    assert (yield from harness.request("DELETE", None, headers)).status == 204
    yield from interrupted.wait()
    assert (yield from pending.join()).status == 404


@testing.effect
def test_should_preserve_the_june_wire_transcript_when_requests_use_stdio():
    """McpServer / should preserve the June wire transcript when requests use stdio"""
    harness = yield from stdio_harness(P.v2025_06_18)
    yield from harness.send(
        {
            "jsonrpc": "2.0",
            "id": 0,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "TestClient", "version": "1.0.0"},
            },
        }
    )
    assert (yield from harness.receive()) == {
        "jsonrpc": "2.0",
        "id": 0,
        "result": {
            "protocolVersion": "2025-06-18",
            "capabilities": {"completions": {}, "logging": {}},
            "serverInfo": {"name": "test-server", "version": "1.0.0"},
        },
    }
    yield from harness.send({"jsonrpc": "2.0", "id": 1, "method": "ping", "params": {}})
    assert (yield from harness.receive()) == {"jsonrpc": "2.0", "id": 1, "result": {}}


@testing.effect
def test_a_finished_request_leaves_no_event_stream_on_its_session():
    """Not an Effect title (its streams are RPC clients it drops when they
    end): a long session must not keep one stream per request it served."""
    protocol = P.v2025_03_26
    servers: list[M.McpServerService] = []
    registration = M.McpServer().map(servers.append)
    harness = yield from http_harness(server_layer("Streams", (protocol,), registration))
    headers = yield from initialize_session(harness, protocol)
    ping: dict[str, Any] = {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}}
    yield from read_message((yield from harness.post(ping, headers)))
    yield from read_message((yield from harness.post([ping], headers)))
    peers = list(servers[0]._peers.values())  # pyright: ignore[reportPrivateUsage]
    assert [cast("Any", peer).streams for peer in peers] == [[]]


@testing.effect
def test_a_tools_partial_annotations_list_the_hints_they_leave_out():
    """Not an Effect title; Effect's ``ToolAnnotations`` default each hint, so
    a tool registered directly lists all four from 2025-06-18 on, title kept."""

    @fx.gen
    def registration():
        tool: Any = {
            "name": "Partial",
            "title": "T",
            "inputSchema": {"type": "object"},
            "annotations": {"readOnlyHint": True, "title": "A"},
        }
        yield from _blocking_tool_entry(tool)

    harness = yield from stdio_harness(P.v2025_06_18, None, registration)
    yield from harness.initialize()
    reply = yield from harness.send_request("tools/list")
    assert reply["result"]["tools"][0]["annotations"] == {
        "title": "A",
        "readOnlyHint": True,
        "destructiveHint": True,
        "idempotentHint": False,
        "openWorldHint": True,
    }


@testing.effect
def test_a_requests_own_progress_has_no_message_on_2024_11_05():
    """Not an Effect title; Effect under the same request sends ``message``
    from 2025-03-26 on and drops it on 2024-11-05."""

    @fx.gen
    def registration():
        server = yield from M.McpServer()
        progress: MS.JsonObject = {"progressToken": "p", "progress": 1, "total": 2, "message": "m"}

        def report(_: object) -> fx.Effect[Any]:
            return server.notify("notifications/progress", progress).as_({"content": []})

        yield from _blocking_tool("Report", report)

    for protocol, expected in (
        (P.v2024_11_05, {"progressToken": "p", "progress": 1, "total": 2}),
        (
            P.v2025_03_26,
            {"progressToken": "p", "progress": 1, "total": 2, "message": "m"},
        ),
    ):
        harness = yield from http_harness(server_layer("Progress", (protocol,), registration))
        headers = yield from initialize_session(harness, protocol)
        response = yield from harness.post(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {"name": "Report", "arguments": {}, "_meta": {"progressToken": "p"}},
            },
            headers,
        )
        reader = yield from sse_reader(response)
        assert (yield from reader.take())["params"] == expected


# --- a session's event streams ----------------------------------------------------------------


def _session_stream_server(progressed: list[int]) -> fx.Effect[None, Any, M.McpServer]:
    @fx.gen
    def run():
        server = yield from M.McpServer()

        def chatty(_: object) -> fx.Effect[Any]:
            @fx.gen
            def report():
                for index in range(100):
                    yield from server.notify(
                        "notifications/progress", {"progressToken": "p", "progress": index}
                    )
                    progressed.append(index)
                return cast("Any", {"content": []})

            return report

        tool: Any = {"name": "Chatty", "inputSchema": {"type": "object"}}
        yield from server.add_tool(ToolEntry(tool, Context.empty(), chatty))

    return run


@testing.effect
def test_a_session_request_waits_for_a_reader_that_stopped_reading_its_stream():
    """Effect's 16-message stream buffer holds for a session's POST too: under
    Node, a tool reporting progress on an unread body stops at 16."""
    progressed: list[int] = []
    app = server_layer(
        "Backpressure", (P.v2025_11_25,), _session_stream_server(progressed), mode="server"
    )
    harness = yield from http_harness(app)
    headers = yield from initialize_session(harness, P.v2025_11_25)
    yield from harness.post(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"name": "Chatty", "arguments": {}, "_meta": {"progressToken": "p"}},
        },
        headers,
    )
    for _ in range(50):
        yield from fx.yield_now()
    assert 16 <= len(progressed) <= 18


@testing.effect
def test_a_session_stream_nobody_reads_holds_up_no_other_stream_of_the_session():
    """Effect delivers a broadcast to each POST on its own, so one stalled
    stream costs the others nothing."""
    never_answered = Deferred[None]()
    servers: list[M.McpServerService] = []

    def announcing(_: object) -> fx.Effect[Any]:
        @fx.gen
        def run():
            yield from servers[0].notify(
                "notifications/progress", {"progressToken": "p", "progress": 1}
            )
            yield from never_answered.wait()
            return cast("Any", {"content": []})

        return run

    @fx.gen
    def registrations():
        yield from _session_stream_server([])
        server = yield from M.McpServer()
        servers.append(server)
        tool: Any = {"name": "Announcing", "inputSchema": {"type": "object"}}
        yield from server.add_tool(ToolEntry(tool, Context.empty(), announcing))

    app = server_layer("Backpressure", (P.v2025_11_25,), registrations, mode="server")
    harness = yield from http_harness(app)
    headers = yield from initialize_session(harness, P.v2025_11_25)

    def call(id: int, name: str) -> dict[str, Any]:
        return {
            "jsonrpc": "2.0",
            "id": id,
            "method": "tools/call",
            "params": {"name": name, "arguments": {}, "_meta": {"progressToken": "p"}},
        }

    yield from harness.post(call(2, "Chatty"), headers)
    for _ in range(50):
        yield from fx.yield_now()
    response = yield from harness.post(call(3, "Announcing"), headers)
    stream = yield from sse_reader(response)
    assert (yield from stream.take())["method"] == "notifications/progress"
    yield from servers[0].notify("notifications/tools/list_changed")
    message = yield from stream.take().timeout("1 second")
    assert message["method"] == "notifications/tools/list_changed"
    yield from never_answered.succeed(None)


@testing.effect
def test_a_dead_stdio_writer_ends_the_server():
    """Otherwise every writer waits on the bounded output for good."""
    stdin = Queue[bytes, Done]()
    served = M.run_stdio(name="s", version="1", protocols=(P.v2025_11_25,)).pipe(
        fx.provide_service(M.McpServer, (yield from M.make()))
    )

    def write(_: object) -> fx.Effect[None]:
        return fx.die(OSError("the pipe broke"))

    def dying_output(*, end_on_done: bool = False) -> Any:
        return sink.for_each(write)

    fiber = yield from served.pipe(
        fx.provide(stdio.layer_test(stdin=stream.from_queue(stdin), stdout=dying_output))
    ).fork_scoped()
    line = {"jsonrpc": "2.0", "id": 1, "method": "ping"}
    yield from stdin.offer((json.dumps(line) + "\n").encode())
    for _ in range(100):
        yield from fx.yield_now()
    assert fiber.poll_unsafe() is not None


@testing.effect
def test_the_direct_service_has_no_client_to_ask():
    """``McpServer.callTool`` and ``getPrompt`` outside a request: Effect's "Client
    input is not supported by this MCP protocol"."""
    server = yield from M.make()
    outcome: Any = MS.InputRequired(request_state="s")
    tool: Any = {"name": "T", "inputSchema": {"type": "object"}}
    yield from server.add_tool(ToolEntry(tool, Context.empty(), lambda _: fx.succeed(outcome)))
    yield from server.add_prompt(
        PromptEntry({"name": "P"}, Context.empty(), {}, lambda _: fx.succeed(outcome))
    )
    called = yield from _direct(server.call_tool({"name": "T", "arguments": {}})).flip()
    assert isinstance(called, MS.InvalidParams)
    assert called.message == "Client input is not supported by this MCP protocol"
    prompted = yield from _direct(server.get_prompt_result("P", {})).flip()
    assert isinstance(prompted, MS.InvalidParams)
    assert prompted.message == "Client input is not supported by this MCP protocol"
