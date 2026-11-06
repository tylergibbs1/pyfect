"""An MCP server (Effect's ``McpServer``): tools, resources, resource
templates, prompts and completions served to MCP clients over stdio or
Streamable HTTP.

Register what the server offers with layers (``toolkit``, ``resource``,
``resource_template``, ``prompt``) or effects (``register_*``), and run a
transport layer with them::

    server = mcp_server.layer_stdio(
        name="notes", version="1.0.0", protocols=(mcp_protocol.v2025_11_25,)
    )
    app = mcp_server.toolkit(NotesToolkit).pipe(layer.provide(NotesToolkit.to_layer(...)))
    app.pipe(layer.provide_merge(server)).pipe(layer.provide(stdio.layer)).launch()

A handler runs with the request's ``McpRequestContext`` and
``McpServerClient``; ``elicit`` asks the client's user for input and
``McpServerService.notify`` sends notifications.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, Literal, LiteralString, Never

from pyfect import byte_size
from pyfect._core import Effect
from pyfect.ai._mcp import http as _http
from pyfect.ai._mcp import sessions as _sessions
from pyfect.ai._mcp import stdio as _stdio
from pyfect.ai._mcp.core import (
    McpServer,
    McpServerService,
    PromptEntry,
    ResourceEntry,
    ResourceTemplateEntry,
    ToolEntry,
)
from pyfect.ai._mcp.dispatch import ServerInfo
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
from pyfect.ai.mcp_protocol import AnyProtocolAdapter, ProtocolAdapter, make_registry
from pyfect.ai.mcp_schema import CompletionContext, Icon, PromptMessage, Role
from pyfect.ai.toolkit import Handlers, Toolkit
from pyfect.context import Context
from pyfect.duration import Duration
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
) -> ServerInfo:
    return ServerInfo(
        name=name,
        version=version,
        title=title,
        description=description,
        website_url=website_url,
        icons=tuple(icons),
        instructions=instructions,
        extensions=extensions,
    )


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
    )
    return make_registry(protocols).flat_map(lambda registry: _stdio.serve(info, registry))


def layer_stdio(
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
) -> Layer[McpServer, IllegalArgumentError, Stdio]:
    """``run_stdio`` in the background of a layer providing the
    ``McpServer``. As in Effect, the fiber that built the layer is interrupted
    when the server ends: ``.launch()`` ends at the end of input, and
    ``run_main`` exits 130."""
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
    )

    @gen
    def started():
        yield from make_registry(protocols)
        builder = yield from current_fiber()
        ended = builder.interrupt().fork_daemon(start_immediately=True).as_void()
        yield from running.ignore().ensuring(ended).fork_scoped()

    return effect_discard(started).pipe(provide_merge(layer))


def layer_http(
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
    session_idle_timeout: Duration = _sessions.DEFAULT_IDLE_TIMEOUT,
    max_message_bytes: byte_size.Input = _sessions.DEFAULT_MAX_MESSAGE_BYTES,
) -> Layer[McpServer, IllegalArgumentError, HttpRouter]:
    """Serve MCP's Streamable HTTP transport at ``path`` of the router.

    A request with an ``Origin`` header not in ``allowed_origins`` is
    refused (403); one without an ``Origin`` is served. With
    ``allow_session_termination`` a client ends its session with DELETE.
    At most ``max_sessions`` sessions are open (an ``initialize`` past
    that gets 503); a session idle for ``session_idle_timeout`` seconds
    ends; a message larger than ``max_message_bytes`` gets 413. With
    ``allow_subscriptions=False``, 2026-07-28 discovery advertises no list
    changes and ``subscriptions/listen`` is method not found; earlier
    revisions are unchanged."""
    info = _info(
        name,
        version,
        title=title,
        description=description,
        website_url=website_url,
        icons=icons,
        instructions=instructions,
        extensions=extensions,
    )
    limits = _sessions.limits(max_sessions, session_idle_timeout, max_message_bytes)
    routes = limits.flat_map(
        lambda parsed: make_registry(protocols).flat_map(
            lambda registry: _http.serve(
                info,
                registry,
                path=path,
                allowed_origins=allowed_origins,
                allow_session_termination=allow_session_termination,
                limits=parsed,
                allow_subscriptions=allow_subscriptions,
            )
        )
    )
    return effect_discard(routes).pipe(provide_merge(layer))


def layer_http_request_scoped(
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
) -> Layer[McpServer, IllegalArgumentError, HttpRouter]:
    """Serve sessionless MCP at ``path`` with each POST's execution belonging
    to that request: nothing keeps running after its response, and handlers see
    the request's services over the layer's. Sessionful revisions are refused
    (``IllegalArgumentError``, for an untyped caller).

    Tools, resources, prompts, completions, ``InputRequired`` round trips and
    a request's own progress and logs work as in ``layer_http``. There are no
    subscriptions (discovery advertises no list changes, ``subscriptions/listen``
    is method not found) or broadcast notifications, and DELETE gets 405."""
    info = _info(
        name,
        version,
        title=title,
        description=description,
        website_url=website_url,
        icons=icons,
        instructions=instructions,
        extensions=extensions,
    )
    sessionful: tuple[AnyProtocolAdapter, ...] = tuple(p for p in protocols if not p.is_stateless)
    if sessionful:
        version_name = sessionful[0].protocol_version
        refused = IllegalArgumentError(
            "McpServer.layer_http_request_scoped does not support the sessionful "
            f"MCP protocol {version_name}"
        )
        return effect_discard(fail(refused)).pipe(provide_merge(layer))
    limits = _sessions.limits(
        _sessions.DEFAULT_MAX_SESSIONS, _sessions.DEFAULT_IDLE_TIMEOUT, max_message_bytes
    )
    routes = limits.flat_map(
        lambda parsed: make_registry(protocols).flat_map(
            lambda registry: _http.serve(
                info,
                registry,
                path=path,
                allowed_origins=allowed_origins,
                allow_session_termination=False,
                limits=parsed,
                allow_subscriptions=False,
                request_services=True,
            )
        )
    )
    return effect_discard(routes).pipe(provide_merge(layer))


def toolkit[N: LiteralString, RP, HE, R](
    toolkit: Toolkit[N, RP, HE, R],
) -> Layer[Never, Never, Handlers[N] | R]:
    """A layer registering ``toolkit`` (see ``register_toolkit``)."""
    registered: Layer[Never, Never, Any] = effect_discard(register_toolkit(toolkit))
    return registered.pipe(provide(layer))


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
) -> Layer[Never, Never, R]:
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
    return effect_discard(registered).pipe(provide(layer))


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
) -> Layer[Never, Never, R]:
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
    return effect_discard(registered).pipe(provide(layer))


def prompt[P = Mapping[str, Never], E = Never, R = Never](
    *,
    name: str,
    content: Callable[[P], Effect[Sequence[PromptMessage] | str, E, R]],
    parameters: Codec[P, Any, Any, Any] | None = None,
    completion: Mapping[str, CompletionFunction] | None = None,
    title: str | None = None,
    description: str | None = None,
    annotations: Context[Never] | None = None,
) -> Layer[Never, Never, R]:
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
    return effect_discard(registered).pipe(provide(layer))


__all__ = [
    "INTERNAL_TOOL_ERROR_MESSAGE",
    "CompletionContext",
    "CompletionFunction",
    "IllegalArgumentError",
    "McpServer",
    "McpServerService",
    "PlatformError",
    "PromptEntry",
    "ResourceContent",
    "ResourceEntry",
    "ResourceTemplateEntry",
    "ToolEntry",
    "UriTemplate",
    "client_capabilities",
    "elicit",
    "layer",
    "layer_http",
    "layer_http_request_scoped",
    "layer_stdio",
    "make",
    "prompt",
    "register_prompt",
    "register_resource",
    "register_resource_template",
    "register_toolkit",
    "resource",
    "resource_template",
    "run_stdio",
    "toolkit",
    "uri_template",
]
