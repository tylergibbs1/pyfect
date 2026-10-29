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
    layer.merge(server, app).pipe(layer.provide(stdio.layer)).launch()

A handler runs with the request's ``McpRequestContext`` and
``McpServerClient``; ``elicit`` asks the client's user for input and
``McpServerService.notify`` sends notifications.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, LiteralString, Never

from pyfect._core import Effect
from pyfect.ai._mcp import http as _http
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
from pyfect.ai.mcp_protocol import AnyProtocolAdapter, make_registry
from pyfect.ai.mcp_schema import CompletionContext, Icon, PromptMessage, Role
from pyfect.ai.toolkit import Handlers, Toolkit
from pyfect.context import Context
from pyfect.effect import succeed
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
    """Serve the client on standard input and output until its input ends.
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
    ``McpServer``."""
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
    checked = make_registry(protocols).and_then(running.ignore().fork_scoped())
    return effect_discard(checked).pipe(provide_merge(layer))


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
) -> Layer[McpServer, IllegalArgumentError, HttpRouter]:
    """Serve MCP's Streamable HTTP transport at ``path`` of the router.

    A request with an ``Origin`` header not in ``allowed_origins`` is
    refused (403); one without an ``Origin`` is served. With
    ``allow_session_termination`` a client ends its session with DELETE."""
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
    routes = make_registry(protocols).flat_map(
        lambda registry: _http.serve(
            info,
            registry,
            path=path,
            allowed_origins=allowed_origins,
            allow_session_termination=allow_session_termination,
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
    "McpServer",
    "McpServerService",
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
