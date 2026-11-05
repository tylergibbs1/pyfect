"""Ports of Effect's MCP conformance base-protocol titles
(test/ai/McpServer/McpConformance/BaseProtocolTest.ts): ``suite`` and
``statefulLegacySuite`` for every stateful revision, as the per-revision
files run them, and ``suite`` and ``statelessModernSuite`` for 2026-07-28.

Effect checks "exactly one response" by waiting one virtual millisecond
for a second message; these wait the same way with the test clock.

Omitted: none.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as TK
from pyfect.scope import Scope

from ._mcp import StdioHarness, stdio_harness
from ._mcp_http import (
    Conformance,
    Json,
    conformance,
    http_harness,
    initialize_session,
    read_message,
    server_layer,
)

STATEFUL = [P.v2024_11_05, P.v2025_03_26, P.v2025_06_18, P.v2025_11_25]
MODERN = P.v2026_07_28
ALL = [*STATEFUL, MODERN]


def _id(protocol: P.AnyProtocolAdapter) -> str:
    return protocol.protocol_version


def _no_second_message(harness: StdioHarness) -> fx.Effect[None]:
    @fx.gen
    def run():
        waiting = yield from harness.receive().timeout_option(0.001).fork()
        yield from testing.adjust(0.001)
        assert (yield from waiting.join()) is None

    return run


# --- suite ----------------------------------------------------------------------------------


@pytest.mark.parametrize("protocol", ALL, ids=_id)
@testing.effect
def test_should_preserve_additional_result_metadata_fields_when_decoding_a_result(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Base Protocol > General fields / should preserve additional result metadata fields when decoding a result"""  # noqa: E501
    meta = {"example/conformance": {"enabled": True, "labels": ["one", "two"]}}
    result = yield from S.decode_unknown_effect(MS.READ_RESOURCE.success_schema)(
        {"contents": [], "_meta": meta}
    )
    assert result.get("_meta") == meta


# --- statelessModernSuite -------------------------------------------------------------------

_METADATA: Json = {
    "io.modelcontextprotocol/protocolVersion": MODERN.protocol_version,
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "stdio-client", "version": "1.0.0"},
}


def _modern(test: Conformance, body: Json) -> fx.Effect[Json]:
    @fx.gen
    def run():
        discovered = yield from test.initialize()
        response = yield from test.send(discovered, body)
        return (yield from test.decode_error(response))

    return run


@testing.effect
def test_should_preserve_string_and_numeric_identifiers_when_requests_succeed():
    """Mcp Conformance / Base Protocol > Stateless messages / should preserve string and numeric identifiers when requests succeed"""  # noqa: E501
    harness = yield from stdio_harness(MODERN)
    for id in ("discover-1", 42):
        message = yield from harness.send_request("server/discover", {}, id)
        assert message["id"] == id


@testing.effect
def test_should_reject_a_request_when_its_json_rpc_version_is_invalid():
    """Mcp Conformance / Base Protocol > Stateless messages / should reject a request when its JSON-RPC version is invalid"""  # noqa: E501
    test = yield from conformance(MODERN)
    body: Json = {"jsonrpc": "1.0", "id": 2, "method": "server/discover", "params": {}}
    message = yield from _modern(test, body)
    assert message["id"] == 2
    assert message["error"]["code"] == MS.INVALID_REQUEST_ERROR_CODE


@testing.effect
def test_should_reject_a_request_when_its_identifier_is_not_a_string_or_integer():
    """Mcp Conformance / Base Protocol > Stateless messages / should reject a request when its identifier is not a string or integer"""  # noqa: E501
    test = yield from conformance(MODERN)
    body: Json = {"jsonrpc": "2.0", "id": True, "method": "server/discover", "params": {}}
    message = yield from _modern(test, body)
    assert message["id"] is None
    assert message["error"]["code"] == MS.INVALID_REQUEST_ERROR_CODE


@testing.effect
def test_should_return_method_not_found_when_the_requested_method_is_unknown():
    """Mcp Conformance / Base Protocol > Stateless messages / should return method not found when the requested method is unknown"""  # noqa: E501
    harness = yield from stdio_harness(MODERN)
    message = yield from harness.send_request("unknown/method", {}, 3)
    assert message["id"] == 3
    assert message["error"]["code"] == MS.METHOD_NOT_FOUND_ERROR_CODE


@pytest.mark.parametrize(
    "method",
    ["ping", "initialize", "logging/setLevel", "resources/subscribe", "resources/unsubscribe"],
)
@testing.effect
def test_a_method_2026_07_28_removed_is_not_found_over_stdio(method: str):
    """As over HTTP: 2026-07-28 has no session to change (checked against Effect
    under Node, whose stdio answers each with method not found)."""
    harness = yield from stdio_harness(MODERN)
    message = yield from harness.send_request(method, {"uri": "file:///a"}, 3)
    assert message["error"]["code"] == MS.METHOD_NOT_FOUND_ERROR_CODE


@testing.effect
def test_should_return_invalid_params_when_request_parameters_do_not_match_the_method_schema():
    """Mcp Conformance / Base Protocol > Stateless messages / should return invalid params when request parameters do not match the method schema"""  # noqa: E501
    harness = yield from stdio_harness(MODERN)
    message = yield from harness.send_request("tools/list", {"cursor": 1}, 7)
    assert message["id"] == 7
    assert message["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE


@testing.effect
def test_should_send_no_response_when_an_unknown_notification_is_received():
    """Mcp Conformance / Base Protocol > Stateless messages / should send no response when an unknown notification is received"""  # noqa: E501
    harness = yield from stdio_harness(MODERN)
    yield from harness.send_notification("unknown/method", {"_meta": _METADATA})
    yield from _no_second_message(harness)


@testing.effect
def test_should_send_no_response_when_notification_parameters_are_invalid():
    """Mcp Conformance / Base Protocol > Stateless messages / should send no response when notification parameters are invalid"""  # noqa: E501
    harness = yield from stdio_harness(MODERN)
    yield from harness.send_notification(
        "notifications/cancelled", {"requestId": True, "_meta": _METADATA}
    )
    yield from _no_second_message(harness)


@testing.effect
def test_should_send_exactly_one_result_response_when_a_request_succeeds():
    """Mcp Conformance / Base Protocol > Stateless messages / should send exactly one result response when a request succeeds"""  # noqa: E501
    harness = yield from stdio_harness(MODERN)
    yield from harness.send(
        {"jsonrpc": "2.0", "id": 4, "method": "server/discover", "params": {"_meta": _METADATA}}
    )
    message = yield from harness.receive()
    assert message["id"] == 4
    assert "result" in message and "error" not in message
    yield from _no_second_message(harness)


@testing.effect
def test_should_send_exactly_one_error_response_when_a_request_fails():
    """Mcp Conformance / Base Protocol > Stateless messages / should send exactly one error response when a request fails"""  # noqa: E501
    harness = yield from stdio_harness(MODERN)
    yield from harness.send(
        {"jsonrpc": "2.0", "id": 8, "method": "unknown/method", "params": {"_meta": _METADATA}}
    )
    message = yield from harness.receive()
    assert message["id"] == 8
    assert "error" in message and "result" not in message
    yield from _no_second_message(harness)


@testing.effect
def test_should_return_a_parse_error_when_a_json_message_is_malformed():
    """Mcp Conformance / Base Protocol > Stateless messages / should return a parse error when a JSON message is malformed"""  # noqa: E501
    test = yield from conformance(MODERN)
    discovered = yield from test.initialize()
    message = yield from test.decode_error((yield from test.send_text(discovered, "{")))
    assert message["id"] is None
    assert message["error"]["code"] == MS.PARSE_ERROR_CODE


@testing.effect
def test_should_return_invalid_request_when_a_json_rpc_message_omits_its_method():
    """Mcp Conformance / Base Protocol > Stateless messages / should return invalid request when a JSON-RPC message omits its method"""  # noqa: E501
    test = yield from conformance(MODERN)
    message = yield from _modern(test, {"jsonrpc": "2.0", "id": 10, "params": {}})
    assert message["id"] == 10
    assert message["error"]["code"] == MS.INVALID_REQUEST_ERROR_CODE


# --- statefulLegacySuite: request metadata --------------------------------------------------


_METADATA_TOOL = (
    T.make("Metadata", success=S.String)
    .add_dependency(MS.McpRequestContext)
    .add_dependency(MS.McpServerClient)
)
_METADATA_TOOLKIT = TK.make(_METADATA_TOOL)


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_preserve_custom_request_metadata_when_a_legacy_tool_reads_either_context_api(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Base Protocol / should preserve custom request metadata when a legacy tool reads either context API"""  # noqa: E501

    @fx.gen
    def metadata():
        context = yield from MS.McpRequestContext()
        client = yield from MS.McpServerClient()
        return json.dumps({"context": context.request_metadata, "client": client.request_metadata})

    registration = M.register_toolkit(_METADATA_TOOLKIT).pipe(
        fx.provide(_METADATA_TOOLKIT.to_layer(_METADATA_TOOL.handler(lambda _, __: metadata)))
    )
    harness = yield from http_harness(server_layer("RequestMetadata", (protocol,), registration))
    headers = yield from initialize_session(harness, protocol)
    meta = {
        "marker": "tool-call",
        "progressToken": "progress-1",
        "custom": {"values": [None, True, 42]},
    }
    response = yield from harness.post(
        {
            "jsonrpc": "2.0",
            "id": "call",
            "method": "tools/call",
            "params": {"name": "Metadata", "arguments": {}, "_meta": meta},
        },
        headers,
    )
    message = yield from read_message(response)
    text = message["result"]["content"][0]["text"]
    assert json.loads(text) == {"context": meta, "client": meta}


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_expose_current_metadata_when_a_legacy_resource_completion_reads_either_context_api(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Base Protocol / should expose current metadata when a legacy resource completion reads either context API"""  # noqa: E501

    @fx.gen
    def current():
        context = yield from MS.McpRequestContext()
        client = yield from MS.McpServerClient()
        payload = {"context": context.request_metadata, "client": client.request_metadata}
        return [json.dumps(payload)]

    registration = M.register_resource_template(
        M.uri_template("file:///metadata/", MS.param("name", S.String)),
        name="metadata",
        content=lambda _uri, _name: fx.succeed("content"),
        completion={"name": lambda _value, _context: current},
    )
    harness = yield from http_harness(server_layer("CompletionMetadata", (protocol,), registration))
    headers = yield from initialize_session(harness, protocol)
    meta = {"marker": "completion", "progressToken": "progress-1"}
    response = yield from harness.post(
        {
            "jsonrpc": "2.0",
            "id": "complete",
            "method": "completion/complete",
            "params": {
                "ref": {"type": "ref/resource", "uri": "file:///metadata/{name}"},
                "argument": {"name": "name", "value": ""},
                "_meta": meta,
            },
        },
        headers,
    )
    message = yield from read_message(response)
    values = message["result"]["completion"]["values"]
    assert json.loads(values[0]) == {"context": meta, "client": meta}


# --- statefulLegacySuite: Messages ----------------------------------------------------------


def _initialized(test: Conformance) -> fx.Effect[Any]:
    return test.initialize().tap(test.notify_initialized)


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_schema_accepts_json_rpc_2_0_requests_with_string_identifiers(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Base Protocol / Messages / Requests / SCHEMA accepts JSON-RPC 2.0 requests with string identifiers"""  # noqa: E501
    test = yield from conformance(protocol)
    session = yield from _initialized(test)
    response = yield from test.send(session, {"jsonrpc": "2.0", "id": "ping-1", "method": "ping"})
    assert (yield from test.decode_result(response))["id"] == "ping-1"


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_schema_accepts_json_rpc_2_0_requests_with_numeric_identifiers(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Base Protocol / Messages / Requests / SCHEMA accepts JSON-RPC 2.0 requests with numeric identifiers"""  # noqa: E501
    test = yield from conformance(protocol)
    session = yield from _initialized(test)
    response = yield from test.ping(session, 42)
    assert (yield from test.decode_result(response))["id"] == 42


def _error_of(protocol: P.AnyProtocolAdapter, body: Json) -> fx.Effect[Json, Any, Scope]:
    @fx.gen
    def run():
        test = yield from conformance(protocol)
        session = yield from _initialized(test)
        return (yield from test.decode_error((yield from test.send(session, body))))

    return run


def _accepted_silently(protocol: P.AnyProtocolAdapter, body: Json) -> fx.Effect[None, Any, Scope]:
    @fx.gen
    def run():
        test = yield from conformance(protocol)
        session = yield from _initialized(test)
        response = yield from test.send(session, body)
        assert response.status == 202
        assert (yield from response.text) == ""

    return run


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_reject_requests_with_an_invalid_json_rpc_version(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Base Protocol / Messages / Requests / MUST reject requests with an invalid JSON-RPC version"""  # noqa: E501
    message = yield from _error_of(protocol, {"jsonrpc": "1.0", "id": 2, "method": "ping"})
    assert message["id"] == 2
    assert message["error"]["code"] == MS.INVALID_REQUEST_ERROR_CODE


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_return_method_not_found_for_unknown_request_methods(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Base Protocol / Messages / Requests / MUST return method not found for unknown request methods"""  # noqa: E501
    message = yield from _error_of(
        protocol, {"jsonrpc": "2.0", "id": 3, "method": "unknown/method"}
    )
    assert message["id"] == 3
    assert message["error"]["code"] == MS.METHOD_NOT_FOUND_ERROR_CODE


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_return_invalid_params_for_request_payloads_that_do_not_match_the_method_schema(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Base Protocol / Messages / Requests / MUST return invalid params for request payloads that do not match the method schema"""  # noqa: E501
    body = {"jsonrpc": "2.0", "id": 7, "method": "ping", "params": "invalid"}
    message = yield from _error_of(protocol, body)
    assert message["id"] == 7
    assert message["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_not_reply_to_unknown_notifications(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Base Protocol / Messages / Requests / MUST not reply to unknown notifications"""  # noqa: E501
    yield from _accepted_silently(protocol, {"jsonrpc": "2.0", "method": "unknown/method"})


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_not_reply_to_notifications_with_invalid_params(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Base Protocol / Messages / Requests / MUST not reply to notifications with invalid params"""  # noqa: E501
    yield from _accepted_silently(
        protocol, {"jsonrpc": "2.0", "method": "ping", "params": "invalid"}
    )


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_reject_requests_with_invalid_identifiers(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Base Protocol / Messages / Requests / MUST reject requests with invalid identifiers"""  # noqa: E501
    message = yield from _error_of(protocol, {"jsonrpc": "2.0", "id": True, "method": "ping"})
    assert message["id"] is None
    assert message["error"]["code"] == MS.INVALID_REQUEST_ERROR_CODE


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_return_exactly_one_result_response_for_a_successful_request(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Base Protocol / Messages / Responses / MUST return exactly one result response for a successful request"""  # noqa: E501
    harness = yield from stdio_harness(protocol)
    yield from harness.initialize()
    yield from harness.send({"jsonrpc": "2.0", "id": 4, "method": "ping"})
    message = yield from harness.receive()
    assert message["id"] == 4
    assert message["result"] == {}
    yield from _no_second_message(harness)


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_return_exactly_one_error_response_for_a_failed_request(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Base Protocol / Messages / Responses / MUST return exactly one error response for a failed request"""  # noqa: E501
    harness = yield from stdio_harness(protocol)
    yield from harness.initialize()
    yield from harness.send({"jsonrpc": "2.0", "id": 8, "method": "unknown/method"})
    message = yield from harness.receive()
    assert message["id"] == 8
    assert "error" in message and "result" not in message
    yield from _no_second_message(harness)


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_schema_preserves_the_request_identifier_in_result_responses(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Base Protocol / Messages / Responses / SCHEMA preserves the request identifier in result responses"""  # noqa: E501
    test = yield from conformance(protocol)
    session = yield from _initialized(test)
    assert (yield from test.decode_result((yield from test.ping(session, 5))))["id"] == 5


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_schema_preserves_the_request_identifier_in_error_responses(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Base Protocol / Messages / Responses / SCHEMA preserves the request identifier in error responses"""  # noqa: E501
    body = {"jsonrpc": "2.0", "id": "unknown-1", "method": "unknown/method"}
    assert (yield from _error_of(protocol, body))["id"] == "unknown-1"


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_not_include_both_result_and_error_in_a_response(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Base Protocol / Messages / Responses / MUST not include both result and error in a response"""  # noqa: E501
    test = yield from conformance(protocol)
    session = yield from _initialized(test)
    response = yield from test.send(
        session, {"jsonrpc": "2.0", "id": 9, "method": "unknown/method"}
    )
    raw = json.loads((yield from response.text))
    assert "error" in raw and "result" not in raw


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_accept_notifications_without_an_identifier_and_send_no_response(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Base Protocol / Messages / Notifications / MUST accept notifications without an identifier and send no response"""  # noqa: E501
    test = yield from conformance(protocol)
    session = yield from test.initialize()
    response = yield from test.send(
        session, {"jsonrpc": "2.0", "method": "notifications/initialized"}
    )
    assert response.status == 202
    assert (yield from response.text) == ""


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_return_a_parse_error_for_malformed_json(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Base Protocol / Messages / MUST return a parse error for malformed JSON"""
    test = yield from conformance(protocol)
    session = yield from _initialized(test)
    message = yield from test.decode_error((yield from test.send_text(session, "{")))
    assert message["id"] is None
    assert message["error"]["code"] == MS.PARSE_ERROR_CODE


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_return_an_invalid_request_error_for_malformed_json_rpc_messages(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Base Protocol / Messages / MUST return an invalid request error for malformed JSON-RPC messages"""  # noqa: E501
    message = yield from _error_of(protocol, {"jsonrpc": "2.0", "id": 10})
    assert message["id"] == 10
    assert message["error"]["code"] == MS.INVALID_REQUEST_ERROR_CODE
