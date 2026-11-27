"""MCP spans (DOGFOOD atlas #8). The server's follow Effect's, after the OpenTelemetry MCP
semantic conventions: each request is a server span named after its method, with the tool
appended for ``tools/call`` (``tools/call add``), carrying ``mcp.method.name`` and
``gen_ai.tool.name`` but not the arguments. Effect's ``McpClient`` makes no spans of its
own (4.1.5: no ``withSpan``, its functions ``fnUntraced``), nor does pyfect's: the server's
span joins the caller's trace through the HTTP client's propagated context, under its POST."""

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
def test_the_server_span_sits_under_the_http_post_in_the_callers_trace(
    protocol: C.ClientProtocol,
):
    tracer, spans = recording()

    @fx.gen
    def session():
        client = yield from connect(protocol)
        tool = yield from find_tool(client, "add")
        return (yield from client.call_tool(tool, {"a": 1, "b": 2}))

    traced: Any = fx.scoped(session).with_span("caller")
    program: Any = traced.pipe(fx.provide_service(CurrentTracer, tracer))
    result = fx.run_blocking(program.timeout("10 seconds").or_die())
    assert result.get("structuredContent") == {"total": 3}

    assert not [span.name for span in spans if span.name.startswith("McpClient")]
    [caller] = called(spans, "caller")
    [server] = called(spans, "tools/call add")
    assert server.kind == "server"
    assert server.attributes["mcp.method.name"] == "tools/call"
    assert server.attributes["gen_ai.tool.name"] == "add"
    assert "gen_ai.tool.call.arguments" not in server.attributes
    assert server.trace_id == caller.trace_id
    assert server.parent is not None
    [post] = [span for span in spans if span.span_id == server.parent.span_id]
    assert post.kind == "client"
    assert post.attributes["http.request.method"] == "POST"
    assert post.parent is caller
    assert called(spans, "tools/list")
