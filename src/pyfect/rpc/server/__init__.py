"""RPC servers (Effect's ``RpcServer``).

``layer(Group)`` runs a server of the group over the ``ServerProtocol``
in the context; ``layer_http(Group, path=...)`` serves it on an
``HttpRouter`` route, over WebSockets (the default) or HTTP POSTs;
``layer_protocol_socket_server`` over the connections of a
``SocketServer``; ``layer_protocol_stdio`` over standard input and output;
``layer_protocol_worker_runner`` inside a worker,
serving its parent. The serialization (``RpcSerialization``) and the
group's handlers come from the context.
"""

from __future__ import annotations

from typing import Literal, Never, cast

from pyfect._core import Effect
from pyfect.effect import gen
from pyfect.http.router import HttpRouter
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.layer import provide as layer_provide
from pyfect.rpc.group import HandlersFor, RpcGroup
from pyfect.rpc.serialization import RpcSerialization
from pyfect.rpc.server._core import RpcServer, ServerOptions, make_no_serialization
from pyfect.rpc.server._protocol import (
    ProtocolParts,
    ServerProtocol,
    ServerProtocolService,
    with_run,
)
from pyfect.rpc.server._serialized import layer, make
from pyfect.rpc.server._stdio import layer_protocol_stdio, make_protocol_stdio
from pyfect.rpc.server._transports import (
    BufferSize,
    HttpEffect,
    HttpProtocol,
    make_protocol_socket_server,
    make_protocol_with_http_effect,
    make_protocol_with_http_effect_websocket,
    make_socket_protocol,
)
from pyfect.rpc.server._worker import (
    layer_protocol_worker_runner,
    make_protocol_worker_runner,
)
from pyfect.scope import Scope, fork_scoped
from pyfect.socket.server import SocketServer


def make_protocol_http(
    path: str, *, stream_buffer_size: BufferSize = 16
) -> Effect[ServerProtocolService, Never, RpcSerialization | HttpRouter]:
    """A server protocol over HTTP POSTs to ``path`` of the router."""

    @gen
    def make_():
        made = yield from make_protocol_with_http_effect(stream_buffer_size=stream_buffer_size)
        router = yield from HttpRouter()
        yield from router.add("POST", path, made.http_effect)
        return made.protocol

    return make_


def make_protocol_websocket(
    path: str,
) -> Effect[ServerProtocolService, Never, RpcSerialization | HttpRouter]:
    """A server protocol over WebSockets upgraded from GETs of ``path``."""

    @gen
    def make_():
        made = yield from make_protocol_with_http_effect_websocket()
        router = yield from HttpRouter()
        yield from router.add("GET", path, made.http_effect)
        return made.protocol

    return make_


def layer_protocol_http(
    path: str, *, stream_buffer_size: BufferSize = 16
) -> Layer[ServerProtocol, Never, RpcSerialization | HttpRouter]:
    return layer_effect(
        ServerProtocol, make_protocol_http(path, stream_buffer_size=stream_buffer_size)
    )


def layer_protocol_websocket(
    path: str,
) -> Layer[ServerProtocol, Never, RpcSerialization | HttpRouter]:
    return layer_effect(ServerProtocol, make_protocol_websocket(path))


layer_protocol_socket_server: Layer[ServerProtocol, Never, RpcSerialization | SocketServer] = (
    layer_effect(ServerProtocol, make_protocol_socket_server())
)


def layer_http[G: RpcGroup](
    group: type[G],
    *,
    path: str,
    protocol: Literal["http", "websocket"] = "websocket",
    options: ServerOptions | None = None,
    stream_buffer_size: BufferSize = 16,
) -> Layer[Never, Never, RpcSerialization | HttpRouter | HandlersFor[G]]:
    """A server of ``group`` on the route ``path`` of the router (Effect's
    ``RpcServer.layerHttp``)."""
    transport = (
        layer_protocol_http(path, stream_buffer_size=stream_buffer_size)
        if protocol == "http"
        else layer_protocol_websocket(path)
    )
    return layer(group, options).pipe(layer_provide(transport))


def _to_http_effect[G: RpcGroup](
    group: type[G],
    made: Effect[HttpProtocol, Never, RpcSerialization],
    options: ServerOptions | None,
) -> Effect[HttpEffect, Never, Scope | RpcSerialization | HandlersFor[G]]:
    from pyfect.effect import provide_service

    @gen
    def run():
        protocol = yield from made
        # pyright cannot remove one member from a union holding a TypeVar.
        running = cast("Effect[Never, Never, ServerProtocol | Scope]", make(group, options))
        server = running.pipe(provide_service(ServerProtocol, protocol.protocol))
        yield from fork_scoped(server)
        return protocol.http_effect

    return cast("Effect[HttpEffect, Never, Scope | RpcSerialization | HandlersFor[G]]", run)


def to_http_effect[G: RpcGroup](
    group: type[G], *, options: ServerOptions | None = None, stream_buffer_size: BufferSize = 16
) -> Effect[HttpEffect, Never, Scope | RpcSerialization | HandlersFor[G]]:
    """A server of ``group`` running in the current scope, and the HTTP
    handler of its POSTs (Effect's ``RpcServer.toHttpEffect``)."""
    made = make_protocol_with_http_effect(stream_buffer_size=stream_buffer_size)
    return _to_http_effect(group, made, options)


def to_http_effect_websocket[G: RpcGroup](
    group: type[G], *, options: ServerOptions | None = None
) -> Effect[HttpEffect, Never, Scope | RpcSerialization | HandlersFor[G]]:
    """``to_http_effect`` over WebSockets."""
    return _to_http_effect(group, make_protocol_with_http_effect_websocket(), options)


__all__ = [
    "HttpEffect",
    "HttpProtocol",
    "ProtocolParts",
    "RpcServer",
    "ServerOptions",
    "ServerProtocol",
    "ServerProtocolService",
    "layer",
    "layer_http",
    "layer_protocol_http",
    "layer_protocol_socket_server",
    "layer_protocol_stdio",
    "layer_protocol_websocket",
    "layer_protocol_worker_runner",
    "make",
    "make_no_serialization",
    "make_protocol_http",
    "make_protocol_socket_server",
    "make_protocol_stdio",
    "make_protocol_websocket",
    "make_protocol_with_http_effect",
    "make_protocol_with_http_effect_websocket",
    "make_protocol_worker_runner",
    "make_socket_protocol",
    "to_http_effect",
    "to_http_effect_websocket",
    "with_run",
]
