"""Ports of Effect's ``test/ai/McpServer/ProtocolAdapters.test.ts`` titles
that run on its per-revision HTTP fixture (``makeFixture`` /
``makeLowLevelFixture``), which needed the streaming HTTP harness.

Each test's docstring is the Effect test title (with its ``describe``).
Content is given as base64 text where Effect builds it from a
``Uint8Array``. Effect's ``RpcClient``-recording reverse protocol is a real
stdio client here (``_mcp_peer``), so "before transport" means the client saw
no request.

Ported elsewhere: ``should expose continuation input to modern resource and
prompt handlers`` and ``should reject client input when the selected protocol
cannot encode it``, in test_mcp_conformance_multi_round_trip.py.
"""

from __future__ import annotations

import json
import math
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, TypedDict, cast

import pytest

import pyfect as fx
from pyfect import layer, logger, testing
from pyfect import schema as S
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai._mcp.core import NotificationMethod, PromptEntry, ResourceEntry, ToolEntry
from pyfect.context import Context
from pyfect.http.server_request import HttpServerRequest

from ._mcp import Json, stdio_harness
from ._mcp_http import HttpHarness, http_harness, read_message, server_layer
from ._mcp_peer import peer, reverse_client

ALL = (P.v2026_07_28, P.v2025_11_25, P.v2025_06_18, P.v2025_03_26, P.v2024_11_05)
HINTS = {
    "readOnlyHint": False,
    "destructiveHint": True,
    "idempotentHint": False,
    "openWorldHint": True,
}
ALL_VERSIONS = ["2026-07-28", "2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"]
STATEFUL_VERSIONS = ["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"]


class Value(TypedDict):
    value: str


class IdentifiedValue(TypedDict):
    value: str


@dataclass
class State:
    shared: int = 0
    structured: int = 0
    capability: int = 0
    projection_mismatch: int = 0
    audio: int = 0
    resource_link: int = 0
    duplicates: list[str] = field(default_factory=list[str])


def _empty_result() -> MS.CallToolResult:
    return {"content": []}


def _counted(state: State, name: str, result: Any) -> fx.Effect[Any]:
    def count() -> Any:
        setattr(state, name, getattr(state, name) + 1)
        return result

    return fx.sync(count)


# --- makeFixture ----------------------------------------------------------------------------


Shared = T.make("shared", success=S.String).annotate(T.Title, "Shared tool title")
StructuredOnly = T.make("structured-only", success=S.Struct(Value)).annotate(
    MS.EnabledWhen, lambda client: client.protocol_version == "2025-06-18"
)
IdentifiedResult = T.make(
    "identified-result",
    success=S.Struct(IdentifiedValue).annotate(identifier="IdentifiedResult"),
)
Capability = T.make("capability", success=S.String).add_dependency(MS.McpRequestContext)
InitializeMetadata = T.make("initialize-metadata", success=S.String).add_dependency(
    MS.McpRequestContext
)
LogLevel = T.make("log-level", success=S.String)
CapabilityGated = T.make("capability-gated", success=S.String).annotate(
    MS.EnabledWhen,
    lambda client: (
        (client.client_info or {}).get("name") == "allowed-client"
        and client.capabilities.get("roots") is not None
    ),
)
_Kit = K.make(
    Shared,
    StructuredOnly,
    IdentifiedResult,
    Capability,
    InitializeMetadata,
    LogLevel,
    CapabilityGated,
)


def _fixture_kit(state: State) -> fx.Effect[None, Any, Any]:
    handlers = _Kit.to_layer(
        Shared.handler(lambda _, __: _counted(state, "shared", "shared-result")),
        StructuredOnly.handler(
            lambda _, __: _counted(state, "structured", Value(value="structured-result"))
        ),
        IdentifiedResult.handler(lambda _, __: fx.succeed(IdentifiedValue(value="identified"))),
        Capability.handler(
            lambda _, __: M.client_capabilities().flat_map(
                lambda capabilities: _counted(state, "capability", json.dumps(capabilities))
            )
        ),
        InitializeMetadata.handler(
            lambda _, __: MS.McpRequestContext().map(
                lambda context: json.dumps(context.request_metadata)
            )
        ),
        LogLevel.handler(lambda _, __: logger.CurrentLogLevel().map(str)),
        CapabilityGated.handler(lambda _, __: fx.succeed("visible")),
    )
    return M.register_toolkit(_Kit).pipe(fx.provide(handlers))


def _audio_prompt(_: object) -> fx.Effect[MS.GetPromptResult]:
    return fx.succeed(
        {
            "messages": [
                {
                    "role": "user",
                    "content": {"type": "audio", "data": "AQID", "mimeType": "audio/wav"},
                }
            ]
        }
    )


def _resource_link_prompt(_: object) -> fx.Effect[MS.GetPromptResult]:
    return fx.succeed(
        {
            "messages": [
                {
                    "role": "user",
                    "content": {
                        "type": "resource_link",
                        "uri": "file:///canonical.txt",
                        "name": "canonical",
                    },
                }
            ]
        }
    )


def _fixture_registrations(state: State) -> fx.Effect[None, Any, Any]:
    @fx.gen
    def run():
        server = yield from M.McpServer()
        yield from _fixture_kit(state)
        yield from server.add_prompt(
            PromptEntry({"name": "audio-prompt"}, Context.empty(), {}, _audio_prompt)
        )
        yield from server.add_prompt(
            PromptEntry(
                {"name": "resource-link-prompt"}, Context.empty(), {}, _resource_link_prompt
            )
        )

    return run


def _server(registrations: fx.Effect[None, Any, Any], **info: Any) -> layer.Layer[Any, Any, Any]:
    served = M.layer_http(path="/mcp", protocols=ALL, **info)
    return layer.effect_discard(registrations).pipe(layer.provide_merge(served))


def _fixture(
    state: State | None = None, extensions: Mapping[str, Any] | None = None
) -> fx.Effect[HttpHarness, Any, Any]:
    return http_harness(
        _server(
            _fixture_registrations(state or State()),
            name="ProtocolAdapterServer",
            version="1.0.0",
            extensions=extensions,
        )
    )


# --- makeLowLevelFixture --------------------------------------------------------------------


SERVER_ICON: MS.Icon = {
    "src": "https://example.com/server.svg",
    "mimeType": "image/svg+xml",
    "sizes": ["48x48", "any"],
    "theme": "dark",
}
RESOURCE_ICON: MS.Icon = {"src": "https://example.com/resource.svg"}
PROMPT_ICON: MS.Icon = {"src": "https://example.com/prompt.svg"}
TOOL_ICON: MS.Icon = {"src": "https://example.com/tool.svg"}


def _low_level_tool(name: str, description: str, handle: Any) -> ToolEntry:
    tool = cast(
        "MS.Tool",
        {
            "name": name,
            "description": description,
            "inputSchema": {"type": "object", "properties": {}},
        },
    )
    return ToolEntry(tool, Context.empty(), lambda _: handle)


def _text(text: str) -> Json:
    return {"type": "text", "text": text}


def _low_level_registrations(state: State) -> fx.Effect[None, Any, Any]:
    @fx.gen
    def run():
        server = yield from M.McpServer()
        yield from server.add_resource(
            ResourceEntry(
                cast(
                    "MS.Resource",
                    {
                        "uri": "file:///metadata.txt",
                        "name": "metadata-resource",
                        "icons": [RESOURCE_ICON],
                        "_meta": {"descriptor": "fixture"},
                    },
                ),
                Context.empty(),
                fx.succeed(
                    cast(
                        "MS.ReadResourceResult",
                        {
                            "contents": [{"uri": "file:///metadata.txt", "text": "metadata"}],
                            "_meta": {"result": "fixture"},
                        },
                    )
                ),
            )
        )

        def metadata_completion(_value: str, _context: object) -> fx.Effect[MS.CompleteResult]:
            return fx.succeed(
                cast(
                    "MS.CompleteResult",
                    {"completion": {"values": ["metadata"]}, "_meta": {"result": "fixture"}},
                )
            )

        def metadata_prompt(_: object) -> fx.Effect[MS.GetPromptResult]:
            return fx.succeed(
                cast(
                    "MS.GetPromptResult",
                    {
                        "messages": [
                            {
                                "role": "user",
                                "content": {**_text("metadata"), "_meta": {"content": "fixture"}},
                            }
                        ],
                        "_meta": {"result": "fixture"},
                    },
                )
            )

        yield from server.add_prompt(
            PromptEntry(
                cast(
                    "MS.Prompt",
                    {
                        "name": "metadata-prompt",
                        "icons": [PROMPT_ICON],
                        "_meta": {"descriptor": "fixture"},
                    },
                ),
                Context.empty(),
                {"value": metadata_completion},
                metadata_prompt,
            )
        )
        boolean_properties = {
            "name": "boolean-properties",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "anything": True,
                    "forbidden": False,
                    "nested": {"type": "object", "properties": {"unchanged": False}},
                },
            },
        }
        yield from server.add_tool(
            ToolEntry(
                cast("MS.Tool", boolean_properties),
                Context.empty(),
                lambda _: fx.succeed(_empty_result()),
            )
        )
        title_precedence: Json = {
            "name": "title-precedence",
            "title": "Canonical title",
            "icons": [TOOL_ICON],
            "inputSchema": {"type": "object", "properties": {}},
            "annotations": {"title": "Legacy annotation title"},
        }
        yield from server.add_tool(
            ToolEntry(
                cast("MS.Tool", title_precedence),
                Context.empty(),
                lambda _: fx.succeed(cast("MS.CallToolResult", {"content": [_text("title")]})),
            )
        )
        audio = {"content": [{"type": "audio", "data": "AQ==", "mimeType": "audio/wav"}]}
        yield from server.add_tool(
            _low_level_tool(
                "projection-mismatch",
                "Claims old support but returns audio",
                _counted(state, "projection_mismatch", audio),
            )
        )
        yield from server.add_tool(
            _low_level_tool(
                "image",
                "Image for both revisions",
                fx.succeed(
                    {"content": [{"type": "image", "data": "AQID", "mimeType": "image/png"}]}
                ),
            )
        )
        yield from server.add_tool(
            _low_level_tool(
                "binary-resource",
                "Binary embedded resource",
                fx.succeed(
                    {
                        "content": [
                            {
                                "type": "resource",
                                "resource": {
                                    "uri": "file:///binary.dat",
                                    "mimeType": "application/octet-stream",
                                    "blob": "BwgJ",
                                },
                            }
                        ]
                    }
                ),
            )
        )
        yield from server.add_tool(
            _low_level_tool(
                "annotated-resource",
                "Annotated embedded resource",
                fx.succeed(
                    {
                        "content": [
                            {
                                "type": "resource",
                                "resource": {
                                    "uri": "file:///annotated.txt",
                                    "mimeType": "text/plain",
                                    "text": "annotated",
                                    "_meta": {"source": "fixture"},
                                },
                                "annotations": {
                                    "audience": ["assistant"],
                                    "priority": 0.75,
                                    "lastModified": "2026-08-13T00:00:00Z",
                                },
                                "_meta": {"content": "fixture"},
                            }
                        ],
                        "_meta": {"result": "fixture"},
                    }
                ),
            )
        )
        yield from server.add_tool(
            _low_level_tool(
                "audio",
                "Current-revision audio",
                _counted(
                    state,
                    "audio",
                    {"content": [{"type": "audio", "data": "BAUG", "mimeType": "audio/wav"}]},
                ),
            )
        )
        schema_output: Json = {
            "name": "schema-output",
            "description": "Tool with an output schema",
            "inputSchema": {"type": "object", "properties": {}},
            "outputSchema": {
                "type": "object",
                "properties": {"value": {"type": "string"}},
                "required": ["value"],
            },
            "_meta": {"descriptor": "fixture"},
        }
        yield from server.add_tool(
            ToolEntry(
                cast("MS.Tool", schema_output),
                Context.empty(),
                lambda _: fx.succeed(cast("MS.CallToolResult", {"content": [_text("schema")]})),
            )
        )
        structured: list[tuple[str, list[Json], object]] = [
            ("structured-object", [_text("structured")], {"value": "fixture"}),
            ("structured-scalar", [_text("structured")], "fixture"),
            ("structured-string-mirror", [_text(json.dumps("fixture"))], "fixture"),
            (
                "structured-string-multiple",
                [_text(json.dumps("fixture")), _text("extra")],
                "fixture",
            ),
        ]
        for name, content, value in structured:
            yield from server.add_tool(
                _low_level_tool(
                    name,
                    "Structured content",
                    fx.succeed({"content": content, "structuredContent": value}),
                )
            )
        yield from server.add_tool(
            _low_level_tool(
                "invalid-structured-content",
                "Non-JSON structured content",
                fx.succeed({"content": [_text("invalid")], "structuredContent": object()}),
            )
        )
        yield from server.add_tool(
            _low_level_tool(
                "invalid-nested-json",
                "Nested non-JSON values",
                fx.succeed(
                    {
                        "content": [_text("invalid")],
                        "structuredContent": {"count": math.nan},
                        "_meta": {"seen": object()},
                    }
                ),
            )
        )
        yield from server.add_tool(
            _low_level_tool(
                "resource-link",
                "Current-revision resource link",
                _counted(
                    state,
                    "resource_link",
                    {
                        "content": [
                            {
                                "type": "resource_link",
                                "name": "linked",
                                "title": "Linked resource",
                                "description": "A linked fixture",
                                "uri": "file:///linked.txt",
                                "mimeType": "text/plain",
                                "annotations": {"audience": ["user"], "priority": 0.5},
                                "size": 42,
                                "_meta": {"source": "fixture"},
                            }
                        ]
                    },
                ),
            )
        )

    return run


def _low_level(state: State | None = None) -> fx.Effect[HttpHarness, Any, Any]:
    return http_harness(
        _server(
            _low_level_registrations(state or State()),
            name="LowLevelProtocolAdapterServer",
            version="1.0.0",
            description="Low-level protocol adapter fixture",
            website_url="https://example.com/low-level-mcp",
            icons=(SERVER_ICON,),
        )
    )


# --- requests -------------------------------------------------------------------------------


def _modern_metadata(capabilities: Json | None = None, client_info: Json | None = None) -> Json:
    return {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": capabilities or {},
        "io.modelcontextprotocol/clientInfo": client_info
        or {"name": "ModernProtocolAdapterClient", "version": "1.0.0"},
    }


def _modern_request(
    id: int, method: str, params: Json | None = None, metadata: Json | None = None
) -> Json:
    return {
        "jsonrpc": "2.0",
        "id": id,
        "method": method,
        "params": {**(params or {}), "_meta": metadata or _modern_metadata()},
    }


def _modern_headers(method: str, version: str = "2026-07-28") -> dict[str, str]:
    return {"MCP-Protocol-Version": version, "Mcp-Method": method}


@dataclass
class Client:
    harness: HttpHarness
    version: str
    session_id: str
    initialize_result: Json
    next_id: int = 1

    def request(self, method: str, params: Json | None = None) -> fx.Effect[Json]:
        self.next_id += 1
        body: Json = {"jsonrpc": "2.0", "id": self.next_id, "method": method}
        if params is not None:
            body["params"] = params
        headers = {"Mcp-Protocol-Version": self.version, "Mcp-Session-Id": self.session_id}
        return self.harness.post(body, headers).flat_map(read_message)

    def tool(self, name: str) -> fx.Effect[Json]:
        return self.request("tools/call", {"name": name})


def _initialize(
    harness: HttpHarness,
    version: str,
    capabilities: Json | None = None,
    client_info: Json | None = None,
) -> fx.Effect[Client]:
    @fx.gen
    def run():
        response = yield from harness.post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": version,
                    "capabilities": capabilities or {},
                    "clientInfo": client_info
                    or {"name": "ProtocolAdapterClient", "version": "1.0.0"},
                },
            }
        )
        body = yield from read_message(response)
        session = response.headers.get("mcp-session-id")
        assert session is not None
        assert body["result"]["protocolVersion"] == version
        return Client(harness, version, session, body["result"])

    return run


def _listed(message: Json, name: str) -> Json:
    found = [tool for tool in message["result"]["tools"] if tool["name"] == name]
    assert len(found) == 1, name
    return found[0]


def _names(message: Json) -> set[str]:
    return {tool["name"] for tool in message["result"]["tools"]}


def _text_of(message: Json) -> str:
    first = message["result"]["content"][0]
    assert first["type"] == "text", first
    return first["text"]


# --- tests ----------------------------------------------------------------------------------


@testing.effect
def test_negotiates_a_stateful_protocol_when_initialize_offers_the_stateless_revision():
    """McpServer protocol adapters / should negotiate a stateful protocol when initialize offers the stateless revision"""  # noqa: E501
    fixture = yield from _fixture()
    response = yield from fixture.post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2026-07-28",
                "capabilities": {},
                "clientInfo": {"name": "legacy-client", "version": "1.0.0"},
            },
        }
    )
    message = yield from read_message(response)
    assert response.status == 200
    assert response.headers.get("mcp-session-id") is not None
    assert message["result"]["protocolVersion"] == "2025-11-25"


@testing.effect
def test_ignores_a_recognized_legacy_session_when_dispatching_a_modern_request():
    """McpServer protocol adapters / should ignore a recognized legacy session when dispatching a modern request"""  # noqa: E501
    fixture = yield from _fixture()
    legacy = yield from _initialize(fixture, "2025-11-25")
    body = _modern_request(19, "server/discover")
    without = yield from fixture.post(body, _modern_headers("server/discover"))
    expected = yield from read_message(without)
    with_session = yield from fixture.post(
        body, {**_modern_headers("server/discover"), "Mcp-Session-Id": legacy.session_id}
    )
    actual = yield from read_message(with_session)
    assert actual["result"] == expected["result"]
    assert with_session.headers.get("mcp-session-id") is None
    assert (yield from legacy.request("ping", {}))["result"] == {}


@testing.effect
def test_discovers_the_modern_server_without_initialization_or_a_session():
    """McpServer protocol adapters / should discover the modern server without initialization or a session"""  # noqa: E501
    fixture = yield from _fixture()
    response = yield from fixture.post(
        _modern_request(19, "server/discover"), _modern_headers("server/discover")
    )
    message = yield from read_message(response)
    assert response.status == 200
    assert response.headers.get("mcp-session-id") is None
    assert message["result"]["supportedVersions"] == ALL_VERSIONS


@testing.effect
def test_keeps_log_levels_isolated_when_one_session_updates_its_level():
    """McpServer protocol adapters / should keep log levels isolated when one session updates its level"""  # noqa: E501
    fixture = yield from _fixture()
    first = yield from _initialize(fixture, "2025-06-18")
    second = yield from _initialize(fixture, "2025-06-18")
    assert "result" in (yield from first.request("logging/setLevel", {"level": "debug"}))
    assert _text_of((yield from first.tool("log-level"))) == "Debug"
    assert _text_of((yield from second.tool("log-level"))) == "Info"


class SessionOwner(TypedDict):
    client: str
    hasSession: bool


@testing.effect
def test_omits_a_legacy_client_when_a_session_registered_toolkit_handles_a_stateless_request():
    """McpServer protocol adapters / registration request context / should omit a legacy client when a toolkit registered in a session handles a stateless request"""  # noqa: E501
    owner = T.make("session-owner", success=S.Struct(SessionOwner))
    kit = K.make(owner)

    def session_owner(_: object, __: object) -> fx.Effect[SessionOwner, Any, Any]:
        @fx.gen
        def run():
            request = yield from MS.McpRequestContext()
            session = yield from fx.service_option(MS.McpServerClient)
            assert request.client_info is not None
            return SessionOwner(client=request.client_info["name"], hasSession=session is not None)

        return run

    register = M.register_toolkit(kit).pipe(fx.provide(kit.to_layer(owner.handler(session_owner))))

    def registering(server: M.McpServerService) -> fx.Effect[None]:
        return server.add_tool(
            ToolEntry(
                {"name": "register", "inputSchema": {"type": "object"}},
                Context.empty(),
                lambda _: register.pipe(fx.provide_service(M.McpServer, server)).as_(
                    _empty_result()
                ),
            )
        )

    harness = yield from http_harness(
        server_layer(
            "RegistrationContext",
            (P.v2026_07_28, P.v2025_06_18),
            M.McpServer().flat_map(registering),
        )
    )
    initialized = yield from harness.post(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "Alice", "version": "1"},
            },
        }
    )
    yield from read_message(initialized)
    session = initialized.headers.get("mcp-session-id")
    assert session is not None
    legacy = {"mcp-session-id": session, "mcp-protocol-version": "2025-06-18"}
    yield from harness.post({"jsonrpc": "2.0", "method": "notifications/initialized"}, legacy)
    registered = yield from harness.post(
        {"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "register"}}, legacy
    ).flat_map(read_message)
    assert registered["result"]["content"] == []
    invoked = yield from harness.post(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {
                "name": "session-owner",
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                    "io.modelcontextprotocol/clientInfo": {"name": "Bob", "version": "1"},
                },
            },
        },
        {
            "mcp-protocol-version": "2026-07-28",
            "mcp-method": "tools/call",
            "mcp-name": "session-owner",
        },
    ).flat_map(read_message)
    assert invoked["result"]["structuredContent"] == {"client": "Bob", "hasSession": False}


@testing.effect
def test_uses_the_current_http_request_when_another_request_registered_the_resource():
    """McpServer protocol adapters / registration request context / should use the current HTTP request when another request registered the resource"""  # noqa: E501

    @fx.gen
    def content():
        request = yield from MS.McpRequestContext()
        http = yield from HttpServerRequest()
        level = yield from logger.CurrentLogLevel()
        assert request.client_info is not None
        owner = request.request_metadata["owner"]
        return f"{request.client_info['name']}:{owner}:{http.headers['x-owner']}:{level}"

    register: fx.Effect[None, Any, Any] = M.register_resource(
        uri="file:///http-owner", name="http-owner", content=content
    )

    def registering(server: M.McpServerService) -> fx.Effect[None]:
        return server.add_tool(
            ToolEntry(
                {"name": "register", "inputSchema": {"type": "object"}},
                Context.empty(),
                lambda _: register.pipe(fx.provide_service(M.McpServer, server)).as_(
                    _empty_result()
                ),
            )
        )

    harness = yield from http_harness(
        server_layer("RegistrationContext", (P.v2026_07_28,), M.McpServer().flat_map(registering))
    )

    def request(name: str, method: str, params: Json) -> fx.Effect[Json]:
        body = {
            "jsonrpc": "2.0",
            "id": name,
            "method": method,
            "params": {
                **params,
                "_meta": {
                    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                    "io.modelcontextprotocol/clientCapabilities": {},
                    "io.modelcontextprotocol/clientInfo": {"name": name, "version": "1"},
                    "io.modelcontextprotocol/logLevel": "error" if name == "Alice" else "debug",
                    "owner": name,
                },
            },
        }
        headers = {
            "mcp-protocol-version": "2026-07-28",
            "mcp-method": method,
            "mcp-name": "register" if method == "tools/call" else "file:///http-owner",
            "x-owner": name,
        }
        return harness.post(body, headers).flat_map(read_message)

    registered = yield from request("Alice", "tools/call", {"name": "register"})
    assert registered["result"]["content"] == []
    read = yield from request("Bob", "resources/read", {"uri": "file:///http-owner"})
    assert read["result"]["contents"] == [
        {"uri": "file:///http-owner", "text": "Bob:Bob:Bob:Debug"}
    ]


@testing.effect
def test_isolates_interleaved_stateful_and_stateless_request_contexts():
    """McpServer protocol adapters / should isolate interleaved stateful and stateless request contexts"""  # noqa: E501
    fixture = yield from _fixture()
    legacy = yield from _initialize(
        fixture, "2025-11-25", {"roots": {}}, {"name": "legacy-client", "version": "1.0.0"}
    )
    assert _text_of((yield from legacy.tool("capability"))) == json.dumps({"roots": {}})
    response = yield from fixture.post(
        _modern_request(
            20,
            "tools/call",
            {"name": "capability", "arguments": {}},
            _modern_metadata({"sampling": {}}, {"name": "modern-client", "version": "2.0.0"}),
        ),
        {
            **_modern_headers("tools/call"),
            "Mcp-Name": "capability",
            "Mcp-Session-Id": "ignored-modern-session",
        },
    )
    modern = yield from read_message(response)
    assert response.headers.get("mcp-session-id") is None
    assert modern["result"]["structuredContent"] == json.dumps({"sampling": {}})
    assert _text_of((yield from legacy.tool("capability"))) == json.dumps({"roots": {}})


@testing.effect
def test_keeps_requests_out_of_legacy_routing_when_modern_metadata_is_malformed():
    """McpServer protocol adapters / should keep requests out of legacy routing when modern metadata is malformed"""  # noqa: E501
    fixture = yield from _fixture()
    unsupported = "2099-01-01"
    cases: list[tuple[str, Json, dict[str, str], int, int, list[str] | None]] = [
        (
            "missing request metadata",
            {"jsonrpc": "2.0", "id": 30, "method": "tools/list", "params": {}},
            _modern_headers("tools/list"),
            400,
            MS.INVALID_PARAMS_ERROR_CODE,
            None,
        ),
        (
            "missing protocol header",
            _modern_request(31, "tools/list"),
            {"Mcp-Method": "tools/list"},
            400,
            MS.HEADER_MISMATCH_ERROR_CODE,
            None,
        ),
        (
            "malformed client identity",
            _modern_request(
                32,
                "tools/list",
                {},
                {**_modern_metadata(), "io.modelcontextprotocol/clientInfo": True},
            ),
            _modern_headers("tools/list"),
            200,
            MS.INVALID_PARAMS_ERROR_CODE,
            None,
        ),
        (
            "unsupported protocol version",
            _modern_request(
                33,
                "tools/list",
                {},
                {**_modern_metadata(), "io.modelcontextprotocol/protocolVersion": unsupported},
            ),
            _modern_headers("tools/list", unsupported),
            400,
            -32022,
            ALL_VERSIONS,
        ),
        (
            "modern metadata on initialize",
            {
                "jsonrpc": "2.0",
                "id": 34,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2025-11-25",
                    "capabilities": {},
                    "clientInfo": {"name": "legacy-shape", "version": "1.0.0"},
                    "_meta": _modern_metadata(),
                },
            },
            _modern_headers("initialize"),
            404,
            MS.METHOD_NOT_FOUND_ERROR_CODE,
            None,
        ),
    ]
    for name, body, headers, status, code, supported in cases:
        response = yield from fixture.post(body, headers)
        message = yield from read_message(response)
        assert "error" in message, name
        assert response.status == status, name
        assert message["error"]["code"] == code, name
        if supported is not None:
            assert message["error"]["data"]["supported"] == supported, name


@testing.effect
def test_rejects_prompt_content_when_the_negotiated_schema_cannot_represent_it():
    """McpServer protocol adapters / should reject prompt content when the negotiated schema cannot represent it"""  # noqa: E501
    fixture = yield from _fixture()
    old = yield from _initialize(fixture, "2024-11-05")
    march = yield from _initialize(fixture, "2025-03-26")
    june = yield from _initialize(fixture, "2025-06-18")
    audio = {"name": "audio-prompt"}
    link = {"name": "resource-link-prompt"}
    reply = yield from old.request("prompts/get", audio)
    assert reply["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE
    assert "messages" in (yield from march.request("prompts/get", audio))["result"]
    reply = yield from march.request("prompts/get", link)
    assert reply["error"]["code"] == MS.INVALID_PARAMS_ERROR_CODE
    assert "messages" in (yield from june.request("prompts/get", link))["result"]


@pytest.mark.parametrize("version", STATEFUL_VERSIONS)
@testing.effect
def test_preserves_server_extensions_when_initializing(version: str):
    """McpServer protocol adapters / should preserve server extensions when initializing ${protocolVersion} requests"""  # noqa: E501
    extensions = {"example/extension": {"enabled": True}}
    fixture = yield from _fixture(extensions=extensions)
    client = yield from _initialize(fixture, version)
    assert client.initialize_result["capabilities"]["extensions"] == extensions


@testing.effect
def test_omits_elicitation_when_the_negotiated_protocol_predates_2025_06_18():
    """McpServer protocol adapters / should omit elicitation when the negotiated protocol predates v2025-06-18"""  # noqa: E501
    fixture = yield from _fixture()
    for version in ("2024-11-05", "2025-03-26"):
        client = yield from _initialize(fixture, version, {"elicitation": {}})
        assert "elicitation" not in client.initialize_result["capabilities"]
        assert _text_of((yield from client.tool("capability"))) == "{}"


@testing.effect
def test_exposes_current_request_metadata_when_invoking_a_handler():
    """McpServer protocol adapters / should expose current request metadata when invoking a handler"""  # noqa: E501
    fixture = yield from _fixture()
    for version in ("2024-11-05", "2025-03-26", "2025-06-18"):
        response = yield from fixture.post(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": version,
                    "capabilities": {},
                    "clientInfo": {"name": "metadata-client", "version": "1.0.0"},
                    "_meta": {"progressToken": version},
                },
            }
        )
        session = response.headers.get("mcp-session-id")
        assert session is not None
        tool = yield from fixture.post(
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "initialize-metadata",
                    "_meta": {"progressToken": f"call-{version}"},
                },
            },
            {"Mcp-Protocol-Version": version, "Mcp-Session-Id": session},
        )
        body = yield from read_message(tool)
        assert _text_of(body) == json.dumps({"progressToken": f"call-{version}"})


@pytest.mark.parametrize(
    "protocol", [P.v2024_11_05, P.v2025_03_26], ids=lambda p: p.protocol_version
)
@testing.effect
def test_rejects_elicitation_before_transport_when_the_protocol_predates_2025_06_18(
    protocol: P.AnyProtocolAdapter,
):
    """McpServer protocol adapters / should reject elicitation before transport when the protocol predates v2025-06-18"""  # noqa: E501
    made = yield from peer(protocol, {"elicitation": {}})
    request: Any = {"message": "test", "requestedSchema": {"type": "object", "properties": {}}}
    exit_ = yield from made.run(reverse_client().flat_map(lambda client: client.elicit(request)))
    assert isinstance(exit_, fx.exit.Failure)
    assert isinstance(exit_.cause.squash(), MS.McpReverseOperationUnsupported)
    assert made.requests == []


@testing.effect
def test_rejects_direct_reverse_operations_when_the_selected_protocol_is_stateless():
    """McpServer protocol adapters / should reject direct reverse operations when the selected protocol is stateless"""  # noqa: E501
    # Effect builds the adapter's reverse client directly and every operation fails. pyfect's
    # reverse client belongs to a session, and a stateless request has none to reach it through.
    seen: list[bool] = []

    def probe(_: object) -> fx.Effect[MS.CallToolResult]:
        return fx.service_option(MS.McpServerClient).map(
            lambda session: (seen.append(session is not None), _empty_result())[1]
        )

    registration = M.McpServer().flat_map(
        lambda server: server.add_tool(
            ToolEntry({"name": "probe", "inputSchema": {"type": "object"}}, Context.empty(), probe)
        )
    )
    harness = yield from stdio_harness(P.v2026_07_28, None, registration)
    reply = yield from harness.send_request("tools/call", {"name": "probe"})
    assert reply["result"]["content"] == []
    assert seen == [False]


@testing.effect
def test_preserves_boolean_property_semantics_when_projecting_old_tool_descriptors():
    """McpServer protocol adapters / should preserve boolean property semantics when projecting old tool descriptors"""  # noqa: E501
    fixture = yield from _low_level()
    for version in ("2024-11-05", "2025-03-26"):
        client = yield from _initialize(fixture, version)
        tool = _listed((yield from client.request("tools/list")), "boolean-properties")
        assert tool["inputSchema"] == {
            "type": "object",
            "properties": {
                "anything": {},
                "forbidden": {"not": {}},
                "nested": {"type": "object", "properties": {"unchanged": False}},
            },
        }


@testing.effect
def test_omits_june_fields_when_projecting_a_march_tool_descriptor():
    """McpServer protocol adapters / should omit June fields when projecting a March tool descriptor"""  # noqa: E501
    fixture = yield from _fixture()
    client = yield from _initialize(fixture, "2025-03-26")
    shared = _listed((yield from client.request("tools/list")), "shared")
    assert shared["inputSchema"] == {"type": "object"}
    assert shared["annotations"] == {"title": "Shared tool title", **HINTS}
    assert "title" not in shared
    assert "outputSchema" not in shared
    assert "_meta" not in shared


@testing.effect
def test_prefers_the_canonical_title_when_projecting_march_annotations():
    """McpServer protocol adapters / should prefer the canonical title when projecting March annotations"""  # noqa: E501
    fixture = yield from _low_level()
    client = yield from _initialize(fixture, "2025-03-26")
    tool = _listed((yield from client.request("tools/list")), "title-precedence")
    assert tool["annotations"] == {"title": "Canonical title", **HINTS}


@testing.effect
def test_returns_a_typed_protocol_error_when_a_result_cannot_be_projected():
    """McpServer protocol adapters / should return a typed protocol error when a result cannot be projected"""  # noqa: E501
    state = State()
    fixture = yield from _low_level(state)
    client = yield from _initialize(fixture, "2024-11-05")
    error = (yield from client.tool("projection-mismatch"))["error"]
    assert error["code"] == MS.INVALID_PARAMS_ERROR_CODE
    assert "audio tool content is not supported by MCP 2024-11-05" in error["message"]
    assert state.projection_mismatch == 1


@testing.effect
def test_routes_each_session_through_its_negotiated_rpc_group_when_revisions_coexist():
    """McpServer protocol adapters / should route each session through its negotiated RPC group when revisions coexist"""  # noqa: E501
    fixture = yield from _fixture()
    old = yield from _initialize(fixture, "2024-11-05")
    current = yield from _initialize(fixture, "2025-06-18")
    assert "title" not in _listed((yield from old.request("tools/list")), "shared")
    assert _listed((yield from current.request("tools/list")), "shared")["title"] == (
        "Shared tool title"
    )
    response = yield from fixture.post(
        {"jsonrpc": "2.0", "id": 2, "method": "ping", "params": {}},
        {"Mcp-Protocol-Version": "2025-11-25", "Mcp-Session-Id": current.session_id},
    )
    assert response.status == 400
    assert (yield from read_message(response)) == {
        "jsonrpc": "2.0",
        "id": 2,
        "error": {
            "code": MS.HEADER_MISMATCH_ERROR_CODE,
            "message": "MCP-Protocol-Version header '2025-11-25' does not match "
            "negotiated protocol version '2025-06-18'",
        },
    }


@pytest.mark.parametrize("version", STATEFUL_VERSIONS)
@testing.effect
def test_exposes_the_negotiated_client_profile(version: str):
    """McpServer protocol adapters / should expose the negotiated client profile when serving ${protocolVersion} requests"""  # noqa: E501
    state = State()
    fixture = yield from _fixture(state)
    advertised = {
        "extensions": {"example/extension": {"enabled": True}},
        "roots": {"listChanged": True},
        "sampling": {},
    }
    allowed = yield from _initialize(
        fixture, version, advertised, {"name": "allowed-client", "version": "2.0.0"}
    )
    denied = yield from _initialize(
        fixture, version, {}, {"name": "other-client", "version": "1.0.0"}
    )
    assert "capability-gated" in _names((yield from allowed.request("tools/list")))
    assert "capability-gated" not in _names((yield from denied.request("tools/list")))
    assert json.loads(_text_of((yield from allowed.tool("capability")))) == advertised
    assert state.capability == 1


@testing.effect
def test_preserves_tool_titles_and_hints_when_listing_tools_for_each_revision():
    """McpServer protocol adapters / should preserve tool titles and hints when listing tools for each revision"""  # noqa: E501
    fixture = yield from _fixture()
    old = yield from _initialize(fixture, "2024-11-05")
    shared = _listed((yield from old.request("tools/list")), "shared")
    for absent in ("title", "annotations", "_meta", "outputSchema"):
        assert absent not in shared
    for version in ("2025-06-18", "2025-11-25"):
        client = yield from _initialize(fixture, version)
        shared = _listed((yield from client.request("tools/list")), "shared")
        assert shared["title"] == "Shared tool title"
        assert shared["annotations"] == {"title": "Shared tool title", **HINTS}


@testing.effect
def test_projects_output_schema_only_when_the_protocol_revision_supports_it():
    """McpServer protocol adapters / should project outputSchema only when the protocol revision supports it"""  # noqa: E501
    fixture = yield from _low_level()
    current = yield from _initialize(fixture, "2025-06-18")
    old = yield from _initialize(fixture, "2024-11-05")
    current_tool = _listed((yield from current.request("tools/list")), "schema-output")
    old_tool = _listed((yield from old.request("tools/list")), "schema-output")
    assert current_tool["outputSchema"] == {
        "type": "object",
        "properties": {"value": {"type": "string"}},
        "required": ["value"],
    }
    assert current_tool["_meta"] == {"descriptor": "fixture"}
    assert "outputSchema" not in old_tool
    assert "_meta" not in old_tool


@testing.effect
def test_inlines_identified_output_schemas_on_the_2025_wire():
    """McpServer protocol adapters / should inline identified output schemas on the 2025 wire"""
    fixture = yield from _fixture()
    for version in ("2025-06-18", "2025-11-25"):
        client = yield from _initialize(fixture, version)
        tool = _listed((yield from client.request("tools/list")), "identified-result")
        assert tool["outputSchema"] == {
            "type": "object",
            "properties": {"value": {"type": "string"}},
            "required": ["value"],
            "additionalProperties": True,
        }


@testing.effect
def test_encodes_binary_content_for_every_revision_that_can_represent_it():
    """McpServer protocol adapters / should encode binary content for every revision that can represent it"""  # noqa: E501
    fixture = yield from _low_level()
    for version in ("2024-11-05", "2025-03-26", "2025-06-18"):
        client = yield from _initialize(fixture, version)
        image = (yield from client.tool("image"))["result"]
        assert image["content"] == [{"type": "image", "data": "AQID", "mimeType": "image/png"}]
        embedded = (yield from client.tool("binary-resource"))["result"]
        assert embedded["content"] == [
            {
                "type": "resource",
                "resource": {
                    "uri": "file:///binary.dat",
                    "mimeType": "application/octet-stream",
                    "blob": "BwgJ",
                },
            }
        ]
    for version in ("2025-03-26", "2025-06-18"):
        client = yield from _initialize(fixture, version)
        audio = (yield from client.tool("audio"))["result"]
        assert audio["content"] == [{"type": "audio", "data": "BAUG", "mimeType": "audio/wav"}]


@testing.effect
def test_projects_structured_content_according_to_the_negotiated_revision():
    """McpServer protocol adapters / should project structured content according to the negotiated revision"""  # noqa: E501
    fixture = yield from _low_level()
    for version in STATEFUL_VERSIONS:
        client = yield from _initialize(fixture, version)
        mirror = (yield from client.tool("structured-string-mirror"))["result"]
        custom = (yield from client.tool("structured-scalar"))["result"]
        multiple = (yield from client.tool("structured-string-multiple"))["result"]
        assert mirror["content"] == [_text("fixture")]
        assert custom["content"] == [_text("structured")]
        assert multiple["content"] == [_text(json.dumps("fixture")), _text("extra")]
        for result in (mirror, custom, multiple):
            assert "structuredContent" not in result
    for version in ("2024-11-05", "2025-03-26"):
        client = yield from _initialize(fixture, version)
        assert "structuredContent" not in (yield from client.tool("structured-object"))["result"]
        assert "structuredContent" not in (yield from client.tool("structured-scalar"))["result"]
    for version in ("2025-06-18", "2025-11-25"):
        client = yield from _initialize(fixture, version)
        result = (yield from client.tool("structured-object"))["result"]
        assert result["structuredContent"] == {"value": "fixture"}
        assert "structuredContent" not in (yield from client.tool("structured-scalar"))["result"]

    def modern(id: int, name: str) -> fx.Effect[Json]:
        return fixture.post(
            _modern_request(id, "tools/call", {"name": name, "arguments": {}}),
            {**_modern_headers("tools/call"), "Mcp-Name": name},
        ).flat_map(read_message)

    assert (yield from modern(41, "structured-scalar"))["result"]["structuredContent"] == "fixture"
    mirrored = (yield from modern(42, "structured-string-mirror"))["result"]
    assert mirrored["structuredContent"] == "fixture"
    assert mirrored["content"] == [_text(json.dumps("fixture"))]


@testing.effect
def test_preserves_only_supported_metadata_when_projecting_embedded_resource_content():
    """McpServer protocol adapters / should preserve only supported metadata when projecting embedded resource content"""  # noqa: E501
    fixture = yield from _low_level()
    for version in ("2025-11-25", "2025-06-18", "2025-03-26", "2024-11-05"):
        client = yield from _initialize(fixture, version)
        result = (yield from client.tool("annotated-resource"))["result"]
        content = result["content"][0]
        assert result["_meta"] == {"result": "fixture"}
        resource = content["resource"]
        expected: Json = {"audience": ["assistant"], "priority": 0.75}
        if version == "2025-11-25":
            expected["lastModified"] = "2026-08-13T00:00:00Z"
        assert content["annotations"] == expected
        assert resource["uri"] == "file:///annotated.txt"
        assert resource["mimeType"] == "text/plain"
        assert resource["text"] == "annotated"
        if version in ("2025-11-25", "2025-06-18"):
            assert resource["_meta"] == {"source": "fixture"}
            assert content["_meta"] == {"content": "fixture"}
        else:
            assert "_meta" not in resource
            assert "_meta" not in content


@testing.effect
def test_preserves_result_metadata_while_omitting_june_only_metadata_for_older_revisions():
    """McpServer protocol adapters / should preserve result metadata while omitting June-only metadata for older revisions"""  # noqa: E501
    fixture = yield from _low_level()
    for version in ("2024-11-05", "2025-03-26", "2025-06-18"):
        client = yield from _initialize(fixture, version)
        resources = (yield from client.request("resources/list"))["result"]["resources"]
        resource = next(r for r in resources if r["uri"] == "file:///metadata.txt")
        read = yield from client.request("resources/read", {"uri": "file:///metadata.txt"})
        prompts = (yield from client.request("prompts/list"))["result"]["prompts"]
        descriptor = next(p for p in prompts if p["name"] == "metadata-prompt")
        prompt = (yield from client.request("prompts/get", {"name": "metadata-prompt"}))["result"]
        completion = yield from client.request(
            "completion/complete",
            {
                "ref": {"type": "ref/prompt", "name": "metadata-prompt"},
                "argument": {"name": "value", "value": "m"},
            },
        )
        assert read["result"]["_meta"] == {"result": "fixture"}
        assert prompt["_meta"] == {"result": "fixture"}
        assert completion["result"]["_meta"] == {"result": "fixture"}
        content = prompt["messages"][0]["content"]
        if version == "2025-06-18":
            assert resource["_meta"] == {"descriptor": "fixture"}
            assert descriptor["_meta"] == {"descriptor": "fixture"}
            assert content["_meta"] == {"content": "fixture"}
        else:
            assert "_meta" not in resource
            assert "_meta" not in descriptor
            assert "_meta" not in content


@testing.effect
def test_exposes_implementation_metadata_and_descriptor_icons_when_supported_by_the_protocol():
    """McpServer protocol adapters / should expose implementation metadata and descriptor icons when supported by the protocol"""  # noqa: E501
    fixture = yield from _low_level()
    november = yield from _initialize(fixture, "2025-11-25")
    june = yield from _initialize(fixture, "2025-06-18")
    assert november.initialize_result["serverInfo"] == {
        "name": "LowLevelProtocolAdapterServer",
        "version": "1.0.0",
        "description": "Low-level protocol adapter fixture",
        "websiteUrl": "https://example.com/low-level-mcp",
        "icons": [SERVER_ICON],
    }
    assert june.initialize_result["serverInfo"] == {
        "name": "LowLevelProtocolAdapterServer",
        "version": "1.0.0",
    }
    resources = (yield from november.request("resources/list"))["result"]["resources"]
    resource = next(r for r in resources if r["uri"] == "file:///metadata.txt")
    assert resource["icons"] == [RESOURCE_ICON]
    prompts = (yield from november.request("prompts/list"))["result"]["prompts"]
    prompt = next(p for p in prompts if p["name"] == "metadata-prompt")
    assert prompt["icons"] == [PROMPT_ICON]
    tool = _listed((yield from november.request("tools/list")), "title-precedence")
    assert tool["icons"] == [TOOL_ICON]


@testing.effect
def test_hides_and_rejects_a_tool_when_its_declaration_is_incompatible_with_the_revision():
    """McpServer protocol adapters / should hide and reject a tool when its declaration is incompatible with the revision"""  # noqa: E501
    state = State()
    fixture = yield from _fixture(state)
    current = yield from _initialize(fixture, "2025-06-18")
    old = yield from _initialize(fixture, "2024-11-05")
    assert "structured-only" in _names((yield from current.request("tools/list")))
    assert "structured-only" not in _names((yield from old.request("tools/list")))
    call = yield from old.request("tools/call", {"name": "structured-only", "arguments": {}})
    assert "error" in call
    assert state.structured == 0


@testing.effect
def test_rejects_after_invocation_when_a_tool_result_cannot_be_projected():
    """McpServer protocol adapters / should reject after invocation when a tool result cannot be projected"""  # noqa: E501
    state = State()
    fixture = yield from _low_level(state)
    current = yield from _initialize(fixture, "2025-06-18")
    old = yield from _initialize(fixture, "2024-11-05")
    for client in (current, old):
        names = _names((yield from client.request("tools/list")))
        assert "audio" in names
        assert "resource-link" in names
    assert "error" in (yield from old.tool("audio"))
    assert "error" in (yield from old.tool("resource-link"))
    assert state.audio == 1
    assert state.resource_link == 1


@testing.effect
def test_rejects_invalid_structured_content_at_the_protocol_serialization_boundary():
    """McpServer protocol adapters / should reject invalid structured content at the protocol serialization boundary"""  # noqa: E501
    fixture = yield from _low_level()
    for name in ("invalid-structured-content", "invalid-nested-json"):
        response = yield from fixture.post(
            _modern_request(50, "tools/call", {"name": name, "arguments": {}}),
            {**_modern_headers("tools/call"), "Mcp-Name": name},
        )
        message = yield from read_message(response)
        assert response.status == 200, name
        assert message["error"]["code"] == MS.INTERNAL_ERROR_CODE, name


def test_rejects_a_tool_schema_when_input_schema_is_not_an_object():
    """McpServer protocol adapters / should reject a tool schema when inputSchema is not an object"""  # noqa: E501
    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(MS.TOOL)({"name": "invalid", "inputSchema": "anything"})


@pytest.mark.parametrize(
    "protocol",
    [P.v2024_11_05, P.v2025_03_26, P.v2025_06_18],
    ids=lambda p: p.protocol_version,
)
@testing.effect
def test_projects_canonical_notifications_when_encoding_each_protocol_revision(
    protocol: P.AnyProtocolAdapter,
):
    """McpServer protocol adapters / should project canonical notifications when encoding each protocol revision"""  # noqa: E501
    harness = yield from stdio_harness(protocol)
    yield from harness.initialize()
    yield from harness.send_request("ping", {})
    metadata = {"source": "test"}
    server = harness.server
    cases: list[tuple[NotificationMethod, Json, Json]] = [
        (
            "notifications/progress",
            {
                "_meta": metadata,
                "progressToken": "task-1",
                "progress": 1,
                "total": 2,
                "message": "half way",
            },
            {
                "_meta": metadata,
                "progressToken": "task-1",
                "progress": 1,
                "total": 2,
                **({} if protocol is P.v2024_11_05 else {"message": "half way"}),
            },
        ),
        (
            "notifications/cancelled",
            {"_meta": metadata, "requestId": 1, "reason": "done"},
            {"_meta": metadata, "requestId": 1, "reason": "done"},
        ),
        (
            "notifications/message",
            {"_meta": metadata, "level": "info", "logger": "test", "data": {"ready": True}},
            {"_meta": metadata, "level": "info", "logger": "test", "data": {"ready": True}},
        ),
        (
            "notifications/resources/list_changed",
            {"_meta": metadata},
            {"_meta": metadata},
        ),
        ("notifications/tools/list_changed", {"_meta": metadata}, {"_meta": metadata}),
        ("notifications/prompts/list_changed", {"_meta": metadata}, {"_meta": metadata}),
    ]
    for method, sent, expected in cases:
        yield from server.notify(method, sent)
        received = yield from harness.receive()
        assert received["method"] == method
        assert received["params"] == expected, method
    # A revision without it drops the notification; a ping shows nothing came before.
    client_id = next(iter(server._peers))  # pyright: ignore[reportPrivateUsage]
    yield from server.notify_elicitation_complete(client_id, "elicitation-1")
    pong = yield from harness.send_request("ping", {}, 99)
    assert pong["id"] == 99


@testing.effect
def test_projects_elicitation_complete_on_2025_11_25():
    """McpServer protocol adapters / should project canonical notifications when encoding each protocol revision (2025-11-25's elicitation complete)"""  # noqa: E501
    harness = yield from stdio_harness(P.v2025_11_25)
    yield from harness.initialize()
    yield from harness.send_request("ping", {})
    server = harness.server
    client_id = next(iter(server._peers))  # pyright: ignore[reportPrivateUsage]
    yield from server.notify_elicitation_complete(client_id, "elicitation-1")
    received = yield from harness.receive()
    assert received["method"] == "notifications/elicitation/complete"
    assert received["params"] == {"elicitationId": "elicitation-1"}
