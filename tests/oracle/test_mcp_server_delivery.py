"""Ports of Effect 4.1.2's new ``test/ai/McpServer/McpServer.test.ts`` titles
on delivery and encoding: list changes per HTTP session, Effect RPC control
methods over stdio, and tool results and declared failures encoded through
their JSON codecs."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, TypedDict, cast

import pyfect as fx
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai import mcp_test
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai._mcp.core import ToolEntry
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.queue import Queue
from pyfect.schema import getter as G
from pyfect.schema import transformation as Tr

from ._held_scheduler import held_scheduler
from ._mcp import stdio_harness
from ._mcp_http import http_harness, initialize_session, server_layer, sse_reader

HOLD: Any = {"name": "Hold", "inputSchema": {"type": "object"}}


@testing.effect
def test_should_treat_effect_rpc_control_methods_from_stdio_clients_as_unknown_notifications():
    """McpServer / should treat Effect RPC control methods from stdio clients as unknown notifications"""  # noqa: E501
    harness = yield from stdio_harness(P.v2025_11_25)
    yield from harness.initialize()
    yield from harness.send_notification("@effect/rpc/Ping")
    yield from harness.send_notification("@effect/rpc/Eof")
    response = yield from harness.send_request("ping", {}, "after-control")
    assert response == {"jsonrpc": "2.0", "id": "after-control", "result": {}}
    # Only the initialize and ping responses reach stdout: no ``@effect/rpc/Pong``.
    assert json.loads((yield from harness.raw_stdout.take()))["id"] == 1
    assert json.loads((yield from harness.raw_stdout.take())) == response


@testing.effect
def test_should_deliver_list_changes_to_every_initialized_http_session():
    """McpServer / should deliver list changes to every initialized HTTP session"""
    holding = Queue[None]()
    release = Deferred[None]()
    ready = Deferred[M.McpServerService]()

    @fx.gen
    def register():
        server = yield from M.McpServer()

        def handle(_: object) -> fx.Effect[Any]:
            return holding.offer(None).and_then(release.wait()).as_({"content": []})

        yield from server.add_tool(ToolEntry(HOLD, Context.empty(), handle))
        yield from ready.succeed(server)

    harness = yield from http_harness(server_layer("HttpListChanges", (P.v2025_11_25,), register))
    server = yield from ready.wait()

    def call(id: str) -> fx.Effect[Any, Any, Any]:
        body = {"jsonrpc": "2.0", "id": id, "method": "tools/call", "params": {"name": "Hold"}}
        return initialize_session(harness, P.v2025_11_25).flat_map(
            lambda headers: harness.post(body, headers)
        )

    calls = yield from fx.for_each(("first", "second"), lambda id: call(id).fork_scoped())
    yield from holding.take()
    yield from holding.take()

    yield from server.notify("notifications/tools/list_changed", {})
    streams = yield from fx.for_each(calls, lambda fiber: fiber.join().flat_map(sse_reader))
    for stream in streams:
        assert (yield from stream.take())["method"] == "notifications/tools/list_changed"
    yield from release.succeed(None)
    drained = yield from fx.for_each(streams, lambda stream: stream.drain())
    assert [[message["id"] for message in messages] for messages in drained] == [
        ["first"],
        ["second"],
    ]


@testing.effect
def test_should_not_deliver_list_changes_from_before_an_http_session_initialized():
    """McpServer / should not deliver list changes from before an HTTP session initialized"""
    held = yield from held_scheduler()
    holding = Deferred[None]()
    resume = Deferred[None]()

    @fx.gen
    def register():
        server = yield from M.McpServer()

        def handle(_: object) -> fx.Effect[Any]:
            return (
                holding.succeed(None)
                .and_then(resume.wait())
                .and_then(server.notify("notifications/tools/list_changed", {}))
                .as_({"content": []})
            )

        yield from server.add_tool(ToolEntry(HOLD, Context.empty(), handle))

    # The web handler builds the server itself, so the scheduler reaches it through the layer.
    app = server_layer("HttpStaleListChange", (P.v2025_11_25,), register).pipe(
        layer.provide(layer.succeed(fx.CurrentScheduler, held))
    )
    harness = yield from http_harness(app)
    headers = yield from initialize_session(harness, P.v2025_11_25)
    body = {"jsonrpc": "2.0", "id": "hold", "method": "tools/call", "params": {"name": "Hold"}}
    call = yield from harness.post(body, headers).fork_scoped()
    yield from holding.wait()

    # The registration's list change goes out while the request is in flight;
    # a newer one, emitted after the session initialized, follows it.
    yield from held.release
    yield from resume.succeed(None)
    stream = yield from sse_reader((yield from call.join()))
    messages = yield from stream.drain()
    assert [message.get("method", message.get("id")) for message in messages] == [
        "notifications/tools/list_changed",
        "hold",
    ]


@dataclass(eq=False)
class _Consumable:
    """A body read at most once, like a fetch ``Response``'s."""

    text: str
    read: bool = False

    def consume(self) -> str:
        assert not self.read, "the body was read twice"
        self.read = True
        return self.text


class _Body(TypedDict):
    body: _Consumable


_CONSUMABLE = S.String.pipe(
    S.decode_to(
        S.instance_of(_Consumable),
        Tr.Transformation(G.transform(_Consumable), G.transform(_Consumable.consume)),
    )
)
ConsumableResult = T.make("ConsumableResultTool", success=S.Struct(_Body, body=_CONSUMABLE))


@testing.effect
def test_encodes_a_tool_result_once_for_structured_content():
    """McpServer / registerToolkit / encodes a tool result once for structured content"""
    kit = K.make(ConsumableResult)
    handlers = kit.to_layer(
        ConsumableResult.handler(lambda _, __: fx.sync(lambda: {"body": _Consumable("hello")}))
    )
    client = yield from mcp_test.make_client(
        M.toolkit(kit).pipe(layer.provide(handlers)), protocols=(P.v2025_11_25,)
    )

    result = yield from client.call_tool({"name": "ConsumableResultTool", "arguments": {}})

    assert result.get("isError") is not True
    assert result.get("structuredContent") == {"body": "hello"}
    assert result["content"] == [
        {"type": "text", "text": json.dumps({"body": "hello"}, separators=(",", ":"))}
    ]


class _Charge(TypedDict):
    missingCents: int
    retryAfter: float


def _declared_failure(failure_mode: Literal["error", "return"]):
    @fx.gen
    def run():
        charge = T.make(
            "Charge",
            failure=S.Struct(_Charge, missingCents=S.BigInt, retryAfter=S.FiniteFromString),
            failure_mode=cast("Any", failure_mode),
        )
        kit = K.make(charge)
        failed = cast("_Charge", {"missingCents": 250, "retryAfter": 5.0})
        handlers = kit.to_layer(charge.handler(lambda _, __: fx.fail(failed)))
        client = yield from mcp_test.make_client(
            M.toolkit(kit).pipe(layer.provide(handlers)), protocols=(P.v2025_06_18,)
        )
        result = yield from client.call_tool({"name": "Charge"})

        assert result.get("isError") is True
        text = cast("Any", result["content"][0])["text"]
        assert text == json.dumps({"missingCents": "250", "retryAfter": "5"}, separators=(",", ":"))

    return run


@testing.effect
def test_encodes_declared_failures_with_their_json_codec_in_error_mode():
    """McpServer / registerToolkit / encodes declared failures with their JSON codec in ${failureMode} mode"""  # noqa: E501
    yield from _declared_failure("error")


@testing.effect
def test_encodes_declared_failures_with_their_json_codec_in_return_mode():
    """McpServer / registerToolkit / encodes declared failures with their JSON codec in ${failureMode} mode"""  # noqa: E501
    yield from _declared_failure("return")
