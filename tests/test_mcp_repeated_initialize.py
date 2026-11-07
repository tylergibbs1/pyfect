"""A second ``initialize`` on one stdio session, as Effect's McpServer
answers it (run under Node): accepted, answered with the protocol the first
one chose, and the session takes the new capabilities, client info and
payload."""

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

_SEEN: list[tuple[str, Any, Any, Any]] = []


def _probe(_: object) -> fx.Effect[MS.CallToolResult, Any, Any]:
    def record(client: MS.ServerClient) -> MS.CallToolResult:
        _SEEN.append(
            (
                client.protocol_version,
                client.client_capabilities,
                client.client_info,
                client.initialize_payload["clientInfo"],
            )
        )
        return {"content": []}

    return MS.McpServerClient().map(record)


def _register(server: M.McpServerService) -> fx.Effect[None]:
    entry = ToolEntry({"name": "probe", "inputSchema": {"type": "object"}}, Context.empty(), _probe)
    return server.add_tool(entry)


@testing.effect
def test_a_repeated_initialize_keeps_the_protocol_and_replaces_the_client():
    _SEEN.clear()
    harness = yield from stdio_harness(
        P.v2025_03_26, (P.v2025_06_18, P.v2025_03_26), M.McpServer().flat_map(_register)
    )
    first = {"name": "first", "version": "1"}
    reply = yield from harness.send_request(
        "initialize", {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": first}
    )
    assert reply["result"]["protocolVersion"] == "2025-03-26"
    yield from harness.send_notification("notifications/initialized")
    yield from harness.send_request("tools/call", {"name": "probe", "arguments": {}})

    second = {"name": "second", "version": "2"}
    roots = {"roots": {"listChanged": True}}
    reply = yield from harness.send_request(
        "initialize", {"protocolVersion": "2025-06-18", "capabilities": roots, "clientInfo": second}
    )
    assert reply["result"]["protocolVersion"] == "2025-03-26"
    yield from harness.send_request("tools/call", {"name": "probe", "arguments": {}})

    assert [
        ("2025-03-26", {}, first, first),
        ("2025-03-26", roots, second, second),
    ] == _SEEN
