"""Ports of Effect's ``socket/Socket.test.ts``.

Each test's docstring is the Effect test title. The ``fromWebSocket``
group drives ``TestWebSocket``, a ``WebSocketLike`` whose events the test
dispatches.
"""

from collections.abc import Callable
from typing import Any

from pyfect import stream, testing
from pyfect.effect import fail, gen, never, succeed, suspend, sync, void
from pyfect.exit import Failure, Success
from pyfect.latch import Latch
from pyfect.result import Ok
from pyfect.scope import add_finalizer
from pyfect.socket import (
    Chunk,
    Listener,
    Reader,
    SocketCloseError,
    SocketError,
    SocketService,
    SocketWriteError,
    WebSocketEvent,
    WebSocketEventType,
    Writer,
    from_web_socket,
    make,
    reader_bytes,
    reader_string,
    to_channel,
    unsupported_upgrade,
)
from pyfect.socket._errors import close_error


def stub_socket(pull: Any) -> tuple[SocketService, Callable[[], bool]]:
    upgraded = [False]

    def upgrade(_options: object) -> Any:
        return sync(lambda: upgraded.__setitem__(0, True))

    socket = make(
        reader=succeed(Reader(pull, upgrade)),
        writer=succeed(Writer(lambda _chunk: void, lambda _chunks: void)),
    )
    return socket, lambda: upgraded[0]


@testing.effect
def test_exposes_upgrade():
    """exposes TLS upgrade on the acquired reader"""
    socket, was_upgraded = stub_socket(never)
    reader = yield from socket.reader
    yield from reader.upgrade()
    assert was_upgraded()


@testing.effect
def test_reader_bytes():
    """readerBytes maps pulls to bytes"""
    socket, _ = stub_socket(succeed(("hello",)))
    pull = yield from reader_bytes(socket)
    (message,) = yield from pull
    assert message == b"hello"


@testing.effect
def test_reader_string():
    """readerString maps pulls to strings"""
    socket, _ = stub_socket(succeed((b"hello",)))
    pull = yield from reader_string(socket)
    (message,) = yield from pull
    assert message == "hello"


@testing.effect
def test_reader_string_split():
    """readerString decodes characters split across pulls"""
    pulls: list[tuple[Chunk, ...]] = [(bytes([0x61, 0xE2, 0x98]),), (bytes([0x95]),)]
    socket, _ = stub_socket(sync(lambda: pulls.pop(0)))
    pull = yield from reader_string(socket)
    assert (yield from pull) == ("a",)
    assert (yield from pull) == ("☕",)


@testing.effect
def test_reader_string_flush_before_text():
    """readerString flushes an incomplete character before a string frame"""
    socket, _ = stub_socket(succeed((bytes([0x61, 0xE2]), "b")))
    pull = yield from reader_string(socket)
    assert (yield from pull) == ("a", "�b")


@testing.effect
def test_reader_string_flush_on_close():
    """readerString flushes an incomplete character on a normal close"""
    close = close_error(1000)
    pulls: list[Any] = [succeed((bytes([0x61, 0xE2, 0x98]),))]
    socket, _ = stub_socket(suspend(lambda: pulls.pop(0) if pulls else fail(close)))
    pull = yield from reader_string(socket)
    assert (yield from pull) == ("a",)
    assert (yield from pull) == ("�",)
    assert (yield from pull.flip()) == close


@testing.effect
def test_to_channel_write_failure():
    """reports a write failure while a pull is suspended"""
    write_error = SocketError(SocketWriteError(RuntimeError("write failed")))

    def reader():
        # An idle reader that only fails once its acquisition scope closes,
        # which is why ``to_channel`` needs no per-pull race.
        closed = Latch(False)
        yield from add_finalizer(lambda _exit: closed.open())
        pull = closed.wait().and_then(fail(SocketError(SocketCloseError(1000))))
        return Reader(pull, unsupported_upgrade)

    socket = make(
        reader=gen(reader),
        writer=succeed(Writer(lambda _chunk: fail(write_error), lambda _chunks: fail(write_error))),
    )
    exit = yield from (
        stream.make("hello")
        .encode_text()
        .pipe_through_channel(to_channel(socket))
        .run_drain()
        .exit()
    )
    assert isinstance(exit, Failure)
    found = exit.cause.find_error()
    assert isinstance(found, Ok) and found.value is write_error


class TestWebSocket:
    __test__ = False

    def __init__(self, open_listener_attached: Latch) -> None:
        self.open_listener_attached = open_listener_attached
        self.listeners: dict[WebSocketEventType, list[tuple[Listener, bool]]] = {}
        self.ready_state = 0
        self.pause_count = 0
        self.resume_count = 0

    def pause(self) -> None:
        self.pause_count += 1

    def resume(self) -> None:
        self.resume_count += 1

    def add_event_listener(
        self, type: WebSocketEventType, listener: Listener, *, once: bool = False
    ) -> None:
        self.listeners.setdefault(type, []).append((listener, once))
        if type == "open":
            self.open_listener_attached.unsafe_open()

    def remove_event_listener(self, type: WebSocketEventType, listener: Listener) -> None:
        entries = self.listeners.get(type, [])
        entries[:] = [entry for entry in entries if entry[0] is not listener]

    def dispatch(self, type: WebSocketEventType, event: WebSocketEvent) -> None:
        entries = self.listeners.get(type, [])
        for entry in list(entries):
            if entry[1]:
                entries.remove(entry)
            entry[0](event)

    def listener_count(self, type: WebSocketEventType) -> int:
        return len(self.listeners.get(type, []))

    def close(self, code: int | None = None, reason: str | None = None) -> None:
        pass

    def send(self, data: bytes | str) -> None:
        pass


@testing.effect
def test_from_web_socket_removes_open_listener():
    """removes the open listener when the socket closes while connecting"""
    open_listener_attached = Latch(False)
    ws = TestWebSocket(open_listener_attached)
    socket = from_web_socket(succeed(ws))
    reader = yield from socket.reader.exit().fork(start_immediately=True)

    yield from open_listener_attached.wait()
    ws.dispatch("close", WebSocketEvent(code=1006, reason="closed while connecting"))

    assert not isinstance((yield from reader.join()), Success)
    assert ws.listener_count("open") == 0


@testing.effect
def test_from_web_socket_pauses_at_high_water_mark():
    """pauses at the highWaterMark and resumes after draining"""
    ws = TestWebSocket(Latch(False))
    ws.ready_state = 1
    socket = from_web_socket(succeed(ws), high_water_mark=10)
    reader = yield from socket.reader
    first_pull = yield from reader.pull.fork(start_immediately=True)

    ws.dispatch("message", WebSocketEvent(data="first"))
    assert (yield from first_pull.join()) == ("first",)

    ws.dispatch("message", WebSocketEvent(data="hello"))
    assert ws.pause_count == 0
    ws.dispatch("message", WebSocketEvent(data="world"))
    assert ws.pause_count == 1

    assert (yield from reader.pull) == ("hello", "world")
    assert ws.resume_count == 1


@testing.effect
def test_from_web_socket_counts_utf8_bytes():
    """counts text frames toward the highWaterMark by UTF-8 byte length"""
    ws = TestWebSocket(Latch(False))
    ws.ready_state = 1
    socket = from_web_socket(succeed(ws), high_water_mark=3)
    reader = yield from socket.reader

    ws.dispatch("message", WebSocketEvent(data="€"))

    assert ws.pause_count == 1
    assert (yield from reader.pull) == ("€",)


@testing.effect
def test_from_web_socket_default_high_water_mark():
    """uses the default highWaterMark for pausable sockets"""
    ws = TestWebSocket(Latch(False))
    ws.ready_state = 1
    socket = from_web_socket(succeed(ws))
    reader = yield from socket.reader
    payload = "a" * (64 * 1024)

    ws.dispatch("message", WebSocketEvent(data=payload))
    assert ws.pause_count == 1
    assert (yield from reader.pull) == (payload,)
    assert ws.resume_count == 1
