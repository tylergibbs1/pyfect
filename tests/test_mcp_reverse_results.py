"""Results a client sends back for server-to-client requests are decoded
with the method's schema: an elicitation answer with an unknown action is
no acceptance."""

from __future__ import annotations

from typing import Any, cast

import pytest
from oracle._mcp import stdio_harness

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import ToolEntry
from pyfect.context import Context


def _ask() -> fx.Effect[MS.CallToolResult, Any, Any]:
    asked = M.elicit(message="Delete everything?", schema=S.Record(S.String, S.String))
    answered = asked.as_("accepted").pipe(
        fx.catch_tag(MS.ElicitationDeclined, lambda _: fx.succeed("declined"))
    )
    return answered.map(
        lambda text: cast("MS.CallToolResult", {"content": [{"type": "text", "text": text}]})
    )


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        ({"action": "accept", "content": {}}, "accepted"),
        ({"action": "decline"}, "declined"),
        ({"action": "acept", "content": {}}, "declined"),
        ({"action": None}, "declined"),
        ({}, "declined"),
    ],
)
@testing.effect
def test_an_elicitation_answer_is_decoded_before_it_counts(answer: dict[str, Any], expected: str):
    def register(server: M.McpServerService) -> fx.Effect[None]:
        entry = ToolEntry(
            {"name": "Ask", "inputSchema": {"type": "object"}}, Context.empty(), lambda _: _ask()
        )
        return server.add_tool(entry)

    harness = yield from stdio_harness(P.v2025_11_25, None, M.McpServer().flat_map(register))
    yield from harness.initialize({"elicitation": {}})
    yield from harness.send(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {"name": "Ask", "arguments": {}},
        }
    )
    asked = yield from harness.receive()
    assert asked["method"] == "elicitation/create"
    yield from harness.send({"jsonrpc": "2.0", "id": asked["id"], "result": answer})
    reply = yield from harness.response_to(7)
    assert reply["result"]["content"] == [{"type": "text", "text": expected}]
