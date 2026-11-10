"""An MCP server (Effect's ``McpServer``): tools, resources, resource
templates, prompts and completions served to MCP clients over stdio or
Streamable HTTP.

Register what the server offers with layers (``toolkit``, ``resource``,
``resource_template``, ``prompt``, ``skill``), which need the ``McpServer``,
or effects (``register_*``), and give them to a transport layer::

    app = mcp_server.toolkit(NotesToolkit).pipe(layer.provide(NotesToolkit.to_layer(...)))
    server = mcp_server.layer_stdio(
        name="notes", version="1.0.0", protocols=(mcp_protocol.v2025_11_25,), registrations=app
    )
    server.pipe(layer.provide(stdio.layer)).launch()

``middleware`` and ``visibility`` run around the requests of the
registrations their layers are provided to. A handler runs with the request's
``McpRequestContext`` and ``McpServerClient``; ``elicit`` asks the client's
user for input and ``McpServerService.notify`` sends notifications.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, LiteralString, Never

from pyfect import byte_size
from pyfect._core import Effect
from pyfect._layer_core import require_layer
from pyfect._public import publish
from pyfect.ai._mcp import cache_hints as _cache_hints
from pyfect.ai._mcp import http as _http
from pyfect.ai._mcp import sessions as _sessions
from pyfect.ai._mcp import stdio as _stdio
from pyfect.ai._mcp.cache_hints import CacheHint, CacheHints
from pyfect.ai._mcp.core import (
    McpServer,
    McpServerService,
    PromptEntry,
    ResourceEntry,
    ResourceTemplateEntry,
    ToolEntry,
)
from pyfect.ai._mcp.dispatch import ServerInfo
from pyfect.ai._mcp.invoke import (
    MiddlewareMethod,
    MiddlewareOptions,
    MiddlewareSuccess,
    RequestRejected,
    ResourceNotFound,
)
from pyfect.ai._mcp.middleware import (
    Middleware,
    MiddlewareFunction,
    VisibilityCheck,
    middleware,
    visibility,
)
from pyfect.ai._mcp.register import (
    INTERNAL_TOOL_ERROR_MESSAGE,
    CompletionFunction,
    ResourceContent,
    UriTemplate,
    client_capabilities,
    elicit,
    register_prompt,
    register_resource,
    register_resource_template,
    register_toolkit,
    uri_template,
)
from pyfect.ai._mcp.register_skill import register_skill
from pyfect.ai._mcp.routing_header import decode_routing_header
from pyfect.ai._mcp.skills import SkillFile, SkillFileInput
from pyfect.ai.mcp_protocol import AnyProtocolAdapter, ProtocolAdapter, make_registry
from pyfect.ai.mcp_schema import CompletionContext, Icon, McpServerClient, PromptMessage, Role
from pyfect.ai.toolkit import Handlers, Toolkit
from pyfect.context import Context
from pyfect.duration import Input as DurationInput
from pyfect.effect import current_fiber, fail, gen, succeed
from pyfect.errors import IllegalArgumentError
from pyfect.http.router import HttpRouter
from pyfect.layer import Layer, effect_discard, provide, provide_merge
from pyfect.layer import effect as layer_effect
from pyfect.platform_error import PlatformError
from pyfect.schema import Codec
from pyfect.stdio import Stdio


def make() -> Effect[McpServerService]:
    """A server with nothing registered (Effect's ``McpServer.make``)."""
    return succeed(None).map(lambda _: McpServerService())


layer: Layer[McpServer] = layer_effect(McpServer, make())
"""The ``McpServer`` the registration layers and the transports share."""


def _info(
    name: str,
    version: str,
    *,
    title: str | None,
    description: str | None,
    website_url: str | None,
    icons: Sequence[Icon],
    instructions: str | None,
    extensions: Mapping[str, Any] | None,
    cache_hints: CacheHints | None,
) -> Effect[ServerInfo, IllegalArgumentError]:
    return _cache_hints.parse(cache_hints).map(
        lambda ttls: ServerInfo(
            name=name,
            version=version,
            title=title,
            description=description,
            website_url=website_url,
            icons=tuple(icons),
            instructions=instructions,
            extensions=extensions,
            cache_hints=ttls,
        )
    )


def _require_registrations(registrations: object) -> None:
    if registrations is not None:
        require_layer(registrations, "registrations")


def _serving[RE, RR](
    routes: Effect[None, IllegalArgumentError, Any],
    registrations: Layer[Any, RE, RR] | None,
) -> Layer[McpServer, Any, Any]:
    """A transport's layer: ``registrations`` built first, then the routes,
    sharing one ``McpServer``."""
    served: Layer[Never, Any, Any] = effect_discard(routes)
    if registrations is not None:
        served = served.pipe(provide(registrations))
    return served.pipe(provide_merge(layer))


def run_stdio(
    *,
    name: str,
    version: str,
    protocols: Sequence[AnyProtocolAdapter],
    title: str | None = None,
    description: str | None = None,
    website_url: str | None = None,
    icons: Sequence[Icon] = (),
    instructions: str | None = None,
    extensions: Mapping[str, Any] | None = None,
    cache_hints: CacheHints | None = None,
) -> Effect[None, IllegalArgumentError | PlatformError, McpServer | Stdio]:
    """Serve the client on standard input and output and return once its
    input ends and its requests are answered, so ``run_main`` exits 0.
    ``protocols`` are the revisions spoken, the first the one offered to a
    client asking for another."""
    info = _info(
        name,
        version,
        title=title,
        description=description,
        website_url=website_url,
        icons=icons,
        instructions=instructions,
        extensions=extensions,
        cache_hints=cache_hints,
    )
    return info.flat_map(
        lambda served: make_registry(protocols).flat_map(
            lambda registry: _stdio.serve(served, registry)
        )
    )


def layer_stdio[RE = Never, RR = Never](
    *,
    name: str,
    version: str,
    protocols: Sequence[AnyProtocolAdapter],
    title: str | None = None,
    description: str | None = None,
    website_url: str | None = None,
    icons: Sequence[Icon] = (),
    instructions: str | None = None,
    extensions: Mapping[str, Any] | None = None,
    cache_hints: CacheHints | None = None,
    registrations: Layer[Any, RE, RR | McpServer | McpServerClient] | None = None,
) -> Layer[McpServer, IllegalArgumentError | RE, Stdio | RR]:
    """``run_stdio`` in the background of a layer providing the
    ``McpServer``. As in Effect, the fiber that built the layer is interrupted
    when the server ends: ``.launch()`` ends at the end of input, and
    ``run_main`` exits 130. ``registrations`` are built before the server
    starts."""
    _require_registrations(registrations)
    running = run_stdio(
        name=name,
        version=version,
        protocols=protocols,
        title=title,
        description=description,
        website_url=website_url,
        icons=icons,
        instructions=instructions,
        extensions=extensions,
        cache_hints=cache_hints,
    )

    @gen
    def started():
        yield from make_registry(protocols)
        yield from _cache_hints.parse(cache_hints)
        builder = yield from current_fiber()
        ended = builder.interrupt().fork_daemon(start_immediately=True).as_void()
        yield from running.ignore().ensuring(ended).fork_scoped()

    return _serving(started, registrations)


def layer_http[RE = Never, RR = Never](
    *,
    name: str,
    version: str,
    path: str,
    protocols: Sequence[AnyProtocolAdapter],
    title: str | None = None,
    description: str | None = None,
    website_url: str | None = None,
    icons: Sequence[Icon] = (),
    instructions: str | None = None,
    extensions: Mapping[str, Any] | None = None,
    allowed_origins: Sequence[str] | None = None,
    allow_session_termination: bool = False,
    allow_subscriptions: bool = True,
    max_sessions: int = _sessions.DEFAULT_MAX_SESSIONS,
    session_idle_timeout: DurationInput = _sessions.DEFAULT_IDLE_TIMEOUT,
    max_message_bytes: byte_size.Input = _sessions.DEFAULT_MAX_MESSAGE_BYTES,
    cache_hints: CacheHints | None = None,
    registrations: Layer[Any, RE, RR | McpServer | McpServerClient] | None = None,
) -> Layer[McpServer, IllegalArgumentError | RE, HttpRouter | RR]:
    """Serve MCP's Streamable HTTP transport at ``path`` of the router.

    A request with an ``Origin`` header not in ``allowed_origins`` is
    refused (403); one without an ``Origin`` is served. With
    ``allow_session_termination`` a client ends its session with DELETE.
    At most ``max_sessions`` sessions are open (an ``initialize`` past
    that gets 503); a session idle for ``session_idle_timeout`` ends;
    a message larger than ``max_message_bytes`` gets 413. With
    ``allow_subscriptions=False``, 2026-07-28 discovery advertises no list
    changes and ``subscriptions/listen`` is method not found; earlier
    revisions are unchanged. ``registrations`` are built before the routes."""
    _require_registrations(registrations)
    info = _info(
        name,
        version,
        title=title,
        description=description,
        website_url=website_url,
        icons=icons,
        instructions=instructions,
        extensions=extensions,
        cache_hints=cache_hints,
    )

    @gen
    def routes():
        parsed = yield from _sessions.limits(max_sessions, session_idle_timeout, max_message_bytes)
        registry = yield from make_registry(protocols)
        yield from _http.serve(
            (yield from info),
            registry,
            path=path,
            allowed_origins=allowed_origins,
            allow_session_termination=allow_session_termination,
            limits=parsed,
            allow_subscriptions=allow_subscriptions,
        )

    return _serving(routes, registrations)


def layer_http_request_scoped[RE = Never, RR = Never](
    *,
    name: str,
    version: str,
    path: str,
    protocols: Sequence[ProtocolAdapter[Literal["2026-07-28"]]],
    title: str | None = None,
    description: str | None = None,
    website_url: str | None = None,
    icons: Sequence[Icon] = (),
    instructions: str | None = None,
    extensions: Mapping[str, Any] | None = None,
    allowed_origins: Sequence[str] | None = None,
    max_message_bytes: byte_size.Input = _sessions.DEFAULT_MAX_MESSAGE_BYTES,
    cache_hints: CacheHints | None = None,
    registrations: Layer[Any, RE, RR | McpServer | McpServerClient] | None = None,
) -> Layer[McpServer, IllegalArgumentError | RE, HttpRouter | RR]:
    """Serve sessionless MCP at ``path`` with each POST's execution belonging
    to that request: nothing keeps running after its response, and handlers see
    the request's services over the layer's. Sessionful revisions are refused
    (``IllegalArgumentError``, for an untyped caller).

    Tools, resources, prompts, completions, ``InputRequired`` round trips and
    a request's own progress and logs work as in ``layer_http``. There are no
    subscriptions (discovery advertises no list changes, ``subscriptions/listen``
    is method not found) or broadcast notifications, and DELETE gets 405."""
    _require_registrations(registrations)
    info = _info(
        name,
        version,
        title=title,
        description=description,
        website_url=website_url,
        icons=icons,
        instructions=instructions,
        extensions=extensions,
        cache_hints=cache_hints,
    )
    sessionful: tuple[AnyProtocolAdapter, ...] = tuple(p for p in protocols if not p.is_stateless)
    if sessionful:
        version_name = sessionful[0].protocol_version
        refused = IllegalArgumentError(
            "McpServer.layer_http_request_scoped does not support the sessionful "
            f"MCP protocol {version_name}"
        )
        return _serving(fail(refused), registrations)

    @gen
    def routes():
        parsed = yield from _sessions.limits(
            _sessions.DEFAULT_MAX_SESSIONS, _sessions.DEFAULT_IDLE_TIMEOUT, max_message_bytes
        )
        registry = yield from make_registry(protocols)
        yield from _http.serve(
            (yield from info),
            registry,
            path=path,
            allowed_origins=allowed_origins,
            allow_session_termination=False,
            limits=parsed,
            allow_subscriptions=False,
            request_services=True,
        )

    return _serving(routes, registrations)


def toolkit[N: LiteralString, RP, HE, R](
    toolkit: Toolkit[N, RP, HE, R],
) -> Layer[Never, Never, McpServer | Handlers[N] | R]:
    """A layer registering ``toolkit`` (see ``register_toolkit``). It needs
    the ``McpServer``: pass it to a transport as ``registrations``, or
    provide the transport to it."""
    return effect_discard(register_toolkit(toolkit))


def resource[E = Never, R = Never](
    *,
    uri: str,
    name: str,
    content: Effect[ResourceContent, E, R],
    title: str | None = None,
    description: str | None = None,
    mime_type: str | None = None,
    audience: Sequence[Role] | None = None,
    priority: float | None = None,
    annotations: Context[Never] | None = None,
) -> Layer[Never, Never, McpServer | R]:
    """A layer registering a resource (see ``register_resource``)."""
    registered = register_resource(
        uri=uri,
        name=name,
        content=content,
        title=title,
        description=description,
        mime_type=mime_type,
        audience=audience,
        priority=priority,
        annotations=annotations,
    )
    return effect_discard(registered)


def resource_template[*Ts, E = Never, R = Never](
    template: UriTemplate[*Ts],
    *,
    name: str,
    content: Callable[[str, *Ts], Effect[ResourceContent, E, R]],
    completion: Mapping[str, CompletionFunction] | None = None,
    title: str | None = None,
    description: str | None = None,
    mime_type: str | None = None,
    audience: Sequence[Role] | None = None,
    priority: float | None = None,
    annotations: Context[Never] | None = None,
) -> Layer[Never, Never, McpServer | R]:
    """A layer registering a resource template (see
    ``register_resource_template``)."""
    registered = register_resource_template(
        template,
        name=name,
        content=content,
        completion=completion,
        title=title,
        description=description,
        mime_type=mime_type,
        audience=audience,
        priority=priority,
        annotations=annotations,
    )
    return effect_discard(registered)


def prompt[P = Mapping[str, Never], E = Never, R = Never](
    *,
    name: str,
    content: Callable[[P], Effect[Sequence[PromptMessage] | str, E, R]],
    parameters: Codec[P, Any, Any, Any] | None = None,
    completion: Mapping[str, CompletionFunction] | None = None,
    title: str | None = None,
    description: str | None = None,
    annotations: Context[Never] | None = None,
) -> Layer[Never, Never, McpServer | R]:
    """A layer registering a prompt (see ``register_prompt``)."""
    registered = register_prompt(
        name=name,
        content=content,
        parameters=parameters,
        completion=completion,
        title=title,
        description=description,
        annotations=annotations,
    )
    return effect_discard(registered)


def skill(
    uri: str,
    files: Mapping[str, SkillFileInput],
    *,
    annotations: Context[Never] | None = None,
) -> Layer[Never, IllegalArgumentError, McpServer]:
    """A layer registering an Agent Skill (see ``register_skill``)::

    refunds = mcp_server.skill(
        "skill://billing/refunds/SKILL.md",
        {
            "SKILL.md": "---\nname: refunds\ndescription: Process refunds\n---\n",
            "references/policy.md": "Refunds above CHF 500 need approval.\n",
        },
    )
    """
    return effect_discard(register_skill(uri, files, annotations=annotations))


def decode_name_header(value: str) -> str | None:
    """An ``Mcp-Name`` header's name, base64-wrapped or not; ``None`` when
    malformed. For ``HttpRouter`` middleware identifying the tool, prompt or
    resource a 2026-07-28 request targets (earlier revisions name it only in
    the JSON-RPC body)."""
    return decode_routing_header(value)


__all__ = [
    "INTERNAL_TOOL_ERROR_MESSAGE",
    "CacheHint",
    "CacheHints",
    "CompletionContext",
    "CompletionFunction",
    "IllegalArgumentError",
    "McpServer",
    "McpServerService",
    "Middleware",
    "MiddlewareFunction",
    "MiddlewareMethod",
    "MiddlewareOptions",
    "MiddlewareSuccess",
    "PlatformError",
    "PromptEntry",
    "RequestRejected",
    "ResourceContent",
    "ResourceEntry",
    "ResourceNotFound",
    "ResourceTemplateEntry",
    "SkillFile",
    "SkillFileInput",
    "ToolEntry",
    "UriTemplate",
    "VisibilityCheck",
    "client_capabilities",
    "decode_name_header",
    "elicit",
    "layer",
    "layer_http",
    "layer_http_request_scoped",
    "layer_stdio",
    "make",
    "middleware",
    "prompt",
    "register_prompt",
    "register_resource",
    "register_resource_template",
    "register_skill",
    "register_toolkit",
    "resource",
    "resource_template",
    "run_stdio",
    "skill",
    "toolkit",
    "uri_template",
    "visibility",
]

publish(globals())
