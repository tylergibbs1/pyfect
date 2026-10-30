"""Ports of the WebSocket cases of Effect's
``platform-node/test/NodeSocket.test.ts`` (the ``WebSocket`` group and
"closes with a pending pre-run WebSocket"), on ``pyfect.socket.ws`` and
localhost.

Node's ``ws`` peers become ``websockets``' threaded servers and clients;
``mock-socket``'s ``WS`` server becomes a ``websockets`` server that queues
what it receives. Each test's docstring is the Effect test title.

Omitted: the Blob half of "messages" (Python has no ``Blob``; the bytes
half is kept).
"""

import gc
import queue
import socket
import threading
from collections.abc import Iterator
from typing import Any

import pytest

pytest.importorskip("websockets")

from websockets.sync.client import connect as sync_connect
from websockets.sync.server import Server as SyncServer
from websockets.sync.server import ServerConnection as SyncServerConnection
from websockets.sync.server import serve as sync_serve

from pyfect import testing
from pyfect.deferred import Deferred
from pyfect.effect import blocking, gen, provide_service, service_option, succeed, sync
from pyfect.exit import Failure, Success
from pyfect.layer import provide
from pyfect.net.net_address import InetAddressV4
from pyfect.option import Some
from pyfect.redacted import Redacted
from pyfect.scope import CloseableScope, Scope, acquire_release, scoped
from pyfect.socket import (
    Listener,
    SocketCloseError,
    SocketError,
    SocketOpenError,
    SocketService,
    SocketUpgradeError,
    SocketWriteError,
    TlsUpgradeOptions,
    WebSocket,
    WebSocketClientOptions,
    WebSocketConstructor,
    WebSocketEventType,
    make_web_socket,
    reader_bytes,
)
from pyfect.socket import ws as ws_platform

live = testing.live(timeout=10)

pytestmark = pytest.mark.filterwarnings(
    "error::ResourceWarning", "error::pytest.PytestUnraisableExceptionWarning"
)


@pytest.fixture(autouse=True)
def collect_leaks() -> Iterator[None]:
    yield
    gc.collect()


def port_of(address: object) -> int:
    assert isinstance(address, InetAddressV4)
    return address.port


class Peer:
    """A threaded ``websockets`` server (``mock-socket``'s ``WS``): it
    queues the messages it receives and can send and close."""

    def __init__(self) -> None:
        self.messages: queue.Queue[bytes | str] = queue.Queue()
        self.connected = threading.Event()
        self.connection: SyncServerConnection | None = None
        self.server: SyncServer = sync_serve(self._handle, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.server.socket.getsockname()[1]}"

    def _handle(self, connection: SyncServerConnection) -> None:
        self.connection = connection
        self.connected.set()
        for message in connection:
            self.messages.put(message)

    def send(self, data: bytes | str) -> None:
        assert self.connection is not None
        self.connection.send(data)

    def close(self, code: int = 1000, reason: str = "") -> None:
        assert self.connection is not None
        self.connection.close(code, reason)

    def shutdown(self) -> None:
        self.server.shutdown()


def peer_server():
    return acquire_release(sync(Peer), lambda peer, _: sync(peer.shutdown))


def ws_client(url: str):
    """A ``ws`` client (websockets' threaded one), closed with the scope."""

    def open_client() -> Any:
        return sync_connect(url).__enter__()

    return acquire_release(blocking(open_client), lambda c, _: sync(c.close))


with_constructor = provide(ws_platform.layer_web_socket_constructor)


def pending_handshake_server():
    """A TCP server that accepts and never answers the WebSocket upgrade."""
    listener = socket.create_server(("127.0.0.1", 0))
    accepted = threading.Event()
    connections: list[socket.socket] = []

    def accept() -> None:
        try:
            conn, _ = listener.accept()
        except OSError:
            return
        connections.append(conn)
        accepted.set()

    threading.Thread(target=accept, daemon=True).start()

    def close() -> None:
        for conn in connections:
            conn.close()
        listener.close()

    port = listener.getsockname()[1]
    return acquire_release(sync(lambda: (port, accepted)), lambda _p, _e: sync(close))


@testing.effect
def test_pending_handshake_timeout():
    """safely closes a pending ws handshake on timeout"""
    port, accepted = yield from pending_handshake_server()

    def open_reader():
        socket = yield from make_web_socket(f"ws://127.0.0.1:{port}", open_timeout=0.1)
        yield from socket.reader

    reader = yield from scoped(gen(open_reader)).pipe(with_constructor).fork()
    yield from blocking(lambda: accepted.wait(5))
    yield from testing.adjust(0.1)
    exit = yield from reader.await_exit()
    assert isinstance(exit, Failure)
    error = exit.cause.squash()
    assert isinstance(error, SocketError) and isinstance(error.reason, SocketOpenError)
    assert error.reason.kind == "Timeout"


@testing.effect
def test_pending_handshake_interruption():
    """safely closes a pending ws handshake on interruption"""
    port, accepted = yield from pending_handshake_server()

    def open_reader():
        socket = yield from make_web_socket(f"ws://127.0.0.1:{port}", open_timeout=0.1)
        yield from socket.reader

    reader = yield from scoped(gen(open_reader)).pipe(with_constructor).fork()
    yield from blocking(lambda: accepted.wait(5))
    yield from reader.interrupt()
    exit = yield from reader.await_exit()
    assert isinstance(exit, Failure) and exit.cause.has_interrupts


@live
def test_closes_with_pending_pre_run_web_socket():
    """closes with a pending pre-run WebSocket"""
    scope = CloseableScope()
    srv = yield from ws_platform.make_server(0, "127.0.0.1").pipe(provide_service(Scope, scope))
    yield from ws_client(f"ws://127.0.0.1:{port_of(srv.address)}")
    exit = yield from scope.close(Success(None)).timeout(1.0).exit()
    assert isinstance(exit, Success)


@live
def test_receives_messages_after_paused_handover():
    """receives messages after handing a paused WebSocket to the reader"""
    received = yield from Deferred[tuple[bytes | str, ...]].make()
    srv = yield from ws_platform.make_server(0, "127.0.0.1")

    def handler(sock: SocketService):
        def body():
            native = yield from service_option(WebSocket)
            assert isinstance(native, Some) and isinstance(native.value, ws_platform.WsWebSocket)
            reader = yield from sock.reader
            writer = yield from sock.writer
            yield from writer.write("reader-ready")
            yield from received.succeed((yield from reader.pull))

        return scoped(gen(body))

    yield from srv.run(handler).fork_scoped()
    client = yield from ws_client(f"ws://127.0.0.1:{port_of(srv.address)}")
    assert (yield from blocking(lambda: client.recv(timeout=1))) == "reader-ready"
    yield from blocking(lambda: client.send("after-ready"))
    assert (yield from received.wait().timeout(1.0)) == ("after-ready",)


@live
def test_passes_headers_and_subprotocol():
    """passes headers and a subprotocol to the opening handshake"""
    handshake: queue.Queue[tuple[str | None, str | None]] = queue.Queue()

    def on_connection(connection: SyncServerConnection) -> None:
        assert connection.request is not None
        handshake.put((connection.request.headers.get("Authorization"), connection.subprotocol))
        connection.recv()

    def start() -> SyncServer:
        server = sync_serve(
            on_connection,
            "127.0.0.1",
            0,
            subprotocols=["graphql-transport-ws"],  # pyright: ignore[reportArgumentType]
        )
        threading.Thread(target=server.serve_forever, daemon=True).start()
        return server

    server = yield from acquire_release(sync(start), lambda s, _: sync(s.shutdown))
    port = server.socket.getsockname()[1]
    socket = yield from make_web_socket(
        f"ws://127.0.0.1:{port}",
        protocols="graphql-transport-ws",
        headers={"Authorization": "Bearer test"},
    ).pipe(with_constructor)
    yield from socket.reader
    assert (yield from blocking(lambda: handshake.get(timeout=1))) == (
        "Bearer test",
        "graphql-transport-ws",
    )


@live
def test_passes_headers():
    """passes headers to the opening handshake"""
    authorization = yield from Deferred[str | None].make()

    def process_request(_connection: Any, request: Any) -> None:
        authorization.done_unsafe(Success(request.headers.get("Authorization")))

    srv = yield from ws_platform.make_server(0, "127.0.0.1", process_request=process_request)
    construct = yield from WebSocketConstructor().pipe(with_constructor)
    options = WebSocketClientOptions(headers={"Authorization": "Bearer test"})
    client = yield from acquire_release(
        sync(lambda: construct(f"ws://127.0.0.1:{port_of(srv.address)}", options)),
        lambda c, _: sync(c.close),
    )

    def ignore(_: object) -> None:
        pass

    client.add_event_listener("error", ignore)
    assert (yield from authorization.wait().timeout(1.0)) == "Bearer test"


@live
def test_web_socket_upgrade_fails():
    """fails TLS upgrade with SocketUpgradeError"""
    peer = yield from peer_server()
    socket = yield from make_web_socket(succeed(peer.url)).pipe(with_constructor)
    reader = yield from socket.reader
    error = yield from reader.upgrade(TlsUpgradeOptions(cert="cert", key=Redacted("key"))).flip()
    assert isinstance(error.reason, SocketUpgradeError)


@live
def test_messages():
    """messages"""
    peer = yield from peer_server()
    socket = yield from make_web_socket(succeed(peer.url)).pipe(with_constructor)
    messages: queue.Queue[bytes] = queue.Queue()

    def read():
        pull = yield from reader_bytes(socket)
        while True:
            for chunk in (yield from pull):
                messages.put(chunk)

    fiber = yield from scoped(gen(read)).fork()

    def write():
        writer = yield from socket.writer
        yield from writer.write(b"Hello")
        yield from writer.write(b"World")

    yield from scoped(gen(write))
    assert (yield from blocking(lambda: peer.messages.get(timeout=1))) == b"Hello"
    assert (yield from blocking(lambda: peer.messages.get(timeout=1))) == b"World"

    peer.send("Right back at you!")
    assert (yield from blocking(lambda: messages.get(timeout=1))) == b"Right back at you!"

    peer.close()
    exit = yield from fiber.await_exit()
    assert isinstance(exit, Failure)
    error = exit.cause.squash()
    assert isinstance(error, SocketError) and isinstance(error.reason, SocketCloseError)


@live
def test_clean_closes_are_errors():
    """clean closes are errors"""
    peer = yield from peer_server()
    socket = yield from make_web_socket(succeed(peer.url)).pipe(with_constructor)

    def read():
        reader = yield from socket.reader
        while True:
            yield from reader.pull

    fiber = yield from scoped(gen(read)).fork()
    yield from blocking(lambda: peer.connected.wait(1))
    peer.close(1000, "done")

    exit = yield from fiber.join().exit()
    assert isinstance(exit, Failure)
    error = exit.cause.squash()
    assert isinstance(error, SocketError) and isinstance(error.reason, SocketCloseError)
    assert error.reason.code == 1000
    assert error.reason.close_reason == "done"


class ThrowingWebSocket:
    ready_state = 1

    def add_event_listener(
        self, type: WebSocketEventType, listener: Listener, *, once: bool = False
    ) -> None:
        pass

    def remove_event_listener(self, type: WebSocketEventType, listener: Listener) -> None:
        pass

    def close(self, code: int | None = None, reason: str | None = None) -> None:
        pass

    def send(self, data: bytes | str) -> None:
        raise RuntimeError("send failed")


@live
def test_reports_send_errors():
    """reports send errors as SocketError"""
    web_socket = ThrowingWebSocket()
    socket = yield from make_web_socket(succeed("ws://localhost:1234")).pipe(
        provide_service(WebSocketConstructor, lambda _url, _options: web_socket)
    )

    def body():
        yield from socket.reader
        writer = yield from socket.writer
        return (yield from writer.write(bytes([1])).exit())

    exit = yield from scoped(gen(body))
    assert isinstance(exit, Failure)
    error = exit.cause.squash()
    assert isinstance(error, SocketError) and isinstance(error.reason, SocketWriteError)
