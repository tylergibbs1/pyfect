"""A cluster runner whose RPCs travel over HTTP or WebSockets (Effect's
``HttpRunner``).

``layer_client_protocol_http`` / ``layer_client_protocol_websocket`` dial
other runners at ``http(s)://host:port/path`` / ``ws(s)://host:port/path``;
``to_http_effect`` / ``to_http_effect_websocket`` serve the runner protocol
as an HTTP handler; ``layer_http_options`` / ``layer_websocket_options``
add it to the ``HttpRouter``, and ``layer_http`` / ``layer_websocket``
serve it at ``/`` on the ``HttpServer``. The ``*_client_only`` layers join
the cluster as a sender only."""

from __future__ import annotations

from typing import Any, Never, cast

from pyfect import layer as layer_
from pyfect.cluster import runner_server, runners, sharding
from pyfect.cluster.message_storage import MessageStorage
from pyfect.cluster.runner_address import RunnerAddress
from pyfect.cluster.runner_health import RunnerHealth
from pyfect.cluster.runner_storage import RunnerStorage
from pyfect.cluster.runners import RpcClientProtocol, RpcClientProtocolService, Rpcs, Runners
from pyfect.cluster.sharding import Sharding
from pyfect.cluster.sharding_config import ShardingConfig
from pyfect.effect import Effect, gen, provide_context, provide_service
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.request import HttpClientRequest
from pyfect.http.router import HttpRouter, serve
from pyfect.http.server import HttpServer
from pyfect.layer import Layer
from pyfect.net.net_address import format_url_host_string
from pyfect.rpc.client import ClientProtocolService, make_protocol_socket
from pyfect.rpc.client import make_protocol_http as make_client_protocol_http
from pyfect.rpc.serialization import RpcSerialization, RpcSerializationService
from pyfect.rpc.server import (
    HttpEffect,
    HttpProtocol,
    ServerOptions,
    ServerProtocol,
    layer_protocol_http,
    layer_protocol_websocket,
    make,
    make_protocol_with_http_effect,
    make_protocol_with_http_effect_websocket,
)
from pyfect.scope import Scope, fork_scoped
from pyfect.socket import Socket, WebSocketConstructor, make_web_socket

_SERVER_OPTIONS = ServerOptions(
    span_prefix="RunnerServer", disable_tracing=True, disable_fatal_defects=True
)


def _url(scheme: str, address: RunnerAddress, path: str) -> str:
    rooted = path if path.startswith("/") else f"/{path}"
    return f"{scheme}://{format_url_host_string(address.host)}:{address.port}{rooted}"


def _http_client_protocol(
    serialization: RpcSerializationService, client: HttpClientService[Any], path: str, https: bool
) -> RpcClientProtocolService:
    def make_protocol(address: RunnerAddress) -> Effect[ClientProtocolService, Never, Scope]:
        base = _url("https" if https else "http", address, path)

        def prepend(request: HttpClientRequest) -> HttpClientRequest:
            return request.prepend_url(base)

        return make_client_protocol_http(client.map_request(prepend)).pipe(
            provide_service(RpcSerialization, serialization)
        )

    return RpcClientProtocolService(make=make_protocol, codec_for=serialization.codec_for)


def layer_client_protocol_http(
    *, path: str, https: bool = False
) -> Layer[RpcClientProtocol, Never, RpcSerialization | HttpClient]:
    """Dial runners over HTTP POSTs to ``path`` (``https`` for TLS)."""

    @gen
    def make_():
        serialization = yield from RpcSerialization()
        client = yield from HttpClient()
        return _http_client_protocol(serialization, client, path, https)

    return layer_.effect(RpcClientProtocol, make_)


layer_client_protocol_http_default: Layer[
    RpcClientProtocol, Never, RpcSerialization | HttpClient
] = layer_client_protocol_http(path="/")
"""``layer_client_protocol_http`` dialing runners over HTTP at ``/``."""


def layer_client_protocol_websocket(
    *, path: str, https: bool = False
) -> Layer[RpcClientProtocol, Never, RpcSerialization | WebSocketConstructor]:
    """Dial runners over WebSockets at ``path`` (``https`` for ``wss``)."""

    @gen
    def make_():
        serialization = yield from RpcSerialization()
        constructor = yield from WebSocketConstructor()

        def make_protocol(address: RunnerAddress) -> Effect[ClientProtocolService, Never, Scope]:
            @gen
            def connect():
                url = _url("wss" if https else "ws", address, path)
                socket = yield from make_web_socket(url).pipe(
                    provide_service(WebSocketConstructor, constructor)
                )
                return (
                    yield from make_protocol_socket()
                    .pipe(provide_service(Socket, socket))
                    .pipe(provide_service(RpcSerialization, serialization))
                )

            return connect

        return RpcClientProtocolService(make=make_protocol, codec_for=serialization.codec_for)

    return layer_.effect(RpcClientProtocol, make_)


layer_client_protocol_websocket_default: Layer[
    RpcClientProtocol, Never, RpcSerialization | WebSocketConstructor
] = layer_client_protocol_websocket(path="/")
"""``layer_client_protocol_websocket`` dialing runners over a WebSocket at ``/``."""


def _serving(
    made: Effect[HttpProtocol, Never, RpcSerialization],
) -> Effect[HttpEffect, Never, Scope | RpcSerialization | Sharding | MessageStorage]:
    @gen
    def run():
        protocol = yield from made
        with_protocol = provide_service(ServerProtocol, protocol.protocol)
        handlers = yield from runner_server.layer_handlers.build().pipe(with_protocol)
        server: Effect[Never, Never, Any] = make(Rpcs, _SERVER_OPTIONS)
        yield from fork_scoped(server.pipe(provide_context(handlers)).pipe(with_protocol))
        return protocol.http_effect

    return run


to_http_effect: Effect[HttpEffect, Never, Scope | RpcSerialization | Sharding | MessageStorage] = (
    _serving(make_protocol_with_http_effect())
)
"""The runner protocol served as an HTTP handler of POSTs, its server
running in the current scope (Effect's ``HttpRunner.toHttpEffect``)."""

to_http_effect_websocket: Effect[
    HttpEffect, Never, Scope | RpcSerialization | Sharding | MessageStorage
] = _serving(make_protocol_with_http_effect_websocket())
"""``to_http_effect`` over WebSockets."""

layer_client: Layer[
    Sharding | Runners,
    Never,
    ShardingConfig | RpcClientProtocol | MessageStorage | RunnerStorage | RunnerHealth,
] = sharding.layer.pipe(layer_.provide_merge(runners.layer_rpc))
"""``Sharding`` and the RPC ``Runners`` over the ``RpcClientProtocol``."""

type _ServerNeeds = (
    RunnerStorage
    | RunnerHealth
    | RpcSerialization
    | MessageStorage
    | ShardingConfig
    | RpcClientProtocol
)


def layer_http_options(*, path: str) -> Layer[Sharding | Runners, Never, _ServerNeeds | HttpRouter]:
    """A runner serving the runner protocol on POSTs to ``path`` of the
    ``HttpRouter``."""
    return runner_server.layer_with_clients.pipe(layer_.provide(layer_protocol_http(path)))


def layer_websocket_options(
    *, path: str
) -> Layer[Sharding | Runners, Never, _ServerNeeds | HttpRouter]:
    """A runner serving the runner protocol on WebSockets at ``path`` of the
    ``HttpRouter``."""
    return runner_server.layer_with_clients.pipe(layer_.provide(layer_protocol_websocket(path)))


def _served(
    routes: Layer[Sharding | Runners, Never, _ServerNeeds | HttpRouter],
) -> Layer[Sharding | Runners, Never, _ServerNeeds | HttpServer]:
    # ``serve`` reads the routes' other requirements from where it is built;
    # its overloads type only the router's own.
    return cast(
        "Layer[Sharding | Runners, Never, _ServerNeeds | HttpServer]", serve(cast(Any, routes))
    )


layer_http: Layer[
    Sharding | Runners,
    Never,
    RpcSerialization
    | ShardingConfig
    | HttpClient
    | HttpServer
    | MessageStorage
    | RunnerStorage
    | RunnerHealth,
] = _served(layer_http_options(path="/")).pipe(layer_.provide(layer_client_protocol_http_default))
"""A runner serving at ``/`` of the ``HttpServer`` and dialing others
over HTTP."""

layer_http_client_only: Layer[
    Sharding | Runners,
    Never,
    RpcSerialization | ShardingConfig | HttpClient | MessageStorage | RunnerStorage,
] = runner_server.layer_client_only.pipe(layer_.provide(layer_client_protocol_http_default))
"""A sender-only member of the cluster, dialing runners over HTTP."""

layer_websocket: Layer[
    Sharding | Runners,
    Never,
    RpcSerialization
    | ShardingConfig
    | WebSocketConstructor
    | HttpServer
    | MessageStorage
    | RunnerStorage
    | RunnerHealth,
] = _served(layer_websocket_options(path="/")).pipe(
    layer_.provide(layer_client_protocol_websocket_default)
)
"""A runner serving WebSockets at ``/`` of the ``HttpServer`` and dialing
others over WebSockets."""

layer_websocket_client_only: Layer[
    Sharding | Runners,
    Never,
    RpcSerialization | ShardingConfig | WebSocketConstructor | MessageStorage | RunnerStorage,
] = runner_server.layer_client_only.pipe(layer_.provide(layer_client_protocol_websocket_default))
"""A sender-only member of the cluster, dialing runners over WebSockets."""

__all__ = [
    "layer_client",
    "layer_client_protocol_http",
    "layer_client_protocol_http_default",
    "layer_client_protocol_websocket",
    "layer_client_protocol_websocket_default",
    "layer_http",
    "layer_http_client_only",
    "layer_http_options",
    "layer_websocket",
    "layer_websocket_client_only",
    "layer_websocket_options",
    "to_http_effect",
    "to_http_effect_websocket",
]
