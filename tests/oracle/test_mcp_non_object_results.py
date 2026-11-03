"""A tool whose result is not a JSON object, served on a revision whose
``structuredContent`` must be an object (2025-06-18, 2025-11-25): the result
is wrapped as ``{"result": ...}`` and the output schema says so, as other MCP
SDKs do, and pyfect's client unwraps it (DOGFOOD atlas #4). Not an Effect
port: Effect's ``McpServer`` drops the output schema and the structured
result there, leaving only the text. A string result is still text alone."""

from __future__ import annotations

from typing import Any, TypedDict

import pytest

import pyfect as fx
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.ai import mcp_client as C
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai.mcp_schema import Tool
from pyfect.http.client import HttpClient

from ._mcp import MCP_ENDPOINT, in_memory_http


class Answer(TypedDict):
    answer: str


Arr = T.make("Arr", success=S.Array(S.Int))
Str = T.make("Str", success=S.String)
Obj = T.make("Obj", success=S.Struct(Answer))
Untyped = T.make("Untyped")
KIT = K.make(Arr, Str, Obj, Untyped)
HANDLERS = KIT.to_layer(
    Arr.handler(lambda _, __: fx.succeed((1, 2))),
    Str.handler(lambda _, __: fx.succeed("hi")),
    Obj.handler(lambda _, __: fx.succeed(Answer(answer="a"))),
    Untyped.handler(lambda _, __: fx.void),
)
SERVER: Any = layer.merge(
    M.layer_http(
        name="s",
        version="1",
        path="/mcp",
        protocols=(P.v2026_07_28, P.v2025_11_25, P.v2025_06_18),
    ),
    M.toolkit(KIT),
).pipe(layer.provide(HANDLERS))


def connect(protocol: C.ClientProtocol) -> fx.Effect[dict[str, tuple[C.McpClientService, Tool]]]:
    @fx.gen
    def run():
        http = yield from in_memory_http(SERVER)
        transport = yield from C.http(url=MCP_ENDPOINT, protocol=protocol).pipe(
            fx.provide_service(HttpClient, http)
        )
        client = yield from C.make(name="c", version="1").pipe(
            fx.provide_service(C.Transport, transport)
        )
        tools = yield from client.list_tools()
        return {tool["name"]: (client, tool) for tool in tools}

    return run  # pyright: ignore[reportReturnType]


LEGACY = [P.v2025_11_25, P.v2025_06_18]


@pytest.mark.parametrize("protocol", LEGACY, ids=lambda p: p.protocol_version)
@testing.effect
def test_a_non_object_result_is_wrapped_and_its_schema_says_so(protocol: C.ClientProtocol):
    tools = yield from connect(protocol)
    client, arr = tools["Arr"]
    assert arr.get("outputSchema") == {
        "type": "object",
        "properties": {"result": {"type": "array", "items": {"type": "integer"}}},
        "required": ["result"],
        "x-fastmcp-wrap-result": True,
    }
    raw = yield from client.call_tool(arr)
    assert raw.get("structuredContent") == {"result": [1, 2]}
    assert raw["content"] == [{"type": "text", "text": "[1,2]"}]
    assert (yield from client.call_tool(arr, schema=S.Unknown)) == [1, 2]
    assert (yield from client.call_tool(arr, schema=S.Array(S.Int))) == (1, 2)

    # An object, a string (whose text is all of it) and no result are as Effect
    # serves them.
    _, str_tool = tools["Str"]
    assert "outputSchema" not in str_tool
    raw = yield from client.call_tool(str_tool)
    assert raw == {"content": [{"type": "text", "text": "hi"}], "isError": False}
    _, obj = tools["Obj"]
    assert (yield from client.call_tool(obj)).get("structuredContent") == {"answer": "a"}
    _, untyped = tools["Untyped"]
    assert "outputSchema" not in untyped
    assert "structuredContent" not in (yield from client.call_tool(untyped))


@testing.effect
def test_the_july_revision_carries_a_non_object_result_as_it_is():
    tools = yield from connect(P.v2026_07_28)
    client, arr = tools["Arr"]
    assert arr.get("outputSchema") == {"type": "array", "items": {"type": "integer"}}
    raw = yield from client.call_tool(arr)
    assert raw.get("structuredContent") == [1, 2]
    assert (yield from client.call_tool(arr, schema=S.Unknown)) == [1, 2]
