"""MCP spans (DOGFOOD atlas #8). The server's follow Effect's: its
``McpServer`` is an ``RpcServer`` with ``spanPrefix: "McpServer"``, so each
request is a server span ``McpServer.<method>`` with ``rpc.system.name`` and
``rpc.method``, and the toolkit names the tool on it (``tool`` and
``parameters``). Effect's ``McpClient`` makes no spans of its own; pyfect's
makes the matching client span ``McpClient.<method>``, naming the tool."""

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect.ai import mcp_client as C
from pyfect.tracer import CurrentTracer, NativeSpan, SpanRequest, Tracer

from .test_mcp_client import PROTOCOLS, connect, find_tool


def recording() -> tuple[Tracer, list[NativeSpan]]:
    spans: list[NativeSpan] = []

    def span(request: SpanRequest) -> NativeSpan:
        made = NativeSpan(request)
        spans.append(made)
        return made

    return Tracer.make(span), spans


def called(spans: list[NativeSpan], name: str) -> list[NativeSpan]:
    return [span for span in spans if span.name == name]


@pytest.mark.parametrize("protocol", PROTOCOLS, ids=lambda p: p.protocol_version)
def test_each_request_is_a_client_span_and_a_server_span_naming_the_method_and_tool(
    protocol: C.ClientProtocol,
):
    tracer, spans = recording()

    @fx.gen
    def session():
        client = yield from connect(protocol)
        tool = yield from find_tool(client, "add")
        return (yield from client.call_tool(tool, {"a": 1, "b": 2}))

    program: Any = fx.scoped(session).pipe(fx.provide_service(CurrentTracer, tracer))
    result = fx.run_blocking(program.timeout("10 seconds").or_die())
    assert result.get("structuredContent") == {"total": 3}

    [client] = called(spans, "McpClient.tools/call")
    assert client.kind == "client"
    assert client.attributes["rpc.method"] == "tools/call"
    assert client.attributes["tool"] == "add"
    [server] = called(spans, "McpServer.tools/call")
    assert server.kind == "server"
    assert server.attributes["rpc.system.name"] == "effect_rpc"
    assert server.attributes["rpc.method"] == "tools/call"
    assert server.attributes["tool"] == "add"
    assert server.attributes["parameters"] == {"a": 1, "b": 2}
    # The server's span is in the client's trace, below the HTTP request.
    assert server.trace_id == client.trace_id
    assert called(spans, "McpClient.tools/list") and called(spans, "McpServer.tools/list")
