"""``socket.server.make_web_socket`` on the ``websockets`` library (extra
``pyfect-dev[websockets]``; Effect's ``NodeSocketServer.makeWebSocket``).
Each accepted WebSocket waits, paused, until a ``run`` hands it to a handler,
which gets the native socket as ``WebSocket`` and the upgrade request as
``IncomingMessage``."""

from __future__ import annotations

import asyncio
import inspect
from http import HTTPStatus
from typing import Any, Never

from pyfect._extras import missing_extra

try:
    from websockets.asyncio.server import Server, ServerConnection, serve
    from websockets.http11 import Request
except ImportError as error:  # pragma: no cover - depends on the environment
    raise missing_extra("pyfect.socket.server.make_web_socket", "websockets", error) from error

from pyfect._core import Effect
from pyfect.effect import provide_service, succeed, sync
from pyfect.http._authority import parse_authority
from pyfect.http.live_server._listener import ABORT_GRACE_PERIOD
from pyfect.http.origin import AllowedOrigins, OriginPolicy
from pyfect.net.net_address import inet_address_from_native_unsafe
from pyfect.scope import Scope, acquire_release
from pyfect.socket._accepted import Accepted, Handler
from pyfect.socket._loop import run
from pyfect.socket._web_socket import (
    DEFAULT_MAX_MESSAGE_SIZE,
    WebSocket,
    WebSocketLike,
    from_web_socket,
)
from pyfect.socket.server import (
    IncomingMessage,
    SocketServerError,
    SocketServerOpenError,
    SocketServerService,
    report_unhandled,
)
from pyfect.socket.ws import WsWebSocket


class _WsIncoming:
    """An accepted WebSocket, paused until a handler reads it."""

    __slots__ = ("_request", "_ws")

    def __init__(self, ws: WsWebSocket, request: Request) -> None:
        self._ws = ws
        self._request = request

    def handle[E, R](self, handler: Handler[E, R]) -> Effect[None, Never, R]:
        ws = self._ws
        opened: Effect[WebSocketLike, Never, Scope] = acquire_release(
            succeed(ws), lambda w, _: sync(w.close)
        )
        socket = from_web_socket(opened, disable_reconnects=True)
        return (
            handler(socket)
            .pipe(provide_service(WebSocket, ws))
            .pipe(provide_service(IncomingMessage, self._request))
            .as_void()
            .catch_cause(report_unhandled)
        )

    def release(self) -> None:
        self._ws.close()

    def abort(self) -> None:
        self._ws.terminate()


def make_web_socket(
    port: int = 0, host: str | None = None, **serve_options: Any
) -> Effect[SocketServerService, SocketServerError, Scope]:
    return AllowedOrigins().flat_map(lambda policy: _make(port, host, policy, serve_options))


def _serve_options(options: dict[str, Any]) -> dict[str, Any]:
    """``websockets.serve``'s options: as a paused ``ws`` socket, an unread
    connection holds about one message (websockets queues 16 frames by
    default, each up to ``max_size``), and no permessage-deflate, which
    ``ws`` servers leave off."""
    return {"max_size": DEFAULT_MAX_MESSAGE_SIZE, "max_queue": 1, "compression": None, **options}


def _make(
    port: int, host: str | None, policy: OriginPolicy, serve_options: dict[str, Any]
) -> Effect[SocketServerService, SocketServerError, Scope]:
    accepted = Accepted()
    serve_options = _serve_options(serve_options)
    then = serve_options.pop("process_request", None)
    scheme = "wss" if serve_options.get("ssl") is not None else "ws"

    async def process_request(connection: ServerConnection, request: Request) -> Any:
        own = parse_authority(request.headers.get("Host", ""))
        if not policy.allows(request.headers.get("Origin"), own, scheme):
            return connection.respond(HTTPStatus.FORBIDDEN, "Origin not allowed\n")
        if then is None:
            return None
        answer = then(connection, request)
        return (await answer) if inspect.isawaitable(answer) else answer

    async def on_connection(connection: ServerConnection) -> None:
        ws = WsWebSocket(paused=True)
        request = connection.request
        assert request is not None  # websockets calls the handler after the handshake
        accepted.add(_WsIncoming(ws, request))
        await ws._serve(connection)  # pyright: ignore[reportPrivateUsage]

    async def start() -> Server:
        return await serve(
            on_connection, host, port, process_request=process_request, **serve_options
        )

    def stop(server: Server, _exit: object) -> Effect[None]:
        async def close() -> None:
            accepted.close()
            server.close()
            # websockets waits for every connection, one still in its TLS or
            # HTTP handshake too (up to its ``open_timeout``); Node's
            # ``server.close`` drops those at once.
            try:
                await asyncio.wait_for(server.wait_closed(), ABORT_GRACE_PERIOD.to_seconds())
            except TimeoutError:
                server.server.abort_clients()
                await server.wait_closed()

        return run(close).ignore()

    def opened(server: Server) -> SocketServerService:
        name = server.sockets[0].getsockname()
        return SocketServerService(inet_address_from_native_unsafe(name[0], name[1]), accepted)

    starting = run(start).map_error(lambda cause: SocketServerError(SocketServerOpenError(cause)))
    return acquire_release(starting, stop).map(opened)
