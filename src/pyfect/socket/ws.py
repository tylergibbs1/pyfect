"""WebSockets on the ``websockets`` library (extra ``pyfect[websockets]``;
Effect's ``NodeSocket.layerWebSocketConstructorWS`` and
``NodeSocketServer.makeWebSocket``).

``WsWebSocket`` is a ``WebSocketLike`` over a ``websockets`` connection run
on the socket loop thread; its events are dispatched there. ``layer_web_socket_constructor``
provides ``WebSocketConstructor`` with it, ``layer_web_socket`` a client
``Socket``, and ``make_server`` a ``SocketServerService`` whose handlers get
each accepted WebSocket (also as the ``WebSocket`` service)::

    socket = make_web_socket("ws://127.0.0.1:8080").pipe(
        provide(layer_web_socket_constructor)
    )
"""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Mapping, Sequence
from typing import Any, Never

from websockets.asyncio.client import connect
from websockets.asyncio.connection import Connection as WsConnection
from websockets.asyncio.server import Server, ServerConnection, serve
from websockets.exceptions import ConnectionClosed
from websockets.typing import Subprotocol

from pyfect._core import Effect
from pyfect._js import to_well_formed
from pyfect.duration import Duration
from pyfect.effect import provide_service, succeed, sync
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.layer import provide as layer_provide
from pyfect.layer import succeed as layer_succeed
from pyfect.net.net_address import inet_address_from_native_unsafe
from pyfect.scope import Scope, acquire_release
from pyfect.socket._accepted import Accepted, Handler
from pyfect.socket._loop import call_soon, get_loop, run
from pyfect.socket._socket import Socket
from pyfect.socket._web_socket import (
    CLOSED,
    CLOSING,
    CONNECTING,
    OPEN,
    Listener,
    WebSocket,
    WebSocketClientOptions,
    WebSocketConstructor,
    WebSocketEvent,
    WebSocketEventType,
    WebSocketLike,
    from_web_socket,
)
from pyfect.socket._web_socket import (
    layer_web_socket as layer_web_socket_with,
)
from pyfect.socket.server import (
    SocketServer,
    SocketServerError,
    SocketServerOpenError,
    SocketServerService,
    report_unhandled,
)


class WsWebSocket:
    """A browser-style WebSocket over a ``websockets`` connection. Methods
    may be called from any thread; listeners run on the socket loop.
    ``pause`` stops reading messages until ``resume``."""

    def __init__(self, *, paused: bool = False) -> None:
        self._lock = threading.Lock()
        self._listeners: dict[WebSocketEventType, list[tuple[Listener, bool]]] = {}
        self._state = CONNECTING
        self._paused = paused
        self._outgoing: asyncio.Queue[bytes | str | tuple[int, str]] = asyncio.Queue()
        self._flowing = asyncio.Event()
        if not paused:
            self._flowing.set()
        self._task: asyncio.Task[None] | None = None
        self._connection: WsConnection | None = None

    @classmethod
    def connect(cls, url: str, options: WebSocketClientOptions) -> WsWebSocket:
        """Open a client connection to ``url``."""
        ws = cls()
        call_soon(lambda: ws._begin(url, options))
        return ws

    # --- WebSocketLike -----------------------------------------------------

    @property
    def ready_state(self) -> int:
        return self._state

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def connection(self) -> WsConnection | None:
        """The ``websockets`` connection, once open."""
        return self._connection

    def add_event_listener(
        self, type: WebSocketEventType, listener: Listener, *, once: bool = False
    ) -> None:
        with self._lock:
            entries = self._listeners.setdefault(type, [])
            if all(entry is not listener for entry, _ in entries):
                entries.append((listener, once))

    def remove_event_listener(self, type: WebSocketEventType, listener: Listener) -> None:
        with self._lock:
            entries = self._listeners.get(type, [])
            entries[:] = [(entry, once) for entry, once in entries if entry is not listener]

    def send(self, data: bytes | str) -> None:
        state = self._state
        if state == CONNECTING:
            raise RuntimeError("WebSocket is not open: readyState 0 (CONNECTING)")
        if state == OPEN:
            # A browser sends a USVString: lone surrogates become U+FFFD.
            message = to_well_formed(data) if isinstance(data, str) else data
            get_loop().call_soon_threadsafe(self._outgoing.put_nowait, message)

    def close(self, code: int | None = None, reason: str | None = None) -> None:
        """Start the closing handshake; as in a browser, ``code`` must be
        1000 or 3000 to 4999 and ``reason`` at most 123 UTF-8 bytes."""
        if code is not None and code != 1000 and not 3000 <= code <= 4999:
            raise ValueError(f"invalid WebSocket close code: {code}")
        text = to_well_formed(reason or "")
        if len(text.encode()) > 123:
            raise ValueError("WebSocket close reason is longer than 123 bytes")
        call_soon(lambda: self._close(1000 if code is None else code, text))

    def pause(self) -> None:
        self._paused = True
        call_soon(self._flowing.clear)

    def resume(self) -> None:
        self._paused = False
        call_soon(self._flowing.set)

    def terminate(self) -> None:
        """Drop the connection without a closing handshake."""

        def abort() -> None:
            connection = self._connection
            if connection is not None:
                connection.transport.abort()
            elif self._task is not None:
                self._task.cancel()

        call_soon(abort)

    # --- loop side -----------------------------------------------------------

    def _dispatch(self, type: WebSocketEventType, event: WebSocketEvent) -> None:
        with self._lock:
            entries = self._listeners.get(type, [])
            called = list(entries)
            entries[:] = [(listener, once) for listener, once in entries if not once]
        for listener, _ in called:
            try:
                listener(event)
            except Exception as error:
                get_loop().call_exception_handler(
                    {"message": "WebSocket listener failed", "exception": error}
                )

    def _close(self, code: int, reason: str) -> None:
        if self._state == CONNECTING:
            self._state = CLOSING
            if self._task is not None:
                self._task.cancel()
        elif self._state == OPEN:
            self._state = CLOSING
            self._outgoing.put_nowait((code, reason))

    def _begin(self, url: str, options: WebSocketClientOptions) -> None:
        task = get_loop().create_task(self._connect(url, options))
        self._task = task

        def done(finished: asyncio.Task[None]) -> None:
            # Closed (or terminated) while connecting.
            if finished.cancelled():
                self._closed_before_open(_closed_while_connecting())

        task.add_done_callback(done)

    async def _connect(self, url: str, options: WebSocketClientOptions) -> None:
        protocols = options.protocols
        subprotocols = (
            None
            if protocols is None
            else [
                Subprotocol(p) for p in ([protocols] if isinstance(protocols, str) else protocols)
            ]
        )
        try:
            connection = await connect(
                url,
                subprotocols=subprotocols,
                additional_headers=None if options.headers is None else dict(options.headers),
                open_timeout=None,
                proxy=None,
            )
        except Exception as error:
            self._closed_before_open(error)
            return
        if self._state != CONNECTING:
            await connection.close()
            self._closed_before_open(_closed_while_connecting())
            return
        await self._serve(connection)

    def _closed_before_open(self, error: BaseException) -> None:
        self._state = CLOSED
        self._dispatch("error", WebSocketEvent(type="error", data=error))
        self._dispatch("close", WebSocketEvent(type="close", code=1006, reason=""))

    async def _serve(self, connection: WsConnection) -> None:
        self._connection = connection
        self._state = OPEN
        self._dispatch("open", WebSocketEvent(type="open"))
        sender = asyncio.get_running_loop().create_task(self._send_all(connection))
        try:
            while True:
                await self._wait_flowing(connection)
                try:
                    message = await connection.recv()
                except ConnectionClosed:
                    break
                self._dispatch("message", WebSocketEvent(type="message", data=message))
        finally:
            sender.cancel()
            self._state = CLOSED
        code = connection.close_code
        self._dispatch(
            "close",
            WebSocketEvent(
                type="close",
                code=1006 if code is None else code,
                reason=connection.close_reason or "",
            ),
        )

    async def _wait_flowing(self, connection: WsConnection) -> None:
        """Wait while paused; once the connection closes, the messages it
        still holds are delivered regardless, so the close is seen."""
        if self._flowing.is_set():
            return
        loop = asyncio.get_running_loop()
        waits = {loop.create_task(self._flowing.wait()), loop.create_task(connection.wait_closed())}
        try:
            await asyncio.wait(waits, return_when=asyncio.FIRST_COMPLETED)
        finally:
            for wait in waits:
                wait.cancel()

    async def _send_all(self, connection: WsConnection) -> None:
        try:
            while True:
                item = await self._outgoing.get()
                if isinstance(item, tuple):
                    await connection.close(*item)
                    return
                await connection.send(item)
        except ConnectionClosed:
            pass
        except Exception as error:
            # A send that fails ends the connection, so readers see it close.
            get_loop().call_exception_handler(
                {"message": "WebSocket send failed", "exception": error}
            )
            connection.transport.abort()


def _closed_while_connecting() -> Exception:
    return RuntimeError("WebSocket was closed before the connection was established")


layer_web_socket_constructor: Layer[WebSocketConstructor] = layer_succeed(
    WebSocketConstructor, WsWebSocket.connect
)
"""``WebSocketConstructor`` on the ``websockets`` client."""


def layer_web_socket(
    url: str | Effect[str],
    *,
    open_timeout: Duration | None = None,
    protocols: str | Sequence[str] | None = None,
    headers: Mapping[str, str] | None = None,
    high_water_mark: int | None = None,
) -> Layer[Socket]:
    """``Socket`` as a WebSocket client on the ``websockets`` library."""
    client = layer_web_socket_with(
        url,
        open_timeout=open_timeout,
        protocols=protocols,
        headers=headers,
        high_water_mark=high_water_mark,
    )
    return client.pipe(layer_provide(layer_web_socket_constructor))


# --- server -----------------------------------------------------------------


class _WsIncoming:
    """An accepted WebSocket, paused until a handler reads it."""

    __slots__ = ("_ws",)

    def __init__(self, ws: WsWebSocket) -> None:
        self._ws = ws

    def handle[E, R](self, handler: Handler[E, R]) -> Effect[None, Never, R]:
        ws = self._ws
        opened: Effect[WebSocketLike, Never, Scope] = acquire_release(
            succeed(ws), lambda w, _: sync(w.close)
        )
        socket = from_web_socket(opened)
        return (
            handler(socket)
            .pipe(provide_service(WebSocket, ws))
            .as_void()
            .catch_cause(report_unhandled)
        )

    def release(self) -> None:
        self._ws.close()

    def abort(self) -> None:
        self._ws.terminate()


def make_server(
    port: int = 0, host: str | None = None, **serve_options: Any
) -> Effect[SocketServerService, SocketServerError, Scope]:
    """A WebSocket server listening on ``host:port`` (port 0: any free
    port), closed with the scope; ``serve_options`` go to ``websockets``'
    ``serve`` (``process_request``, ``subprotocols``, ...)."""
    accepted = Accepted()

    async def on_connection(connection: ServerConnection) -> None:
        ws = WsWebSocket(paused=True)
        accepted.add(_WsIncoming(ws))
        await ws._serve(connection)  # pyright: ignore[reportPrivateUsage]

    async def start() -> Server:
        return await serve(on_connection, host, port, **serve_options)

    def stop(server: Server, _exit: object) -> Effect[None]:
        async def close() -> None:
            accepted.close()
            server.close()
            await server.wait_closed()

        return run(close).ignore()

    def opened(server: Server) -> SocketServerService:
        name = server.sockets[0].getsockname()
        return SocketServerService(inet_address_from_native_unsafe(name[0], name[1]), accepted)

    starting = run(start).map_error(lambda cause: SocketServerError(SocketServerOpenError(cause)))
    return acquire_release(starting, stop).map(opened)


def layer_server(
    port: int = 0, host: str | None = None, **serve_options: Any
) -> Layer[SocketServer, SocketServerError]:
    """``SocketServer`` as a ``make_server`` WebSocket server."""
    return layer_effect(SocketServer, make_server(port, host, **serve_options))


__all__ = [
    "WsWebSocket",
    "layer_server",
    "layer_web_socket",
    "layer_web_socket_constructor",
    "make_server",
]
