"""Events a WebSocket dispatched before the socket listened still reach it.

A browser dispatches WebSocket events in a later task than the one that made
the socket, so ``fromWebSocket`` always attaches its listeners first. Here the
socket loop runs beside the fiber, so a socket can open, fail or close before
``from_web_socket`` listens; these sockets finish all of that before the
constructor returns them.
"""

from __future__ import annotations

import ast
import threading

import _ports
import _source
import pytest
from _timing import wait_until

import pyfect as fx
from pyfect.scope import scoped
from pyfect.socket import (
    SocketCloseError,
    SocketError,
    SocketOpenError,
    SocketService,
    WebSocketClientOptions,
    WebSocketConstructor,
    WebSocketEvent,
    WebSocketEventType,
    WebSocketLike,
    from_web_socket,
    make_web_socket,
)
from pyfect.socket._event_target import EventTarget, ListenerEntry
from pyfect.socket._loop import call_soon
from pyfect.socket._web_socket import Listener

pytest.importorskip("websockets")

from websockets.sync.server import ServerConnection, serve

from pyfect.socket.ws import WsWebSocket

_CLOSED = 3


def _settled(url: str, options: WebSocketClientOptions) -> WebSocketLike:
    """A client connected to ``url`` that has closed, and whose loop has
    dispatched every event, before anything listens to it."""
    ws = WsWebSocket.connect(url, options)
    wait_until(lambda: ws.ready_state == _CLOSED, what="the WebSocket to close")
    # The close event is dispatched in the loop step that closed it.
    dispatched = threading.Event()
    call_soon(dispatched.set)
    assert dispatched.wait(10)
    return ws


def _read_error(url: str) -> SocketError:
    @fx.fn
    def pull(sock: SocketService):
        reader = yield from sock.reader
        return (yield from reader.pull)

    socket = make_web_socket(url).pipe(fx.provide_service(WebSocketConstructor, _settled))
    error = fx.run_blocking(scoped(socket.flat_map(pull)).flip().timeout("10 seconds").or_die())
    assert isinstance(error, SocketError)
    return error


def test_a_refusal_before_listening_is_an_open_error() -> None:
    url = f"ws://127.0.0.1:{_ports.refused_tcp_port()}/rpc"
    reason = _read_error(url).reason
    assert isinstance(reason, SocketOpenError)
    assert reason.target == url


def test_a_close_before_listening_keeps_its_code() -> None:
    def handler(connection: ServerConnection) -> None:
        connection.close(4000, "bye")

    with serve(handler, "127.0.0.1", 0) as server:
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            port = server.socket.getsockname()[1]
            reason = _read_error(f"ws://127.0.0.1:{port}").reason
        finally:
            server.shutdown()
            thread.join(10)
    assert isinstance(reason, SocketCloseError)
    assert (reason.code, reason.close_reason) == (4000, "bye")


class _EarlySocket:
    """A WebSocket that opened and got messages before anyone listened."""

    def __init__(self, *messages: str) -> None:
        def report(error: Exception) -> None:
            raise error

        self.events = EventTarget(report)
        self.ready_state = 1
        self.events.dispatch("open", WebSocketEvent(type="open"))
        for message in messages:
            self.events.dispatch("message", WebSocketEvent(type="message", data=message))

    def add_event_listener(
        self, type: WebSocketEventType, listener: Listener, *, once: bool = False
    ) -> None:
        self.events.add_event_listener(type, listener, once=once)

    def remove_event_listener(self, type: WebSocketEventType, listener: Listener) -> None:
        self.events.remove_event_listener(type, listener)

    def add_event_listeners(self, entries: tuple[ListenerEntry, ...]) -> None:
        self.events.add_event_listeners(entries)

    def close(self, code: int | None = None, reason: str | None = None) -> None:
        pass

    def send(self, data: bytes | str) -> None:
        pass


def test_messages_before_listening_are_read_in_order() -> None:
    @fx.fn
    def pull(sock: SocketService):
        reader = yield from sock.reader
        return (yield from reader.pull)

    socket = from_web_socket(fx.succeed(_EarlySocket("a", "b")))
    assert fx.run_blocking(scoped(pull(socket)).timeout("10 seconds").or_die()) == ("a", "b")


SRC = _source.SRC


def test_every_web_socket_keeps_its_listeners_in_an_event_target() -> None:
    """A WebSocket of pyfect's dispatches from a loop thread, so its
    listeners live in an ``EventTarget``, which holds early events."""
    found: list[str] = []
    for path in _source.files(SRC):
        for node in _source.walk(path):
            if not isinstance(node, ast.ClassDef) or node.name == "EventTarget":
                continue
            methods = {item.name for item in node.body if isinstance(item, ast.FunctionDef)}
            protocol = any(ast.unparse(base) == "Protocol" for base in node.bases)
            if "add_event_listener" not in methods or protocol:
                continue
            found.append(node.name)
            assert "add_event_listeners" in methods, node.name
            assert "EventTarget(" in ast.unparse(node), node.name
    assert sorted(found) == ["AsgiWebSocket", "WsWebSocket"]
