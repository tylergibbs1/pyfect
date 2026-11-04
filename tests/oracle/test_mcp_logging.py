"""Ports of Effect's MCP conformance logging titles
(test/ai/McpServer/McpConformance/LoggingTest.ts), run over stdio for each
stateful revision and over 2026-07-28 for the stateless suite.

Omitted:
- the HTTP background-log titles ("should filter background HTTP logs when
  the destination session selects ...", "should isolate background HTTP log
  levels ...", "MUST not deliver logs from ... on an HTTP subscription
  stream"): they read an SSE stream the in-memory HTTP harness buffers whole.
- "SCHEMA preserves ...", "MUST allow arbitrary JSON-compatible log data",
  "should preserve the level, logger, and JSON data when decoding a log
  notification": schema decoding, pinned in test_mcp_schema.py.
- "SCENARIO does not corrupt the stdio protocol stream with log output":
  the harness reads parsed frames, so a corrupt line fails every test.
"""

from __future__ import annotations

from typing import Any, Never

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K

from ._mcp import Json, StdioHarness, stdio_harness

STATEFUL = [P.v2024_11_05, P.v2025_03_26, P.v2025_06_18, P.v2025_11_25]
LEVELS = ["debug", "info", "notice", "warning", "error", "critical", "alert", "emergency"]
EFFECT_LEVELS = {
    "debug": "Debug",
    "info": "Info",
    "notice": "Info",
    "warning": "Warn",
    "error": "Error",
    "critical": "Fatal",
    "alert": "Fatal",
    "emergency": "Fatal",
}

LogLevelTool = T.make("LogLevelTool", success=S.String)


def _current_level(_params: Any, _context: Any) -> fx.Effect[str]:
    return fx.CurrentLogLevel().map(str)


def _fixture(
    protocol: P.AnyProtocolAdapter,
) -> fx.Effect[tuple[StdioHarness, M.McpServerService], Any, Any]:
    """An initialized stdio client and the server it talks to."""
    servers: list[M.McpServerService] = []
    kit = K.make(LogLevelTool)
    registration = M.register_toolkit(kit).pipe(
        fx.provide(kit.to_layer(LogLevelTool.handler(_current_level)))
    )
    capture = M.McpServer().map(servers.append).as_void()

    @fx.gen
    def run():
        harness = yield from stdio_harness(protocol, None, registration, capture)
        yield from harness.initialize()
        # A round trip, so ``notifications/initialized`` is handled before
        # the test broadcasts (Effect's harness awaits it).
        yield from harness.send_request("ping", {})
        return harness, servers[0]

    return run


def _message(harness: StdioHarness) -> fx.Effect[Json]:
    """The next ``notifications/message``, skipping other messages."""

    @fx.gen
    def run():
        while True:
            message = yield from harness.receive()
            if message.get("method") == "notifications/message":
                return message

    return run


def _tool_text(response: Json) -> str:
    return response["result"]["content"][0]["text"]


@pytest.mark.parametrize("protocol", STATEFUL, ids=lambda p: p.protocol_version)
@testing.effect
def test_must_accept_every_specified_log_level(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Logging / Setting Log Level / MUST accept every specified log level"""
    harness, _ = yield from _fixture(protocol)
    for level in LEVELS:
        response = yield from harness.send_request("logging/setLevel", {"level": level})
        assert response["result"] == {}


@pytest.mark.parametrize("protocol", STATEFUL, ids=lambda p: p.protocol_version)
@testing.effect
def test_must_reject_an_unknown_log_level(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Logging / Setting Log Level / MUST reject an unknown log level"""
    harness, _ = yield from _fixture(protocol)
    response = yield from harness.send_request("logging/setLevel", {"level": "verbose"})
    assert response["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE


@pytest.mark.parametrize("protocol", STATEFUL, ids=lambda p: p.protocol_version)
@testing.effect
def test_should_update_the_minimum_level_for_subsequent_operations(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Logging / Setting Log Level / SHOULD update the minimum level for subsequent operations"""  # noqa: E501
    harness, _ = yield from _fixture(protocol)
    call: Json = {"name": "LogLevelTool", "arguments": {}}
    # Before the client sets one, handlers run at the server's level.
    assert _tool_text((yield from harness.send_request("tools/call", call))) == "Info"
    yield from harness.send_request("logging/setLevel", {"level": "debug"})
    assert _tool_text((yield from harness.send_request("tools/call", call))) == "Debug"


@pytest.mark.parametrize("protocol", STATEFUL, ids=lambda p: p.protocol_version)
@testing.effect
def test_should_send_notifications_at_the_selected_level_and_higher(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Logging / Setting Log Level / SHOULD send notifications at the selected level and higher"""  # noqa: E501
    harness, server = yield from _fixture(protocol)
    yield from harness.send_request("logging/setLevel", {"level": "warning"})
    payload: Json = {"level": "warning", "logger": "conformance", "data": "at-threshold"}
    yield from server.notify("notifications/message", payload)
    assert (yield from _message(harness))["params"] == payload


@pytest.mark.parametrize("protocol", STATEFUL, ids=lambda p: p.protocol_version)
@testing.effect
def test_must_not_send_notifications_below_the_selected_level(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Logging / Setting Log Level / MUST not send notifications below the selected level"""  # noqa: E501
    harness, server = yield from _fixture(protocol)
    yield from harness.send_request("logging/setLevel", {"level": "warning"})
    below: Json = {"level": "debug", "logger": "conformance", "data": "below-threshold"}
    allowed: Json = {"level": "warning", "logger": "conformance", "data": "allowed-sentinel"}
    yield from server.notify("notifications/message", below)
    yield from server.notify("notifications/message", allowed)
    assert (yield from _message(harness))["params"] == allowed


@pytest.mark.parametrize("protocol", STATEFUL, ids=lambda p: p.protocol_version)
@testing.effect
def test_drops_debug_logs_before_the_client_sets_a_level(protocol: P.AnyProtocolAdapter):
    """Effect's canDeliver: a session's threshold starts at the server's
    CurrentLogLevel (Info), compared on Effect's levels, so ``debug`` is
    dropped and ``notice`` (Effect's Info) is sent."""
    harness, server = yield from _fixture(protocol)
    dropped: Json = {"level": "debug", "data": "dropped"}
    sent: Json = {"level": "notice", "data": "sent"}
    yield from server.notify("notifications/message", dropped)
    yield from server.notify("notifications/message", sent)
    assert (yield from _message(harness))["params"] == {"level": "notice", "data": "sent"}


@pytest.mark.parametrize("protocol", [*STATEFUL, P.v2026_07_28], ids=lambda p: p.protocol_version)
@testing.effect
def test_starts_sessions_at_the_servers_current_log_level(protocol: P.AnyProtocolAdapter):
    """Effect's layerWithRuntime reads ``CurrentLogLevel`` once, where the
    server is built: a server run at Debug sends ``debug`` before the client
    sets a level, and its handlers run at Debug."""
    harness, server = yield from _fixture(protocol).pipe(
        fx.provide_service(fx.CurrentLogLevel, fx.LogLevel.DEBUG)
    )
    meta = {"_meta": _METADATA} if protocol.is_stateless else {}
    call: Json = {"name": "LogLevelTool", "arguments": {}, **meta}
    text = _tool_text((yield from harness.send_request("tools/call", call)))
    # 2026-07-28 lists the result as JSON text.
    assert text == ('"Debug"' if protocol.is_stateless else "Debug")
    if not protocol.is_stateless:
        yield from server.notify("notifications/message", {"level": "debug", "data": "sent"})
        assert (yield from _message(harness))["params"] == {"level": "debug", "data": "sent"}


@pytest.mark.parametrize("protocol", STATEFUL, ids=lambda p: p.protocol_version)
@testing.effect
def test_must_emit_log_messages_as_notifications_without_an_identifier(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Logging / Log Message Notifications / MUST emit log messages as notifications without an identifier"""  # noqa: E501
    harness, server = yield from _fixture(protocol)
    payload: Json = {"level": "warning", "logger": "database", "data": {"message": "slow query"}}
    yield from server.notify("notifications/message", payload)
    message = yield from _message(harness)
    assert message["jsonrpc"] == "2.0"
    assert message["params"] == payload
    assert "id" not in message
    assert "result" not in message


# --- 2026-07-28: request-scoped levels ----------------------------------------------------

_METADATA: Json = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}


def _modern_call(harness: StdioHarness, level: object | None) -> fx.Effect[Json]:
    meta = dict(_METADATA)
    if level is not None:
        meta["io.modelcontextprotocol/logLevel"] = level
    return harness.send_request(
        "tools/call", {"name": "LogLevelTool", "arguments": {}, "_meta": meta}
    )


@testing.effect
def test_should_advertise_logging_when_request_scoped_log_filtering_is_supported():
    """Mcp Conformance (2026-07-28) / Logging > Stateless modern / should advertise logging when request-scoped log filtering is supported"""  # noqa: E501
    harness, _ = yield from _fixture(P.v2026_07_28)
    response = yield from harness.send_request("server/discover", {"_meta": _METADATA})
    assert "logging" in response["result"]["capabilities"]


@testing.effect
def test_should_apply_every_specified_log_level_to_the_request_that_declares_it():
    """Mcp Conformance (2026-07-28) / Logging > Stateless modern / should apply every specified log level to the request that declares it"""  # noqa: E501
    harness, _ = yield from _fixture(P.v2026_07_28)
    for level in LEVELS:
        response = yield from _modern_call(harness, level)
        assert response["result"]["content"] == [
            {"type": "text", "text": f'"{EFFECT_LEVELS[level]}"'}
        ]


@testing.effect
def test_should_reject_a_request_when_its_request_scoped_log_level_is_unknown():
    """Mcp Conformance (2026-07-28) / Logging > Stateless modern / should reject a request when its request-scoped log level is unknown"""  # noqa: E501
    harness, _ = yield from _fixture(P.v2026_07_28)
    response = yield from _modern_call(harness, "verbose")
    assert response["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE


@testing.effect
def test_sends_a_stateless_requests_logs_at_its_own_level_only():
    """Effect's McpServer: a 2026-07-28 request gets the logs at or above
    the level its ``_meta`` names, and none when it names no level."""
    emitted: list[Json] = []

    def handle(_params: Any, _context: Any) -> fx.Effect[str, Never, M.McpServer]:
        @fx.gen
        def run():
            server = yield from M.McpServer()
            for level in ("debug", "warning"):
                yield from server.notify(
                    "notifications/message", {"level": level, "data": f"{level}-log"}
                )
            return "done"

        return run

    tool = T.make("Logs", success=S.String).add_dependency(M.McpServer)
    kit = K.make(tool)
    registration = M.register_toolkit(kit).pipe(fx.provide(kit.to_layer(tool.handler(handle))))
    harness = yield from stdio_harness(P.v2026_07_28, None, registration)
    for level in (None, "warning", "debug"):
        meta = dict(_METADATA)
        if level is not None:
            meta["io.modelcontextprotocol/logLevel"] = level
        yield from harness.send(
            {
                "jsonrpc": "2.0",
                "id": str(level),
                "method": "tools/call",
                "params": {"name": "Logs", "arguments": {}, "_meta": meta},
            }
        )
        while True:
            message = yield from harness.receive()
            if message.get("id") == str(level):
                break
            emitted.append({"request": str(level), **message["params"]})
    assert emitted == [
        {"request": "warning", "level": "warning", "data": "warning-log"},
        {"request": "debug", "level": "debug", "data": "debug-log"},
        {"request": "debug", "level": "warning", "data": "warning-log"},
    ]


@testing.effect
def test_sends_a_stateless_request_only_the_progress_of_its_own_token():
    """Effect's McpServer: on 2026-07-28 a request gets the progress
    notifications of the ``progressToken`` its ``_meta`` names, no other."""

    def handle(_params: Any, _context: Any) -> fx.Effect[str, Never, M.McpServer]:
        @fx.gen
        def run():
            server = yield from M.McpServer()
            for token in ("other", "mine"):
                yield from server.notify(
                    "notifications/progress", {"progressToken": token, "progress": 1}
                )
            return "done"

        return run

    tool = T.make("Progress", success=S.String).add_dependency(M.McpServer)
    kit = K.make(tool)
    registration = M.register_toolkit(kit).pipe(fx.provide(kit.to_layer(tool.handler(handle))))
    harness = yield from stdio_harness(P.v2026_07_28, None, registration)
    meta = {**_METADATA, "progressToken": "mine"}
    params: Json = {"name": "Progress", "arguments": {}, "_meta": meta}
    yield from harness.send({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": params})
    received: list[Json] = []
    while True:
        message = yield from harness.receive()
        if message.get("id") == 1:
            break
        received.append(message["params"])
    assert received == [{"progressToken": "mine", "progress": 1}]
