"""The registrations of an MCP server and its notification hub.

``McpServerService`` holds the tools, resources, templates and prompts
handlers registered, answers them for a request (``call_tool``, ...), and
delivers server notifications to the connected ``Peer`` s that the
transports register.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal, Protocol

from pyfect._core import Effect
from pyfect.ai.mcp_schema import (
    CallToolParams,
    CallToolResult,
    ClientProfile,
    CompleteParams,
    CompleteResult,
    CompletionContext,
    EnabledWhen,
    GetPromptResult,
    InternalError,
    InvalidParams,
    JsonObject,
    McpError,
    McpRequestContext,
    McpServerClient,
    Prompt,
    ReadResourceResult,
    RequestContext,
    Resource,
    ResourceTemplate,
    ServerClient,
    Tool,
)
from pyfect.context import Context, Tag
from pyfect.effect import fail, gen, provide_service, service_option, succeed, suspend, sync
from pyfect.http.server_request import HttpServerRequest
from pyfect.logger import CurrentLogLevel

type RequestServices = McpRequestContext | McpServerClient
"""What a handler is given by the request it serves."""

type NotificationMethod = Literal[
    "notifications/message",
    "notifications/progress",
    "notifications/cancelled",
    "notifications/resources/updated",
    "notifications/resources/list_changed",
    "notifications/tools/list_changed",
    "notifications/prompts/list_changed",
]

_REQUEST_NOTIFICATIONS = frozenset({"notifications/message", "notifications/progress"})

type CompletionHandler = Callable[
    [str, CompletionContext], Effect[CompleteResult, InternalError, RequestServices]
]

_VOID: Effect[None] = succeed(None)

type Deliver = Callable[[str, JsonObject], Effect[None]]
"""Sends a notification on the stream of the request being served."""


class RequestOutbound(Tag[Deliver], key="pyfect/ai/McpServer/RequestOutbound"):
    """Where the request being served sends its log messages and progress."""


def omit_request_services(context: Context[Any]) -> Context[Any]:
    """``context`` without the services a request provides: a handler
    registered during one request serves later ones with their own."""
    return context.pipe(
        Context.omit(
            McpRequestContext, McpServerClient, HttpServerRequest, RequestOutbound, CurrentLogLevel
        )
    )


@dataclass(frozen=True, slots=True)
class ToolEntry:
    tool: Tool
    annotations: Context[Any]
    handle: Callable[
        [JsonObject | None], Effect[CallToolResult, InvalidParams | InternalError, RequestServices]
    ]
    """Invalid input is ``InvalidParams``, a failed execution ``InternalError``."""


@dataclass(frozen=True, slots=True)
class ResourceEntry:
    resource: Resource
    annotations: Context[Any]
    handle: Effect[ReadResourceResult, McpError, RequestServices]


@dataclass(frozen=True, slots=True)
class ResourceTemplateEntry:
    template: ResourceTemplate
    annotations: Context[Any]
    match: Callable[[str], Mapping[str, str] | None]
    completions: Mapping[str, CompletionHandler]
    handle: Callable[
        [str, Mapping[str, str]], Effect[ReadResourceResult, McpError, RequestServices]
    ]


@dataclass(frozen=True, slots=True)
class PromptEntry:
    prompt: Prompt
    annotations: Context[Any]
    completions: Mapping[str, CompletionHandler]
    handle: Callable[[Mapping[str, str]], Effect[GetPromptResult, McpError, RequestServices]]


class Peer(Protocol):
    """A connected client a transport registered."""

    @property
    def client_id(self) -> int: ...

    def deliver(self, method: str, params: JsonObject) -> Effect[None]:
        """Send a notification (the peer drops one it does not want)."""
        ...


def _visible(annotations: Context[Any], context: RequestContext) -> bool:
    found, enabled = annotations.lookup(EnabledWhen)
    if not found:
        return True
    profile = ClientProfile(
        context.protocol_version, context.client_capabilities, context.client_info
    )
    return bool(enabled(profile))


def request_context_of(client: ServerClient) -> RequestContext:
    return RequestContext(
        client.client_id,
        client.protocol_version,
        client.client_capabilities,
        client.client_info,
        client.request_metadata,
    )


def _with_request[A, E](
    f: Callable[[RequestContext], Effect[A, E, RequestServices]],
) -> Effect[A, E, McpServerClient]:
    """``f`` for the current session's request, given its request context."""

    @gen
    def run():
        client = yield from McpServerClient()
        context = request_context_of(client)
        return (yield from f(context).pipe(provide_service(McpRequestContext, context)))

    return run


class McpServerService:
    """Effect's ``McpServer`` service: what a server offers and its
    notifications (see ``pyfect.ai.mcp_server``)."""

    def __init__(self) -> None:
        self._tools: dict[str, ToolEntry] = {}
        self._resources: dict[str, ResourceEntry] = {}
        self._templates: dict[str, ResourceTemplateEntry] = {}
        self._prompts: dict[str, PromptEntry] = {}
        self._completions: dict[str, CompletionHandler] = {}
        self._peers: dict[int, Peer] = {}
        self._ids = itertools.count(1)

    # --- registrations -----------------------------------------------------------------

    @property
    def tools(self) -> tuple[ToolEntry, ...]:
        return tuple(self._tools.values())

    @property
    def resources(self) -> tuple[ResourceEntry, ...]:
        return tuple(self._resources.values())

    @property
    def resource_templates(self) -> tuple[ResourceTemplateEntry, ...]:
        return tuple(self._templates.values())

    @property
    def prompts(self) -> tuple[PromptEntry, ...]:
        return tuple(self._prompts.values())

    def add_tool(self, entry: ToolEntry) -> Effect[None]:
        """Add (or replace, by name) a tool."""
        return sync(lambda: self._tools.__setitem__(entry.tool["name"], entry)).and_then(
            self.notify("notifications/tools/list_changed")
        )

    def add_resource(self, entry: ResourceEntry) -> Effect[None]:
        """Add (or replace, by URI) a resource."""
        return sync(lambda: self._resources.__setitem__(entry.resource["uri"], entry)).and_then(
            self.notify("notifications/resources/list_changed")
        )

    def add_resource_template(self, entry: ResourceTemplateEntry) -> Effect[None]:
        """Add (or replace, by URI template) a resource template and its
        completions."""
        uri_template = entry.template["uriTemplate"]

        def add() -> None:
            self._templates[uri_template] = entry
            for name, handler in entry.completions.items():
                self._completions[f"resource/{uri_template}/{name}"] = handler

        return sync(add).and_then(self.notify("notifications/resources/list_changed"))

    def add_prompt(self, entry: PromptEntry) -> Effect[None]:
        """Add (or replace, by name) a prompt and its completions."""
        name = entry.prompt["name"]

        def add() -> None:
            self._prompts[name] = entry
            for argument, handler in entry.completions.items():
                self._completions[f"prompt/{name}/{argument}"] = handler

        return sync(add).and_then(self.notify("notifications/prompts/list_changed"))

    @property
    def has_registrations(self) -> tuple[bool, bool, bool]:
        """Whether there are tools, resources (or templates) and prompts."""
        return bool(self._tools), bool(self._resources or self._templates), bool(self._prompts)

    # --- serving -----------------------------------------------------------------------

    def list_tools(self, context: RequestContext) -> list[Tool]:
        return [e.tool for e in self._tools.values() if _visible(e.annotations, context)]

    def list_resources(self, context: RequestContext) -> list[Resource]:
        return [e.resource for e in self._resources.values() if _visible(e.annotations, context)]

    def list_resource_templates(self, context: RequestContext) -> list[ResourceTemplate]:
        return [e.template for e in self._templates.values() if _visible(e.annotations, context)]

    def list_prompts(self, context: RequestContext) -> list[Prompt]:
        return [e.prompt for e in self._prompts.values() if _visible(e.annotations, context)]

    def find_tool(self, name: str, context: RequestContext) -> ToolEntry | None:
        entry = self._tools.get(name)
        return entry if entry is not None and _visible(entry.annotations, context) else None

    def call_tool_for(
        self, params: CallToolParams, context: RequestContext
    ) -> Effect[CallToolResult, InvalidParams | InternalError, RequestServices]:
        """The result of ``params`` 's call; an unknown tool is invalid params."""
        name = params["name"]
        entry = self.find_tool(name, context)
        if entry is None:
            return fail(InvalidParams(f"Tool '{name}' not found"))
        return suspend(lambda: entry.handle(params.get("arguments")))

    def read_resource_for(
        self, uri: str, context: RequestContext
    ) -> Effect[ReadResourceResult, McpError, RequestServices] | None:
        """The read of ``uri``, or ``None`` when nothing serves it."""
        entry = self._resources.get(uri)
        if entry is not None and _visible(entry.annotations, context):
            return entry.handle
        for template in self._templates.values():
            params = template.match(uri)
            if params is not None and _visible(template.annotations, context):
                return suspend(
                    lambda template=template, params=params: template.handle(uri, params)
                )
        return None

    def get_prompt_for(
        self, name: str, arguments: Mapping[str, str], context: RequestContext
    ) -> Effect[GetPromptResult, McpError, RequestServices]:
        entry = self._prompts.get(name)
        if entry is None or not _visible(entry.annotations, context):
            return fail(InvalidParams(f"Prompt '{name}' not found"))
        return suspend(lambda: entry.handle(arguments))

    def complete_for(
        self, params: CompleteParams
    ) -> Effect[CompleteResult, InvalidParams | InternalError, RequestServices]:
        ref = params["ref"]
        argument = params["argument"]
        key = (
            f"prompt/{ref['name']}/{argument['name']}"
            if ref["type"] == "ref/prompt"
            else f"resource/{ref['uri']}/{argument['name']}"
        )
        handler = self._completions.get(key)
        if handler is None:
            return fail(InvalidParams("Unknown completion reference or argument"))
        context = params.get("context") or {}
        return suspend(lambda: handler(argument["value"], context)).map(_at_most_100)

    # --- the direct service (Effect's ``callTool``, ``findResource``, ...) --------------

    def call_tool(
        self, params: CallToolParams
    ) -> Effect[CallToolResult, InvalidParams | InternalError, McpServerClient]:
        """Call a tool for the current session."""
        return _with_request(lambda context: self.call_tool_for(params, context))

    def find_resource(self, uri: str) -> Effect[ReadResourceResult, McpError, McpServerClient]:
        """Read a resource for the current session."""

        def read(context: RequestContext) -> Effect[ReadResourceResult, McpError, RequestServices]:
            found = self.read_resource_for(uri, context)
            return fail(InvalidParams(f"Resource '{uri}' not found")) if found is None else found

        return _with_request(read)

    def get_prompt_result(
        self, name: str, arguments: Mapping[str, str] | None = None
    ) -> Effect[GetPromptResult, McpError, McpServerClient]:
        """Get a prompt for the current session."""
        return _with_request(lambda context: self.get_prompt_for(name, arguments or {}, context))

    def completion(
        self, params: CompleteParams
    ) -> Effect[CompleteResult, InvalidParams | InternalError, McpServerClient]:
        """Complete an argument for the current session."""
        return _with_request(lambda _: self.complete_for(params))

    # --- notifications -----------------------------------------------------------------

    def connect(self, peer: Peer) -> None:
        self._peers[peer.client_id] = peer

    def next_client_id(self) -> int:
        return next(self._ids)

    def disconnect(self, client_id: int) -> None:
        self._peers.pop(client_id, None)

    def notify(self, method: NotificationMethod, params: JsonObject | None = None) -> Effect[None]:
        """Send a notification. A log message or progress sent while serving
        a request goes to that request's client; the others go to every
        connected client that wants them."""
        body: JsonObject = {} if params is None else params

        @gen
        def run():
            current = yield from service_option(RequestOutbound)
            if method in _REQUEST_NOTIFICATIONS and current is not None:
                yield from current.value(method, body)
                return None
            for peer in list(self._peers.values()):
                yield from peer.deliver(method, body)
            return None

        return run

    def notify_elicitation_complete(self, client_id: int, elicitation_id: str) -> Effect[None]:
        """Tell one client that its URL elicitation finished (a no-op when
        the client is gone)."""
        peer = self._peers.get(client_id)
        if peer is None:
            return _VOID
        return peer.deliver("notifications/elicitation/complete", {"elicitationId": elicitation_id})


class McpServer(Tag[McpServerService], key="effect/ai/McpServer"):
    """The MCP server whose tools, resources and prompts the transports
    serve."""


def _at_most_100(result: CompleteResult) -> CompleteResult:
    completion = result["completion"]
    values = completion["values"]
    if len(values) <= 100:
        return result
    return {
        **result,
        "completion": {**completion, "values": values[:100], "hasMore": True},
    }
