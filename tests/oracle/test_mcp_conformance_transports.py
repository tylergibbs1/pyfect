"""Ports of Effect's MCP conformance transport titles
(test/ai/McpServer/McpConformance/TransportsTest.ts): ``suite`` for every
stateful revision, as the per-revision files run it (the HTTP describe is
"Streamable HTTP", or "Single-endpoint HTTP compatibility extension" on
2024-11-05), and ``statelessModernSuite`` for 2026-07-28.

Omitted: none.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.exit import Success

from ._mcp import stdio_harness
from ._mcp_http import Conformance, Json, conformance

STATEFUL = [P.v2024_11_05, P.v2025_03_26, P.v2025_06_18, P.v2025_11_25]
HEADER_REVISIONS = [P.v2025_06_18, P.v2025_11_25]
UUID_V4 = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}")
ATTACKER = "https://attacker.example"
MODERN = P.v2026_07_28


def _id(protocol: P.AnyProtocolAdapter) -> str:
    return protocol.protocol_version


def _initialize(protocol: P.AnyProtocolAdapter, client: str = "stdio-client") -> Json:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": protocol.protocol_version,
            "capabilities": {},
            "clientInfo": {"name": client, "version": "1.0.0"},
        },
    }


def _empty_202(test: Conformance, body: object) -> fx.Effect[None, Any]:
    @fx.gen
    def run():
        session = yield from test.initialize()
        response = yield from test.send(session, body)
        assert response.status == 202
        assert (yield from response.text) == ""

    return run


def _ended(exit_: fx.Exit[object, object]) -> bool:
    return isinstance(exit_, Success) or exit_.cause.has_interrupts_only


# --- stdio ----------------------------------------------------------------------------------


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_exchange_compact_utf8_newline_delimited_json_rpc_records(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / stdio / MUST exchange compact UTF-8 newline-delimited JSON-RPC records"""  # noqa: E501
    harness = yield from stdio_harness(protocol)
    yield from harness.send(_initialize(protocol))
    frame = yield from harness.raw_stdout.take().or_die()
    assert frame.endswith("\n")
    assert "\n" not in frame[:-1]
    message = json.loads(frame)
    assert message["jsonrpc"] == "2.0" and message["id"] == 1
    assert "result" in message


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_scenario_parses_utf8_json_rpc_records_split_across_input_chunks(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / stdio / SCENARIO parses UTF-8 JSON-RPC records split across input chunks"""  # noqa: E501
    harness = yield from stdio_harness(protocol)
    data = (json.dumps(_initialize(protocol, "stdio-🧪"), ensure_ascii=False) + "\n").encode()
    split = data.index(0xF0) + 2
    yield from harness.send_chunk(data[:split])
    yield from harness.send_chunk(data[split:])
    message = yield from harness.receive()
    assert message["jsonrpc"] == "2.0" and message["id"] == 1


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_scenario_processes_consecutive_stdio_messages_independently(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / stdio / SCENARIO processes consecutive stdio messages independently"""  # noqa: E501
    harness = yield from stdio_harness(protocol)
    yield from harness.send(_initialize(protocol))
    yield from harness.receive()
    yield from harness.send({"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}})
    yield from harness.send({"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}})
    assert (yield from harness.receive()) == {"jsonrpc": "2.0", "id": 2, "result": {}}
    assert (yield from harness.receive()) == {"jsonrpc": "2.0", "id": 3, "result": {}}


@pytest.mark.parametrize("protocol", [p for p in STATEFUL if p is not P.v2025_03_26], ids=_id)
@testing.effect
def test_must_reject_json_rpc_batches_over_stdio(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Transports / stdio / MUST reject JSON-RPC batches over stdio"""
    harness = yield from stdio_harness(protocol)
    yield from harness.send(_initialize(protocol))
    yield from harness.receive()
    yield from harness.send_raw(
        json.dumps(
            [
                {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
                {"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}},
            ]
        )
    )
    assert (yield from harness.receive()) == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {
            "code": MS.INVALID_REQUEST_ERROR_CODE,
            "message": "JSON-RPC batches are not supported",
        },
    }


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_shut_down_when_the_client_closes_stdin(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Transports / stdio / MUST shut down when the client closes stdin"""
    harness = yield from stdio_harness(protocol)
    yield from harness.close
    assert _ended((yield from harness.fiber.await_exit()))


# --- Streamable HTTP: Sending Messages to the Server ----------------------------------------


@pytest.mark.parametrize("protocol", HEADER_REVISIONS, ids=_id)
@testing.effect
def test_must_reject_json_rpc_batches(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Transports / Streamable HTTP / Sending Messages to the Server / MUST reject JSON-RPC batches"""  # noqa: E501
    test = yield from conformance(protocol)
    response = yield from test.post([test.initialize_request()])
    assert response.status >= 400


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_accept_json_rpc_requests_through_post_on_the_mcp_endpoint(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Sending Messages to the Server / MUST accept JSON-RPC requests through POST on the MCP endpoint"""  # noqa: E501
    test = yield from conformance(protocol)
    assert (yield from test.post(test.initialize_request())).status == 200


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_accept_json_rpc_notifications_through_post_on_the_mcp_endpoint(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Sending Messages to the Server / MUST accept JSON-RPC notifications through POST on the MCP endpoint"""  # noqa: E501
    test = yield from conformance(protocol)
    session = yield from test.initialize()
    response = yield from test.notify_initialized(session)
    assert response.status == 202
    assert (yield from response.text) == ""


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_accept_json_rpc_responses_through_post_on_the_mcp_endpoint(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Sending Messages to the Server / MUST accept JSON-RPC responses through POST on the MCP endpoint"""  # noqa: E501
    test = yield from conformance(protocol)
    yield from _empty_202(test, {"jsonrpc": "2.0", "id": 99, "result": {}})


@pytest.mark.parametrize("protocol", HEADER_REVISIONS, ids=_id)
@testing.effect
def test_must_reject_a_protocol_version_header_other_than_the_negotiated_version(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Sending Messages to the Server / MUST reject a protocol-version header other than the negotiated version after initialization"""  # noqa: E501
    test = yield from conformance(protocol)
    session = yield from test.initialize()
    assert session.session_id is not None
    other = "2025-06-18" if protocol is P.v2025_11_25 else "2025-03-26"
    mismatched = yield from test.ping(session, 3, protocol_version=other)
    assert mismatched.status >= 400


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_require_the_application_json_content_type_for_post_requests(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Sending Messages to the Server / MUST require the application/json content type for POST requests"""  # noqa: E501
    test = yield from conformance(protocol)
    accepted = yield from test.request(
        "POST", test.initialize_request(), {"content-type": "Application/JSON; charset=utf-8"}
    )
    assert accepted.status == 200
    for content_type in ("text/plain", "application/json-malicious", ""):
        response = yield from test.request(
            "POST", test.initialize_request(), {"content-type": content_type}
        )
        assert response.status == 415, content_type


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_require_clients_to_accept_application_json_and_text_event_stream(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Sending Messages to the Server / MUST require clients to accept application/json and text/event-stream"""  # noqa: E501
    test = yield from conformance(protocol)
    accepted = yield from test.request(
        "POST",
        test.initialize_request(),
        {"accept": " Text/Event-Stream; q=0.9, Application/JSON "},
    )
    assert accepted.status == 200
    for accept in (
        "application/json",
        "text/event-stream",
        "*/*",
        "application/json, text/event-stream; q=0",
        "application/json, text/event-stream; q=bogus",
        "application/json, text/event-stream; q=2",
        "application/json, text/event-stream; q=-1",
        "application/json-malicious, text/event-stream",
        "",
    ):
        response = yield from test.request("POST", test.initialize_request(), {"accept": accept})
        assert response.status == 406, accept


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_return_application_json_for_a_single_json_rpc_response(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Sending Messages to the Server / MUST return application/json for a single JSON-RPC response"""  # noqa: E501
    test = yield from conformance(protocol)
    response = yield from test.post(test.initialize_request())
    assert re.match(r"^application/json\b", response.headers.get("content-type") or "")


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_return_an_empty_202_response_for_accepted_notifications_and_responses(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Sending Messages to the Server / MUST return an empty 202 response for accepted notifications and responses"""  # noqa: E501
    test = yield from conformance(protocol)
    session = yield from test.initialize()
    notification = yield from test.notify_initialized(session)
    response = yield from test.send(session, {"jsonrpc": "2.0", "id": 99, "result": {}})
    assert notification.status == 202
    assert (yield from notification.text) == ""
    assert response.status == 202
    assert (yield from response.text) == ""


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_reject_unsupported_http_methods_with_method_not_allowed(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Sending Messages to the Server / MUST reject unsupported HTTP methods with method not allowed"""  # noqa: E501
    test = yield from conformance(protocol)
    for method in ("PUT", "PATCH", "HEAD"):
        assert (yield from test.request(method)).status == 405, method


# --- Streamable HTTP: Listening, Session Management -----------------------------------------


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_return_method_not_allowed_when_get_sse_is_not_offered(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Listening for Messages from the Server / MUST return method not allowed when GET SSE is not offered"""  # noqa: E501
    test = yield from conformance(protocol)
    response = yield from test.request("GET")
    assert response.status == 405
    assert response.headers.get("allow") == "POST"


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_scenario_returns_an_mcp_session_identifier_during_initialization(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Session Management / SCENARIO returns an MCP session identifier during initialization"""  # noqa: E501
    test = yield from conformance(protocol)
    assert (yield from test.initialize()).session_id is not None


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_scenario_uses_distinct_uuidv4_session_identifiers(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Transports / Streamable HTTP / Session Management / SCENARIO uses distinct UUIDv4 session identifiers"""  # noqa: E501
    test = yield from conformance(protocol)
    first = yield from test.initialize()
    second = yield from test.initialize(2)
    assert UUID_V4.fullmatch(first.session_id or "")
    assert UUID_V4.fullmatch(second.session_id or "")
    assert first.session_id != second.session_id


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_require_the_returned_session_identifier_on_subsequent_http_requests(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Session Management / MUST require the returned session identifier on subsequent HTTP requests"""  # noqa: E501
    test = yield from conformance(protocol)
    yield from test.initialize()
    response = yield from test.request(
        "POST", test.ping_request(), {"Mcp-Protocol-Version": protocol.protocol_version}
    )
    assert response.status == 400
    error = yield from test.decode_error(response)
    assert error["id"] == 2
    assert error["error"]["code"] == MS.INVALID_REQUEST_ERROR_CODE
    assert (
        error["error"]["message"]
        == "MCP-Session-Id header is required; send initialize to start a session"
    )


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_reject_an_unknown_session_identifier_with_not_found(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Session Management / MUST reject an unknown session identifier with not found"""  # noqa: E501
    test = yield from conformance(protocol)
    response = yield from test.request(
        "POST",
        test.ping_request(),
        {"Mcp-Protocol-Version": protocol.protocol_version, "Mcp-Session-Id": "unknown-session"},
    )
    assert response.status == 404


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_scenario_declines_client_session_termination_without_invalidating_the_session(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Session Management / SCENARIO declines client session termination without invalidating the session"""  # noqa: E501
    test = yield from conformance(protocol)
    session = yield from test.initialize()
    assert session.session_id is not None
    response = yield from test.request(
        "DELETE",
        None,
        {"Mcp-Protocol-Version": protocol.protocol_version, "Mcp-Session-Id": session.session_id},
    )
    assert response.status == 405
    assert response.headers.get("allow") == "POST"
    assert (yield from test.ping(session)).status == 200


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_reject_initialize_requests_carrying_a_session_identifier(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Session Management / MUST reject initialize requests carrying a session identifier"""  # noqa: E501
    test = yield from conformance(protocol)
    session = yield from test.initialize()
    repeated = yield from test.send(session, test.initialize_request(2))
    assert repeated.status == 400
    error = yield from test.decode_error(repeated)
    assert error["id"] == 2
    assert error["error"]["code"] == MS.INVALID_REQUEST_ERROR_CODE
    unknown = yield from test.request(
        "POST", test.initialize_request(3), {"Mcp-Session-Id": "unknown-session"}
    )
    assert unknown.status == 404


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_scenario_keeps_two_distinct_post_sessions_live(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Transports / Streamable HTTP / Session Management / SCENARIO keeps two distinct POST sessions live"""  # noqa: E501
    test = yield from conformance(protocol)
    first = yield from test.initialize()
    second = yield from test.initialize(2)
    assert (yield from test.ping(first, 3)).status == 200
    assert (yield from test.ping(second, 4)).status == 200


# --- Streamable HTTP: Protocol Version Header -----------------------------------------------


@pytest.mark.parametrize("protocol", HEADER_REVISIONS, ids=_id)
@testing.effect
def test_should_use_the_negotiated_protocol_version_when_the_header_is_absent(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Protocol Version Header / SHOULD use the negotiated protocol version when the header is absent"""  # noqa: E501
    test = yield from conformance(protocol)
    session = yield from test.initialize()
    response = yield from test.ping(session, include_protocol_version=False)
    assert response.status == 200
    assert response.headers.get("mcp-protocol-version") == protocol.protocol_version
    assert (yield from test.decode_result(response))["result"] == {}


@pytest.mark.parametrize("protocol", HEADER_REVISIONS, ids=_id)
@testing.effect
def test_must_accept_the_negotiated_protocol_version(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Transports / Streamable HTTP / Protocol Version Header / MUST accept the negotiated protocol version"""  # noqa: E501
    test = yield from conformance(protocol)
    session = yield from test.initialize()
    response = yield from test.ping(session, protocol_version=protocol.protocol_version)
    assert response.status == 200


@pytest.mark.parametrize("protocol", HEADER_REVISIONS, ids=_id)
@testing.effect
def test_must_reject_an_unsupported_protocol_version_with_bad_request(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Protocol Version Header / MUST reject an unsupported protocol version with bad request"""  # noqa: E501
    test = yield from conformance(protocol)
    session = yield from test.initialize()
    response = yield from test.ping(session, protocol_version="2099-01-01")
    assert response.status == 400
    error = yield from test.decode_error(response)
    assert error["id"] == 2
    assert error["error"]["code"] == -32022
    assert error["error"]["data"] == {
        "supported": [protocol.protocol_version],
        "requested": "2099-01-01",
    }


@pytest.mark.parametrize("protocol", HEADER_REVISIONS, ids=_id)
@testing.effect
def test_scenario_replays_the_selected_protocol_version_on_http_responses(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Transports / Streamable HTTP / Protocol Version Header / SCENARIO replays the selected protocol version on HTTP responses"""  # noqa: E501
    test = yield from conformance(protocol)
    session = yield from test.initialize()
    assert session.response.headers.get("mcp-protocol-version") == protocol.protocol_version
    response = yield from test.ping(session)
    assert response.headers.get("mcp-protocol-version") == protocol.protocol_version


# --- Streamable HTTP: Security --------------------------------------------------------------


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_validate_the_origin_header_before_every_mcp_route(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Transports / Streamable HTTP / Security / MUST validate the Origin header before every MCP route"""  # noqa: E501
    test = yield from conformance(protocol)
    assert (yield from test.post(test.initialize_request())).status == 200
    allowed = yield from test.request(
        "POST", test.initialize_request(2), {"origin": "https://allowed.example"}
    )
    assert allowed.status == 200
    for method in ("POST", "GET", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
        body = test.initialize_request(3) if method == "POST" else None
        response = yield from test.request(method, body, {"origin": ATTACKER})
        assert response.status == 403, method


# --- Stateless modern -----------------------------------------------------------------------

_METADATA: Json = {
    "io.modelcontextprotocol/protocolVersion": MODERN.protocol_version,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "transport-client", "version": "1.0.0"},
}


def _modern_request(id: object, method: str = "server/discover") -> Json:
    return {"jsonrpc": "2.0", "id": id, "method": method, "params": {"_meta": _METADATA}}


def _modern_headers(method: str = "server/discover") -> dict[str, str]:
    return {"MCP-Protocol-Version": MODERN.protocol_version, "Mcp-Method": method}


@testing.effect
def test_should_exchange_one_compact_newline_delimited_json_rpc_message_per_stdio_line():
    """Mcp Conformance / Transports > Stateless modern / should exchange one compact newline-delimited JSON-RPC message per stdio line"""  # noqa: E501
    harness = yield from stdio_harness(MODERN)
    pending = yield from harness.send_request("server/discover", {}, 1).fork()
    frame = yield from harness.raw_stdout.take().or_die()
    assert frame.endswith("\n")
    assert "\n" not in frame[:-1]
    message = json.loads(frame)
    assert message["jsonrpc"] == "2.0" and message["id"] == 1
    yield from pending.join()


@testing.effect
def test_should_reconstruct_a_utf8_stdio_message_when_its_bytes_arrive_in_separate_chunks():
    """Mcp Conformance / Transports > Stateless modern / should reconstruct a UTF-8 stdio message when its bytes arrive in separate chunks"""  # noqa: E501
    harness = yield from stdio_harness(MODERN)
    data = (json.dumps(_modern_request("stdio-🧪"), ensure_ascii=False) + "\n").encode()
    split = data.index(0xF0) + 2
    yield from harness.send_chunk(data[:split])
    yield from harness.send_chunk(data[split:])
    message = yield from harness.receive()
    assert message["jsonrpc"] == "2.0" and message["id"] == "stdio-🧪"


@testing.effect
def test_should_process_consecutive_stateless_stdio_requests_independently():
    """Mcp Conformance / Transports > Stateless modern / should process consecutive stateless stdio requests independently"""  # noqa: E501
    harness = yield from stdio_harness(MODERN)
    yield from harness.send(_modern_request(2))
    yield from harness.send(_modern_request(3))
    first = yield from harness.receive()
    second = yield from harness.receive()
    assert (first["jsonrpc"], first["id"]) == ("2.0", 2)
    assert (second["jsonrpc"], second["id"]) == ("2.0", 3)


@testing.effect
def test_should_shut_down_the_stdio_server_when_the_client_closes_stdin():
    """Mcp Conformance / Transports > Stateless modern / should shut down the stdio server when the client closes stdin"""  # noqa: E501
    harness = yield from stdio_harness(MODERN)
    yield from harness.close
    assert _ended((yield from harness.fiber.await_exit()))


@testing.effect
def test_should_return_http_404_when_a_request_needs_an_unavailable_server_capability():
    """Mcp Conformance / Transports > Stateless modern / should return HTTP 404 when a request needs an unavailable server capability"""  # noqa: E501
    test = yield from conformance(MODERN)
    discovered = yield from test.initialize()
    assert "prompts" not in discovered.message["result"]["capabilities"]
    response = yield from test.post(
        _modern_request("unavailable", "prompts/list"), _modern_headers("prompts/list")
    )
    error = yield from test.decode_error(response)
    assert error["id"] == "unavailable"
    assert error["error"]["code"] == MS.METHOD_NOT_FOUND_ERROR_CODE
    assert response.status == 404


@testing.effect
def test_should_require_application_json_content_and_both_response_media_types_for_http_post():
    """Mcp Conformance / Transports > Stateless modern / should require application/json content and both supported response media types for HTTP POST"""  # noqa: E501
    test = yield from conformance(MODERN)
    body = _modern_request(4)
    accepted = yield from test.request(
        "POST",
        body,
        {
            **_modern_headers(),
            "content-type": "Application/JSON; charset=utf-8",
            "accept": "Text/Event-Stream, Application/JSON",
        },
    )
    assert accepted.status == 200
    for content_type in ("text/plain", "application/json-malicious", ""):
        response = yield from test.request(
            "POST", body, {**_modern_headers(), "content-type": content_type}
        )
        assert response.status == 415, content_type
    for accept in ("application/json", "text/event-stream", "*/*", ""):
        response = yield from test.request("POST", body, {**_modern_headers(), "accept": accept})
        assert response.status == 406, accept


@testing.effect
def test_should_return_application_json_when_an_http_request_has_one_json_rpc_response():
    """Mcp Conformance / Transports > Stateless modern / should return application/json when an HTTP request has one JSON-RPC response"""  # noqa: E501
    test = yield from conformance(MODERN)
    response = yield from test.request("POST", _modern_request(5), _modern_headers())
    assert response.status == 200
    assert re.match(r"^application/json\b", response.headers.get("content-type") or "")


@testing.effect
def test_should_reject_get_and_unsupported_http_methods_when_only_post_is_available():
    """Mcp Conformance / Transports > Stateless modern / should reject GET and unsupported HTTP methods when only POST is available"""  # noqa: E501
    test = yield from conformance(MODERN)
    for method in ("GET", "PUT", "PATCH", "HEAD"):
        response = yield from test.request(method)
        assert response.status == 405, method
        assert response.headers.get("allow") == "POST"


@testing.effect
def test_should_reject_every_mcp_http_route_when_its_origin_is_not_explicitly_allowed():
    """Mcp Conformance / Transports > Stateless modern / should reject every MCP HTTP route when its Origin is not explicitly allowed"""  # noqa: E501
    test = yield from conformance(MODERN)
    for method in ("POST", "GET", "PUT", "PATCH", "DELETE", "HEAD", "OPTIONS"):
        body = _modern_request(6) if method == "POST" else None
        response = yield from test.request(method, body, {**_modern_headers(), "origin": ATTACKER})
        assert response.status == 403, method
