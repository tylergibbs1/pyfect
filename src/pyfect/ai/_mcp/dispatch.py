"""One client's side of an MCP server: its session and the handling of
each JSON-RPC message it sends.

A ``Connection`` is a stdio process's client or an HTTP session.
``dispatch`` takes one parsed message and writes what it causes through
``out``: a request is served on its own fiber (so the client can answer
the server's requests meanwhile, or cancel it) and its response written
when done; a response to a server request completes the waiting call.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from typing import Any, Literal, Never, cast

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect.ai._mcp import projection
from pyfect.ai._mcp.core import McpServerService, RequestOutbound, RequestServices
from pyfect.ai.mcp_protocol import AnyProtocolAdapter, Registry
from pyfect.ai.mcp_schema import (
    CALL_TOOL_PARAMS,
    COMPLETE_PARAMS,
    CREATE_MESSAGE_RESULT,
    ELICIT_RESULT,
    GET_PROMPT,
    INITIALIZE_PARAMS,
    LIST_ROOTS_RESULT,
    LIST_TOOLS,
    METHOD_NOT_FOUND_ERROR_CODE,
    READ_RESOURCE,
    SET_LEVEL,
    SUBSCRIBE,
    UNSUPPORTED_PROTOCOL_VERSION_ERROR_CODE,
    CallToolParams,
    CallToolResult,
    ClientCapabilities,
    CreateMessageParams,
    CreateMessageResult,
    ElicitRequestFormParams,
    ElicitResult,
    Icon,
    Implementation,
    InternalError,
    InvalidParams,
    InvalidRequest,
    JsonObject,
    ListRootsResult,
    LoggingLevel,
    McpError,
    McpRequestContext,
    McpReverseOperationError,
    McpReverseOperationUnsupported,
    McpServerClient,
    ProtocolError,
    RequestContext,
    RequestId,
    ReverseClient,
    ReverseError,
    ReverseOperation,
    ServerCapabilities,
    ServerClient,
)
from pyfect.cause import Cause, Fail
from pyfect.deferred import Deferred
from pyfect.effect import fail, fail_cause, gen, provide_service, succeed, suspend, sync
from pyfect.exit import Success

type Wire = dict[str, Any]
"""A result as written."""

type Send = Callable[[JsonObject], Effect[None]]
"""Writes a message to the client."""

PROTOCOL_VERSION_META = "io.modelcontextprotocol/protocolVersion"
CLIENT_INFO_META = "io.modelcontextprotocol/clientInfo"
CLIENT_CAPABILITIES_META = "io.modelcontextprotocol/clientCapabilities"
SERVER_INFO_META = "io.modelcontextprotocol/serverInfo"

_LEVELS: tuple[LoggingLevel, ...] = (
    "debug",
    "info",
    "notice",
    "warning",
    "error",
    "critical",
    "alert",
    "emergency",
)
_VOID: Effect[None] = succeed(None)


@dataclass(frozen=True, slots=True, kw_only=True)
class ServerInfo:
    """How the server describes itself."""

    name: str
    version: str
    title: str | None = None
    description: str | None = None
    website_url: str | None = None
    icons: tuple[Icon, ...] = ()
    instructions: str | None = None
    extensions: Mapping[str, Any] | None = None

    def implementation(self) -> Implementation:
        info: Implementation = {"name": self.name, "version": self.version}
        if self.title is not None:
            info["title"] = self.title
        if self.description is not None:
            info["description"] = self.description
        if self.website_url is not None:
            info["websiteUrl"] = self.website_url
        if self.icons:
            info["icons"] = list(self.icons)
        return info


def response(id: RequestId | None, result: Mapping[str, Any]) -> JsonObject:
    return {"jsonrpc": "2.0", "id": id, "result": dict(result)}


def error_response(id: RequestId | None, error: McpError) -> JsonObject:
    return {"jsonrpc": "2.0", "id": id, "error": cast("Any", error.to_wire())}


def notification(method: str, params: JsonObject) -> JsonObject:
    return {"jsonrpc": "2.0", "method": method, "params": params}


def _is_request_id(value: object) -> bool:
    return isinstance(value, str) or (isinstance(value, int) and not isinstance(value, bool))


type Kind = Literal["request", "notification", "response", "invalid"]


@dataclass(frozen=True, slots=True)
class Classified:
    """What a parsed JSON value is, with the id to answer it with."""

    kind: Kind
    id: RequestId | None = None
    method: str = ""
    params: JsonObject = field(default_factory=dict[str, Any])
    body: JsonObject = field(default_factory=dict[str, Any])


def classify(message: object) -> Classified:  # noqa: PLR0911
    if not isinstance(message, dict):
        return Classified("invalid")
    body = cast("JsonObject", message)
    raw_id = body.get("id")
    id = cast("RequestId", raw_id) if _is_request_id(raw_id) else None
    if body.get("jsonrpc") != "2.0":
        return Classified("invalid", id)
    method = body.get("method")
    params = body.get("params", {})
    if isinstance(method, str):
        if params is not None and not isinstance(params, dict):
            return Classified("invalid", id, method)
        params_object: JsonObject = params or {}
        if "id" not in body:
            return Classified("notification", None, method, params_object)
        if id is None:
            return Classified("invalid", None, method)
        return Classified("request", id, method, params_object)
    if "method" not in body and ("result" in body or "error" in body):
        return Classified("response", id, body=body)
    return Classified("invalid", id)


def requested_protocol_version(params: Mapping[str, Any]) -> str | None:
    """The version a stateless request names in its ``_meta``."""
    meta = params.get("_meta")
    if not isinstance(meta, dict):
        return None
    version = cast("JsonObject", meta).get(PROTOCOL_VERSION_META)
    return version if isinstance(version, str) else None


def _decode(schema: S.Top, params: object) -> Effect[Any, InvalidParams]:
    decode = cast("Callable[[object], Effect[Any, S.SchemaError]]", S.decode_unknown_effect(schema))
    return decode(params).map_error(lambda error: InvalidParams(error.message))


def _method_not_found(method: str) -> McpError:
    return ProtocolError(f"Method not found: {method}", error_code=METHOD_NOT_FOUND_ERROR_CODE)


def _as_mcp_error(cause: Cause[object]) -> Effect[Wire, McpError]:
    """A request's failure as the error to answer with: its own MCP error,
    else an internal error. Interruption stays interruption."""
    if cause.has_interrupts_only:
        return fail_cause(cast("Cause[Never]", cause))
    found = cause.find_recoverable_error()
    if isinstance(found, Fail) and isinstance(found.error, McpError):
        return fail(found.error)
    return fail(InternalError("Internal error"))


@dataclass(frozen=True, slots=True)
class Identity:
    """Who sent a request: a session's client, fixed by ``initialize``, or
    a stateless request's own ``_meta``. Passed to each request rather
    than read from the connection, so one request cannot change another's."""

    capabilities: ClientCapabilities = field(default_factory=ClientCapabilities)
    info: Implementation | None = None


@dataclass(eq=False)
class Connection:
    """One client: a stdio process's or an HTTP session's."""

    server: McpServerService
    info: ServerInfo
    registry: Registry
    client_id: int
    transport: Literal["stdio", "http"]
    broadcast: Send
    protocol: AnyProtocolAdapter | None = None
    identity: Identity = field(default_factory=Identity)
    initialize_payload: JsonObject = field(default_factory=dict[str, Any])
    initialized: bool = False
    log_level: LoggingLevel | None = None
    subscriptions: set[str] = field(default_factory=set[str])
    _pending: dict[RequestId, Deferred[JsonObject]] = field(
        default_factory=dict[RequestId, "Deferred[JsonObject]"]
    )
    _inflight: dict[RequestId, Fiber[Any, Any]] = field(
        default_factory=dict[RequestId, "Fiber[Any, Any]"]
    )
    _reverse_ids: itertools.count[int] = field(default_factory=lambda: itertools.count(1))

    # --- messages ----------------------------------------------------------------------

    def dispatch(self, message: object, out: Send) -> Effect[None]:
        """Handle one message; a request is answered through ``out`` from
        its own fiber."""
        classified = classify(message)
        match classified.kind:
            case "request" if classified.method == "initialize":
                # Answered before the next message, which may rely on it.
                return self.answer(
                    cast("RequestId", classified.id), classified.method, classified.params, out
                ).flat_map(lambda reply: _VOID if reply is None else out(reply))
            case "request":
                return self.start(classified, out).as_void()
            case "notification":
                return self._notified(classified.method, classified.params)
            case "response":
                return self._answered(classified.body)
            case "invalid":
                return out(error_response(classified.id, InvalidRequest("Invalid Request")))

    @property
    def busy(self) -> bool:
        """Whether a request is still being served."""
        return bool(self._inflight)

    def close(self) -> Effect[None]:
        """Interrupt the requests still being served."""

        @gen
        def run():
            for fiber in list(self._inflight.values()):
                yield from fiber.interrupt()

        return run

    def drain(self) -> Effect[None]:
        """Wait for the requests still being served."""

        @gen
        def run():
            while self._inflight:
                yield from next(iter(self._inflight.values())).await_exit()

        return run

    def start(self, request: Classified, out: Send) -> Effect[Fiber[None, Never]]:
        """Serve ``request`` on its own fiber, which ends once its response
        is written or it is cancelled (writing nothing)."""
        id = cast("RequestId", request.id)

        def done() -> None:
            self._inflight.pop(id, None)

        served = (
            self.answer(id, request.method, request.params, out)
            .flat_map(lambda reply: _VOID if reply is None else out(reply))
            .ensuring(sync(done))
        )

        def track(fiber: Fiber[None, Never]) -> Fiber[None, Never]:
            self._inflight[id] = fiber
            return fiber

        return served.fork_daemon().map(track)

    def answer(
        self, id: RequestId, method: str, params: JsonObject, out: Send
    ) -> Effect[JsonObject | None]:
        """The response to a request (``None`` when it was cancelled)."""
        version = requested_protocol_version(params)
        stateless = self.registry.find(version) if version is not None else None
        if stateless is not None and stateless.is_stateless:
            answered = self._stateless(stateless, method, params, out)
        elif version is not None and stateless is None and _offers_stateless(self.registry):
            answered = fail(_unsupported_version(version, self.registry))
        else:
            answered = self._stateful(method, params, out)
        replied: Effect[JsonObject] = answered.catch_cause(_as_mcp_error).match(
            on_failure=lambda error: error_response(id, error),
            on_success=lambda result: response(id, result),
        )
        return replied.exit().map(lambda exit: exit.value if isinstance(exit, Success) else None)

    def _notified(self, method: str, params: JsonObject) -> Effect[None]:
        if method == "notifications/initialized" and self.protocol is not None:
            return sync(lambda: setattr(self, "initialized", True))
        if method == "notifications/cancelled":
            request_id = params.get("requestId")
            fiber = self._inflight.get(cast("RequestId", request_id))
            if fiber is not None:
                return sync(lambda: fiber.interrupt_as_unsafe(None))
        return _VOID

    def _answered(self, body: JsonObject) -> Effect[None]:
        raw_id = body.get("id")
        deferred = self._pending.get(cast("RequestId", raw_id)) if _is_request_id(raw_id) else None
        return _VOID if deferred is None else deferred.succeed(body).as_void()

    # --- notifications -----------------------------------------------------------------

    def wants(self, method: str, params: Mapping[str, Any]) -> bool:
        if method == "notifications/message":
            level = params.get("level")
            minimum = self.log_level
            return (
                minimum is None
                or level not in _LEVELS
                or _LEVELS.index(level) >= _LEVELS.index(minimum)
            )
        if method == "notifications/resources/updated":
            return params.get("uri") in self.subscriptions
        if method == "notifications/elicitation/complete":
            return self.protocol is not None and self.protocol.supports_icons
        return True

    def deliver(self, method: str, params: JsonObject) -> Effect[None]:
        """A broadcast notification, sent once the client is initialized
        and if it wants it (``Peer``)."""
        if not self.initialized or not self.wants(method, params):
            return _VOID
        return self.broadcast(notification(method, params))

    def _request_outbound(self, out: Send) -> Callable[[str, JsonObject], Effect[None]]:
        def deliver(method: str, params: JsonObject) -> Effect[None]:
            return out(notification(method, params)) if self.wants(method, params) else _VOID

        return deliver

    # --- requests to the client --------------------------------------------------------

    def _reverse_request(
        self, operation: ReverseOperation, params: Mapping[str, Any], out: Send
    ) -> Effect[JsonObject, ReverseError]:
        id = f"server-{self.client_id}-{next(self._reverse_ids)}"
        deferred = Deferred[JsonObject]()
        message: JsonObject = {
            "jsonrpc": "2.0",
            "id": id,
            "method": operation,
            "params": dict(params),
        }

        def answer(reply: JsonObject) -> Effect[JsonObject, ReverseError]:
            error = reply.get("error")
            if isinstance(error, dict):
                return fail(McpReverseOperationError(operation, error))
            result = reply.get("result")
            return succeed(result if isinstance(result, dict) else {})

        return (
            sync(lambda: self._pending.__setitem__(id, deferred))
            .and_then(out(message))
            .and_then(deferred.wait())
            .flat_map(answer)
            .ensuring(sync(lambda: self._pending.pop(id, None)))
        )

    def _reverse_client(
        self, protocol: AnyProtocolAdapter, identity: Identity, out: Send
    ) -> ReverseClient:
        version = protocol.protocol_version

        def refused(
            operation: ReverseOperation, capability: Literal["roots", "sampling", "elicitation"]
        ) -> McpReverseOperationUnsupported | None:
            def unsupported(reason: str) -> McpReverseOperationUnsupported:
                return McpReverseOperationUnsupported(operation, version, reason)

            if protocol.is_stateless:
                return unsupported(f"MCP {version} has no server-to-client requests")
            if capability == "elicitation" and not protocol.supports_structured_content:
                return unsupported(f"MCP {version} has no elicitation")
            if identity.capabilities.get(capability) is None:
                return unsupported(f"Client did not advertise the {capability} capability")
            return None

        def request[A](
            operation: ReverseOperation,
            capability: Literal["roots", "sampling", "elicitation"],
            params: Mapping[str, Any],
            result: S.Codec[A, Any],
        ) -> Effect[A, ReverseError]:
            """The client's answer, decoded with ``result`` (a malformed one
            is an ``McpReverseOperationError``, never taken as is)."""
            error = refused(operation, capability)
            if error is not None:
                return fail(error)
            decode = cast(
                "Callable[[object], Effect[A, S.SchemaError]]", S.decode_unknown_effect(result)
            )
            return self._reverse_request(operation, params, out).flat_map(
                lambda reply: decode(reply).map_error(
                    lambda invalid: McpReverseOperationError(operation, invalid)
                )
            )

        def list_roots() -> Effect[ListRootsResult, ReverseError]:
            return request("roots/list", "roots", {}, LIST_ROOTS_RESULT)

        def create_message(
            params: CreateMessageParams,
        ) -> Effect[CreateMessageResult, ReverseError]:
            return request("sampling/createMessage", "sampling", params, CREATE_MESSAGE_RESULT)

        def elicit(params: ElicitRequestFormParams) -> Effect[ElicitResult, ReverseError]:
            return request("elicitation/create", "elicitation", params, ELICIT_RESULT)

        return ReverseClient(list_roots, create_message, elicit)

    # --- serving -----------------------------------------------------------------------

    def _serve(
        self,
        protocol: AnyProtocolAdapter,
        identity: Identity,
        params: JsonObject,
        out: Send,
        handler: Callable[[RequestContext], Effect[Wire, McpError, RequestServices]],
    ) -> Effect[Wire, McpError]:
        """``handler`` given the request's services."""
        meta = params.get("_meta")
        metadata: JsonObject = meta if isinstance(meta, dict) else {}
        version = protocol.protocol_version
        context = RequestContext(
            self.client_id, version, identity.capabilities, identity.info, metadata
        )
        client = ServerClient(
            self.client_id,
            version,
            identity.capabilities,
            identity.info,
            self.initialize_payload,
            succeed(self._reverse_client(protocol, identity, out)),
            metadata,
        )
        return (
            suspend(lambda: handler(context))
            .pipe(provide_service(McpRequestContext, context))
            .pipe(provide_service(McpServerClient, client))
            .pipe(provide_service(RequestOutbound, self._request_outbound(out)))
        )

    def _stateful(self, method: str, params: JsonObject, out: Send) -> Effect[Wire, McpError]:
        if method == "ping":
            return succeed({})
        if method == "initialize":
            return self._initialize(params)
        protocol = self.protocol
        if protocol is None:
            return fail(InvalidRequest("Server not initialized"))
        return self._feature(protocol, self.identity, method, params, out)

    def _initialize(self, params: JsonObject) -> Effect[Wire, McpError]:
        offered = params.get("protocolVersion")
        protocol = self.registry.select_stateful(offered if isinstance(offered, str) else None)
        if protocol is None:
            return fail(_method_not_found("initialize"))

        def start(payload: Any) -> Wire:
            self.protocol = protocol
            self.identity = Identity(payload["capabilities"], payload["clientInfo"])
            self.initialize_payload = dict(params)
            result: Wire = {
                "protocolVersion": protocol.protocol_version,
                "capabilities": cast("Any", self.capabilities_for(protocol)),
                "serverInfo": projection.implementation(protocol, self.info.implementation()),
            }
            if self.info.instructions is not None:
                result["instructions"] = self.info.instructions
            return result

        return _decode(INITIALIZE_PARAMS, params).map(start)

    def capabilities_for(self, protocol: AnyProtocolAdapter) -> ServerCapabilities:
        tools, resources, prompts = self.server.has_registrations
        stateless = protocol.is_stateless
        capabilities: ServerCapabilities = {"logging": {}}
        if protocol.supports_audio:
            capabilities["completions"] = {}
        if self.info.extensions is not None:
            capabilities["extensions"] = dict(self.info.extensions)
        if prompts:
            capabilities["prompts"] = {"listChanged": not stateless}
        if resources:
            subscribe = self.transport == "stdio" and not stateless
            capabilities["resources"] = {"listChanged": not stateless, "subscribe": subscribe}
        if tools:
            capabilities["tools"] = {"listChanged": not stateless}
        return capabilities

    def _feature(  # noqa: PLR0911
        self,
        protocol: AnyProtocolAdapter,
        identity: Identity,
        method: str,
        params: JsonObject,
        out: Send,
    ) -> Effect[Wire, McpError]:
        server = self.server

        def serve(
            handler: Callable[[RequestContext], Effect[Wire, McpError, RequestServices]],
        ) -> Effect[Wire, McpError]:
            return self._serve(protocol, identity, params, out, handler)

        def listed(
            key: str, items: Callable[[RequestContext], list[Any]]
        ) -> Effect[Wire, McpError]:
            return serve(lambda c: succeed({key: items(c)}))

        match method:
            case "logging/setLevel":
                return _decode(SET_LEVEL.payload_schema, params).map(self._set_level)
            case "resources/subscribe" | "resources/unsubscribe" if self.transport == "stdio":
                subscribe = method == "resources/subscribe"
                return _decode(SUBSCRIBE.payload_schema, params).map(
                    lambda decoded: self._subscribe(decoded["uri"], subscribe)
                )
            case "tools/list":
                return _decode(LIST_TOOLS.payload_schema, params).and_then(
                    listed(
                        "tools",
                        lambda c: [projection.tool(protocol, t) for t in server.list_tools(c)],
                    )
                )
            case "tools/call":
                return _decode(CALL_TOOL_PARAMS, params).flat_map(
                    lambda call: serve(lambda c: _call_tool(server, protocol, call, c))
                )
            case "resources/list":
                return listed(
                    "resources",
                    lambda c: [projection.resource(protocol, r) for r in server.list_resources(c)],
                )
            case "resources/templates/list":
                return listed(
                    "resourceTemplates",
                    lambda c: [
                        projection.resource_template(protocol, t)
                        for t in server.list_resource_templates(c)
                    ],
                )
            case "resources/read":
                return _decode(READ_RESOURCE.payload_schema, params).flat_map(
                    lambda decoded: serve(lambda c: self._read(protocol, decoded["uri"], c))
                )
            case "prompts/list":
                return listed(
                    "prompts",
                    lambda c: [projection.prompt(protocol, p) for p in server.list_prompts(c)],
                )
            case "prompts/get":
                return _decode(GET_PROMPT.payload_schema, params).flat_map(
                    lambda decoded: serve(
                        lambda c: server.get_prompt_for(
                            decoded["name"], decoded.get("arguments") or {}, c
                        ).map(lambda result: projection.get_prompt_result(protocol, result))
                    )
                )
            case "completion/complete":
                return _decode(COMPLETE_PARAMS, params).flat_map(
                    lambda decoded: serve(lambda _: server.complete_for(decoded).map(_wire))
                )
            case _:
                return fail(_method_not_found(method))

    def _set_level(self, decoded: Any) -> JsonObject:
        self.log_level = decoded["level"]
        return {}

    def _subscribe(self, uri: str, subscribe: bool) -> JsonObject:
        if subscribe:
            self.subscriptions.add(uri)
        else:
            self.subscriptions.discard(uri)
        return {}

    def _read(
        self, protocol: AnyProtocolAdapter, uri: str, context: RequestContext
    ) -> Effect[Wire, McpError, RequestServices]:
        found = self.server.read_resource_for(uri, context)
        if found is None:
            return fail(
                ProtocolError(
                    f"Resource '{uri}' not found",
                    {"uri": uri},
                    error_code=protocol.resource_not_found_code,
                )
            )
        return found.map(_wire)

    # --- 2026-07-28 ----------------------------------------------------------------------

    def _stateless(
        self, protocol: AnyProtocolAdapter, method: str, params: JsonObject, out: Send
    ) -> Effect[Wire, McpError]:
        meta = cast("JsonObject", params.get("_meta") or {})
        capabilities = meta.get(CLIENT_CAPABILITIES_META)
        info = meta.get(CLIENT_INFO_META)
        identity = Identity(
            cast("ClientCapabilities", capabilities if isinstance(capabilities, dict) else {}),
            cast("Implementation", info) if isinstance(info, dict) else None,
        )
        server_info = projection.implementation(protocol, self.info.implementation())

        def complete(result: JsonObject, cacheable: bool) -> JsonObject:
            own = result.get("_meta")
            merged: JsonObject = {**(own if isinstance(own, dict) else {})}
            merged[SERVER_INFO_META] = cast("Any", server_info)
            completed: JsonObject = {**result, "_meta": merged, "resultType": "complete"}
            if cacheable:
                completed["ttlMs"] = 0
                completed["cacheScope"] = "private"
            return completed

        if method == "server/discover":
            discovery: JsonObject = {
                "supportedVersions": list(self.registry.versions),
                "capabilities": cast("Any", self.capabilities_for(protocol)),
            }
            if self.info.instructions is not None:
                discovery["instructions"] = self.info.instructions
            return succeed(complete(discovery, True))
        if method in ("ping", "initialize", "logging/setLevel", "resources/subscribe"):
            return fail(_method_not_found(method))
        cacheable = method in _CACHEABLE
        return self._feature(protocol, identity, method, params, out).map(
            lambda result: complete(result, cacheable)
        )


_CACHEABLE = frozenset(
    {"tools/list", "prompts/list", "resources/list", "resources/templates/list", "resources/read"}
)
"""The 2026-07-28 results carrying ``ttlMs`` and ``cacheScope`` (with
``server/discover``)."""


def _call_tool(
    server: McpServerService,
    protocol: AnyProtocolAdapter,
    call: CallToolParams,
    context: RequestContext,
) -> Effect[Wire, McpError, RequestServices]:
    """A tool's result on ``protocol`` 's wire. An unknown tool is always a
    protocol error; the tool's own failures are ``isError`` results when the
    revision reports them so (Effect's per-revision ``tools/call``)."""
    name = call["name"]
    if server.find_tool(name, context) is None:
        return fail(InvalidParams(f"Tool '{name}' not found"))
    called = server.call_tool_for(call, context)
    if protocol.reports_tool_errors_as_results:
        called = called.catch_all(
            lambda error: succeed(
                cast(
                    "CallToolResult",
                    {"isError": True, "content": [{"type": "text", "text": str(error)}]},
                )
            )
        )
    return called.map(lambda result: projection.call_tool_result(protocol, result))


def _wire(value: Mapping[str, Any]) -> Wire:
    return dict(value)


def _offers_stateless(registry: Registry) -> bool:
    return any(p.is_stateless for p in registry.protocols)


def _unsupported_version(requested: str, registry: Registry) -> McpError:
    return ProtocolError(
        "Unsupported protocol version",
        {"requested": requested, "supported": list(registry.versions)},
        error_code=UNSUPPORTED_PROTOCOL_VERSION_ERROR_CODE,
    )
