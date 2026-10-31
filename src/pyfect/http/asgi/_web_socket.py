"""A WebSocket request over ASGI (Effect's ``NodeHttpServer`` upgrade
handler for ``Upgrade: websocket``).

The app sees a ``GET`` request whose ``upgrade`` is a socket over the ASGI
connection: acquiring its reader sends ``websocket.accept`` (choosing the
client's first subprotocol, as Node's ``ws`` does), and the reader's scope
closes it with the handler's code (1000 on success, 1001 when interrupted,
1011 on failure) unless the handler closed it first. An app that never
upgrades answers with its HTTP response (the ``websocket.http.response``
extension; servers without it answer 403). A connection lost without a
closing handshake interrupts the app (a client abort).
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable
from typing import Any, Never

from pyfect._core import Effect, _WithFiber
from pyfect._fiber import Fiber
from pyfect.context import Context
from pyfect.effect import fail, from_async, succeed, sync, try_async, void
from pyfect.exit import Exit
from pyfect.http.asgi import _scope
from pyfect.http.asgi._http import encode_headers
from pyfect.http.asgi._types import Message, Receive, Scope, Send
from pyfect.http.headers import Headers
from pyfect.http.http_effect import HttpMiddleware, to_handled
from pyfect.http.server_error import CLIENT_ABORT_ANNOTATION
from pyfect.http.server_request import HttpServerRequest, ServerRequest, SourceRequest
from pyfect.http.server_response import HttpServerResponse, empty
from pyfect.http.web import WebResponse
from pyfect.http.web_handler import Fork, response_to_web
from pyfect.scope import acquire_release
from pyfect.socket._errors import SocketError, open_error
from pyfect.socket._socket import SocketService
from pyfect.socket._web_socket import (
    CLOSED,
    CLOSING,
    CONNECTING,
    OPEN,
    Listener,
    Outgoing,
    WebSocketEvent,
    WebSocketEventType,
    close_code,
    from_web_socket,
)

_UPGRADED = empty(status=101)
"""What middleware sees as sent once the connection is upgraded."""

_LOST = (1005, 1006)
"""Disconnect codes of a connection that ended without a closing handshake."""


class AsgiWebSocket:
    """A browser-style WebSocket over an ASGI ``websocket`` connection.
    Methods may be called from any thread; listeners run on the server's
    loop. Messages wait (one at a time) while paused; ``buffered_amount``
    counts what was sent but the server has not taken."""

    def __init__(self, receive: Receive, send: Send) -> None:
        self._loop = asyncio.get_running_loop()
        self._receive = receive
        self._send = send
        self._lock = threading.Lock()
        self._listeners: dict[WebSocketEventType, list[tuple[Listener, bool]]] = {}
        self._state = CONNECTING
        self._paused = True
        self._flowing = asyncio.Event()
        self._outgoing: asyncio.Queue[tuple[Message, int] | None] = asyncio.Queue()
        self._unsent = Outgoing()
        self._writer: asyncio.Task[None] | None = None
        self._closing = False
        self.lost: asyncio.Event = asyncio.Event()
        """Set when the connection ends without a closing handshake."""
        self._reader = self._loop.create_task(self._read())

    # --- WebSocketLike ---------------------------------------------------------

    @property
    def ready_state(self) -> int:
        return self._state

    @property
    def is_paused(self) -> bool:
        return self._paused

    @property
    def buffered_amount(self) -> int:
        return self._unsent.amount

    def when_drained(self, below: int, callback: Callable[[], None]) -> Callable[[], None]:
        return self._unsent.when_drained(below, callback)

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
        if self._state == CONNECTING:
            raise RuntimeError("WebSocket is not open: readyState 0 (CONNECTING)")
        if self._state == OPEN:
            message: Message = (
                {"type": "websocket.send", "text": data}
                if isinstance(data, str)
                else {"type": "websocket.send", "bytes": data}
            )
            size = self._unsent.queued(data)
            self._loop.call_soon_threadsafe(self._outgoing.put_nowait, (message, size))

    def close(self, code: int | None = None, reason: str | None = None) -> None:
        self._loop.call_soon_threadsafe(self._close, 1000 if code is None else code, reason or "")

    def pause(self) -> None:
        self._paused = True
        self._loop.call_soon_threadsafe(self._flowing.clear)

    def resume(self) -> None:
        self._paused = False
        self._loop.call_soon_threadsafe(self._flowing.set)

    # --- loop side -------------------------------------------------------------

    @property
    def accepted(self) -> bool:
        return self._writer is not None

    async def accept(self, subprotocol: str | None) -> None:
        if self._state != CONNECTING:
            raise ConnectionError("The socket closed before the upgrade")
        await self._send({"type": "websocket.accept", "subprotocol": subprotocol})
        self._state = OPEN
        self._writer = self._loop.create_task(self._write())
        self._dispatch("open", WebSocketEvent(type="open"))

    def _dispatch(self, type: WebSocketEventType, event: WebSocketEvent) -> None:
        with self._lock:
            entries = self._listeners.get(type, [])
            called = list(entries)
            entries[:] = [(listener, once) for listener, once in entries if not once]
        for listener, _ in called:
            try:
                listener(event)
            except Exception as error:
                self._loop.call_exception_handler(
                    {"message": "WebSocket listener failed", "exception": error}
                )

    def _close(self, code: int, reason: str) -> None:
        if self._state == OPEN:
            self._state = CLOSING
            close: Message = {"type": "websocket.close", "code": code, "reason": reason}
            self._outgoing.put_nowait((close, 0))

    async def _read(self) -> None:
        while True:
            message = await self._receive()
            if message["type"] == "websocket.disconnect":
                self._disconnected(message.get("code", 1005), message.get("reason") or "")
                return
            if message["type"] == "websocket.receive":
                await self._flowing.wait()
                data = message.get("bytes")
                self._dispatch(
                    "message",
                    WebSocketEvent(
                        type="message", data=message.get("text", "") if data is None else data
                    ),
                )

    def _disconnected(self, code: int, reason: str) -> None:
        opened = self._state != CONNECTING
        self._state = CLOSED
        if not self._closing and (code in _LOST or not opened):
            self.lost.set()
        self._outgoing.put_nowait(None)
        self._unsent.close()
        self._dispatch("close", WebSocketEvent(type="close", code=code, reason=reason))

    async def _write(self) -> None:
        try:
            while (item := await self._outgoing.get()) is not None:
                message, size = item
                closing = message["type"] == "websocket.close"
                # Set first: the server reports our own close as a disconnect.
                self._closing = self._closing or closing
                try:
                    await self._send(message)
                except OSError:
                    return
                self._unsent.sent(size)
                if closing:
                    return
        finally:
            self._unsent.close()

    async def finish(self) -> None:
        """Once the handler is done: close the connection if it is still
        open, send what is queued, and stop reading."""
        self._close(1000, "")
        if self._writer is not None:
            await self._writer
        self._reader.cancel()


def _socket(ws: AsgiWebSocket, scope: Scope) -> SocketService:
    protocols: list[str] = scope.get("subprotocols", [])

    def on_error(cause: Exception) -> SocketError:
        return open_error(cause)

    accept: Effect[AsgiWebSocket, SocketError] = try_async(
        lambda: ws.accept(protocols[0] if protocols else None), on_error
    ).as_(ws)
    return from_web_socket(
        acquire_release(accept, lambda opened, exit: sync(lambda: opened.close(close_code(exit))))
    )


async def _send_response(send: Send, scope: Scope, response: WebResponse) -> None:
    if "websocket.http.response" not in scope.get("extensions", {}):
        await send({"type": "websocket.close", "code": 1008})
        return
    body = await response.read()
    await send(
        {
            "type": "websocket.http.response.start",
            "status": response.status,
            "headers": encode_headers(response.header_lines),
        }
    )
    await send({"type": "websocket.http.response.body", "body": body})


def _request(ws: AsgiWebSocket, scope: Scope, url: str) -> SourceRequest:
    lines = _scope.header_lines(scope)
    joined: dict[str, str] = {}
    for name, value in lines:
        joined[name] = f"{joined[name]}, {value}" if name in joined else value
    socket = _socket(ws, scope)

    def upgrade(headers: Headers) -> Effect[SocketService, object]:
        if headers:
            return fail(RuntimeError("WebSocket upgrades do not support custom response headers"))
        return succeed(socket)

    return SourceRequest(
        "GET",
        url,
        Headers(joined),
        None,
        source=scope,
        remote_address=_scope.remote_address(scope),
        upgrade=upgrade,
    )


async def serve_websocket(
    scope: Scope,
    receive: Receive,
    send: Send,
    *,
    app: Effect[HttpServerResponse, Any, Any],
    middleware: HttpMiddleware | None,
    context: Context[Any],
    fork: Fork,
) -> None:
    """Answer one ``websocket`` scope with ``app``."""
    if (await receive())["type"] != "websocket.connect":
        return
    url = _scope.url(scope, _scope.header_lines(scope))
    if url is None:
        await _send_response(send, scope, WebResponse(status=400))
        return
    ws = AsgiWebSocket(receive, send)

    def respond(_request: ServerRequest, response: HttpServerResponse) -> Effect[object, Never]:
        if ws.accepted:
            return succeed(_UPGRADED)
        if ws.ready_state == CLOSED:
            return void

        def body(fiber: Fiber[Any, Any]) -> Effect[object, Never]:
            web = response_to_web(response, context=fiber._context)
            return from_async(lambda: _send_response(send, scope, web))

        return _WithFiber(body)

    fiber = fork(
        to_handled(app, respond, middleware),
        context.add(HttpServerRequest, _request(ws, scope, url)),
    )
    loop = asyncio.get_running_loop()
    done: asyncio.Future[None] = loop.create_future()

    def finished(_exit: Exit[Any, Any]) -> None:
        loop.call_soon_threadsafe(lambda: None if done.done() else done.set_result(None))

    fiber.add_observer_unsafe(finished)
    lost = loop.create_task(ws.lost.wait())
    try:
        await asyncio.wait((done, lost), return_when=asyncio.FIRST_COMPLETED)
        if not done.done():
            fiber.interrupt_as_unsafe(None, CLIENT_ABORT_ANNOTATION)
            await done
    except asyncio.CancelledError:
        fiber.interrupt_as_unsafe(None, CLIENT_ABORT_ANNOTATION)
        raise
    finally:
        lost.cancel()
    await ws.finish()
