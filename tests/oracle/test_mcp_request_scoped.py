"""Ports of Effect's LayerHttpRequestScoped.test.ts.

Adapted, with the reason:
- "should serve each POST when timers from completed requests never fire" runs
  on Cloudflare's workerd in Effect: here on a test clock nobody adjusts, where
  a timer never fires either.
- "should interrupt ... when the client aborts": pyfect's in-memory client has
  no abort signal. Before headers an abort is interrupting the requesting
  fiber; after them it is the client's scope closing, which closes the request's.

The shared conformance suites Effect re-runs in request mode (BaseProtocol,
Tools, Resources, Prompts) run again in test_mcp_request_mode_suites.py;
MultiRoundTrip and the Mcp-Param-* titles run in both modes in
test_mcp_conformance_multi_round_trip.py and test_mcp_conformance_tools.py.
"""

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import layer, testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import ToolEntry
from pyfect.context import Context, Reference
from pyfect.deferred import Deferred
from pyfect.errors import IllegalArgumentError
from pyfect.exit import Failure, Success
from pyfect.http import request as R
from pyfect.http import router
from pyfect.scope import CloseableScope, Scope

from ._mcp_features import MRTR_PROMPT, MRTR_TOOL, features_conformance
from ._mcp_http import HttpHarness, Json, http_harness, read_message, server_layer, sse_reader

PROTOCOL = P.v2026_07_28
PROGRESS_TOKEN = "progress-1"
METADATA: Json = {
    "io.modelcontextprotocol/protocolVersion": PROTOCOL.protocol_version,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "test", "version": "1.0.0"},
}
CALL_RESULT: Any = {"content": [{"type": "text", "text": "done"}]}


def _call_tool(
    name: str, id: int, arguments: Json | None = None, metadata: Json | None = None
) -> tuple[Json, dict[str, str]]:
    return (
        {
            "jsonrpc": "2.0",
            "id": id,
            "method": "tools/call",
            "params": {
                "name": name,
                "arguments": arguments or {},
                "_meta": {"progressToken": PROGRESS_TOKEN, **(metadata or {}), **METADATA},
            },
        },
        {
            "MCP-Protocol-Version": PROTOCOL.protocol_version,
            "Mcp-Method": "tools/call",
            "Mcp-Name": name,
        },
    )


type _Handle = Callable[[M.McpServerService, Any], fx.Effect[Any, Any, Any]]


def _registration(name: str, handle: _Handle) -> fx.Effect[None, Any, M.McpServer]:
    def register(server: M.McpServerService) -> fx.Effect[None]:
        return server.add_tool(
            ToolEntry(
                {"name": name, "inputSchema": {"type": "object"}},
                Context.empty(),
                lambda arguments: handle(server, arguments),
            )
        )

    return M.McpServer().flat_map(register)


def _tool_layer(name: str, handle: _Handle) -> layer.Layer[Any, Any, Any]:
    return server_layer("RequestMode", (PROTOCOL,), _registration(name, handle), mode="request")


def _report_progress(server: M.McpServerService) -> fx.Effect[Any]:
    return server.notify(
        "notifications/progress", {"progressToken": PROGRESS_TOKEN, "progress": 1}
    ).as_(CALL_RESULT)


def _sse_messages(body: str) -> list[Json]:
    return [json.loads(line[6:]) for line in body.split("\n") if line.startswith("data: ")]


@testing.effect
def test_should_expose_tools_registered_after_the_first_post_in_later_lists_and_discovery():
    """McpServer.layerHttpRequestScoped / should expose tools registered after the first POST in later lists and discovery"""  # noqa: E501
    ready = Deferred[M.McpServerService]()
    registration = M.McpServer().flat_map(lambda server: ready.succeed(server).as_void())
    harness = yield from http_harness(
        server_layer("LateRegistration", (PROTOCOL,), registration, mode="request")
    )
    ids = iter(range(1, 100))

    def post(method: str) -> fx.Effect[Json]:
        @fx.gen
        def run():
            response = yield from harness.post(
                {
                    "jsonrpc": "2.0",
                    "id": next(ids),
                    "method": method,
                    "params": {"_meta": METADATA},
                },
                {"MCP-Protocol-Version": PROTOCOL.protocol_version, "Mcp-Method": method},
            )
            assert response.status == 200
            return (yield from read_message(response))["result"]

        return run

    assert (yield from post("tools/list"))["tools"] == []
    before = yield from post("server/discover")
    assert "tools" not in before["capabilities"]
    server = yield from ready.wait()
    yield from server.add_tool(
        ToolEntry(
            {"name": "LateTool", "inputSchema": {"type": "object"}},
            Context.empty(),
            lambda _: fx.succeed({"content": []}),
        )
    )
    assert (yield from post("tools/list"))["tools"] == [
        {"name": "LateTool", "inputSchema": {"type": "object"}}
    ]
    after = yield from post("server/discover")
    assert after["capabilities"]["tools"] == {"listChanged": False}


class _Label(Reference[str]):
    @classmethod
    def default(cls) -> str:
        return "default"


@testing.effect
def test_should_let_each_request_s_services_override_the_layer_services_seen_by_tools():
    """McpServer.layerHttpRequestScoped / should let each request's services override the layer services seen by tools"""  # noqa: E501
    tool = _tool_layer(
        "Label",
        lambda _, __: _Label().map(lambda text: {"content": [{"type": "text", "text": text}]}),
    ).pipe(layer.provide(layer.succeed(_Label, "layer")))
    harness = yield from http_harness(tool)
    body, headers = _call_tool("Label", 1)
    for override in (None, "first", "second"):
        posted = harness.post(body, headers)
        if override is not None:
            posted = posted.pipe(fx.provide_service(_Label, override))
        message = yield from read_message((yield from posted))
        assert message["result"]["content"][0]["text"] == (override or "layer")


@testing.effect
def test_should_serve_each_post_when_timers_from_completed_requests_never_fire():
    """McpServer.layerHttpRequestScoped / should serve each POST when timers from completed requests never fire"""  # noqa: E501
    harness = yield from http_harness(
        _tool_layer("ReportProgress", lambda server, _: _report_progress(server))
    )
    first = yield from harness.request("GET")
    assert first.status == 405
    for id in (1, 2):
        body, headers = _call_tool("ReportProgress", id)
        response = yield from harness.post(body, headers)
        messages = _sse_messages((yield from response.text))
        assert [m.get("method", m.get("id")) for m in messages] == ["notifications/progress", id]


@testing.effect
def test_should_interrupt_the_handler_when_the_client_aborts_its_post():
    """McpServer.layerHttpRequestScoped / should interrupt the handler when the client aborts its POST"""  # noqa: E501
    entered = Deferred[None]()
    interrupted = Deferred[None]()
    harness = yield from http_harness(
        _tool_layer(
            "Block",
            lambda _, __: (
                entered.succeed(None).and_then(fx.never).on_interrupt(interrupted.succeed(None))
            ),
        )
    )
    body, headers = _call_tool("Block", 1)
    posting = yield from harness.post(body, headers).fork()
    yield from entered.wait()
    yield from posting.interrupt()
    yield from interrupted.wait().timeout(1)


def _client_in_own_scope(
    app: layer.Layer[Any, Any, Any],
) -> fx.Effect[tuple[HttpHarness, CloseableScope], Any, Any]:
    """A client whose scope closing is the client going away."""

    @fx.gen
    def run():
        outer: CloseableScope = yield from Scope()
        scope = yield from outer.fork()
        harness = yield from http_harness(app).pipe(fx.provide_service(Scope, scope))
        return harness, scope

    return run


@pytest.mark.parametrize("cancel", ["abort", "body"])
@testing.effect
def test_should_interrupt_a_streaming_handler_when_the_client_cancels_after_headers(cancel: str):
    """McpServer.layerHttpRequestScoped / should interrupt a streaming handler when the client cancels by ${cancel} after headers"""  # noqa: E501
    interrupted = Deferred[None]()
    harness, scope = yield from _client_in_own_scope(
        _tool_layer(
            "ProgressThenBlock",
            lambda server, _: (
                _report_progress(server).and_then(fx.never).on_interrupt(interrupted.succeed(None))
            ),
        )
    )
    body, headers = _call_tool("ProgressThenBlock", 1)
    reader = yield from sse_reader((yield from harness.post(body, headers)))
    assert (yield from reader.take())["method"] == "notifications/progress"
    if cancel == "abort":
        yield from scope.close(Success(None))
    else:
        yield from reader.cancel
    yield from interrupted.wait().timeout(1)


@testing.effect
def test_should_interrupt_a_streaming_handler_when_the_client_aborts_while_its_unread_body_is_full():  # noqa: E501
    """McpServer.layerHttpRequestScoped / should interrupt a streaming handler when the client aborts while its unread body is full"""  # noqa: E501
    headers_sent = Deferred[None]()
    backpressured = Deferred[None]()
    interrupted = Deferred[None]()

    def handle(server: M.McpServerService, _: object) -> fx.Effect[Any]:
        @fx.gen
        def run():
            yield from _report_progress(server)
            yield from headers_sent.wait()
            # Later chunks arrive while the client reads nothing.
            yield from _report_progress(server)
            yield from _report_progress(server)
            yield from backpressured.succeed(None)
            return (yield from fx.never)

        return run.on_interrupt(interrupted.succeed(None))

    harness, scope = yield from _client_in_own_scope(_tool_layer("ProgressUnread", handle))
    body, headers = _call_tool("ProgressUnread", 1)
    yield from harness.post(body, headers)
    yield from headers_sent.succeed(None)
    yield from backpressured.wait()
    yield from scope.close(Success(None))
    yield from interrupted.wait().timeout(1)


@testing.effect
def test_should_deliver_overlapping_requests_only_their_own_notifications():
    """McpServer.layerHttpRequestScoped / should deliver overlapping requests only their own notifications"""  # noqa: E501
    arrived = {"a": Deferred[None](), "b": Deferred[None]()}

    def handle(server: M.McpServerService, arguments: Any) -> fx.Effect[Any]:
        marker: str = arguments["marker"]

        @fx.gen
        def run():
            # Both requests are in flight before either emits a notification.
            yield from arrived[marker].succeed(None)
            yield from arrived["b" if marker == "a" else "a"].wait()
            yield from server.notify(
                "notifications/progress",
                {"progressToken": PROGRESS_TOKEN, "progress": 1, "message": marker},
            )
            yield from server.notify("notifications/message", {"level": "info", "data": marker})
            if marker == "a":
                yield from server.notify("notifications/tools/list_changed")
            return {"content": [{"type": "text", "text": marker}]}

        return run

    harness = yield from http_harness(_tool_layer("Overlap", handle))

    def post(marker: str) -> fx.Effect[tuple[str, list[Json]]]:
        # Both requests reuse the same JSON-RPC id and progress token.
        body, headers = _call_tool(
            "Overlap", 1, {"marker": marker}, {"io.modelcontextprotocol/logLevel": "debug"}
        )
        return (
            harness.post(body, headers)
            .flat_map(lambda response: response.text.or_die())
            .map(lambda text: (marker, _sse_messages(text)))
        )

    responses = yield from fx.for_each(("a", "b"), post, concurrency="unbounded")
    for marker, messages in responses:
        assert [
            (m.get("method", m.get("id")), m.get("params", m.get("result", {}).get("content")))
            for m in messages
        ] == [
            (
                "notifications/progress",
                {"progressToken": PROGRESS_TOKEN, "progress": 1, "message": marker},
            ),
            ("notifications/message", {"level": "info", "data": marker}),
            (1, [{"type": "text", "text": marker}]),
        ]


@testing.effect
def test_should_keep_layer_http_notifications_when_a_request_scoped_endpoint_shares_the_server():
    """McpServer.layerHttpRequestScoped / should keep layerHttp notifications when a request-scoped endpoint shares the server"""  # noqa: E501
    served = layer.merge(
        M.layer_http(name="DefaultMode", version="1.0.0", path="/mcp", protocols=(PROTOCOL,)),
        M.layer_http_request_scoped(
            name="RequestMode", version="1.0.0", path="/request", protocols=(PROTOCOL,)
        ),
    )
    registration = layer.effect_discard(
        _registration("ReportProgress", lambda server, _: _report_progress(server))
    )
    client = yield from router.in_memory_client(registration.pipe(layer.provide_merge(served)))
    for path in ("/mcp", "/request"):
        body, headers = _call_tool("ReportProgress", 1)
        request = (
            R.make("POST", f"http://localhost{path}")
            .body_text(json.dumps(body), "application/json")
            .set_headers(
                {"accept": "application/json, text/event-stream", **headers},
            )
        )
        response = yield from client.execute(request)
        messages = _sse_messages((yield from response.text))
        assert [m.get("method", m.get("id")) for m in messages] == ["notifications/progress", 1]


# --- Not Effect titles ------------------------------------------------------------------------


@testing.effect
def test_refuses_a_sessionful_protocol():
    """A caller past the type checker gets Effect's refusal when the layer builds."""
    served = M.layer_http_request_scoped(
        name="Sessionful",
        version="1.0.0",
        path="/mcp",
        protocols=(P.v2025_11_25,),  # pyright: ignore[reportArgumentType]
    )
    built = yield from router.in_memory_client(served).exit()
    assert isinstance(built, Failure)
    error = built.cause.find_error().get_or_none()
    assert isinstance(error, IllegalArgumentError)
    assert "sessionful MCP protocol 2025-11-25" in str(error)


@testing.effect
def test_serves_tools_resources_prompts_and_base_protocol_in_request_mode():
    """The shared conformance suites' paths in request mode, end to end."""
    test = yield from features_conformance(PROTOCOL, "request")
    session = yield from test.initialize()
    capabilities = session.message["result"]["capabilities"]
    assert capabilities["tools"] == {"listChanged": False}
    assert capabilities["resources"] == {"listChanged": False, "subscribe": False}
    assert capabilities["prompts"] == {"listChanged": False}

    def request(id: int, method: str, params: Json) -> fx.Effect[Any]:
        return test.send(session, {"jsonrpc": "2.0", "id": id, "method": method, "params": params})

    discovered = yield from test.decode_result((yield from request(1, "server/discover", {})))
    assert discovered["result"]["resultType"] == "complete"
    tools = yield from test.decode_result((yield from request(2, "tools/list", {})))
    assert {"TestTool", MRTR_TOOL} <= {tool["name"] for tool in tools["result"]["tools"]}
    called = yield from test.decode_result(
        (
            yield from request(
                3, "tools/call", {"name": "TestTool", "arguments": {"value": "called"}}
            )
        )
    )
    assert called["result"]["content"] == [{"type": "text", "text": "called"}]
    resource = yield from test.decode_result(
        (yield from request(4, "resources/read", {"uri": "file:///test"}))
    )
    assert resource["result"]["contents"][0]["text"] == "test"
    prompts = yield from test.decode_result((yield from request(5, "prompts/list", {})))
    assert {"TestPrompt", MRTR_PROMPT} <= {
        prompt["name"] for prompt in prompts["result"]["prompts"]
    }
    prompt = yield from test.decode_result(
        (yield from request(6, "prompts/get", {"name": "TestPrompt", "arguments": {}}))
    )
    assert prompt["result"]["messages"][0]["content"]["text"] == "tested"
    unknown = yield from test.decode_error((yield from request(7, "tools/unknown", {})))
    assert unknown["error"]["code"] == -32601
    deleted = yield from test.request("DELETE")
    assert deleted.status == 405
