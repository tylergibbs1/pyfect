"""Ports of Effect's MCP conformance utility titles
(test/ai/McpServer/McpConformance/UtilitiesTest.ts): ``suite`` and the
HTTP titles of ``statefulLegacySuite`` for every stateful revision, as the
per-revision files run them, and ``statelessModernSuite`` for 2026-07-28.

The HTTP titles read each response's event stream as the server writes
it (``_mcp_http.sse_reader``).

Omitted: the batch titles of ``statefulLegacySuite`` (the STDIO sibling
cancellation and the HTTP batch cancellations), ported in
test_mcp_batch_cancellation.py.
"""

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import ToolEntry
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.exit import Success

from ._mcp import stdio_harness
from ._mcp_http import (
    Conformance,
    Json,
    conformance,
    http_harness,
    initialize_session,
    server_layer,
    sse_reader,
)

STATEFUL = [P.v2024_11_05, P.v2025_03_26, P.v2025_06_18, P.v2025_11_25]
MODERN = P.v2026_07_28


def _id(protocol: P.AnyProtocolAdapter) -> str:
    return protocol.protocol_version


def _tool(name: str, handle: Any) -> ToolEntry:
    return ToolEntry(
        {"name": name, "inputSchema": {"type": "object", "properties": {}}}, Context.empty(), handle
    )


def _released(text: str) -> Json:
    return {"content": [{"type": "text", "text": text}]}


def _silently_accepted(test: Conformance, body: Json) -> fx.Effect[None, Any]:
    @fx.gen
    def run():
        session = yield from test.initialize()
        yield from test.notify_initialized(session)
        response = yield from test.send(session, body)
        assert response.status == 202
        assert (yield from response.text) == ""

    return run


# --- suite: Ping ----------------------------------------------------------------------------


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_respond_to_a_client_ping_with_an_empty_result(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Utilities / Ping / MUST respond to a client ping with an empty result"""
    test = yield from conformance(protocol)
    session = yield from test.initialize()
    yield from test.notify_initialized(session)
    response = yield from test.ping(session, 42)
    message = yield from test.decode_result(response)
    assert response.status == 200
    assert message["id"] == 42
    assert message["result"] == {}


# --- suite: Cancellation --------------------------------------------------------------------


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_not_send_a_response_to_a_cancellation_notification(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Utilities / Cancellation / MUST not send a response to a cancellation notification"""  # noqa: E501
    test = yield from conformance(protocol)
    params = {"requestId": "unknown-request", "reason": "No longer needed"}
    body = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": params}
    yield from _silently_accepted(test, body)


def _gated(entered: Deferred[None], release: Deferred[None], interrupted: Deferred[None]) -> Any:
    def handle(_: object) -> fx.Effect[Any]:
        return (
            entered.succeed(None)
            .and_then(release.wait())
            .on_interrupt(interrupted.succeed(None))
            .as_(_released("released"))
        )

    return handle


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_stop_work_and_suppress_the_response_after_cancellation(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Utilities / Cancellation / SHOULD stop work and suppress the response after cancellation"""  # noqa: E501
    entered, release, interrupted = Deferred[None](), Deferred[None](), Deferred[None]()
    yield from fx.add_finalizer(lambda _: release.succeed(None))
    harness = yield from stdio_harness(protocol)
    yield from harness.server.add_tool(_tool("GatedTool", _gated(entered, release, interrupted)))
    yield from harness.initialize()
    yield from harness.send(
        {
            "jsonrpc": "2.0",
            "id": "cancelled-tool-call",
            "method": "tools/call",
            "params": {"name": "GatedTool", "arguments": {}},
        }
    )
    yield from entered.wait()
    yield from harness.send_notification(
        "notifications/cancelled",
        {"requestId": "cancelled-tool-call", "reason": "No longer needed"},
    )
    yield from interrupted.wait()
    yield from harness.send({"jsonrpc": "2.0", "id": "post-cancellation-ping", "method": "ping"})
    while True:
        message = yield from harness.receive()
        assert message.get("id") != "cancelled-tool-call"
        if message.get("id") == "post-cancellation-ping":
            assert message["result"] == {}
            break


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_ignore_cancellation_for_an_unknown_request_identifier(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Utilities / Cancellation / SHOULD ignore cancellation for an unknown request identifier"""  # noqa: E501
    test = yield from conformance(protocol)
    body = {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 999}}
    yield from _silently_accepted(test, body)


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_allow_a_later_request_to_reuse_an_unknown_cancelled_identifier(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Utilities / Cancellation / SHOULD allow a later request to reuse an unknown cancelled identifier"""  # noqa: E501
    harness = yield from stdio_harness(protocol)
    yield from harness.initialize()
    yield from harness.send_notification("notifications/cancelled", {"requestId": "reused-id"})
    reused = yield from harness.send_request("ping", None, "reused-id").fork()
    yield from fx.yield_now()
    control = yield from harness.send_request("ping", None, "control-id")
    assert control["result"] == {}
    yield from fx.yield_now()
    reused_exit = reused.poll_unsafe()
    assert isinstance(reused_exit, Success)
    assert reused_exit.value["result"] == {}


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_ignore_cancellation_for_an_already_completed_request_identifier(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Utilities / Cancellation / SHOULD ignore cancellation for an already completed request identifier"""  # noqa: E501
    test = yield from conformance(protocol)
    session = yield from test.initialize()
    yield from test.notify_initialized(session)
    yield from test.ping(session, 11)
    response = yield from test.send(
        session,
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": 11}},
    )
    assert response.status == 202
    assert (yield from response.text) == ""


# --- suite: Progress ------------------------------------------------------------------------


def _progress(params: Json) -> Json:
    return {"jsonrpc": "2.0", "method": "notifications/progress", "params": params}


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_accept_string_progress_tokens(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Utilities / Progress / MUST accept string progress tokens"""
    test = yield from conformance(protocol)
    yield from _silently_accepted(test, _progress({"progressToken": "task-1", "progress": 1}))


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_accept_numeric_progress_tokens(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Utilities / Progress / MUST accept numeric progress tokens"""
    test = yield from conformance(protocol)
    yield from _silently_accepted(test, _progress({"progressToken": 12, "progress": 1}))


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_schema_accepts_the_optional_total(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Utilities / Progress / SCHEMA accepts the optional total"""
    test = yield from conformance(protocol)
    params = {"progressToken": "task-with-total", "progress": 1, "total": 2}
    yield from _silently_accepted(test, _progress(params))


# --- statelessModernSuite -------------------------------------------------------------------


@testing.effect
def test_should_send_no_response_when_a_cancellation_notification_is_received():
    """Mcp Conformance / Utilities > Stateless modern / Cancellation / should send no response when a cancellation notification is received"""  # noqa: E501
    test = yield from conformance(MODERN)
    discovered = yield from test.initialize()
    params = {"requestId": "unknown-request", "reason": "No longer needed"}
    response = yield from test.send(
        discovered, {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": params}
    )
    assert response.status == 202
    assert (yield from response.text) == ""


@testing.effect
def test_should_interrupt_work_and_suppress_its_response_when_an_active_request_is_cancelled():
    """Mcp Conformance / Utilities > Stateless modern / Cancellation / should interrupt work and suppress its response when an active request is cancelled"""  # noqa: E501
    entered, release, interrupted = Deferred[None](), Deferred[None](), Deferred[None]()
    yield from fx.add_finalizer(lambda _: release.succeed(None))
    harness = yield from stdio_harness(MODERN)
    yield from harness.server.add_tool(
        _tool("ModernGatedTool", _gated(entered, release, interrupted))
    )
    yield from harness.initialize()
    yield from harness.send(
        {
            "jsonrpc": "2.0",
            "id": "cancelled-tool-call",
            "method": "tools/call",
            "params": harness.with_metadata({"name": "ModernGatedTool", "arguments": {}}),
        }
    )
    yield from entered.wait()
    yield from harness.send_notification(
        "notifications/cancelled",
        harness.with_metadata({"requestId": "cancelled-tool-call", "reason": "No longer needed"}),
    )
    yield from interrupted.wait()
    control = yield from harness.send_request("server/discover", {}, "post-cancellation-discover")
    assert control["id"] == "post-cancellation-discover"


@testing.effect
def test_should_allow_a_later_request_to_reuse_an_identifier_cancelled_before_it_was_active():
    """Mcp Conformance / Utilities > Stateless modern / Cancellation / should allow a later request to reuse an identifier cancelled before it was active"""  # noqa: E501
    harness = yield from stdio_harness(MODERN)
    yield from harness.initialize()
    yield from harness.send_notification(
        "notifications/cancelled",
        harness.with_metadata({"requestId": "reused-id"}),
    )
    reused = yield from harness.send_request("server/discover", {}, "reused-id")
    assert reused["id"] == "reused-id"
    assert "result" in reused


# --- statefulLegacySuite: HTTP --------------------------------------------------------------


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.live
def test_should_cancel_only_the_owning_request_when_http_sessions_reuse_a_request_id(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Utilities > Cancellation > HTTP / should cancel only the owning request when HTTP sessions reuse a request ID"""  # noqa: E501
    interrupted, other_interrupted = Deferred[None](), Deferred[None]()
    release_other = Deferred[None]()

    @fx.gen
    def registrations():
        server = yield from M.McpServer()
        for name in ("Wait", "Keep"):

            def handle(_: object, name: str = name) -> fx.Effect[Any]:
                body = fx.never if name == "Wait" else release_other.wait()
                flag = interrupted if name == "Wait" else other_interrupted
                return (
                    server.notify("notifications/message", {"level": "error", "data": name})
                    .and_then(body)
                    .on_interrupt(flag.succeed(None))
                    .as_(_released("kept"))
                )

            yield from server.add_tool(
                ToolEntry(
                    {"name": name, "inputSchema": {"type": "object"}}, Context.empty(), handle
                )
            )

    harness = yield from http_harness(server_layer("HttpCancellation", (protocol,), registrations))
    other_headers = yield from initialize_session(harness, protocol)
    call: Json = {"jsonrpc": "2.0", "id": "wait", "method": "tools/call"}
    other_response = yield from harness.post(
        {**call, "params": {"name": "Keep", "arguments": {}}}, other_headers
    )
    other_stream = yield from sse_reader(other_response)
    assert (yield from other_stream.take())["method"] == "notifications/message"
    headers = yield from initialize_session(harness, protocol)
    response = yield from harness.post(
        {**call, "params": {"name": "Wait", "arguments": {}}}, headers
    )
    stream = yield from sse_reader(response)
    assert (yield from stream.take())["method"] == "notifications/message"
    cancelled = yield from harness.post(
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": "wait"}},
        headers,
    )
    assert cancelled.status == 202
    yield from interrupted.wait().timeout("1 second")
    assert (yield from stream.drain().timeout("1 second")) == []
    yield from release_other.succeed(None)
    assert (yield from other_stream.drain().timeout("1 second")) == [
        {"jsonrpc": "2.0", "id": "wait", "result": _released("kept")}
    ]
    assert not (yield from other_interrupted.is_done())


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.live
def test_should_close_without_a_reply_when_a_tool_is_cancelled_before_emitting_http_output(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Utilities > Cancellation > HTTP / should close without a reply when a tool is cancelled before emitting HTTP output"""  # noqa: E501
    entered, interrupted = Deferred[None](), Deferred[None]()

    def wait(_: object) -> fx.Effect[Any]:
        return entered.succeed(None).and_then(fx.never).on_interrupt(interrupted.succeed(None))

    @fx.gen
    def registrations():
        server = yield from M.McpServer()
        yield from server.add_tool(
            ToolEntry({"name": "Wait", "inputSchema": {"type": "object"}}, Context.empty(), wait)
        )

    harness = yield from http_harness(server_layer("HttpCancellation", (protocol,), registrations))
    headers = yield from initialize_session(harness, protocol)
    pending = yield from harness.post(
        {
            "jsonrpc": "2.0",
            "id": "wait",
            "method": "tools/call",
            "params": {"name": "Wait", "arguments": {}},
        },
        headers,
    ).fork()
    yield from entered.wait()
    cancelled = yield from harness.post(
        {"jsonrpc": "2.0", "method": "notifications/cancelled", "params": {"requestId": "wait"}},
        headers,
    )
    assert cancelled.status == 202
    yield from interrupted.wait().timeout("1 second")
    response = yield from pending.join().timeout("1 second")
    assert response.status == 200
    assert response.headers.get("content-type") == "text/event-stream"
    assert (yield from response.text) == ""
