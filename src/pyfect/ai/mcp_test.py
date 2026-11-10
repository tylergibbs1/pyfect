"""An in-memory MCP client of a server, for tests (Effect's ``McpTest``).

``make_client`` builds the server with ``registrations``, connects a client
to it through JSON-RPC messages, as a transport would, and performs the
handshake: ``initialize`` and ``notifications/initialized`` for a revision
with sessions, the request ``_meta`` on every request for 2026-07-28::

    client = yield from mcp_test.make_client(
        mcp_server.resource(uri="test://greeting", name="greeting", content=fx.succeed("hello")),
        protocols=(mcp_protocol.v2025_11_25,),
    )
    result = yield from client.read_resource({"uri": "test://greeting"})

Requests go through the server's routing, middleware and response encoding,
so results and errors are what a wire client gets. A request answered with an
error fails with an ``McpError`` of its code, message and data. The server's
notifications are queued on ``notifications`` in delivery order; its requests
to the client (elicitation, sampling, roots) are answered with method not
found. Client and server live in the surrounding ``Scope``.
"""

from __future__ import annotations

import itertools
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Never, cast

from pyfect._core import Effect
from pyfect._js import or_default
from pyfect._layer_core import require_layer
from pyfect.ai import mcp_server
from pyfect.ai._mcp.core import McpServer, McpServerService
from pyfect.ai._mcp.dispatch import (
    CLIENT_CAPABILITIES_META,
    CLIENT_INFO_META,
    PROTOCOL_VERSION_META,
    Connection,
    ServerInfo,
    error_response,
    notification,
)
from pyfect.ai.mcp_protocol import AnyProtocolAdapter, make_registry
from pyfect.ai.mcp_schema import (
    INTERNAL_ERROR_CODE,
    INVALID_PARAMS_ERROR_CODE,
    INVALID_REQUEST_ERROR_CODE,
    METHOD_NOT_FOUND_ERROR_CODE,
    PARSE_ERROR_CODE,
    CallToolParams,
    CallToolResult,
    ClientCapabilities,
    CompleteParams,
    CompleteResult,
    GetPromptResult,
    Implementation,
    InternalError,
    InvalidParams,
    InvalidRequest,
    JsonObject,
    JsonValue,
    ListPromptsResult,
    ListResourcesResult,
    ListResourceTemplatesResult,
    ListToolsResult,
    McpError,
    McpServerClient,
    MethodNotFound,
    ParseError,
    ProtocolError,
    ReadResourceResult,
)
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.effect import fail, gen, succeed, suspend, sync
from pyfect.errors import IllegalArgumentError
from pyfect.layer import Layer, provide_merge
from pyfect.logger import CurrentLogLevel
from pyfect.queue import Dequeue, Queue
from pyfect.scope import Scope, acquire_release

DEFAULT_CLIENT_INFO: Implementation = {"name": "McpTest", "version": "1.0.0"}

_ERRORS: Mapping[int, type[McpError]] = {
    PARSE_ERROR_CODE: ParseError,
    INVALID_REQUEST_ERROR_CODE: InvalidRequest,
    METHOD_NOT_FOUND_ERROR_CODE: MethodNotFound,
    INVALID_PARAMS_ERROR_CODE: InvalidParams,
    INTERNAL_ERROR_CODE: InternalError,
}


def _error_of(wire: Mapping[str, Any]) -> McpError:
    code = cast("int", wire.get("code"))
    message = cast("str", wire.get("message", ""))
    data = cast("JsonValue", wire.get("data"))
    known = _ERRORS.get(code)
    return ProtocolError(message, data, error_code=code) if known is None else known(message, data)


@dataclass(frozen=True, slots=True)
class Notification:
    """A notification the server sent the client, as written."""

    method: str
    payload: JsonObject


@dataclass(eq=False)
class McpTestClient:
    """A client connected to an in-memory server (Effect's ``McpTest.Client``)."""

    protocol_version: str
    """The protocol the handshake chose."""
    server: McpServerService
    """The server, to register with or send notifications from a test."""
    _notifications: Queue[Notification, Never]
    _connection: Connection
    _metadata: JsonObject | None
    _pending: dict[int, Deferred[JsonObject]] = field(default_factory=dict[int, Any])
    _ids: itertools.count[int] = field(default_factory=lambda: itertools.count(2))

    @property
    def notifications(self) -> Dequeue[Notification, Never]:
        """What the server sent this client, in delivery order."""
        return self._notifications

    def _receive(self, message: JsonObject) -> Effect[None]:
        """A message the server wrote."""
        return suspend(lambda: self._received(message))

    def _received(self, message: JsonObject) -> Effect[None]:
        method = message.get("method")
        id = message.get("id")
        if isinstance(method, str) and id is not None:
            # A request to the client: refused, as the client offers none.
            refused = MethodNotFound(f"Method not found: {method}")
            return self._connection.dispatch(
                error_response(cast("Any", id), refused), self._receive
            )
        if isinstance(method, str):
            payload = cast("JsonObject", message.get("params") or {})
            return self._notifications.offer(Notification(method, payload)).as_void()
        waiting = self._pending.pop(cast("int", id), None)
        return succeed(None) if waiting is None else waiting.succeed(message).as_void()

    def request(
        self, method: str, params: Mapping[str, Any] | None = None
    ) -> Effect[JsonObject, McpError]:
        """Send a request; its result, or its error as an ``McpError``."""

        @gen
        def run():
            id = next(self._ids)
            reply = Deferred[JsonObject]()
            self._pending[id] = reply
            body: JsonObject = dict(params or {})
            if self._metadata is not None:
                own = cast("JsonObject", body.get("_meta") or {})
                body["_meta"] = {**self._metadata, **own}
            message: JsonObject = {"jsonrpc": "2.0", "id": id, "method": method, "params": body}
            yield from self._connection.dispatch(message, self._receive)
            answer = yield from reply.wait()
            error = answer.get("error")
            if isinstance(error, dict):
                return (yield from fail(_error_of(cast("Mapping[str, Any]", error))))
            return cast("JsonObject", answer.get("result") or {})

        return run

    @property
    def ping(self) -> Effect[None, McpError]:
        return self.request("ping").as_void()

    def list_tools(self, params: JsonObject | None = None) -> Effect[ListToolsResult, McpError]:
        return cast("Any", self.request("tools/list", params))

    def call_tool(self, params: CallToolParams) -> Effect[CallToolResult, McpError]:
        return cast("Any", self.request("tools/call", params))

    def list_resources(
        self, params: JsonObject | None = None
    ) -> Effect[ListResourcesResult, McpError]:
        return cast("Any", self.request("resources/list", params))

    def list_resource_templates(
        self, params: JsonObject | None = None
    ) -> Effect[ListResourceTemplatesResult, McpError]:
        return cast("Any", self.request("resources/templates/list", params))

    def read_resource(self, params: Mapping[str, Any]) -> Effect[ReadResourceResult, McpError]:
        return cast("Any", self.request("resources/read", params))

    def subscribe(self, params: Mapping[str, Any]) -> Effect[None, McpError]:
        return self.request("resources/subscribe", params).as_void()

    def unsubscribe(self, params: Mapping[str, Any]) -> Effect[None, McpError]:
        return self.request("resources/unsubscribe", params).as_void()

    def list_prompts(self, params: JsonObject | None = None) -> Effect[ListPromptsResult, McpError]:
        return cast("Any", self.request("prompts/list", params))

    def get_prompt(self, params: Mapping[str, Any]) -> Effect[GetPromptResult, McpError]:
        return cast("Any", self.request("prompts/get", params))

    def complete(self, params: CompleteParams) -> Effect[CompleteResult, McpError]:
        return cast("Any", self.request("completion/complete", params))

    def set_level(self, params: Mapping[str, Any]) -> Effect[None, McpError]:
        return self.request("logging/setLevel", params).as_void()


def make_client[RE = Never, RR = Never](
    registrations: Layer[Any, RE, RR | McpServer | McpServerClient],
    *,
    protocols: Sequence[AnyProtocolAdapter],
    protocol_version: str | None = None,
    name: str = "McpTest",
    version: str = "1.0.0",
    instructions: str | None = None,
    extensions: Mapping[str, Any] | None = None,
    client_info: Implementation | None = None,
    client_capabilities: ClientCapabilities | None = None,
) -> Effect[McpTestClient, IllegalArgumentError | RE, RR | Scope]:
    """A client of a server built with ``registrations`` (``mcp_server.layer``
    and the transports' ``registrations``), speaking ``protocol_version``,
    by default the first of ``protocols``."""
    require_layer(registrations, "registrations")
    selected = (
        protocols[0]
        if protocol_version is None
        else next((p for p in protocols if p.protocol_version == protocol_version), None)
    )
    info: Implementation = or_default(client_info, DEFAULT_CLIENT_INFO)
    capabilities: ClientCapabilities = or_default(client_capabilities, {})

    @gen
    def run():
        if selected is None:
            return (
                yield from fail(
                    IllegalArgumentError(
                        f"MCP protocol {protocol_version} is not in the configured protocols"
                    )
                )
            )
        registry = yield from make_registry(protocols)
        # ``McpServerClient`` is provided per request, not to the build.
        registering: Layer[Any, Any, Any] = registrations
        built: Context[Any] = yield from registering.pipe(provide_merge(mcp_server.layer)).build()
        server = built.get_unsafe(McpServer)
        level = yield from CurrentLogLevel()
        queue = Queue[Notification, Never]()
        metadata: JsonObject | None = None
        if selected.is_stateless:
            metadata = {
                PROTOCOL_VERSION_META: selected.protocol_version,
                CLIENT_CAPABILITIES_META: cast("Any", capabilities),
                CLIENT_INFO_META: cast("Any", info),
            }
        client: McpTestClient

        def broadcast(message: JsonObject) -> Effect[None]:
            return client._receive(message)  # pyright: ignore[reportPrivateUsage]

        connection = Connection(
            server,
            ServerInfo(
                name=name, version=version, instructions=instructions, extensions=extensions
            ),
            registry,
            server.next_client_id(),
            "stdio",
            broadcast=broadcast,
            default_log_level=level,
        )
        client = McpTestClient(selected.protocol_version, server, queue, connection, metadata)
        yield from acquire_release(
            sync(lambda: server.connect(connection)),
            lambda _, __: sync(lambda: server.disconnect(connection.client_id)).and_then(
                connection.close()
            ),
        )
        if not selected.is_stateless:
            yield from client.request(
                "initialize",
                {
                    "protocolVersion": selected.protocol_version,
                    "capabilities": cast("Any", capabilities),
                    "clientInfo": cast("Any", info),
                },
            ).or_die()
            yield from connection.dispatch(notification("notifications/initialized", {}), broadcast)
        return client

    return cast("Any", run)


__all__ = [
    "DEFAULT_CLIENT_INFO",
    "IllegalArgumentError",
    "McpError",
    "McpTestClient",
    "Notification",
    "make_client",
]
