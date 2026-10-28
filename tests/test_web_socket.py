"""WebSocket socket behavior beyond the Effect ports: thread races of
``from_web_socket`` and the ``websockets`` adapter."""

import asyncio
import gc
import queue
import socket as stdlib_socket
import threading
from collections.abc import Iterator

import pytest

pytest.importorskip("websockets")

from websockets.sync.server import Server as SyncServer
from websockets.sync.server import ServerConnection as SyncServerConnection
from websockets.sync.server import serve as sync_serve

import pyfect as fx
from pyfect import testing
from pyfect.effect import blocking, gen, succeed, sync
from pyfect.exit import Failure
from pyfect.layer import provide
from pyfect.scope import acquire_release, scoped
from pyfect.socket import (
    CloseEvent,
    Listener,
    SocketError,
    SocketOpenError,
    SocketReadError,
    SocketWriteError,
    WebSocketClientOptions,
    WebSocketEvent,
    WebSocketEventType,
    from_web_socket,
    make_web_socket,
)
from pyfect.socket import ws as ws_platform

pytestmark = pytest.mark.filterwarnings(
    "error::ResourceWarning", "error::pytest.PytestUnraisableExceptionWarning"
)

with_constructor = provide(ws_platform.layer_web_socket_constructor)


@pytest.fixture(autouse=True)
def collect_leaks() -> Iterator[None]:
    yield
    gc.collect()


class FakeWebSocket:
    """A WebSocket without pause/resume that opens when its open listener
    is added, without an event (as one opening on another thread would)."""

    def __init__(self) -> None:
        self.ready_state = 0
        self.listeners: dict[WebSocketEventType, list[Listener]] = {}

    def add_event_listener(
        self, type: WebSocketEventType, listener: Listener, *, once: bool = False
    ) -> None:
        self.listeners.setdefault(type, []).append(listener)
        if type == "open":
            self.ready_state = 1

    def remove_event_listener(self, type: WebSocketEventType, listener: Listener) -> None:
        self.listeners[type] = [
            entry for entry in self.listeners.get(type, []) if entry is not listener
        ]

    def dispatch(self, type: WebSocketEventType, event: WebSocketEvent) -> None:
        for listener in list(self.listeners.get(type, [])):
            listener(event)

    def close(self, code: int | None = None, reason: str | None = None) -> None:
        pass

    def send(self, data: bytes | str) -> None:
        pass


@testing.effect
def test_opens_when_it_opened_before_the_open_listener():
    ws = FakeWebSocket()
    socket = from_web_socket(succeed(ws), open_timeout=1.0)
    yield from socket.reader.timeout(0.5)


@testing.effect
def test_an_unpausable_socket_fails_past_the_high_water_mark():
    ws = FakeWebSocket()
    ws.ready_state = 1
    socket = from_web_socket(succeed(ws), high_water_mark=3)
    reader = yield from socket.reader
    ws.dispatch("message", WebSocketEvent(data="abcd"))
    # Buffered messages come first, then the failure.
    assert (yield from reader.pull) == ("abcd",)
    error = yield from reader.pull.flip()
    assert isinstance(error.reason, SocketReadError)
    assert str(error.reason.cause) == "Socket highWaterMark of 3 bytes exceeded"


class Echo:
    """A threaded ``websockets`` echo server that records what it got."""

    def __init__(self) -> None:
        self.received: queue.Queue[bytes | str] = queue.Queue()
        self.server: SyncServer = sync_serve(self._handle, "127.0.0.1", 0)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.server.socket.getsockname()[1]}"

    def _handle(self, connection: SyncServerConnection) -> None:
        for message in connection:
            self.received.put(message)
            connection.send(message)


def echo_server():
    return acquire_release(sync(Echo), lambda e, _: sync(e.server.shutdown))


@testing.live(timeout=10)
def test_text_with_a_lone_surrogate_is_sent_as_a_browser_sends_it():
    # WebSocket.send takes a USVString: a lone surrogate becomes U+FFFD,
    # and later sends still go out.
    echo = yield from echo_server()
    socket = yield from make_web_socket(echo.url).pipe(with_constructor)
    writer = yield from socket.writer
    yield from socket.reader
    yield from writer.write("a\ud800")
    yield from writer.write("b")
    assert (yield from blocking(lambda: echo.received.get(timeout=2))) == "a�"
    assert (yield from blocking(lambda: echo.received.get(timeout=2))) == "b"


@testing.live(timeout=10)
def test_closing_while_connecting_fails_the_open():
    # A server that accepts TCP but never answers the upgrade.
    listener = stdlib_socket.create_server(("127.0.0.1", 0))
    yield from acquire_release(sync(lambda: listener), lambda s, _: sync(s.close))
    port = listener.getsockname()[1]
    ws = ws_platform.WsWebSocket.connect(f"ws://127.0.0.1:{port}", WebSocketClientOptions())
    socket = from_web_socket(succeed(ws), open_timeout=5.0)
    reader = yield from scoped(socket.reader).fork(start_immediately=True)
    ws.close()
    exit = yield from reader.await_exit()
    assert isinstance(exit, Failure)
    error = exit.cause.squash()
    assert isinstance(error, SocketError)
    # As in a browser: an error event, then a close with code 1006.
    assert isinstance(error.reason, SocketOpenError) and error.reason.kind == "Unknown"


def test_round_trip_on_the_asyncio_runtime():
    def body():
        echo = yield from echo_server()
        socket = yield from make_web_socket(echo.url).pipe(with_constructor)
        writer = yield from socket.writer
        reader = yield from socket.reader
        yield from writer.write_all(["ping"])
        return (yield from reader.pull)

    async def main() -> object:
        return await fx.run_async(scoped(gen(body)).or_die())

    assert asyncio.run(main()) == ("ping",)


@testing.live(timeout=10)
def test_an_invalid_close_code_is_a_write_error():
    # A browser's close() throws for codes other than 1000 and 3000-4999.
    echo = yield from echo_server()
    socket = yield from make_web_socket(echo.url).pipe(with_constructor)
    writer = yield from socket.writer
    yield from socket.reader
    error = yield from writer.write(CloseEvent(1001)).flip()
    assert isinstance(error.reason, SocketWriteError)
    yield from writer.write(CloseEvent(4000, "done"))
