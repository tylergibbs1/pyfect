"""Ports of Effect's MCP batch titles about server notifications and
cancellation: the batch SSE framing title of McpServer.test.ts and the
batch cancellation titles of the conformance UtilitiesTest.ts
(``statefulLegacySuite``, for the revisions that accept batches).

The in-memory client streams response bodies, so these read the first SSE
events before cancelling, as Effect's do.
"""

from __future__ import annotations

import json
from typing import Any, cast

import pytest

import pyfect as fx
from pyfect import layer, testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import ToolEntry
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.http import request as R
from pyfect.http.client import HttpClientService
from pyfect.http.response import HttpClientResponse

from ._mcp import CLIENT_INFO, Json, in_memory_http, stdio_harness
from ._mcp_http import sse_reader

URL = "http://localhost/mcp"
ACCEPT = "application/json, text/event-stream"
BATCHING = [
    p for p in (P.v2024_11_05, P.v2025_03_26, P.v2025_06_18, P.v2025_11_25) if p.accepts_batches
]

type Http = HttpClientService[Any, Any]


def _http(
    protocol: P.AnyProtocolAdapter, registrations: fx.Effect[None, Any, M.McpServer]
) -> fx.Effect[Http, Any, Any]:
    app = M.layer_http(name="test-server", version="1.0.0", path="/mcp", protocols=(protocol,))
    registered = layer.effect_discard(registrations).pipe(layer.provide(M.layer))
    return in_memory_http(layer.merge(app, registered))


def _post(
    http: Http, body: object, headers: dict[str, str] | None = None
) -> fx.Effect[HttpClientResponse]:
    request = (
        R.post(URL)
        .set_headers({"accept": ACCEPT, **(headers or {})})
        .body_text(json.dumps(body), "application/json")
    )
    return http.execute(request)


def _session(http: Http, protocol: P.AnyProtocolAdapter) -> fx.Effect[dict[str, str]]:
    version = protocol.protocol_version

    @fx.gen
    def run():
        params = {"protocolVersion": version, "capabilities": {}, "clientInfo": CLIENT_INFO}
        initialize = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params}
        response = yield from _post(http, initialize)
        session = response.headers.get("mcp-session-id")
        assert session is not None
        headers = {"mcp-session-id": session, "mcp-protocol-version": version}
        yield from _post(http, {"jsonrpc": "2.0", "method": "notifications/initialized"}, headers)
        return headers

    return run


def _events(text: str) -> list[Any]:
    """The messages of an SSE body, one per ``data:`` event."""
    return [
        json.loads(line[len("data: ") :]) for line in text.split("\n") if line.startswith("data: ")
    ]


def _flat(messages: list[Any]) -> list[Any]:
    flat: list[Any] = []
    for message in messages:
        if isinstance(message, list):
            flat.extend(cast("list[Any]", message))
        else:
            flat.append(message)
    return flat


def _tool(name: str, handle: Any) -> ToolEntry:
    return ToolEntry({"name": name, "inputSchema": {"type": "object"}}, Context.empty(), handle)


def _call(id: object, name: str) -> Json:
    return {
        "jsonrpc": "2.0",
        "id": id,
        "method": "tools/call",
        "params": {"name": name, "arguments": {}},
    }


def _cancel(request_id: object) -> Json:
    return {
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {"requestId": request_id},
    }


@testing.effect
def test_should_frame_http_batch_notifications_and_results_as_separate_sse_events():
    """McpServer / should frame HTTP batch notifications and results as separate SSE events"""

    @fx.gen
    def registrations():
        server = yield from M.McpServer()

        def emit(_: object) -> fx.Effect[Any]:
            return server.notify(
                "notifications/message", {"level": "error", "data": "batch-log"}
            ).as_({"content": []})

        yield from server.add_tool(_tool("Emit", emit))

    http = yield from _http(P.v2025_03_26, registrations)
    headers = yield from _session(http, P.v2025_03_26)
    response = yield from _post(http, [_call(2, "Emit")], headers)
    assert response.status == 200
    assert response.headers.get("content-type") == "text/event-stream"
    assert _events((yield from response.text)) == [
        {
            "jsonrpc": "2.0",
            "method": "notifications/message",
            "params": {"level": "error", "data": "batch-log"},
        },
        [{"jsonrpc": "2.0", "id": 2, "result": {"content": []}}],
    ]


@pytest.mark.parametrize("protocol", BATCHING, ids=lambda p: p.protocol_version)
@testing.effect
def test_should_preserve_the_remaining_batch_result_when_a_sibling_stdio_request_is_cancelled(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Utilities > Cancellation > STDIO / should preserve the remaining batch result when a sibling STDIO request is cancelled"""  # noqa: E501
    entered = Deferred[None]()
    interrupted = Deferred[None]()

    def wait(_: object) -> fx.Effect[Any]:
        return entered.succeed(None).and_then(fx.never).on_interrupt(interrupted.succeed(None))

    @fx.gen
    def registrations():
        server = yield from M.McpServer()
        yield from server.add_tool(_tool("Wait", wait))

    harness = yield from stdio_harness(protocol, None, registrations)
    yield from harness.initialize()
    yield from harness.send_raw(
        json.dumps([_call(1, "Wait"), {"jsonrpc": "2.0", "id": "1", "method": "ping"}])
    )
    yield from entered.wait()
    yield from harness.send_notification("notifications/cancelled", {"requestId": 1})
    yield from interrupted.wait()
    reply = yield from harness.stdout.take().or_die().timeout(1)
    assert _flat([reply]) == [{"jsonrpc": "2.0", "id": "1", "result": {}}]


@pytest.mark.parametrize("cancelled", ["one", "all"])
@pytest.mark.parametrize("protocol", BATCHING, ids=lambda p: p.protocol_version)
@testing.effect
def test_should_omit_cancelled_replies_and_preserve_remaining_results(
    protocol: P.AnyProtocolAdapter, cancelled: str
):
    """Mcp Conformance / Utilities > Cancellation > HTTP / should omit cancelled replies and preserve remaining results when cancellation affects ${cancelled} of the batch requests"""  # noqa: E501
    release = Deferred[None]()
    interrupted = Deferred[None]()
    other_interrupted = Deferred[None]()

    @fx.gen
    def registrations():
        server = yield from M.McpServer()
        for name in ("Cancel", "Keep"):

            def handle(_: object, name: str = name) -> fx.Effect[Any]:
                body = fx.never if name == "Cancel" else release.wait()
                flag = interrupted if name == "Cancel" else other_interrupted
                return (
                    server.notify("notifications/message", {"level": "error", "data": name})
                    .and_then(body)
                    .on_interrupt(flag.succeed(None))
                    .as_({"content": [{"type": "text", "text": name}]})
                )

            yield from server.add_tool(_tool(name, handle))

    http = yield from _http(protocol, registrations)
    headers = yield from _session(http, protocol)
    response = yield from _post(http, [_call(1, "Cancel"), _call("1", "Keep")], headers)
    stream = yield from sse_reader(response)
    assert (yield from stream.take())["method"] == "notifications/message"
    assert (yield from stream.take())["method"] == "notifications/message"
    yield from _post(http, _cancel(1), headers)
    yield from interrupted.wait().timeout(1)
    assert not (yield from other_interrupted.is_done())
    if cancelled == "all":
        yield from _post(http, _cancel("1"), headers)
        yield from other_interrupted.wait().timeout(1)
    else:
        yield from release.succeed(None)
    messages = yield from stream.drain().timeout(1)
    assert _flat(cast("list[Any]", messages)) == (
        []
        if cancelled == "all"
        else [
            {"jsonrpc": "2.0", "id": "1", "result": {"content": [{"type": "text", "text": "Keep"}]}}
        ]
    )
    assert (yield from other_interrupted.is_done()) == (cancelled == "all")


@pytest.mark.parametrize("protocol", BATCHING, ids=lambda p: p.protocol_version)
@testing.effect
def test_should_close_without_a_reply_when_every_batch_request_is_cancelled(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Utilities > Cancellation > HTTP / should close without a reply when every batch request is cancelled before emitting HTTP output"""  # noqa: E501
    entered = fx.Queue[None]()

    def wait(_: object) -> fx.Effect[Any]:
        return entered.offer(None).and_then(fx.never)

    @fx.gen
    def registrations():
        server = yield from M.McpServer()
        yield from server.add_tool(_tool("Wait", wait))

    http = yield from _http(protocol, registrations)
    headers = yield from _session(http, protocol)
    pending = yield from _post(http, [_call(1, "Wait"), _call(2, "Wait")], headers).fork()
    yield from entered.take_n(2)
    yield from _post(http, [_cancel(1), _cancel(2)], headers)
    response = yield from pending.join().timeout(1)
    assert response.status == 200
    assert response.headers.get("content-type") == "text/event-stream"
    assert (yield from response.text) == ""
