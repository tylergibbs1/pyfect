"""Ports of Effect's MCP conformance roots titles
(test/ai/McpServer/McpConformance/RootsTest.ts) over stdio, for the
revisions whose test file runs the suite (every stateful one).

Effect's ``McpTestPeer`` calls the session's ``roots/list`` client directly;
here a tool calls it through ``McpServerClient`` and the test plays the
client, answering the request it receives. A failed request is the
``McpReverseOperationError`` whose ``cause`` is the client's JSON-RPC error.

Omitted: none.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import ToolEntry
from pyfect.context import Context

from ._mcp import Json, stdio_harness

STATEFUL = [P.v2024_11_05, P.v2025_03_26, P.v2025_06_18, P.v2025_11_25]


def _id(protocol: P.AnyProtocolAdapter) -> str:
    return protocol.protocol_version


def _text(text: str) -> MS.CallToolResult:
    return {"content": [{"type": "text", "text": text}]}


def _list_roots(_: object) -> fx.Effect[MS.CallToolResult, Any, Any]:
    """Answers with the client's roots, or its error, as JSON."""

    @fx.gen
    def run():
        client = yield from MS.McpServerClient()
        reverse = yield from client.get_client
        listed = reverse.list_roots().map(lambda result: {"roots": result["roots"]})
        seen = yield from listed.pipe(
            fx.catch_tag(
                MS.McpReverseOperationError, lambda error: fx.succeed({"error": error.cause})
            )
        )
        return _text(json.dumps(seen))

    return run


def _roots(
    protocol: P.AnyProtocolAdapter, capabilities: Json, reply: Json
) -> fx.Effect[Json, Any, Any]:
    """Calls the roots tool as a client advertising ``capabilities`` that
    answers ``roots/list`` with ``reply``; gives the method the server asked
    for and what the tool saw."""

    @fx.gen
    def run():
        entry = ToolEntry(
            {"name": "Roots", "inputSchema": {"type": "object"}}, Context.empty(), _list_roots
        )
        register = M.McpServer().flat_map(lambda server: server.add_tool(entry))
        harness = yield from stdio_harness(protocol, None, register)
        yield from harness.initialize(capabilities)
        call: Json = {"jsonrpc": "2.0", "id": 7, "method": "tools/call"}
        yield from harness.send({**call, "params": {"name": "Roots", "arguments": {}}})
        asked = yield from harness.receive()
        yield from harness.send({"jsonrpc": "2.0", "id": asked["id"], **reply})
        answer = yield from harness.response_to(7)
        return {"method": asked["method"], **json.loads(answer["result"]["content"][0]["text"])}

    return run


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_send_roots_requests_when_the_client_advertises_roots(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Roots / Capabilities / MUST send roots requests when the client advertises roots"""  # noqa: E501
    seen = yield from _roots(protocol, {"roots": {}}, {"result": {"roots": []}})
    assert seen["method"] == "roots/list"


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_accept_roots_requests_when_the_client_advertises_list_changes(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Roots / Capabilities / MUST accept roots requests when the client advertises list changes"""  # noqa: E501
    capabilities = {"roots": {"listChanged": True}}
    seen = yield from _roots(protocol, capabilities, {"result": {"roots": []}})
    assert seen["method"] == "roots/list"


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_accept_roots_with_file_uris_and_preserve_optional_names(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Roots / Listing Roots / MUST accept roots with file URIs and preserve optional names"""  # noqa: E501
    roots = [{"uri": "file:///workspace", "name": "Workspace"}, {"uri": "file:///unnamed"}]
    seen = yield from _roots(protocol, {"roots": {}}, {"result": {"roots": roots}})
    assert [(r["uri"], r.get("name")) for r in seen["roots"]] == [
        ("file:///workspace", "Workspace"),
        ("file:///unnamed", None),
    ]


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_may_accept_an_empty_roots_list(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Roots / Listing Roots / MAY accept an empty roots list"""
    seen = yield from _roots(protocol, {"roots": {}}, {"result": {"roots": []}})
    assert seen["roots"] == []


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_surface_client_errors_returned_by_roots_list(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Roots / Listing Roots / MUST surface client errors returned by roots/list"""  # noqa: E501
    error = {"code": MS.INTERNAL_ERROR_CODE, "message": "Roots unavailable"}
    seen = yield from _roots(protocol, {"roots": {}}, {"error": error})
    assert seen["error"]["code"] == MS.INTERNAL_ERROR_CODE
    assert seen["error"]["message"] == "Roots unavailable"
