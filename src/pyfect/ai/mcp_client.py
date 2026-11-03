"""An MCP client (Effect's ``McpClient``): call the tools, prompts and
resources of an MCP server over stdio or Streamable HTTP.

The client speaks one revision, ``mcp_protocol.v2025_11_25`` (initialize
and a session) or ``mcp_protocol.v2026_07_28`` (stateless); ``make``
negotiates it within ``timeout`` (60 seconds by default)::

    client = yield from mcp_client.make(name="app", version="1.0.0")
    tools = yield from client.list_tools()
    result = yield from client.call_tool(tools[0], {"query": "pyfect"})

``layer_stdio`` runs the server as a child process and ``layer_http``
reaches one at a URL; ``toolkit`` turns the server's tools into a
``Toolkit`` a language model can call. Every failure is an
``McpClientError`` with its ``reason``.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Literal, Never, TypedDict, cast, overload

from pyfect import schema as S
from pyfect._core import Effect
from pyfect.ai import tool as Tool
from pyfect.ai import toolkit as Toolkit
from pyfect.ai._mcp.client_transport import (
    ClientProtocol,
    ClientProtocolVersion,
    TransportService,
)
from pyfect.ai._mcp.client_transport import http as _http
from pyfect.ai._mcp.client_transport import stdio as _stdio
from pyfect.ai._mcp.client_wire import failure, limit_error, requires_tasks, to_text
from pyfect.ai._mcp.projection import WRAP_RESULT
from pyfect.ai.mcp_client_error import (
    ClosedError,
    ConfigurationError,
    HttpError,
    McpClientError,
    ProtocolError,
    TimeoutError,
    ToolError,
    UnsupportedError,
    ValidationError,
)
from pyfect.ai.mcp_schema import (
    CALL_TOOL_RESULT,
    GET_PROMPT_RESULT,
    IMPLEMENTATION,
    LIST_PROMPTS,
    LIST_RESOURCES,
    LIST_TOOLS,
    READ_RESOURCE_RESULT,
    SERVER_CAPABILITIES,
    UNSUPPORTED_PROTOCOL_VERSION_ERROR_CODE,
    CallToolResult,
    GetPromptResult,
    Icon,
    Implementation,
    JsonObject,
    Prompt,
    ReadResourceResult,
    Resource,
    ServerCapabilities,
)
from pyfect.ai.mcp_schema import Tool as McpTool
from pyfect.context import Context, Tag
from pyfect.deferred import Deferred
from pyfect.duration import Duration, Seconds, to_seconds
from pyfect.effect import fail, gen, provide_context, succeed, suspend
from pyfect.http.client import HttpClient
from pyfect.layer import Layer, provide
from pyfect.layer import effect as layer_effect
from pyfect.process import ChildProcessSpawner, Command
from pyfect.scope import Scope, add_finalizer

DEFAULT_TIMEOUT = Seconds(60)
MAX_DISCOVERY_PAGES = 100
MAX_DISCOVERY_ITEMS = 10_000

_MODEL_TOOL_NAME = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
_SERVER_INFO_META = "io.modelcontextprotocol/serverInfo"


class _CacheableResult(TypedDict):
    resultType: Literal["complete"]
    ttlMs: int
    cacheScope: Literal["public", "private"]


_CACHEABLE_RESULT = S.Struct(_CacheableResult, ttlMs=S.Int.check(S.is_greater_than_or_equal_to(0)))
"""What a 2026-07-28 list result has besides its items."""


class Transport(Tag[TransportService], key="effect/ai/McpClient/Transport"):
    """How the client reaches its server (``stdio`` or ``http``)."""


def _decode(schema: S.Top, value: object) -> Effect[Any, McpClientError]:
    decode = cast("Callable[[object], Effect[Any, S.SchemaError]]", S.decode_unknown_effect(schema))
    return decode(value).map_error(
        lambda cause: failure(ValidationError("Invalid MCP payload", cause))
    )


@dataclass(frozen=True, slots=True, eq=False)
class McpClientService:
    """A connected client (Effect's ``McpClient``)."""

    protocol_version: ClientProtocolVersion
    server_info: Implementation | None
    instructions: str | None
    capabilities: ServerCapabilities
    _request: Callable[[str, JsonObject, McpTool | None], Effect[Any, McpClientError]] = field(
        repr=False
    )
    _deadline: Callable[
        [Effect[Any, McpClientError], str, Seconds | None], Effect[Any, McpClientError]
    ] = field(repr=False)
    _is_callable: Callable[[McpTool], bool] = field(repr=False)
    _timeout: Seconds = field(repr=False)

    def _call(
        self, kind: str, method: str, params: JsonObject, tool: McpTool | None = None
    ) -> Effect[Any, McpClientError]:
        if self.capabilities.get(kind) is None:
            return fail(failure(UnsupportedError(f"Server does not advertise {kind}")))
        return self._request(method, params, tool)

    def _check_cacheable(self, raw: object) -> Effect[None, McpClientError]:
        """A 2026-07-28 list or read result's cache fields."""
        if self.protocol_version != "2026-07-28":
            return succeed(None)
        return _decode(_CACHEABLE_RESULT, raw).as_void()

    def _list(
        self, kind: str, schema: S.Top, timeout: Duration | None
    ) -> Effect[list[Any], McpClientError]:
        @gen
        def run():
            items: list[Any] = []
            if self.capabilities.get(kind) is None:
                return items
            cursors: set[str] = set()
            cursor: str | None = None
            for _ in range(MAX_DISCOVERY_PAGES):
                params: JsonObject = {} if cursor is None else {"cursor": cursor}
                raw: dict[str, Any] = yield from self._request(f"{kind}/list", params, None)
                listed = raw.get(kind)
                if isinstance(listed, list) and len(items) + len(cast("list[Any]", listed)) > (
                    MAX_DISCOVERY_ITEMS
                ):
                    return (
                        yield from fail(
                            limit_error(f"MCP {kind} discovery exceeded its item limit")
                        )
                    )
                yield from self._check_cacheable(raw)
                result: dict[str, Any] = yield from _decode(schema, raw)
                page: list[Any] = result[kind]
                items.extend(page)
                next_cursor: str | None = result.get("nextCursor")
                if next_cursor is None:
                    return items
                if next_cursor in cursors:
                    return (yield from fail(limit_error(f"MCP {kind} discovery repeated a cursor")))
                cursors.add(next_cursor)
                cursor = next_cursor
            return (yield from fail(limit_error(f"MCP {kind} discovery exceeded its page limit")))

        deadline = self._timeout if timeout is None else to_seconds(timeout)
        return self._deadline(run, f"{kind} discovery", deadline)

    def list_tools(
        self, *, timeout: Duration | None = None
    ) -> Effect[list[McpTool], McpClientError]:
        """Every tool the server lists (and this transport can call)."""
        return self._list("tools", LIST_TOOLS.success_schema, timeout).map(
            lambda tools: [t for t in tools if self._is_callable(t)]
        )

    def list_prompts(
        self, *, timeout: Duration | None = None
    ) -> Effect[list[Prompt], McpClientError]:
        return self._list("prompts", LIST_PROMPTS.success_schema, timeout)

    def list_resources(
        self, *, timeout: Duration | None = None
    ) -> Effect[list[Resource], McpClientError]:
        return self._list("resources", LIST_RESOURCES.success_schema, timeout)

    def get_prompt(
        self,
        prompt: Prompt,
        arguments: Mapping[str, str] | None = None,
        *,
        timeout: Duration | None = None,
    ) -> Effect[GetPromptResult, McpClientError]:
        params: JsonObject = {"name": prompt["name"]}
        if arguments is not None:
            params["arguments"] = dict(arguments)
        got = self._call("prompts", "prompts/get", params).flat_map(
            lambda raw: _decode(GET_PROMPT_RESULT, raw)
        )
        return self._deadline(got, "prompts/get", _optional_seconds(timeout))

    def read_resource(
        self, uri: str, *, timeout: Duration | None = None
    ) -> Effect[ReadResourceResult, McpClientError]:
        read = (
            self._call("resources", "resources/read", {"uri": uri})
            .tap(self._check_cacheable)
            .flat_map(lambda raw: _decode(READ_RESOURCE_RESULT, raw))
        )
        return self._deadline(read, "resources/read", _optional_seconds(timeout))

    @overload
    def call_tool(
        self,
        tool: McpTool,
        arguments: Mapping[str, Any] | None = None,
        *,
        timeout: Duration | None = None,
    ) -> Effect[CallToolResult, McpClientError]: ...
    @overload
    def call_tool[A, R](
        self,
        tool: McpTool,
        arguments: Mapping[str, Any] | None = None,
        *,
        schema: S.Codec[A, Any, R, Any],
        timeout: Duration | None = None,
    ) -> Effect[A, McpClientError, R]: ...
    def call_tool(
        self,
        tool: McpTool,
        arguments: Mapping[str, Any] | None = None,
        *,
        schema: S.Codec[Any, Any, Any, Any] | None = None,
        timeout: Duration | None = None,
    ) -> Effect[Any, McpClientError, Any]:
        """Call ``tool``. With ``schema``, its ``structuredContent`` decoded
        (unwrapped from ``{"result": ...}`` when ``tool``'s output schema has
        ``x-fastmcp-wrap-result``; a tool error then fails with
        ``ToolError``); else the whole result. Unbounded unless given a
        ``timeout``."""
        params: JsonObject = {"name": tool["name"]}
        if arguments is not None:
            params["arguments"] = dict(arguments)

        def typed(result: CallToolResult) -> Effect[Any, McpClientError, Any]:
            if schema is None:
                return succeed(result)
            if result.get("isError") is True:
                return fail(failure(ToolError(result)))
            decode = cast(
                "Callable[[object], Effect[Any, S.SchemaError, Any]]",
                S.decode_unknown_effect(schema),
            )
            return decode(_structured(tool, result)).map_error(
                lambda cause: failure(
                    ValidationError("MCP structured result validation failed", cause)
                )
            )

        called = (
            self._call("tools", "tools/call", params, tool)
            .flat_map(lambda raw: _decode(CALL_TOOL_RESULT, raw))
            .flat_map(typed)
        )
        return self._deadline(called, "tools/call", _optional_seconds(timeout))


def _structured(tool: McpTool, result: CallToolResult) -> object:
    """``result``'s ``structuredContent``, unwrapped when ``tool``'s output
    schema says the server wrapped it as ``{"result": ...}``."""
    structured = result.get("structuredContent")
    schema: Mapping[str, Any] = tool.get("outputSchema") or {}
    if schema.get(WRAP_RESULT) is True and isinstance(structured, Mapping):
        return cast("Mapping[str, Any]", structured).get("result")
    return structured


class McpClient(Tag[McpClientService], key="effect/ai/McpClient"):
    """The MCP client a program uses."""


def _traced[A](
    request: Effect[A, McpClientError], method: str, tool: McpTool | None
) -> Effect[A, McpClientError]:
    """``request`` in a client span naming its method and tool (the server's
    is ``McpServer.<method>``, as Effect's)."""
    attributes: dict[str, object] = {"rpc.system.name": "jsonrpc", "rpc.method": method}
    if tool is not None:
        attributes["tool"] = tool["name"]
    return request.with_span(
        f"McpClient.{method}", kind="client", capture_stack_trace=False, attributes=attributes
    )


def _optional_seconds(timeout: Duration | None) -> Seconds | None:
    return None if timeout is None else to_seconds(timeout)


def _version_rejected(error: McpClientError, version: str) -> bool:
    reason = error.reason
    if not isinstance(reason, ProtocolError | HttpError):
        return False
    code = cast("Any", reason).code
    data = cast("Any", reason).data
    return (
        code == UNSUPPORTED_PROTOCOL_VERSION_ERROR_CODE
        and isinstance(data, dict)
        and cast("dict[str, Any]", data).get("requested") == version
        and version in (cast("dict[str, Any]", data).get("supported") or [])
    )


def make(  # noqa: PLR0915
    *,
    name: str,
    version: str,
    title: str | None = None,
    description: str | None = None,
    website_url: str | None = None,
    icons: Sequence[Icon] = (),
    timeout: Duration | None = None,
) -> Effect[McpClientService, McpClientError, Transport | Scope]:
    """Connect over the ``Transport``: initialize (2025-11-25) or discover
    the server (2026-07-28) within ``timeout``."""
    limit = DEFAULT_TIMEOUT if timeout is None else to_seconds(timeout)

    @gen
    def run():
        transport = yield from Transport()
        protocol: ClientProtocol = transport.protocol
        protocol_version = protocol.protocol_version
        modern = protocol_version == "2026-07-28"
        closed = Deferred[Never, McpClientError]()
        yield from add_finalizer(
            lambda _: closed.fail(failure(ClosedError(description="MCP client scope closed")))
        )
        ids = iter(range(1, 1 << 62))
        client_info: Implementation = {"name": name, "version": version}
        for key, value in (
            ("title", title),
            ("description", description),
            ("websiteUrl", website_url),
        ):
            if value is not None:
                client_info[key] = value
        if icons:
            client_info["icons"] = list(icons)
        meta: JsonObject = {
            "io.modelcontextprotocol/protocolVersion": protocol_version,
            "io.modelcontextprotocol/clientInfo": cast("Any", client_info),
            "io.modelcontextprotocol/clientCapabilities": {},
        }

        def request(
            method: str, params: JsonObject, tool: McpTool | None
        ) -> Effect[Any, McpClientError]:
            # Each run takes its own id: a retried request is a new request.
            return suspend(lambda: send(method, params, tool))

        def send(
            method: str, params: JsonObject, tool: McpTool | None
        ) -> Effect[Any, McpClientError]:
            payload: JsonObject = {**params, "_meta": meta} if modern else params
            message: JsonObject = {
                "jsonrpc": "2.0",
                "id": next(ids),
                "method": method,
                "params": payload,
            }

            def answered(response: JsonObject) -> Effect[Any, McpClientError]:
                error = response.get("error")
                if isinstance(error, dict):
                    remote = cast("Mapping[str, Any]", error)
                    return fail(
                        failure(
                            ProtocolError(
                                remote.get("code"), remote.get("data"), remote.get("message")
                            )
                        )
                    )
                result: Any = response.get("result")
                if not isinstance(result, dict):
                    return fail(failure(ValidationError("Invalid MCP payload")))
                body = cast("dict[str, Any]", result)
                if modern and "resultType" not in body:
                    body = {**body, "resultType": "complete"}
                if method == "tools/list" and isinstance(body.get("tools"), list):
                    body = {**body, "tools": [t for t in body["tools"] if not requires_tasks(t)]}
                if body.get("resultType") == "input_required":
                    return fail(
                        failure(UnsupportedError("MCP input continuation is not supported"))
                    )
                return succeed(body)

            return _traced(transport.request(message, tool).flat_map(answered), method, tool)

        def deadline(
            effect: Effect[Any, McpClientError], operation: str, duration: Seconds | None
        ) -> Effect[Any, McpClientError]:
            open_ = effect.race_first(closed.wait())
            if duration is None:
                return open_
            return open_.timeout_or_else(duration, lambda: fail(failure(TimeoutError(operation))))

        @gen
        def initialize():
            if not modern:
                return (
                    yield from request(
                        "initialize",
                        {
                            "protocolVersion": protocol_version,
                            "capabilities": {},
                            "clientInfo": cast("Any", client_info),
                        },
                        None,
                    )
                )
            discover = request("server/discover", {}, None)
            return (
                yield from discover.catch_if(
                    lambda error: _version_rejected(error, protocol_version), lambda _: discover
                )
            )

        @gen
        def connect():
            result: dict[str, Any] = yield from initialize
            supported = (
                protocol_version in (result.get("supportedVersions") or [])
                if modern
                else result.get("protocolVersion") == protocol_version
            )
            if not supported:
                return (
                    yield from fail(
                        failure(
                            UnsupportedError(
                                "Server does not support the explicitly selected protocol version"
                            )
                        )
                    )
                )
            meta: dict[str, Any] = result.get("_meta") or {}
            identity: object = meta.get(_SERVER_INFO_META) if modern else result.get("serverInfo")
            capabilities: ServerCapabilities = yield from _decode(
                SERVER_CAPABILITIES, result.get("capabilities")
            )
            server_info: Implementation | None = (
                None if identity is None else (yield from _decode(IMPLEMENTATION, identity))
            )
            if not modern:
                yield from transport.notify(
                    {"jsonrpc": "2.0", "method": "notifications/initialized"}
                )
            instructions: str | None = result.get("instructions")
            return capabilities, instructions, server_info

        def invalid(error: McpClientError) -> McpClientError:
            if isinstance(error.reason, ValidationError):
                return failure(
                    ProtocolError(
                        description="Invalid MCP initialization result", cause=error.reason.cause
                    )
                )
            return error

        connected = yield from deadline(connect.map_error(invalid), "initialization", limit)
        capabilities, instructions, server_info = connected
        return McpClientService(
            protocol_version,
            server_info,
            instructions,
            capabilities,
            request,
            deadline,
            transport.is_callable,
            limit,
        )

    return run


@overload
def toolkit(
    client: McpClientService, prefix: str = "", *, failure_mode: Literal["error"] = "error"
) -> Effect[Toolkit.WithHandler[Any, Any, McpClientError, Never], McpClientError]: ...
@overload
def toolkit(
    client: McpClientService, prefix: str = "", *, failure_mode: Literal["return"]
) -> Effect[Toolkit.WithHandler[Any, Any, Never, Never], McpClientError]: ...
def toolkit(
    client: McpClientService, prefix: str = "", *, failure_mode: Tool.FailureMode = "error"
) -> Effect[Toolkit.WithHandler[Any, Any, Any, Never], McpClientError]:
    """The server's tools as a toolkit with handlers. A model tool's name
    is ``prefix`` and the tool's name joined as they are (pass
    ``"docs__"``, not ``"docs"``), at most 64 letters, digits, ``_`` and
    ``-``; a call's result is the text of the tool result.

    With ``failure_mode="error"`` (Effect's) a tool error (``isError``)
    or a failed request fails the call with ``McpClientError``. With
    ``"return"`` it goes back to the model as a failed result: the tool
    error's text, or the request's error message."""

    @gen
    def run():
        descriptors = yield from client.list_tools()
        tools: list[Tool.AnyTool] = []
        handlers: list[Tool.Handler[Any]] = []
        for descriptor in descriptors:
            model_name = f"{prefix}{descriptor['name']}"
            if _MODEL_TOOL_NAME.match(model_name) is None or any(
                t.name == model_name for t in tools
            ):
                return (
                    yield from fail(
                        failure(
                            ConfigurationError(
                                f"Invalid or duplicate MCP model tool name: {model_name}"
                            )
                        )
                    )
                )
            dynamic = cast(
                "Tool.AnyTool",
                Tool.dynamic(
                    cast("Any", model_name),
                    parameters=cast("Any", descriptor["inputSchema"]),
                    description=descriptor.get("description"),
                    success=S.String,
                    failure=S.Unknown if failure_mode == "error" else S.String,
                    failure_mode=cast("Any", failure_mode),
                ).annotate(Tool.Strict, False),
            )
            handle = _tool_handler(client, descriptor)
            if failure_mode == "return":
                handle = _returning(handle)
            tools.append(dynamic)
            handlers.append(dynamic.handler(handle))
        kit = Toolkit.make(*tools)
        context: Context[Any] = yield from kit.to_handlers(*handlers)
        built: Toolkit.WithHandler[Any, Any, Any, Never] = yield from cast(
            "Effect[Any, Never, Never]", kit
        ).pipe(provide_context(context))
        return built

    return run


def _tool_handler(
    client: McpClientService, descriptor: McpTool
) -> Callable[[Any, Any], Effect[str, McpClientError]]:
    def handle(params: Any, _: Any) -> Effect[str, McpClientError]:
        if not isinstance(params, dict):
            return fail(failure(ValidationError("MCP tool arguments must be a JSON object")))
        arguments = cast("dict[str, Any]", params)

        def text(result: CallToolResult) -> Effect[str, McpClientError]:
            if result.get("isError") is True:
                return fail(failure(ToolError(result)))
            return to_text(result)

        return client.call_tool(descriptor, arguments).flat_map(text)

    return handle


def _returning(
    handle: Callable[[Any, Any], Effect[str, McpClientError]],
) -> Callable[[Any, Any], Effect[str, str]]:
    """``handle`` failing with what the model is told: a tool error's text
    (or its message, when the text has none), any other error's message."""

    def told(error: McpClientError) -> Effect[str, McpClientError]:
        reason = error.reason
        if isinstance(reason, ToolError):
            return to_text(reason.result).map(lambda text: text or reason.message)
        return succeed(error.message)

    def run(params: Any, context: Any) -> Effect[str, str]:
        attempt = handle(params, context)
        return attempt.catch_all(
            lambda error: told(error).catch_all(lambda _: succeed(error.message)).flat_map(fail)
        )

    return run


def stdio(
    *, command: Command, protocol: ClientProtocol, max_message_bytes: int | None = None
) -> Effect[TransportService, McpClientError, ChildProcessSpawner | Scope]:
    """A transport to a child process on its standard input and output."""
    return _stdio(command=command, protocol=protocol, max_message_bytes=max_message_bytes)


def http(
    *,
    url: str,
    protocol: ClientProtocol,
    headers: Mapping[str, str] | None = None,
    max_message_bytes: int | None = None,
) -> Effect[TransportService, McpClientError, HttpClient | Scope]:
    """A Streamable HTTP transport to ``url``."""
    return _http(url=url, protocol=protocol, headers=headers, max_message_bytes=max_message_bytes)


def layer_stdio(
    *,
    name: str,
    version: str,
    command: Command,
    protocol: ClientProtocol,
    title: str | None = None,
    description: str | None = None,
    website_url: str | None = None,
    icons: Sequence[Icon] = (),
    timeout: Duration | None = None,
    max_message_bytes: int | None = None,
) -> Layer[McpClient, McpClientError, ChildProcessSpawner]:
    """An ``McpClient`` of the server ``command`` runs."""
    client = make(
        name=name,
        version=version,
        title=title,
        description=description,
        website_url=website_url,
        icons=icons,
        timeout=timeout,
    )
    transport = layer_effect(
        Transport, stdio(command=command, protocol=protocol, max_message_bytes=max_message_bytes)
    )
    return layer_effect(McpClient, client).pipe(provide(transport))


def layer_http(
    *,
    name: str,
    version: str,
    url: str,
    protocol: ClientProtocol,
    headers: Mapping[str, str] | None = None,
    title: str | None = None,
    description: str | None = None,
    website_url: str | None = None,
    icons: Sequence[Icon] = (),
    timeout: Duration | None = None,
    max_message_bytes: int | None = None,
) -> Layer[McpClient, McpClientError, HttpClient]:
    """An ``McpClient`` of the server at ``url``."""
    client = make(
        name=name,
        version=version,
        title=title,
        description=description,
        website_url=website_url,
        icons=icons,
        timeout=timeout,
    )
    transport = layer_effect(
        Transport,
        http(url=url, protocol=protocol, headers=headers, max_message_bytes=max_message_bytes),
    )
    return layer_effect(McpClient, client).pipe(provide(transport))


__all__ = [
    "DEFAULT_TIMEOUT",
    "MAX_DISCOVERY_ITEMS",
    "MAX_DISCOVERY_PAGES",
    "ClientProtocol",
    "ClientProtocolVersion",
    "McpClient",
    "McpClientService",
    "Transport",
    "TransportService",
    "http",
    "layer_http",
    "layer_stdio",
    "make",
    "stdio",
    "toolkit",
]
