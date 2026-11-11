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

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Never, cast, overload

from pyfect import schema as S
from pyfect._core import Effect
from pyfect.ai._mcp.client_discovery import (
    DEFAULT_DISCOVERY_LIMITS,
    DiscoveryLimitsOptions,
    check_cacheable,
    paginate,
    resolve_limits,
)
from pyfect.ai._mcp.client_skills import (
    ClientExtensions,
    InvalidSkill,
    OnInvalidSkill,
    SkillsClient,
    client_capabilities,
)
from pyfect.ai._mcp.client_toolkit import RemoteTool, ToolDescriptor, toolkit
from pyfect.ai._mcp.client_transport import (
    ClientProtocol,
    ClientProtocolVersion,
    TransportService,
)
from pyfect.ai._mcp.client_transport import http as _http
from pyfect.ai._mcp.client_transport import stdio as _stdio
from pyfect.ai._mcp.client_wire import failure, requires_tasks
from pyfect.ai.mcp_client_error import (
    ClosedError,
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
    Skill,
)
from pyfect.ai.mcp_schema import Tool as McpTool
from pyfect.context import Tag
from pyfect.deferred import Deferred
from pyfect.duration import Duration, from_input_unsafe, millis
from pyfect.duration import Input as DurationInput
from pyfect.effect import fail, gen, succeed, suspend
from pyfect.http.client import HttpClient
from pyfect.layer import Layer, provide
from pyfect.layer import effect as layer_effect
from pyfect.process import ChildProcessSpawner, Command
from pyfect.scope import Scope, add_finalizer

DEFAULT_TIMEOUT = millis(60_000)
MAX_DISCOVERY_PAGES = DEFAULT_DISCOVERY_LIMITS.max_pages
MAX_DISCOVERY_ITEMS = DEFAULT_DISCOVERY_LIMITS.max_items

_SERVER_INFO_META = "io.modelcontextprotocol/serverInfo"


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
        [Effect[Any, McpClientError], str, Duration | None], Effect[Any, McpClientError]
    ] = field(repr=False)
    _is_callable: Callable[[McpTool], bool] = field(repr=False)
    _timeout: Duration = field(repr=False)
    _skills: SkillsClient = field(repr=False)
    """The Skills extension's methods, with the client's discovery limits."""

    def _call(
        self, kind: str, method: str, params: JsonObject, tool: McpTool | None = None
    ) -> Effect[Any, McpClientError]:
        if self.capabilities.get(kind) is None:
            return fail(failure(UnsupportedError(f"Server does not advertise {kind}")))
        return self._request(method, params, tool)

    def _check_cacheable(self, raw: object) -> Effect[None, McpClientError]:
        """A 2026-07-28 list or read result's cache fields."""
        return check_cacheable(self.protocol_version == "2026-07-28", raw)

    def _list(
        self,
        kind: str,
        schema: S.Top,
        timeout: DurationInput | None,
        limits: DiscoveryLimitsOptions | None,
    ) -> Effect[list[Any], McpClientError]:
        def decode_page(raw: dict[str, Any]) -> Effect[dict[str, Any], McpClientError]:
            return self._check_cacheable(raw).and_then(_decode(schema, raw))

        @gen
        def run():
            bounds = yield from resolve_limits(limits, self._skills.limits)
            if self.capabilities.get(kind) is None:
                return list[Any]()
            return (
                yield from paginate(
                    self._request,
                    label=kind,
                    method=f"{kind}/list",
                    key=kind,
                    params={},
                    limits=bounds,
                    decode_page=decode_page,
                )
            )

        deadline = self._timeout if timeout is None else from_input_unsafe(timeout)
        return self._deadline(run, f"{kind} discovery", deadline)

    def list_tools(
        self, *, timeout: DurationInput | None = None, limits: DiscoveryLimitsOptions | None = None
    ) -> Effect[list[McpTool], McpClientError]:
        """Every tool the server lists (and this transport can call), within
        the client's discovery deadline and limits (``timeout`` and
        ``limits`` override them)."""
        return self._list("tools", LIST_TOOLS.success_schema, timeout, limits).map(
            lambda tools: [t for t in tools if self._is_callable(t)]
        )

    def list_prompts(
        self, *, timeout: DurationInput | None = None, limits: DiscoveryLimitsOptions | None = None
    ) -> Effect[list[Prompt], McpClientError]:
        """Every prompt the server lists, with the bounds of ``list_tools``;
        none when it does not advertise prompts. Fails with an
        ``McpClientError``: a ``ConfigurationError`` for invalid limits, a
        limit or timeout error past the bounds, or the request's error."""
        return self._list("prompts", LIST_PROMPTS.success_schema, timeout, limits)

    def list_resources(
        self, *, timeout: DurationInput | None = None, limits: DiscoveryLimitsOptions | None = None
    ) -> Effect[list[Resource], McpClientError]:
        """Every resource the server lists, with the bounds and errors of
        ``list_prompts``; none when it does not advertise resources."""
        return self._list("resources", LIST_RESOURCES.success_schema, timeout, limits)

    def list_skills(
        self,
        *,
        timeout: DurationInput | None = None,
        limits: DiscoveryLimitsOptions | None = None,
        on_invalid_skill: OnInvalidSkill | None = None,
    ) -> Effect[list[Skill], McpClientError]:
        """Every skill the server lists, with the bounds of ``list_tools``;
        none when it does not declare the Skills extension. An entry breaking
        the extension's rules fails the scan, unless ``on_invalid_skill`` is
        given: it is then told of each and the entry is left out. The skill
        methods require ``extensions={"skills": True}``."""
        return self._skills.list_skills(_optional_seconds(timeout), limits, on_invalid_skill)

    def get_skill(
        self, uri: str, *, timeout: DurationInput | None = None
    ) -> Effect[Skill, McpClientError]:
        """The skill whose ``SKILL.md`` is at ``uri``, listed or not.
        Unbounded unless given a ``timeout``."""
        return self._skills.get_skill(uri, _optional_seconds(timeout))

    def read_resource_directory(
        self,
        uri: str,
        *,
        timeout: DurationInput | None = None,
        limits: DiscoveryLimitsOptions | None = None,
    ) -> Effect[list[Resource], McpClientError]:
        """The direct children of a directory of a skill namespace, with the
        bounds of ``list_tools``. Requires the server's ``directoryRead``."""
        return self._skills.read_resource_directory(uri, _optional_seconds(timeout), limits)

    def read_skill_resource(
        self, skill: Skill, uri: str, *, timeout: DurationInput | None = None
    ) -> Effect[ReadResourceResult, McpClientError]:
        """Read a file of ``skill``, failing with a ``ValidationError`` unless
        its bytes match the SHA-256 digest and size of the manifest and, for
        ``SKILL.md``, its frontmatter equals the listed one. A ``"dynamic"``
        skill has no digests: any file in its directory is read, and its
        ``SKILL.md`` still checked. A file outside the manifest or directory
        is never requested. Unbounded unless given a ``timeout``."""
        return self._skills.read_skill_resource(skill, uri, _optional_seconds(timeout))

    def get_prompt(
        self,
        prompt: Prompt,
        arguments: Mapping[str, str] | None = None,
        *,
        timeout: DurationInput | None = None,
    ) -> Effect[GetPromptResult, McpClientError]:
        """The messages of ``prompt`` filled with ``arguments``. Fails with
        an ``UnsupportedError`` when the server does not advertise prompts,
        a ``ValidationError`` for an invalid result, or the request's
        ``McpClientError``. Unbounded unless given a ``timeout``."""
        params: JsonObject = {"name": prompt["name"]}
        if arguments is not None:
            params["arguments"] = dict(arguments)
        got = self._call("prompts", "prompts/get", params).flat_map(
            lambda raw: _decode(GET_PROMPT_RESULT, raw)
        )
        return self._deadline(got, "prompts/get", _optional_seconds(timeout))

    def read_resource(
        self, uri: str, *, timeout: DurationInput | None = None
    ) -> Effect[ReadResourceResult, McpClientError]:
        """The contents of the resource at ``uri``. Fails with an
        ``UnsupportedError`` when the server does not advertise resources, a
        ``ValidationError`` for an invalid result, or the request's
        ``McpClientError``. Unbounded unless given a ``timeout``."""
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
        timeout: DurationInput | None = None,
    ) -> Effect[CallToolResult, McpClientError]: ...
    @overload
    def call_tool[A, R](
        self,
        tool: McpTool,
        arguments: Mapping[str, Any] | None = None,
        *,
        schema: S.Codec[A, Any, R, Any],
        timeout: DurationInput | None = None,
    ) -> Effect[A, McpClientError, R]: ...
    def call_tool(
        self,
        tool: McpTool,
        arguments: Mapping[str, Any] | None = None,
        *,
        schema: S.Codec[Any, Any, Any, Any] | None = None,
        timeout: DurationInput | None = None,
    ) -> Effect[Any, McpClientError, Any]:
        """Call ``tool``. With ``schema``, its ``structuredContent`` decoded
        (a tool error then fails with ``ToolError``); else the whole result.
        Unbounded unless given a ``timeout``."""
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
            structured: object = result.get("structuredContent")
            return decode(structured).map_error(
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


def _optional_seconds(timeout: DurationInput | None) -> Duration | None:
    return None if timeout is None else from_input_unsafe(timeout)


def _version_rejected(error: McpClientError, version: str) -> bool:
    reason = error.reason
    if not isinstance(reason, (ProtocolError, HttpError)):
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
    timeout: DurationInput | None = None,
    discovery_limits: DiscoveryLimitsOptions | None = None,
    extensions: ClientExtensions | None = None,
) -> Effect[McpClientService, McpClientError, Transport | Scope]:
    """Connect over the ``Transport``: initialize (2025-11-25) or discover
    the server (2026-07-28) within ``timeout``, which also bounds each
    complete list scan. ``discovery_limits`` sets the default scan limits
    (100 pages, 10,000 items). ``extensions={"skills": True}`` declares the
    Skills extension and enables the skill methods (else they fail with a
    ``ConfigurationError``)."""
    limit = DEFAULT_TIMEOUT if timeout is None else from_input_unsafe(timeout)
    skills_enabled = (extensions or {}).get("skills") is True
    capabilities_declared = client_capabilities(skills_enabled)

    @gen
    def run():  # noqa: PLR0915
        transport = yield from Transport()
        protocol: ClientProtocol = transport.protocol
        protocol_version = protocol.protocol_version
        modern = protocol_version == "2026-07-28"
        limits = yield from resolve_limits(discovery_limits, DEFAULT_DISCOVERY_LIMITS)
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
            "io.modelcontextprotocol/clientCapabilities": capabilities_declared,
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
            effect: Effect[Any, McpClientError], operation: str, duration: Duration | None
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
                            "capabilities": capabilities_declared,
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
            SkillsClient(request, deadline, limit, capabilities, limits, skills_enabled, modern),
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
    timeout: DurationInput | None = None,
    discovery_limits: DiscoveryLimitsOptions | None = None,
    extensions: ClientExtensions | None = None,
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
        discovery_limits=discovery_limits,
        extensions=extensions,
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
    timeout: DurationInput | None = None,
    discovery_limits: DiscoveryLimitsOptions | None = None,
    extensions: ClientExtensions | None = None,
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
        discovery_limits=discovery_limits,
        extensions=extensions,
    )
    transport = layer_effect(
        Transport,
        http(url=url, protocol=protocol, headers=headers, max_message_bytes=max_message_bytes),
    )
    return layer_effect(McpClient, client).pipe(provide(transport))


__all__ = [
    "DEFAULT_DISCOVERY_LIMITS",
    "DEFAULT_TIMEOUT",
    "MAX_DISCOVERY_ITEMS",
    "MAX_DISCOVERY_PAGES",
    "ClientExtensions",
    "ClientProtocol",
    "ClientProtocolVersion",
    "DiscoveryLimitsOptions",
    "InvalidSkill",
    "McpClient",
    "McpClientError",
    "McpClientService",
    "OnInvalidSkill",
    "RemoteTool",
    "ToolDescriptor",
    "Transport",
    "TransportService",
    "http",
    "layer_http",
    "layer_stdio",
    "make",
    "stdio",
    "toolkit",
]
