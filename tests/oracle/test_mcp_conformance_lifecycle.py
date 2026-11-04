"""Ports of Effect's MCP conformance lifecycle titles
(test/ai/McpServer/McpConformance/LifecycleTest.ts) over the in-memory
HTTP server, for every stateful revision (the 2026-07-28 file runs its own
discovery titles instead).

Omitted: none.
"""

from __future__ import annotations

import json
import re
from typing import Any

import pytest

import pyfect as fx
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import ToolEntry
from pyfect.context import Context
from pyfect.http import request as R
from pyfect.http.client import HttpClientService
from pyfect.http.response import HttpClientResponse

from ._mcp import Json, in_memory_http

STATEFUL = [P.v2024_11_05, P.v2025_03_26, P.v2025_06_18, P.v2025_11_25]
URL = "http://localhost/mcp"
ACCEPT = "application/json, text/event-stream"
INSTRUCTIONS = "Follow the test server instructions."
SERVER_INFO = {"name": "McpConformance", "version": "1.0.0"}
CLIENT_INFO = {"name": "McpConformanceClient", "version": "1.0.0"}

type Http = HttpClientService[Any, Any]


def _id(protocol: P.AnyProtocolAdapter) -> str:
    return protocol.protocol_version


def _features() -> fx.Effect[None, Any, M.McpServer]:
    @fx.gen
    def run():
        yield from M.register_prompt(name="NoArgumentPrompt", content=lambda _: fx.succeed("x"))
        yield from M.register_resource(uri="file:///test", name="T", content=fx.succeed("test"))
        yield from M.register_resource_template(
            M.uri_template("file:///template/", MS.param("path", S.String)),
            name="TestResourceTemplate",
            content=lambda uri, _path: fx.succeed(uri),
        )
        yield from M.McpServer().flat_map(
            lambda server: server.add_tool(
                ToolEntry(
                    {"name": "TestTool", "inputSchema": {"type": "object"}},
                    Context.empty(),
                    lambda _: fx.succeed({"content": []}),
                )
            )
        )

    return run


def _http(protocol: P.AnyProtocolAdapter, *, features: bool = False) -> fx.Effect[Http, Any, Any]:
    app = M.layer_http(
        name=SERVER_INFO["name"],
        version=SERVER_INFO["version"],
        path="/mcp",
        protocols=(protocol,),
        instructions=INSTRUCTIONS,
    )
    if features:
        app = layer.merge(app, layer.effect_discard(_features()).pipe(layer.provide(M.layer)))
    return in_memory_http(app)


def _post(
    http: Http, body: object, headers: dict[str, str] | None = None
) -> fx.Effect[HttpClientResponse, Any]:
    request = (
        R.post(URL)
        .set_headers({"accept": ACCEPT, **(headers or {})})
        .body_text(json.dumps(body), "application/json")
    )
    return http.execute(request)


def _json(response: HttpClientResponse) -> fx.Effect[Any, Any]:
    return response.text.map(json.loads)


def _initialize_body(version: str, **params: object) -> Json:
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": version,
            "capabilities": {},
            "clientInfo": CLIENT_INFO,
            **params,
        },
    }


def _initialize(
    http: Http, version: str
) -> fx.Effect[tuple[HttpClientResponse, Json, str | None], Any]:
    @fx.gen
    def run():
        response = yield from _post(http, _initialize_body(version))
        message = yield from _json(response)
        return response, message, response.headers.get("mcp-session-id")

    return run


INITIALIZED: Json = {"jsonrpc": "2.0", "method": "notifications/initialized"}


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_returns_configured_server_instructions(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Lifecycle / Lifecycle Phases / Initialization / returns configured server instructions"""  # noqa: E501
    http = yield from _http(protocol, features=True)
    _, message, _ = yield from _initialize(http, protocol.protocol_version)
    assert message["result"]["instructions"] == INSTRUCTIONS


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_reject_non_ping_requests_before_initialize(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Lifecycle / Lifecycle Phases / Initialization / MUST reject non-ping requests before initialize"""  # noqa: E501
    http = yield from _http(protocol)
    request: Json = {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}}
    assert (yield from _post(http, request)).status == 400


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_reject_initialized_notifications_before_initialize(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Lifecycle / Lifecycle Phases / Initialization / MUST reject initialized notifications before initialize"""  # noqa: E501
    http = yield from _http(protocol)
    assert (yield from _post(http, INITIALIZED)).status == 400


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_schema_requires_protocol_version_capabilities_and_client_info(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Lifecycle / Lifecycle Phases / Initialization / SCHEMA requires protocolVersion, capabilities, and clientInfo"""  # noqa: E501
    http = yield from _http(protocol)
    version = protocol.protocol_version
    invalid: list[Json] = [
        {"capabilities": {}, "clientInfo": CLIENT_INFO},
        {"protocolVersion": version, "clientInfo": CLIENT_INFO},
        {"protocolVersion": version, "capabilities": {}},
    ]
    for index, params in enumerate(invalid):
        body = {"jsonrpc": "2.0", "id": index + 1, "method": "initialize", "params": params}
        response = yield from _post(http, body)
        error = yield from _json(response)
        assert error["id"] == index + 1
        assert error["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE
        assert response.headers.get("mcp-session-id") is None


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_schema_returns_server_capabilities_and_implementation_information(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Lifecycle / Lifecycle Phases / Initialization / SCHEMA returns server capabilities and implementation information"""  # noqa: E501
    http = yield from _http(protocol)
    response, message, session = yield from _initialize(http, protocol.protocol_version)
    assert response.status == 200
    assert message["id"] == 1
    assert isinstance(message["result"]["capabilities"], dict)
    assert message["result"]["serverInfo"] == SERVER_INFO
    assert session is not None
    assert re.fullmatch(r"[\x21-\x7e]+", session)


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_accept_initialized_after_a_successful_initialize_response(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Lifecycle / Lifecycle Phases / Initialization / MUST accept initialized after a successful initialize response"""  # noqa: E501
    http = yield from _http(protocol)
    _, _, session = yield from _initialize(http, protocol.protocol_version)
    assert session is not None
    headers = {"mcp-session-id": session, "mcp-protocol-version": protocol.protocol_version}
    response = yield from _post(http, INITIALIZED, headers)
    assert response.status == 202
    assert (yield from response.text) == ""


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_echo_a_requested_version_supported_by_the_server(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Lifecycle / Lifecycle Phases / Version Negotiation / MUST echo a requested version supported by the server"""  # noqa: E501
    http = yield from _http(protocol)
    _, message, _ = yield from _initialize(http, protocol.protocol_version)
    assert message["result"]["protocolVersion"] == protocol.protocol_version


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_should_negotiate_an_unsupported_requested_version(protocol: P.AnyProtocolAdapter):
    """Mcp Conformance / Lifecycle / Lifecycle Phases / Version Negotiation / SHOULD negotiate an unsupported requested version to a supported version"""  # noqa: E501
    http = yield from _http(protocol)
    _, message, _ = yield from _initialize(http, "unsupported-version")
    assert message["result"]["protocolVersion"] == protocol.protocol_version


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_schema_advertises_the_registered_prompt_resource_and_tool_capabilities(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Lifecycle / Lifecycle Phases / Capability Negotiation / SCHEMA advertises the registered prompt, resource, and tool capabilities"""  # noqa: E501
    http = yield from _http(protocol, features=True)
    _, message, _ = yield from _initialize(http, protocol.protocol_version)
    capabilities = message["result"]["capabilities"]
    assert capabilities["prompts"] == {"listChanged": True}
    assert capabilities["resources"] == {"listChanged": True, "subscribe": False}
    assert capabilities["tools"] == {"listChanged": True}


@pytest.mark.parametrize("protocol", STATEFUL, ids=_id)
@testing.effect
def test_must_continue_to_use_the_version_negotiated_during_initialization(
    protocol: P.AnyProtocolAdapter,
):
    """Mcp Conformance / Lifecycle / Lifecycle Phases / Operation / MUST continue to use the version negotiated during initialization"""  # noqa: E501
    http = yield from _http(protocol)
    _, _, session = yield from _initialize(http, protocol.protocol_version)
    assert session is not None
    headers = {"mcp-session-id": session, "mcp-protocol-version": protocol.protocol_version}
    yield from _post(http, INITIALIZED, headers)
    ping: Json = {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}}
    response = yield from _post(http, ping, headers)
    assert response.status == 200
    assert response.headers.get("mcp-protocol-version") == protocol.protocol_version
