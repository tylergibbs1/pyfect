"""Ports of Effect's MCP HTTP admission and JSON-RPC batch titles: from
McpServer.test.ts, the 2025-03-26 transport titles of v2025_03_26.test.ts and
the 2026-07-28 transport, discovery and request-metadata titles of
v2026_07_28.test.ts.

Ported elsewhere: the "Multi round-trip request capabilities" titles in
test_mcp_conformance_multi_round_trip.py; "should accept cancellation
notifications without request metadata" in test_mcp_protocol_adapters.py;
"should validate nested mirrored parameters before executing a tool" and "should
treat an unmatched Base64 wrapper as a literal when routing a request" in
test_mcp_conformance_tools.py.
"""

from __future__ import annotations

import base64
import json
from typing import Any

import pytest

import pyfect as fx
from pyfect import layer, testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import PromptEntry, ResourceEntry, ToolEntry
from pyfect.context import Context
from pyfect.http import request as R
from pyfect.http.client import HttpClientService
from pyfect.http.response import HttpClientResponse

from ._mcp import CLIENT_INFO, Json, in_memory_http, stdio_harness
from ._mcp_http import conformance, read_message

URL = "http://localhost/mcp"
ACCEPT = "application/json, text/event-stream"
ALLOWED_ORIGIN = "https://allowed.example"

type Http = HttpClientService[Any, Any]


def _registrations(calls: list[str] | None = None) -> fx.Effect[None, Any, M.McpServer]:
    """A tool, a resource and a prompt to route requests to."""

    def call(_: object) -> fx.Effect[MS.CallToolResult]:
        return fx.sync(lambda: (calls or []).append("call")).as_({"content": []})

    @fx.gen
    def run():
        server = yield from M.McpServer()
        yield from server.add_tool(
            ToolEntry(
                {"name": "ConformanceTool", "inputSchema": {"type": "object"}},
                Context.empty(),
                call,
            )
        )
        yield from server.add_resource(
            ResourceEntry(
                {"uri": "file:///conformance.txt", "name": "Conformance"},
                Context.empty(),
                fx.succeed({"contents": [{"uri": "file:///conformance.txt", "text": "text"}]}),
            )
        )
        yield from server.add_prompt(
            PromptEntry(
                {"name": "ConformancePrompt"},
                Context.empty(),
                {},
                lambda _args: fx.succeed({"messages": []}),
            )
        )

    return run


def _http(
    protocols: tuple[P.AnyProtocolAdapter, ...],
    *,
    allow_session_termination: bool = False,
    registrations: fx.Effect[None, Any, M.McpServer] | None = None,
) -> fx.Effect[Http, Any, Any]:
    app = M.layer_http(
        name="test-server",
        version="1.0.0",
        path="/mcp",
        protocols=protocols,
        allowed_origins=(ALLOWED_ORIGIN,),
        allow_session_termination=allow_session_termination,
    )
    if registrations is not None:
        registered = layer.effect_discard(registrations).pipe(layer.provide(M.layer))
        app = layer.merge(app, registered)
    return in_memory_http(app)


def _post_text(
    http: Http, text: str, headers: dict[str, str] | None = None
) -> fx.Effect[HttpClientResponse, Any]:
    request = (
        R.post(URL)
        .set_headers({"accept": ACCEPT, **(headers or {})})
        .body_text(text, "application/json")
    )
    return http.execute(request)


def _post(
    http: Http, body: object, headers: dict[str, str] | None = None
) -> fx.Effect[HttpClientResponse, Any]:
    return _post_text(http, json.dumps(body), headers)


def _delete(http: Http, headers: dict[str, str]) -> fx.Effect[HttpClientResponse, Any]:
    return http.execute(R.delete(URL).set_headers(headers))


def _initialize(version: str) -> Json:
    params = {"protocolVersion": version, "capabilities": {}, "clientInfo": CLIENT_INFO}
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": params}


def _session(http: Http, version: str) -> fx.Effect[dict[str, str], Any]:
    """An initialized session's headers."""

    @fx.gen
    def run():
        response = yield from _post(http, _initialize(version))
        session = response.headers.get("mcp-session-id")
        assert session is not None
        headers = {"mcp-session-id": session, "mcp-protocol-version": version}
        initialized = {"jsonrpc": "2.0", "method": "notifications/initialized"}
        yield from _post(http, initialized, headers)
        return headers

    return run


def _json(response: HttpClientResponse) -> fx.Effect[Any, Any]:
    return response.text.map(json.loads)


PING: Json = {"jsonrpc": "2.0", "method": "ping", "params": {}, "id": 0}


# --- McpServer.test.ts -------------------------------------------------------------------


@testing.effect
def test_validates_supplied_protocol_versions_on_post():
    """McpServer / validates supplied protocol versions on POST"""
    http = yield from _http((P.v2025_06_18,))
    headers = yield from _session(http, "2025-06-18")
    session = {"mcp-session-id": headers["mcp-session-id"]}
    unsupported = {**session, "mcp-protocol-version": "9999-01-01"}

    response = yield from _post(http, PING, unsupported)
    assert response.status == 400
    assert (yield from _json(response))["error"] == {
        "code": -32022,
        "message": "Unsupported protocol version '9999-01-01'",
        "data": {"supported": ["2025-06-18"], "requested": "9999-01-01"},
    }
    malformed = yield from _post_text(http, "{", unsupported)
    assert malformed.status == 400
    assert (yield from _json(malformed))["error"]["code"] == -32022
    malformed_no_version = yield from _post_text(http, "{", session)
    assert malformed_no_version.status == 200
    body = yield from _json(malformed_no_version)
    assert body["id"] is None
    assert body["error"]["code"] == MS.PARSE_ERROR_CODE
    invalid = yield from _post(http, {"hello": "world"}, unsupported)
    assert invalid.status == 400
    assert (yield from _json(invalid))["error"]["code"] == -32022
    invalid_no_version = yield from _post(http, {"hello": "world"}, session)
    assert invalid_no_version.status == 200
    body = yield from _json(invalid_no_version)
    assert body["id"] is None
    assert body["error"]["code"] == MS.INVALID_REQUEST_ERROR_CODE
    initialize = yield from _post(http, {"method": "initialize", "id": 7}, unsupported)
    assert initialize.status == 400
    assert (yield from _json(initialize))["error"]["code"] == -32022
    answer: Json = {"jsonrpc": "2.0", "id": 1, "result": {}}
    response_only = yield from _post(http, answer, unsupported)
    assert response_only.status == 400
    assert (yield from _json(response_only))["error"]["code"] == -32022
    assert (yield from _post(http, PING, session)).status == 200
    for version in ("2025-03-26", "2024-11-05", "2024-10-07"):
        response = yield from _post(http, PING, {**session, "mcp-protocol-version": version})
        assert response.status == 400
    assert (yield from _post(http, PING, headers)).status == 200


@testing.effect
def test_rejects_disallowed_delete_origins_without_terminating_the_session():
    """McpServer / rejects disallowed DELETE Origins without terminating the session"""
    http = yield from _http((P.v2025_11_25,), allow_session_termination=True)
    headers = yield from _session(http, "2025-11-25")
    blocked = yield from _delete(http, {**headers, "origin": "https://blocked.example"})
    assert blocked.status == 403
    ping = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
    assert (yield from _post(http, ping, headers)).status == 200
    allowed = yield from _delete(http, {**headers, "origin": ALLOWED_ORIGIN})
    assert allowed.status == 204


@testing.effect
def test_rejects_unsupported_or_mismatched_delete_protocol_versions():
    """McpServer / rejects unsupported or mismatched DELETE protocol versions without terminating the session"""  # noqa: E501
    http = yield from _http((P.v2025_06_18, P.v2025_11_25), allow_session_termination=True)
    headers = yield from _session(http, "2025-11-25")
    for version in ("9999-01-01", "2025-06-18"):
        rejected = yield from _delete(http, {**headers, "mcp-protocol-version": version})
        assert rejected.status == 400
        ping = yield from _post(http, {"jsonrpc": "2.0", "id": 2, "method": "ping"}, headers)
        assert ping.status == 200
        assert (yield from _json(ping)) == {"jsonrpc": "2.0", "id": 2, "result": {}}
    assert (yield from _delete(http, headers)).status == 204


@testing.effect
def test_refuses_delete_for_a_stateless_only_server():
    """McpServer / refuses DELETE for a stateless-only server even when termination is enabled"""
    http = yield from _http((P.v2026_07_28,), allow_session_termination=True)
    response = yield from _delete(http, {})
    assert response.status == 405
    assert response.headers.get("allow") == "POST"


_STATELESS_IN_BATCH: list[Json] = [
    {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {
            "name": "ConformanceTool",
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {},
            },
        },
    },
    {"jsonrpc": "2.0", "id": 3, "method": "ping"},
]


@testing.effect
def test_rejects_stateless_requests_inside_a_legacy_http_batch():
    """McpServer / should reject stateless requests inside a legacy http batch"""
    calls: list[str] = []
    protocols = (P.v2026_07_28, P.v2025_03_26)
    http = yield from _http(protocols, registrations=_registrations(calls))
    headers = yield from _session(http, "2025-03-26")
    response = yield from _post(http, _STATELESS_IN_BATCH, headers)
    assert response.status == 400
    assert (yield from response.text) == ""
    assert calls == []


@testing.effect
def test_rejects_stateless_requests_inside_a_legacy_stdio_batch():
    """McpServer / should reject stateless requests inside a legacy stdio batch"""
    calls: list[str] = []
    protocols = [P.v2026_07_28, P.v2025_03_26]
    harness = yield from stdio_harness(P.v2025_03_26, protocols, _registrations(calls))
    yield from harness.initialize()
    yield from harness.send_raw(json.dumps(_STATELESS_IN_BATCH))
    assert (yield from harness.receive()) == {
        "jsonrpc": "2.0",
        "id": None,
        "error": {"code": -32600, "message": "JSON-RPC batches are not supported"},
    }
    assert calls == []


# --- v2025_03_26.test.ts -----------------------------------------------------------------


@testing.effect
def test_must_accept_operational_json_rpc_batches_over_stdio():
    """Mcp Conformance (2025-03-26) / Transport-specific behavior / MUST accept operational JSON-RPC batches over stdio"""  # noqa: E501
    harness = yield from stdio_harness(P.v2025_03_26)
    yield from harness.send_request("initialize", _initialize("2025-03-26")["params"], 1)
    pings: list[Json] = [
        {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
        {"jsonrpc": "2.0", "id": 3, "method": "ping", "params": {}},
    ]
    yield from harness.send_raw(json.dumps(pings))
    replies = yield from harness.stdout.take().or_die()
    assert replies == [
        {"jsonrpc": "2.0", "id": 2, "result": {}},
        {"jsonrpc": "2.0", "id": 3, "result": {}},
    ]


@testing.effect
def test_server_rejects_initialize_as_part_of_a_json_rpc_batch():
    """Mcp Conformance (2025-03-26) / Transport-specific behavior / SERVER rejects initialize as part of a JSON-RPC batch"""  # noqa: E501
    http = yield from _http((P.v2025_03_26,))
    response = yield from _post(http, [_initialize("2025-03-26")])
    assert response.status >= 400
    assert response.headers.get("mcp-session-id") is None


@testing.effect
def test_must_reject_an_empty_json_rpc_batch():
    """Mcp Conformance (2025-03-26) / Transport-specific behavior / MUST reject an empty JSON-RPC batch"""  # noqa: E501
    http = yield from _http((P.v2025_03_26,))
    error = yield from _json((yield from _post(http, [])))
    assert error["id"] is None
    assert error["error"]["code"] == -32600


@testing.effect
def test_must_accept_an_operational_mixed_batch_and_correlate_responses_by_id():
    """Mcp Conformance (2025-03-26) / Transport-specific behavior / MUST accept an operational mixed batch and correlate responses by id"""  # noqa: E501
    http = yield from _http((P.v2025_03_26,))
    headers = yield from _session(http, "2025-03-26")
    batch = [
        {"jsonrpc": "2.0", "id": 41, "method": "ping"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 42, "method": "unknown/method"},
    ]
    session = {"mcp-session-id": headers["mcp-session-id"]}
    messages = yield from _json((yield from _post(http, batch, session)))
    by_id = {message["id"]: message for message in messages}
    assert by_id[41] == {"jsonrpc": "2.0", "id": 41, "result": {}}
    assert by_id[42]["error"]["code"] == MS.METHOD_NOT_FOUND_ERROR_CODE


@testing.effect
def test_must_return_202_with_no_body_for_an_accepted_notification_only_batch():
    """Mcp Conformance (2025-03-26) / Transport-specific behavior / MUST return 202 with no body for an accepted notification-only batch"""  # noqa: E501
    http = yield from _http((P.v2025_03_26,))
    headers = yield from _session(http, "2025-03-26")
    batch = [
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "method": "notifications/roots/list_changed"},
    ]
    response = yield from _post(http, batch, {"mcp-session-id": headers["mcp-session-id"]})
    assert response.status == 202
    assert (yield from response.text) == ""


@testing.effect
def test_must_operate_without_the_later_protocol_version_header():
    """Mcp Conformance (2025-03-26) / Transport-specific behavior / MUST operate without the later protocol-version header"""  # noqa: E501
    http = yield from _http((P.v2025_03_26,))
    headers = yield from _session(http, "2025-03-26")
    ping = {"jsonrpc": "2.0", "id": 2, "method": "ping"}
    response = yield from _post(http, ping, {"mcp-session-id": headers["mcp-session-id"]})
    assert response.status == 200


# --- v2026_07_28.test.ts -----------------------------------------------------------------

_METADATA: Json = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "McpConformanceClient", "version": "1.0.0"},
}


def _request(id: object, method: str, params: Json | None = None) -> Json:
    return {
        "jsonrpc": "2.0",
        "id": id,
        "method": method,
        "params": {**(params or {}), "_meta": _METADATA},
    }


def _headers(method: str, name: str | None = None) -> dict[str, str]:
    headers = {"mcp-protocol-version": "2026-07-28", "mcp-method": method}
    if name is not None:
        headers["mcp-name"] = name
    return headers


def _modern() -> fx.Effect[Http, Any, Any]:
    return _http((P.v2026_07_28,), registrations=_registrations())


@testing.effect
def test_should_return_method_not_found_when_the_removed_initialize_method_is_requested():
    """Mcp Conformance (2026-07-28) / Lifecycle / should return method not found when the removed initialize method is requested"""  # noqa: E501
    http = yield from _modern()
    response = yield from _post(http, _request(10, "initialize"), _headers("initialize"))
    assert response.status == 404
    assert (yield from _json(response))["error"]["code"] == MS.METHOD_NOT_FOUND_ERROR_CODE


@testing.effect
def test_should_return_header_mismatch_when_a_july_only_request_omits_headers_and_metadata():
    """Mcp Conformance (2026-07-28) / Transports / should return HeaderMismatch when a July-only request omits headers and metadata"""  # noqa: E501
    http = yield from _modern()
    cases: list[Json] = [
        {"jsonrpc": "2.0", "id": "missing", "method": "tools/list", "params": {}},
        {**_initialize("2025-11-25"), "id": "legacy-initialize"},
    ]
    for body in cases:
        response = yield from _post(http, body)
        assert response.status == 400, body["id"]
        error = yield from _json(response)
        assert error["id"] == body["id"]
        assert error["error"]["code"] == MS.HEADER_MISMATCH_ERROR_CODE


@testing.effect
def test_should_accept_every_required_routing_name_when_the_header_matches_the_request():
    """Mcp Conformance (2026-07-28) / Transports / should accept every required routing name when the header matches the request"""  # noqa: E501
    http = yield from _modern()
    cases: list[tuple[str, Json, str]] = [
        ("tools/call", {"name": "ConformanceTool", "arguments": {}}, "ConformanceTool"),
        ("resources/read", {"uri": "file:///conformance.txt"}, "file:///conformance.txt"),
        ("prompts/get", {"name": "ConformancePrompt", "arguments": {}}, "ConformancePrompt"),
    ]
    for index, (method, params, name) in enumerate(cases):
        response = yield from _post(
            http, _request(index + 1, method, params), _headers(method, name)
        )
        assert response.status == 200, method
    encoded = f"=?base64?{base64.b64encode(b'file:///conformance.txt').decode()}?="
    read = _request(4, "resources/read", {"uri": "file:///conformance.txt"})
    response = yield from _post(http, read, _headers("resources/read", encoded))
    assert response.status == 200


@testing.effect
def test_should_reject_routing_headers_when_they_are_missing_malformed_or_mismatched():
    """Mcp Conformance (2026-07-28) / Transports / should reject routing headers when they are missing, malformed, or mismatched"""  # noqa: E501
    http = yield from _modern()
    cases: list[tuple[Json, dict[str, str]]] = [
        (_request("missing", "tools/list"), {"mcp-protocol-version": "2026-07-28"}),
        (_request("mismatch", "tools/list"), _headers("tools/call")),
        (
            _request("malformed", "resources/read", {"uri": "file:///conformance.txt"}),
            _headers("resources/read", "=?base64?not-valid!?="),
        ),
        (
            _request("invalid-utf8", "resources/read", {"uri": "�"}),
            _headers("resources/read", "=?base64?/w==?="),
        ),
    ]
    for body, headers in cases:
        response = yield from _post(http, body, headers)
        error = yield from _json(response)
        assert response.status == 400
        assert error["id"] == body["id"]
        assert error["error"]["code"] == MS.HEADER_MISMATCH_ERROR_CODE


@testing.effect
def test_should_reject_an_unsupported_request_version_with_the_supported_versions():
    """Mcp Conformance (2026-07-28) / Transports / should reject an unsupported request version with the supported versions"""  # noqa: E501
    http = yield from _modern()
    body = _request(5, "tools/list")
    body["params"] = {
        "_meta": {**_METADATA, "io.modelcontextprotocol/protocolVersion": "2099-01-01"}
    }
    headers = {"mcp-protocol-version": "2099-01-01", "mcp-method": "tools/list"}
    response = yield from _post(http, body, headers)
    error = yield from _json(response)
    assert response.status == 400
    assert error["id"] == 5
    assert error["error"]["code"] == -32022
    assert error["error"]["data"] == {"supported": ["2026-07-28"], "requested": "2099-01-01"}


@pytest.mark.parametrize(
    "method",
    [
        "unknown/method",
        "ping",
        "logging/setLevel",
        "resources/subscribe",
        "resources/unsubscribe",
        "tasks/get",
    ],
)
@testing.effect
def test_should_return_method_not_found_when_a_request_uses_an_unknown_or_removed_method(
    method: str,
):
    """Mcp Conformance (2026-07-28) / Transports / should return method not found when a request uses an unknown or removed method"""  # noqa: E501
    http = yield from _modern()
    response = yield from _post(http, _request(6, method), _headers(method))
    error = yield from _json(response)
    assert response.status == 404
    assert error["id"] == 6
    assert error["error"]["code"] == MS.METHOD_NOT_FOUND_ERROR_CODE


@testing.effect
def test_should_return_invalid_params_when_required_request_metadata_is_missing():
    """Mcp Conformance (2026-07-28) / Request metadata / should return InvalidParams when required request metadata is missing"""  # noqa: E501
    http = yield from _modern()
    metas: list[Json | None] = [
        None,
        {
            "io.modelcontextprotocol/clientCapabilities": {},
            "io.modelcontextprotocol/clientInfo": _METADATA["io.modelcontextprotocol/clientInfo"],
        },
        {"io.modelcontextprotocol/protocolVersion": "2026-07-28"},
    ]
    for meta in metas:
        body: Json = {
            "jsonrpc": "2.0",
            "id": 20,
            "method": "tools/list",
            "params": {} if meta is None else {"_meta": meta},
        }
        response = yield from _post(http, body, _headers("tools/list"))
        error = yield from _json(response)
        assert response.status == 400
        assert error["id"] == 20
        assert error["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE


@testing.effect
def test_should_accept_a_request_when_optional_client_identity_is_omitted():
    """Mcp Conformance (2026-07-28) / Request metadata / should accept a request when optional client identity is omitted"""  # noqa: E501
    http = yield from _modern()
    body: Json = {
        "jsonrpc": "2.0",
        "id": 22,
        "method": "tools/list",
        "params": {
            "_meta": {
                "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                "io.modelcontextprotocol/clientCapabilities": {},
            }
        },
    }
    response = yield from _post(http, body, _headers("tools/list"))
    assert response.status == 200


# --- v2026_07_28.test.ts: discovery and independent requests --------------------------------


_META: Json = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {
        "elicitation": {"form": {}},
        "roots": {},
        "sampling": {},
    },
    "io.modelcontextprotocol/clientInfo": {"name": "McpConformanceClient", "version": "1.0.0"},
}


def _modern_post(
    http: Http, id: object, method: str, params: Json | None = None
) -> fx.Effect[Any, Any]:
    body = {
        "jsonrpc": "2.0",
        "id": id,
        "method": method,
        "params": {"_meta": _META, **(params or {})},
    }
    return _post(http, body, {"mcp-protocol-version": "2026-07-28", "mcp-method": method})


def _modern_server(**info: Any) -> Any:
    return M.layer_http(
        name="McpConformance",
        version="1.0.0",
        path="/mcp",
        protocols=(P.v2026_07_28, P.v2025_06_18),
        **info,
    )


@testing.effect
def test_should_discover_the_server_when_no_initialization_or_session_exists():
    """Mcp Conformance (2026-07-28) / Discovery / should discover the server when no initialization or session exists"""  # noqa: E501
    http = yield from in_memory_http(
        _modern_server(instructions="Follow the test server instructions.")
    )
    response = yield from _modern_post(http, 1, "server/discover")
    result = (yield from read_message(response))["result"]
    assert response.status == 200
    assert response.headers.get("mcp-session-id") is None
    assert result["supportedVersions"][0] == "2026-07-28"
    assert result["instructions"] == "Follow the test server instructions."


@testing.effect
def test_should_advertise_supported_extension_settings_with_legacy_configuration():
    """Mcp Conformance (2026-07-28) / Discovery / should advertise supported extension settings when discovering a server with legacy configuration"""  # noqa: E501
    extensions = {
        "example/settings": {"enabled": True, "formats": ["text/html"], "nested": {"value": None}},
        "example/empty": {},
    }
    http = yield from in_memory_http(
        _modern_server(
            extensions={
                **extensions,
                "example/boolean": True,
                "example/array": [],
                "example/null": None,
            }
        )
    )
    response = yield from _modern_post(http, "discovery", "server/discover")
    assert response.status == 200
    assert (yield from read_message(response))["result"]["capabilities"] == {
        "completions": {},
        "logging": {},
        "extensions": extensions,
    }


@testing.effect
def test_should_serve_independent_requests_when_no_discovery_or_session_exists():
    """Mcp Conformance (2026-07-28) / Discovery / should serve independent requests when no discovery or session exists"""  # noqa: E501
    http = yield from in_memory_http(_modern_server())
    headers = {"mcp-protocol-version": "2026-07-28", "mcp-method": "tools/list"}
    body = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {"_meta": _META}}
    first = yield from _post(http, body, headers)
    second = yield from _post(
        http, {**body, "id": 2}, {**headers, "mcp-session-id": "ignored-modern-session"}
    )
    assert first.status == 200
    assert second.status == 200
    assert first.headers.get("mcp-session-id") is None


@testing.effect
def test_should_exchange_self_contained_newline_delimited_requests_over_stdio():
    """Mcp Conformance (2026-07-28) / Discovery / should exchange self-contained newline-delimited requests over stdio"""  # noqa: E501
    harness = yield from stdio_harness(P.v2026_07_28)
    result = (yield from harness.send_request("server/discover", {}))["result"]
    assert result["supportedVersions"] == ["2026-07-28"]
    assert result["capabilities"] == {"completions": {}, "logging": {}}
    assert result["resultType"] == "complete"
    assert result["ttlMs"] == 0
    assert result["cacheScope"] == "private"
    assert result["_meta"]["io.modelcontextprotocol/serverInfo"]["version"] == "1.0.0"


@testing.effect
def test_should_preserve_caller_metadata_alongside_authoritative_protocol_facts():
    """Mcp Conformance (2026-07-28) / Request metadata / should preserve caller metadata alongside authoritative protocol facts"""  # noqa: E501
    observed: list[Any] = []

    def probe(_: object) -> fx.Effect[MS.CallToolResult, Any, Any]:
        return MS.McpRequestContext().map(
            lambda context: (observed.append(dict(context.request_metadata)), _empty_call())[1]
        )

    registration = M.McpServer().flat_map(
        lambda server: server.add_tool(
            ToolEntry(
                {"name": "RequestMetadataTool", "inputSchema": {"type": "object"}},
                Context.empty(),
                probe,
            )
        )
    )
    app = layer.effect_discard(registration).pipe(layer.provide_merge(_modern_server()))
    http = yield from in_memory_http(app)
    yield from _post(
        http,
        {
            "jsonrpc": "2.0",
            "id": 8,
            "method": "tools/call",
            "params": {
                "name": "RequestMetadataTool",
                "arguments": {},
                "_meta": {**_META, "sentinel": "preserved"},
            },
        },
        {
            "mcp-protocol-version": "2026-07-28",
            "mcp-method": "tools/call",
            "mcp-name": "RequestMetadataTool",
        },
    )
    assert observed == [{**_META, "sentinel": "preserved"}]


@testing.effect
def test_should_include_the_requested_uri_when_a_resource_is_not_found():
    """Mcp Conformance (2026-07-28) / Result envelopes / should include the requested URI when a resource is not found"""  # noqa: E501
    http = yield from in_memory_http(_modern_server())
    uri = "test://nonexistent-resource-for-conformance-testing"
    response = yield from _post(
        http,
        {
            "jsonrpc": "2.0",
            "id": 29,
            "method": "resources/read",
            "params": {"uri": uri, "_meta": _META},
        },
        {
            "mcp-protocol-version": "2026-07-28",
            "mcp-method": "resources/read",
            "mcp-name": uri,
        },
    )
    error = (yield from read_message(response))["error"]
    assert error["code"] == MS.INVALID_PARAMS_ERROR_CODE
    assert error["data"] == {"uri": uri}


def _empty_call() -> MS.CallToolResult:
    return {"content": []}


@testing.effect
def test_should_reject_a_tools_call_request_when_its_required_routing_name_is_missing():
    """Mcp Conformance / Tools > Modern request headers / should reject a tools/call request when its required routing name is missing"""  # noqa: E501
    test = yield from conformance(P.v2026_07_28)
    initialized = yield from test.initialize()
    response = yield from test.send(
        initialized,
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "tools/call",
            "params": {"arguments": {"value": "called"}},
        },
    )
    error = yield from test.decode_error(response)
    assert error["error"]["code"] == MS.HEADER_MISMATCH_ERROR_CODE
