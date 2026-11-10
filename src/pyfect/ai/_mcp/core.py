"""The registrations of an MCP server and its notification hub.

``McpServerService`` holds the tools, resources, templates and prompts
handlers registered, answers them for a request (``call_tool``, ...), and
delivers server notifications to the connected ``Peer`` s that the
transports register and to the ``subscriptions/listen`` streams.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Never, Protocol

from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect.ai._mcp import skills
from pyfect.ai._mcp.invoke import (
    AnyMiddlewareFn,
    Invoke,
    ListMethod,
    RequestOutbound,
    RequestRejected,
    ResourceNotFound,
    unwrap_rejected,
)
from pyfect.ai._mcp.skills import SkillCatalog, SkillRegistration
from pyfect.ai._mcp.subscriptions import Event, Presence
from pyfect.ai.mcp_schema import (
    CallToolParams,
    CallToolResult,
    ClientProfile,
    CompleteParams,
    CompleteResult,
    CompletionContext,
    EnabledWhen,
    GetPromptResult,
    InputRequired,
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
from pyfect.deferred import Deferred
from pyfect.effect import (
    catch_tag,
    die,
    fail,
    gen,
    provide_service,
    service_option,
    succeed,
    suspend,
    sync,
)
from pyfect.errors import IllegalArgumentError
from pyfect.pubsub import Atomic, PubSub, Subscription
from pyfect.scope import Scope

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
_LIST_CHANGES = frozenset(
    {
        "notifications/resources/list_changed",
        "notifications/tools/list_changed",
        "notifications/prompts/list_changed",
    }
)
_SUBSCRIPTION_EVENTS = _LIST_CHANGES | {"notifications/resources/updated"}
_NO_CLIENT_INPUT = "Client input is not supported by this MCP protocol"

type CompletionHandler = Callable[
    [str, CompletionContext], Effect[CompleteResult, InternalError, RequestServices]
]

_VOID: Effect[None] = succeed(None)


@dataclass(frozen=True, slots=True)
class ToolEntry:
    tool: Tool
    annotations: Context[Any]
    handle: Callable[
        [JsonObject | None],
        Effect[CallToolResult | InputRequired, InvalidParams | InternalError, RequestServices],
    ]
    """Invalid input is ``InvalidParams``, a failed execution ``InternalError``;
    ``InputRequired`` asks a 2026-07-28 client to retry with input."""
    services: Context[Any] | None = None
    """The context it was registered in: its services, under the request's,
    and its MCP middleware (Effect's ``services``)."""


@dataclass(frozen=True, slots=True)
class ResourceEntry:
    resource: Resource
    annotations: Context[Any]
    handle: Effect[ReadResourceResult, McpError, RequestServices]
    services: Context[Any] | None = None


@dataclass(frozen=True, slots=True)
class ResourceTemplateEntry:
    template: ResourceTemplate
    annotations: Context[Any]
    match: Callable[[str], Mapping[str, str] | None]
    completions: Mapping[str, CompletionHandler]
    handle: Callable[
        [str, Mapping[str, str]], Effect[ReadResourceResult, McpError, RequestServices]
    ]
    services: Context[Any] | None = None


@dataclass(frozen=True, slots=True)
class PromptEntry:
    prompt: Prompt
    annotations: Context[Any]
    completions: Mapping[str, CompletionHandler]
    handle: Callable[
        [Mapping[str, str]], Effect[GetPromptResult | InputRequired, McpError, RequestServices]
    ]
    services: Context[Any] | None = None


@dataclass(frozen=True, slots=True)
class _Completion:
    """A completion handler, run as a request of its prompt or template."""

    handler: CompletionHandler
    invoke: Invoke
    target: str
    """The prompt name or URI template middleware sees."""


@dataclass(slots=True)
class _PendingChange:
    """A list change waiting for its window to end; later changes of the kind
    join it, so its revision is the newest one."""

    body: JsonObject
    revision: int
    origin: int | None
    delivered: Deferred[None]


class Peer(Protocol):
    """A connected client a transport registered."""

    @property
    def client_id(self) -> int: ...

    def deliver(self, method: str, params: JsonObject, revision: int | None = None) -> Effect[None]:
        """Send a notification (the peer drops one it does not want). A
        list change carries its ``revision``: a peer drops one from before it
        initialized."""
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
        self.skills = SkillCatalog()
        self._completions: dict[str, _Completion] = {}
        self._invokes: dict[tuple[str, str], Invoke] = {}
        self.global_middleware: list[AnyMiddlewareFn] = []
        """The middleware of every request (``Middleware.layer_global``)."""
        self._peers: dict[int, Peer] = {}
        self._ids = itertools.count(1)
        self._events = PubSub[Event](Atomic(None, None), "dropping")
        self._list_change_revision = 0
        self._pending_changes: dict[str, _PendingChange] = {}

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

    def _invoke(self, kind: str, key: str, services: Context[Any] | None) -> Invoke:
        invoke = Invoke.make(services, self.global_middleware)
        self._invokes[kind, key] = invoke
        return invoke

    def add_tool(self, entry: ToolEntry) -> Effect[None]:
        """Add (or replace, by name) a tool."""
        name = entry.tool["name"]

        def add() -> None:
            self._tools[name] = entry
            self._invoke("tool", name, entry.services)

        return sync(add).and_then(self.notify("notifications/tools/list_changed"))

    def add_resource(self, entry: ResourceEntry) -> Effect[None]:
        """Add (or replace, by URI) a resource. A file of a registered skill
        is not replaced: that is a defect."""
        return self._add_resource(entry, skill_file=False)

    def _add_resource(self, entry: ResourceEntry, *, skill_file: bool) -> Effect[None]:
        uri = entry.resource["uri"]

        # Checking skill ownership and the write happen in one step, so a
        # skill cannot claim the URI in between.
        def add() -> Effect[None]:
            if not skill_file and self.skills.owns_file(uri):
                return die(IllegalArgumentError(f"Resource {uri} is a file of a registered skill"))
            self._resources[uri] = entry
            self._invoke("resource", uri, entry.services)
            return self.notify("notifications/resources/list_changed")

        return suspend(add)

    def add_skill(
        self, registration: SkillRegistration, files: Sequence[ResourceEntry]
    ) -> Effect[None, IllegalArgumentError]:
        """Register a skill: claim its files, then serve them as resources."""

        def claim() -> Effect[None, IllegalArgumentError]:
            refused = self.skills.register(registration, self._resources)
            return succeed(None) if refused is None else fail(refused)

        @gen
        def run():
            yield from suspend(claim)
            for entry in files:
                yield from self._add_resource(entry, skill_file=True)

        return run

    def add_resource_template(self, entry: ResourceTemplateEntry) -> Effect[None]:
        """Add (or replace, by URI template) a resource template and its
        completions."""
        uri_template = entry.template["uriTemplate"]

        def add() -> None:
            self._templates[uri_template] = entry
            invoke = self._invoke("template", uri_template, entry.services)
            for name, handler in entry.completions.items():
                key = f"resource/{uri_template}/{name}"
                self._completions[key] = _Completion(handler, invoke, uri_template)

        return sync(add).and_then(self.notify("notifications/resources/list_changed"))

    def add_prompt(self, entry: PromptEntry) -> Effect[None]:
        """Add (or replace, by name) a prompt and its completions."""
        name = entry.prompt["name"]

        def add() -> None:
            self._prompts[name] = entry
            invoke = self._invoke("prompt", name, entry.services)
            for argument, handler in entry.completions.items():
                self._completions[f"prompt/{name}/{argument}"] = _Completion(handler, invoke, name)

        return sync(add).and_then(self.notify("notifications/prompts/list_changed"))

    @property
    def has_registrations(self) -> Presence:
        """Whether there are tools, resources (or templates) and prompts."""
        return Presence(
            bool(self._tools),
            bool(self._resources or self._templates),
            bool(self._prompts),
            self.skills.present,
        )

    # --- serving -----------------------------------------------------------------------

    def _listed[D](
        self,
        method: ListMethod,
        kind: str,
        entries: Mapping[str, Any],
        descriptor: Callable[[Any], D],
        context: RequestContext,
    ) -> Effect[list[D], RequestRejected, McpRequestContext]:
        """The entries ``EnabledWhen`` shows ``context``, then each
        visibility check passes, in order (Effect's ``filterList``)."""
        enabled = [(key, e) for key, e in entries.items() if _visible(e.annotations, context)]

        @gen
        def run():
            shown: list[D] = []
            for key, entry in enabled:
                if (yield from self._invokes[kind, key].visible(method, key)):
                    shown.append(descriptor(entry))
            return shown

        return run

    def list_tools(
        self, context: RequestContext
    ) -> Effect[list[Tool], RequestRejected, McpRequestContext]:
        return self._listed("tools/list", "tool", self._tools, lambda e: e.tool, context)

    def list_resources(
        self, context: RequestContext
    ) -> Effect[list[Resource], RequestRejected, McpRequestContext]:
        return self._listed(
            "resources/list", "resource", self._resources, lambda e: e.resource, context
        )

    def list_resource_templates(
        self, context: RequestContext
    ) -> Effect[list[ResourceTemplate], RequestRejected, McpRequestContext]:
        return self._listed(
            "resources/templates/list", "template", self._templates, lambda e: e.template, context
        )

    def list_prompts(
        self, context: RequestContext
    ) -> Effect[list[Prompt], RequestRejected, McpRequestContext]:
        return self._listed("prompts/list", "prompt", self._prompts, lambda e: e.prompt, context)

    def find_tool(self, name: str, context: RequestContext) -> ToolEntry | None:
        entry = self._tools.get(name)
        return entry if entry is not None and _visible(entry.annotations, context) else None

    def call_tool_for(
        self, params: CallToolParams, context: RequestContext
    ) -> Effect[
        CallToolResult | InputRequired,
        InvalidParams | InternalError | RequestRejected,
        RequestServices,
    ]:
        """The outcome of ``params`` 's call; an unknown tool is invalid
        params, a hidden one rejected as unknown."""
        name = params["name"]
        entry = self.find_tool(name, context)
        if entry is None:
            return fail(InvalidParams(f"Tool '{name}' not found"))
        return self._invokes["tool", name](
            suspend(lambda: entry.handle(params.get("arguments"))),
            method="tools/call",
            target=name,
            payload=params,
            hidden=RequestRejected(InvalidParams(f"Tool '{name}' not found")),
        )

    def read_resource_for(
        self, uri: str, context: RequestContext
    ) -> Effect[ReadResourceResult, McpError | RequestRejected | ResourceNotFound, RequestServices]:
        """The read of ``uri``: ``ResourceNotFound`` when nothing serves it,
        or a visibility hides what does (a hidden resource does not fall
        through to a template)."""
        entry = self._resources.get(uri)
        if entry is not None and _visible(entry.annotations, context):
            return self._invokes["resource", uri](
                entry.handle,
                method="resources/read",
                target=uri,
                payload={"uri": uri},
                hidden=ResourceNotFound(uri),
            )
        for key, template in self._templates.items():
            params = template.match(uri)
            if params is not None and _visible(template.annotations, context):
                return self._invokes["template", key](
                    suspend(lambda template=template, params=params: template.handle(uri, params)),
                    method="resources/read",
                    target=uri,
                    payload={"uri": uri},
                    hidden=ResourceNotFound(uri),
                )
        return fail(ResourceNotFound(uri))

    def get_prompt_for(
        self, name: str, arguments: Mapping[str, str], context: RequestContext
    ) -> Effect[GetPromptResult | InputRequired, McpError | RequestRejected, RequestServices]:
        entry = self._prompts.get(name)
        not_found = InvalidParams(f"Prompt '{name}' not found")
        if entry is None or not _visible(entry.annotations, context):
            return fail(not_found)
        return self._invokes["prompt", name](
            suspend(lambda: entry.handle(arguments)),
            method="prompts/get",
            target=name,
            payload={"name": name, "arguments": dict(arguments)},
            hidden=not_found,
        )

    def skills_for(
        self, method: str, params: JsonObject, context: RequestContext
    ) -> Effect[JsonObject, McpError, McpRequestContext]:
        """Answer one of the Skills extension's methods."""
        return unwrap_rejected(
            skills.serve(
                self.skills, method, params, lambda annotations: _visible(annotations, context)
            )
        )

    def complete_for(
        self, params: CompleteParams
    ) -> Effect[CompleteResult, InvalidParams | InternalError | RequestRejected, RequestServices]:
        ref = params["ref"]
        argument = params["argument"]
        key = (
            f"prompt/{ref['name']}/{argument['name']}"
            if ref["type"] == "ref/prompt"
            else f"resource/{ref['uri']}/{argument['name']}"
        )
        unknown = InvalidParams("Unknown completion reference or argument")
        found = self._completions.get(key)
        if found is None:
            return fail(unknown)
        context = params.get("context") or {}
        completed = found.invoke(
            suspend(lambda: found.handler(argument["value"], context)),
            method="completion/complete",
            target=found.target,
            payload=params,
            hidden=unknown,
        )
        return completed.map(_at_most_100)

    # --- the direct service (Effect's ``callTool``, ``findResource``, ...) --------------

    def call_tool(
        self, params: CallToolParams
    ) -> Effect[CallToolResult, McpError, McpServerClient]:
        """Call a tool for the current session. Middleware rejecting it
        fails with its MCP error."""
        return _with_request(
            lambda context: unwrap_rejected(self.call_tool_for(params, context))
        ).flat_map(_complete)

    def find_resource(self, uri: str) -> Effect[ReadResourceResult, McpError, McpServerClient]:
        """Read a resource for the current session."""

        def not_found(error: ResourceNotFound) -> Effect[Never, InvalidParams]:
            return fail(InvalidParams(f"Resource '{error.uri}' not found"))

        def read(context: RequestContext) -> Effect[ReadResourceResult, McpError, RequestServices]:
            found = self.read_resource_for(uri, context).pipe(
                catch_tag(ResourceNotFound, not_found)
            )
            return unwrap_rejected(found)

        return _with_request(read)

    def get_prompt_result(
        self, name: str, arguments: Mapping[str, str] | None = None
    ) -> Effect[GetPromptResult, McpError, McpServerClient]:
        """Get a prompt for the current session."""
        return _with_request(
            lambda context: unwrap_rejected(self.get_prompt_for(name, arguments or {}, context))
        ).flat_map(_complete)

    def completion(
        self, params: CompleteParams
    ) -> Effect[CompleteResult, McpError, McpServerClient]:
        """Complete an argument for the current session."""
        return _with_request(lambda _: unwrap_rejected(self.complete_for(params)))

    # --- notifications -----------------------------------------------------------------

    def connect(self, peer: Peer) -> None:
        self._peers[peer.client_id] = peer

    def next_client_id(self) -> int:
        return next(self._ids)

    def disconnect(self, client_id: int) -> None:
        self._peers.pop(client_id, None)

    @property
    def list_change_revision(self) -> int:
        """The newest list change's; a new listener ignores it and older ones."""
        return self._list_change_revision

    @property
    def subscribe_events(self) -> Effect[Subscription[Event], Never, Scope]:
        """A listener's feed of what subscriptions carry, for its scope."""
        return self._events.subscribe()

    def notify(self, method: NotificationMethod, params: JsonObject | None = None) -> Effect[None]:
        """Send a notification. A log message or progress sent while serving
        a request goes to that request's client. List changes of a kind made
        in one scheduling window go out once, after it. The others go to
        every connected client that wants them and every subscription that
        asked; a request waits for its own client's copy, so that it precedes
        the response."""
        body: JsonObject = {} if params is None else params

        @gen
        def run():
            current = yield from service_option(RequestOutbound)
            if method in _REQUEST_NOTIFICATIONS and current is not None:
                yield from current.value(method, body)
                return None
            request = yield from service_option(McpRequestContext)
            origin = None if request is None else request.value.client_id
            if method in _LIST_CHANGES:
                return (yield from self._list_changed(method, body, origin))
            return (yield from self._publish(method, body, None, origin))

        return run

    def _list_changed(self, method: str, body: JsonObject, origin: int | None) -> Effect[None]:
        self._list_change_revision += 1
        revision = self._list_change_revision
        joined = self._pending_changes.get(method)
        if joined is not None:
            joined.revision = revision
            return _VOID
        # Queued even with no client yet: one that initializes before it goes
        # out has a newer revision, so it drops it.
        change = _PendingChange(body, revision, origin, Deferred[None]())
        self._pending_changes[method] = change

        @gen
        def flush():
            del self._pending_changes[method]
            yield from self._publish(method, change.body, change.revision, change.origin)
            yield from change.delivered.succeed(None)

        forked = flush.fork_daemon().as_void()
        return forked if origin is None else forked.and_then(change.delivered.wait())

    def _publish(
        self, method: str, body: JsonObject, revision: int | None, origin: int | None
    ) -> Effect[None]:
        @gen
        def run():
            if method in _SUBSCRIPTION_EVENTS:
                yield from self._events.publish(Event(method, body, revision))
            own: Fiber[None, Never] | None = None
            for peer in list(self._peers.values()):
                # On its own fiber, so one client that stopped reading holds up no other.
                delivery = yield from peer.deliver(method, body, revision).fork_daemon(
                    start_immediately=True
                )
                if peer.client_id == origin:
                    own = delivery
            if own is not None:
                yield from own.await_exit()

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


def _complete[A](outcome: A | InputRequired) -> Effect[A, InvalidParams]:
    """The direct service has no client to return an ``InputRequired`` to."""
    if isinstance(outcome, InputRequired):
        return fail(InvalidParams(_NO_CLIENT_INPUT))
    return succeed(outcome)


def _at_most_100(result: CompleteResult) -> CompleteResult:
    completion = result["completion"]
    values = completion["values"]
    if len(values) <= 100:
        return result
    return {
        **result,
        "completion": {**completion, "values": values[:100], "hasMore": True},
    }
