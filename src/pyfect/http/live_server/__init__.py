"""The live HTTP/1.1 server (Effect's ``NodeHttpServer``), on the standard
library's asyncio streams: no ASGI server needed.

::

    main = server.serve(app).pipe(layer.provide(live_server.layer(port=8080)))

Requests are read with keep-alive, ``Content-Length`` or chunked bodies,
``Expect: 100-continue`` (the ``100`` is sent when the app first reads the
body) and upgrades (``Upgrade: websocket`` speaks RFC 6455, as ``ws``
does under Node); responses get Node's framing and headers. When the
serving scope closes the server stops accepting, closes idle connections
and gives the busy ones ``graceful_shutdown_timeout`` to finish: as Node's
server does, they go on answering keep-alive requests until they have been
idle for ``keep_alive_timeout``.
"""

from __future__ import annotations

from typing import Any, NotRequired, TypedDict, Unpack

from pyfect._core import Effect
from pyfect.duration import Duration, to_seconds
from pyfect.effect import fail, provide_service, suspend
from pyfect.file_system import FileSystem
from pyfect.file_system import layer as file_system_layer
from pyfect.http.client import HttpClient
from pyfect.http.etag import Generator
from pyfect.http.etag import layer_weak as etag_layer_weak
from pyfect.http.http_effect import to_handled
from pyfect.http.httpx_client import layer as httpx_layer
from pyfect.http.live_server._exchange import Exchange
from pyfect.http.live_server._listener import ConnectionState, Listen, Listener, listen
from pyfect.http.live_server._serve import Timeouts, serve_connection
from pyfect.http.platform import HttpPlatform
from pyfect.http.platform import layer_live as platform_layer_live
from pyfect.http.server import (
    HttpApp,
    HttpServer,
    HttpServerService,
    Middleware,
    layer_test_client,
)
from pyfect.http.server import make as make_server
from pyfect.http.server_request import HttpServerRequest, RequestProtocol, SourceRequest
from pyfect.layer import Layer, merge, provide_merge
from pyfect.layer import effect as layer_effect
from pyfect.path import Path
from pyfect.path import layer as path_layer
from pyfect.redacted import Redacted
from pyfect.scope import Scope
from pyfect.socket._loop import get_loop
from pyfect.socket._socket import PemInput, TlsUpgradeOptions
from pyfect.socket._tls import server_context
from pyfect.socket._web_socket import DEFAULT_MAX_MESSAGE_SIZE
from pyfect.socket.server import SocketServerError, SocketServerOpenError


class Options(TypedDict):
    port: NotRequired[int]
    """0 (the default): any free port."""
    host: NotRequired[str]
    """Every interface by default."""
    graceful_shutdown_timeout: NotRequired[Duration]
    """How long requests in flight may run once the server closes (20s)."""
    keep_alive_timeout: NotRequired[Duration]
    """How long a connection may be idle between requests (Node's
    ``keepAliveTimeout``, 5s)."""
    headers_timeout: NotRequired[Duration]
    """How long a request head may take to arrive (Node's
    ``headersTimeout``, 60s); a started one is answered with 408."""
    request_timeout: NotRequired[Duration]
    """How long a whole request (head and body) may take to arrive (Node's
    ``requestTimeout``, 300s); a body that does not fails its read and the
    connection is closed."""
    websocket_max_message_size: NotRequired[int]
    """The longest WebSocket message a client may send (16 MiB, as uvicorn's
    ``ws_max_size``); a longer one closes the connection with 1009."""


class TlsOptions(Options):
    cert: PemInput
    key: Redacted[PemInput] | PemInput


def _serve(listener: Listener, protocol: RequestProtocol, options: Options) -> HttpServerService:
    timeout = to_seconds(options.get("graceful_shutdown_timeout", 20))
    timeouts = Timeouts(
        keep_alive=to_seconds(options.get("keep_alive_timeout", 5)),
        headers=to_seconds(options.get("headers_timeout", 60)),
        request=to_seconds(options.get("request_timeout", 300)),
    )
    max_message = options.get("websocket_max_message_size", DEFAULT_MAX_MESSAGE_SIZE)

    def serve(app: HttpApp, middleware: Middleware | None) -> Effect[None, Any, Scope]:
        def handle(request: SourceRequest, exchange: Exchange) -> Effect[None]:
            handled = to_handled(app, exchange.respond, middleware)
            return handled.pipe(provide_service(HttpServerRequest, request))

        def serve_one(state: ConnectionState) -> Effect[None]:
            return serve_connection(
                listener, state, handle, protocol, timeouts, websocket_max_message_size=max_message
            )

        served = listener.run(serve_one, timeout)
        return served.fork_scoped().as_void()

    assert listener.address is not None
    return make_server(serve=serve, address=listener.address)


def _make(
    listen_with: Listen, protocol: RequestProtocol, options: Options, tls: Any = None
) -> Effect[HttpServerService, SocketServerError, Scope]:
    return listen(listen_with, tls).map(lambda listener: _serve(listener, protocol, options))


def make(**options: Unpack[Options]) -> Effect[HttpServerService, SocketServerError, Scope]:
    """An ``HttpServer`` listening on ``host:port`` until the scope closes."""
    host, port = options.get("host"), options.get("port", 0)
    return _make(lambda factory: get_loop().create_server(factory, host, port), "http", options)


def make_unix(
    path: str, **options: Unpack[Options]
) -> Effect[HttpServerService, SocketServerError, Scope]:
    """An ``HttpServer`` on the Unix socket at ``path``."""
    return _make(lambda factory: get_loop().create_unix_server(factory, path), "http", options)


def make_tls(**options: Unpack[TlsOptions]) -> Effect[HttpServerService, SocketServerError, Scope]:
    """An HTTPS server: requests' ``protocol`` is ``https``."""
    key = options["key"]
    tls = TlsUpgradeOptions(
        cert=options["cert"], key=key if isinstance(key, Redacted) else Redacted(key)
    )

    def body() -> Effect[HttpServerService, SocketServerError, Scope]:
        try:
            context = server_context(tls)
        except (OSError, ValueError) as cause:
            return fail(SocketServerError(SocketServerOpenError(cause)))
        host, port = options.get("host"), options.get("port", 0)
        return _make(
            lambda factory: get_loop().create_server(factory, host, port), "https", options, context
        )

    return suspend(body)


layer_services: Layer[Path | HttpPlatform | FileSystem | Generator] = merge(
    platform_layer_live, path_layer, etag_layer_weak, file_system_layer
)
"""What a live server's apps use: ``HttpPlatform``, ``Path``, weak ETags
and the live ``FileSystem`` (Node's ``layerHttpServices``)."""


def layer_server(**options: Unpack[Options]) -> Layer[HttpServer, SocketServerError]:
    return layer_effect(HttpServer, make(**options))


def layer(
    **options: Unpack[Options],
) -> Layer[HttpServer | Path | HttpPlatform | FileSystem | Generator, SocketServerError]:
    """The server and the services its apps use."""
    return merge(layer_server(**options), layer_services)


def layer_test(
    **options: Unpack[Options],
) -> Layer[
    HttpServer | Path | HttpPlatform | FileSystem | Generator | HttpClient, SocketServerError
]:
    """A server on a free loopback port, its services, and an ``HttpClient``
    (httpx) sending to it."""
    server = layer(**{"host": "127.0.0.1", **options})
    return layer_test_client.pipe(provide_merge(httpx_layer)).pipe(provide_merge(server))


__all__ = [
    "Options",
    "SocketServerError",
    "TlsOptions",
    "layer",
    "layer_server",
    "layer_services",
    "layer_test",
    "make",
    "make_tls",
    "make_unix",
]
