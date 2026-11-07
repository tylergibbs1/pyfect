"""The MCP HTTP paths that park on a reader, on the asyncio runtime. Effect has
one runtime, so it has no such titles; the conformance suites run on
``testing.effect``'s scheduler, and these park and wake across loop tasks."""

from __future__ import annotations

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
import asyncio
from typing import Any, cast

import pyfect as fx
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import ToolEntry
from pyfect.context import Context
from pyfect.deferred import Deferred

from ._mcp_http import http_harness, initialize_session, server_layer, sse_reader

LATEST = P.v2026_07_28
METADATA = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}
LISTEN_HEADERS = {
    "Mcp-Protocol-Version": "2026-07-28",
    "Mcp-Method": "subscriptions/listen",
}


def _run(effect: fx.Effect[Any, Any, Any]) -> Any:
    scoped = cast("fx.Effect[Any]", effect.pipe(fx.scoped))
    return asyncio.run(testing.run_test_async(scoped, timeout="30 seconds"))


def _chatty(progressed: list[int]) -> fx.Effect[None, Any, M.McpServer]:
    @fx.gen
    def run():
        server = yield from M.McpServer()

        def handle(_: object) -> fx.Effect[Any]:
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
        yield from server.add_tool(ToolEntry(tool, Context.empty(), handle))

    return run


def _call(request_id: int) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "id": request_id,
        "method": "tools/call",
        "params": {"name": "Chatty", "arguments": {}, "_meta": {"progressToken": "p"}},
    }


def test_a_session_request_waits_for_its_reader_and_finishes_once_read():
    progressed: list[int] = []

    @fx.gen
    def program():
        app = server_layer("A", (P.v2025_11_25,), _chatty(progressed), mode="server")
        harness = yield from http_harness(app)
        headers = yield from initialize_session(harness, P.v2025_11_25)
        response = yield from harness.post(_call(2), headers)
        for _ in range(50):
            yield from fx.yield_now()
        parked_at = len(progressed)
        reader = yield from sse_reader(response)
        messages: list[Any] = []
        while not messages or "result" not in messages[-1]:
            messages.append((yield from reader.take()))
        return parked_at, len(messages)

    parked_at, read = _run(program)
    assert 16 <= parked_at <= 18
    assert progressed == list(range(100))
    assert read == 101


def test_a_listener_sees_a_change_after_its_acknowledgment():
    servers: list[M.McpServerService] = []

    def tool(name: str) -> ToolEntry:
        entry: Any = {"name": name, "inputSchema": {"type": "object"}}
        return ToolEntry(entry, Context.empty(), lambda _: fx.succeed({"content": []}))

    @fx.gen
    def keep_the_server():
        server = yield from M.McpServer()
        servers.append(server)
        yield from server.add_tool(tool("first"))

    @fx.gen
    def program():
        harness = yield from http_harness(server_layer("A", (LATEST,), keep_the_server))
        body = {
            "jsonrpc": "2.0",
            "id": "watch",
            "method": "subscriptions/listen",
            "params": {"notifications": {"toolsListChanged": True}, "_meta": METADATA},
        }
        response = yield from harness.post(body, LISTEN_HEADERS)
        reader = yield from sse_reader(response)
        acknowledged = yield from reader.take()
        yield from servers[0].add_tool(tool("late"))
        changed = yield from reader.take()
        yield from reader.cancel
        return acknowledged["method"], changed["method"]

    assert _run(program) == (
        "notifications/subscriptions/acknowledged",
        "notifications/tools/list_changed",
    )


def test_a_handler_is_interrupted_when_its_client_goes_away_with_a_full_body():
    interrupted = Deferred[None]()
    full = Deferred[None]()

    def registrations() -> fx.Effect[None, Any, M.McpServer]:
        @fx.gen
        def run():
            server = yield from M.McpServer()

            def handle(_: object) -> fx.Effect[Any]:
                @fx.gen
                def report():
                    for index in range(32):
                        yield from server.notify(
                            "notifications/progress", {"progressToken": "p", "progress": index}
                        )
                    yield from full.succeed(None)
                    return cast("Any", (yield from fx.never))

                return report.on_interrupt(interrupted.succeed(None))

            tool: Any = {"name": "Chatty", "inputSchema": {"type": "object"}}
            yield from server.add_tool(ToolEntry(tool, Context.empty(), handle))

        return run

    @fx.gen
    def client_leaves():
        harness = yield from http_harness(
            server_layer("A", (P.v2025_11_25,), registrations(), mode="server")
        )
        headers = yield from initialize_session(harness, P.v2025_11_25)
        response = yield from harness.post(_call(2), headers)
        for _ in range(50):
            yield from fx.yield_now()
        reader = yield from sse_reader(response)
        yield from reader.take()
        yield from reader.cancel

    @fx.gen
    def program():
        yield from client_leaves
        yield from interrupted.wait()

    _run(program)
