"""``examples/mcp_server.py`` serves its toolkit to this package's MCP
client: a real handshake with the example run as a subprocess."""

import sys
from pathlib import Path
from typing import TypedDict

import pyfect as fx
from pyfect import platform, process, testing
from pyfect import schema as S
from pyfect.ai import mcp_client, mcp_protocol
from pyfect.ai.mcp_client_error import McpClientError, ToolError

EXAMPLE = Path(__file__).parent.parent / "examples" / "mcp_server.py"


class Sum(TypedDict):
    total: int


def _client(protocol: mcp_client.ClientProtocol):
    return mcp_client.layer_stdio(
        name="example-test",
        version="1.0.0",
        command=process.make(sys.executable, [str(EXAMPLE)]),
        protocol=protocol,
        timeout="30 seconds",
    ).pipe(fx.provide(platform.layer))


@testing.effect
def test_example_serves_its_toolkit_over_stdio():
    @fx.gen
    def session():
        client = yield from mcp_client.McpClient()
        tools = {tool["name"]: tool for tool in (yield from client.list_tools())}
        total = yield from client.call_tool(tools["add"], {"a": 2, "b": 3}, schema=S.Struct(Sum))
        shouted = yield from client.call_tool(tools["shout"], {"text": "hi"})
        invalid = yield from client.call_tool(
            tools["add"], {"a": "two"}, schema=S.Struct(Sum)
        ).flip()
        return client, tools, total, shouted, invalid

    client, tools, total, shouted, invalid = yield from fx.scoped(
        session.pipe(fx.provide(_client(mcp_protocol.v2025_11_25)))
    )
    assert client.protocol_version == "2025-11-25"
    assert client.server_info == {"name": "calculator", "version": "1.0.0"}
    assert client.instructions == "Use add for sums and shout for emphasis."
    assert sorted(tools) == ["add", "shout"]
    assert tools["add"].get("annotations", {}).get("readOnlyHint") is True
    assert total == {"total": 5}
    assert shouted == {"content": [{"type": "text", "text": "HI"}], "isError": False}
    # From 2025-11-25 on, invalid arguments are a tool error result.
    assert isinstance(invalid, McpClientError)
    assert isinstance(invalid.reason, ToolError)
    [block] = invalid.reason.result["content"]
    assert block["type"] == "text"
    assert 'at ["a"]' in block["text"]


@testing.effect
def test_example_serves_the_stateless_revision_over_stdio():
    @fx.gen
    def session():
        client = yield from mcp_client.McpClient()
        kit = yield from mcp_client.toolkit(client, "calc_")
        results = yield from kit.handle("calc_add", {"a": 1, "b": 1})
        last = yield from results.run_last()
        return client, last

    client, last = yield from fx.scoped(session.pipe(fx.provide(_client(mcp_protocol.v2026_07_28))))
    assert client.protocol_version == "2026-07-28"
    assert client.server_info == {"name": "calculator", "version": "1.0.0"}
    assert last is not None and last.value.result == '{"total":2}'
