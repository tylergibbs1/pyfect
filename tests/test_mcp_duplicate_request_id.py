"""A request whose id is already in flight on the session, as Effect's
RpcServer answers it (``handleRequest``, run under Node through McpServer
over stdio): refused, so its handler never runs and nothing answers it, and
the first request stays tracked under that id."""

from __future__ import annotations

from typing import Any

from oracle._mcp import stdio_harness

import pyfect as fx
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import ToolEntry
from pyfect.context import Context


@testing.effect
def test_a_request_reusing_an_id_in_flight_is_refused():
    gate = fx.Deferred[None]()
    calls: list[int] = []

    def slow(_: object) -> fx.Effect[MS.CallToolResult, Any, Any]:
        def started() -> int:
            calls.append(len(calls) + 1)
            return calls[-1]

        def answer(call: int) -> fx.Effect[MS.CallToolResult]:
            text: MS.CallToolResult = {"content": [{"type": "text", "text": f"call {call}"}]}
            return gate.wait().as_(text)

        return fx.sync(started).flat_map(answer)

    def register(server: M.McpServerService) -> fx.Effect[None]:
        entry = ToolEntry(
            {"name": "slow", "inputSchema": {"type": "object"}}, Context.empty(), slow
        )
        return server.add_tool(entry)

    harness = yield from stdio_harness(P.v2025_06_18, None, M.McpServer().flat_map(register))
    yield from harness.initialize()
    call = {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "slow"}}
    yield from harness.send(call)
    yield from harness.send(call)
    # Answered in order, so both calls have been dispatched once this returns.
    yield from harness.send_request("ping", {}, "after")
    assert calls == [1]
    # The first call is still the one cancelling id 5 reaches.
    yield from harness.send_notification("notifications/cancelled", {"requestId": 5})
    assert (yield from harness.send_request("ping", {}, "last"))["id"] == "last"
    yield from gate.succeed(None)
    yield from harness.send_request("ping", {}, "end")
    # Neither call 5 wrote anything: the first was cancelled, the second refused.
    assert harness._retained == []  # pyright: ignore[reportPrivateUsage]
    assert calls == [1]
