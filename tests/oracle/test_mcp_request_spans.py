"""Ports of the ``tracing`` titles of Effect's ``test/ai/McpServer/McpServer.test.ts``: each
request's server span, after the OpenTelemetry MCP semantic conventions.

``Toolkit.RecordToolArguments`` is ``toolkit.RecordToolArguments``. The last title's
custom transport is ``layer_rpc_protocol`` over a ``ServerProtocol`` whose ``send`` dies on
the first ``Exit`` of request ``"1"``.
"""

from __future__ import annotations

from typing import Any, TypedDict

import pyfect as fx
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai._mcp.core import ToolEntry
from pyfect.context import Context
from pyfect.exit import Failure
from pyfect.layer import provide
from pyfect.queue import Queue
from pyfect.rpc import server as rpc_server
from pyfect.tracer import CurrentTracer, Ended, NativeSpan, SpanRequest, Tracer

from ._mcp_http import HttpHarness, http_harness, initialize_session, read_message, server_layer
from ._mcp_rpc import Message, custom_transport, request


class _Location(TypedDict):
    location: str


GetWeather = T.make(
    "get_weather",
    parameters=S.Struct(_Location),
    success=S.String,
    failure=S.String,
    failure_mode="return",
)
WeatherToolkit = K.make(GetWeather)


def _weather(params: _Location, _: object) -> fx.Effect[str, str]:
    location = params["location"]
    if location == "Atlantis":
        return fx.fail("unknown location")
    return fx.succeed(f"sunny in {location}")


def _tool_call_tracer(ended: Queue[NativeSpan]) -> Tracer:
    """Offers each ended ``tools/call`` span to ``ended``."""

    class _Span(NativeSpan):
        __slots__ = ()

        def end(self, end_time: int, exit: Any, /) -> None:
            super().end(end_time, exit)
            if self.attributes.get("mcp.method.name") == "tools/call":
                ended.offer_unsafe(self)

    def span(request: SpanRequest) -> NativeSpan:
        return _Span(request)

    return Tracer.make(span)


def _echo() -> fx.Effect[None, Any, Any]:
    entry = ToolEntry(
        {"name": "echo", "inputSchema": {"type": "object"}},
        Context.empty(),
        lambda _: fx.succeed({"content": []}),
    )
    return M.McpServer().flat_map(lambda server: server.add_tool(entry))


def _traced_server(record_tool_arguments: bool = False):
    """A function that sends ``tools/call`` over HTTP and gives its ended MCP span, and the
    session's headers."""

    @fx.gen
    def run():
        ended = yield from Queue[NativeSpan].unbounded()
        tools = layer.merge(
            M.toolkit(WeatherToolkit).pipe(
                layer.provide_merge(WeatherToolkit.to_layer(GetWeather.handler(_weather)))
            ),
            layer.effect_discard(_echo()),
        )
        app = tools.pipe(layer.provide_merge(server_layer("TracingTest", (P.v2025_06_18,))))
        harness: HttpHarness = yield from http_harness(app)
        headers = yield from initialize_session(harness, P.v2025_06_18)

        def call_tool(params: dict[str, Any]) -> fx.Effect[NativeSpan]:
            body = {"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params}
            posted = harness.post(body, headers).flat_map(read_message)
            # The in-memory server handles a request in the client's context.
            traced = posted.pipe(fx.provide_service(CurrentTracer, _tool_call_tracer(ended))).pipe(
                fx.provide_service(K.RecordToolArguments, record_tool_arguments)
            )
            return traced.and_then(ended.take())

        return call_tool, headers

    return run


@testing.effect
def test_names_tool_call_spans_after_the_tool_and_does_not_record_arguments_by_default():
    """McpServer / tracing / names tool call spans after the tool and does not record arguments by default"""  # noqa: E501
    call_tool, headers = yield from _traced_server()
    span = yield from call_tool({"name": "get_weather", "arguments": {"location": "London"}})
    assert span.name == "tools/call get_weather"
    assert {
        "jsonrpc.request.id": "1",
        "mcp.session.id": headers["Mcp-Session-Id"],
        "gen_ai.operation.name": "execute_tool",
        "gen_ai.tool.name": "get_weather",
    }.items() <= span.attributes.items()
    assert "parameters" not in span.attributes
    assert "gen_ai.tool.call.arguments" not in span.attributes


@testing.effect
def test_records_tool_arguments_when_record_tool_arguments_is_enabled():
    """McpServer / tracing / records tool arguments when Toolkit.RecordToolArguments is enabled"""
    call_tool, _ = yield from _traced_server(record_tool_arguments=True)
    # ``echo`` is registered with ``add_tool``, so the toolkit cannot record its arguments.
    span = yield from call_tool({"name": "echo", "arguments": {"text": "hi"}})
    assert span.attributes.get("gen_ai.tool.call.arguments") == '{"text":"hi"}'


@testing.effect
def test_continues_the_client_trace_from_params_meta_traceparent():
    """McpServer / tracing / continues the client trace from params._meta.traceparent"""
    call_tool, _ = yield from _traced_server()
    span = yield from call_tool(
        {
            "name": "get_weather",
            "arguments": {"location": "London"},
            "_meta": {"traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01"},
        }
    )
    assert span.trace_id == "0af7651916cd43dd8448eb211c80319c"
    assert span.parent is not None
    assert span.parent.span_id == "b7ad6b7169203331"


@testing.effect
def test_marks_a_tool_result_with_is_error_as_a_tool_error():
    """McpServer / tracing / marks a tool result with isError as a tool_error"""
    call_tool, _ = yield from _traced_server()
    span = yield from call_tool({"name": "get_weather", "arguments": {"location": "Atlantis"}})
    assert span.attributes.get("error.type") == "tool_error"


@testing.effect
def test_records_the_internal_error_sent_after_an_error_response_fails_to_write():
    """McpServer / tracing / records the internal error sent after an error response fails to write"""  # noqa: E501
    ended = yield from Queue[NativeSpan].unbounded()
    fail_write = [True]

    def send(_: int, message: Message) -> fx.Effect[None]:
        if fail_write[0] and message["_tag"] == "Exit" and message["requestId"] == "1":
            fail_write[0] = False
            return fx.die("write failed")
        return fx.void

    transport = yield from custom_transport(send=send)
    served = M.layer_rpc_protocol(name="TracingTest", version="1.0.0", protocols=[P.v2025_03_26])
    yield from served.pipe(
        provide(layer.succeed(rpc_server.ServerProtocol, transport.protocol))
    ).build()
    write = yield from transport.ready.wait()

    def client_sends(message: Message) -> fx.Effect[None]:
        return write(1, message).pipe(fx.provide_service(CurrentTracer, _tool_call_tracer(ended)))

    client_info = {"name": "client", "version": "1.0.0"}
    payload = {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": client_info}
    yield from client_sends(request("0", "initialize", payload))
    yield from transport.outbound.take()

    # An unknown tool fails with the request error -32602, whose write then fails.
    yield from client_sends(request("1", "tools/call", {"name": "missing_tool"}))

    _, answer = yield from transport.outbound.take()
    assert answer == {
        "_tag": "Exit",
        "requestId": "1",
        "exit": {
            "_tag": "Failure",
            "cause": [{"_tag": "Fail", "error": {"code": -32603, "message": "Internal error"}}],
        },
    }
    span = yield from ended.take()
    assert isinstance(span.status, Ended)
    assert isinstance(span.status.exit, Failure)
    assert span.attributes.get("rpc.status_code") == "-32603"
    assert span.attributes.get("error.type") == "-32603"
