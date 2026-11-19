"""Ports of Effect's ``socket/Socket.test.ts``.

Each test's docstring is the Effect test title. The ``fromWebSocket``
group drives ``TestWebSocket``, a ``WebSocketLike`` whose events the test
dispatches.
"""

from collections.abc import Callable
from typing import Any

import pytest

from pyfect import scope as fx_scope
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
    SocketReadError,
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
    write_error = SocketError(reason=SocketWriteError(cause=RuntimeError("write failed")))

    def reader():
        # An idle reader that only fails once its acquisition scope closes,
        # which is why ``to_channel`` needs no per-pull race.
        closed = Latch(False)
        yield from add_finalizer(lambda _exit: closed.open())
        pull = closed.wait().and_then(fail(SocketError(reason=SocketCloseError(code=1000))))
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
        self.closes: list[tuple[object, ...]] = []
        # Like a global WebSocket, which only accepts 1000 and 3000-4999.
        self.rejects_close_code = False

    def add_event_listener(
        self, type: WebSocketEventType, listener: Listener, *, once: bool = False
    ) -> None:
        self.listeners.setdefault(type, []).append((listener, once))
        if type == "open":
            self.open_listener_attached.open_unsafe()

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
        args = () if code is None else (code, reason)
        if args and self.rejects_close_code:
            raise RuntimeError("InvalidAccessError")
        self.closes.append(args)

    def send(self, data: bytes | str) -> None:
        pass


class PausableTestWebSocket(TestWebSocket):
    __test__ = False

    def __init__(self, open_listener_attached: Latch) -> None:
        super().__init__(open_listener_attached)
        self.pause_count = 0
        self.resume_count = 0

    def pause(self) -> None:
        self.pause_count += 1

    def resume(self) -> None:
        self.resume_count += 1


@testing.effect
def test_from_web_socket_fails_writes_once_terminal():
    """fails writes on a terminal non-reconnectable socket"""
    ws = TestWebSocket(Latch(False))
    ws.ready_state = 1
    scope = yield from fx_scope.make()
    socket = from_web_socket(scope.close(Success(None)).as_(ws), disable_reconnects=True)
    writer = yield from socket.writer

    write = yield from writer.write("later").flip().fork(start_immediately=True)
    error = yield from socket.reader.pipe(fx_scope.provide(scope)).flip()
    assert isinstance(error, SocketError)
    assert (yield from write.join()) is error


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
    ws = PausableTestWebSocket(Latch(False))
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
    ws = PausableTestWebSocket(Latch(False))
    ws.ready_state = 1
    socket = from_web_socket(succeed(ws), high_water_mark=3)
    reader = yield from socket.reader

    ws.dispatch("message", WebSocketEvent(data="€"))

    assert ws.pause_count == 1
    assert (yield from reader.pull) == ("€",)


@testing.effect
def test_from_web_socket_default_high_water_mark():
    """uses the default highWaterMark for pausable sockets"""
    ws = PausableTestWebSocket(Latch(False))
    ws.ready_state = 1
    socket = from_web_socket(succeed(ws))
    reader = yield from socket.reader
    payload = "a" * (64 * 1024)

    ws.dispatch("message", WebSocketEvent(data=payload))
    assert ws.pause_count == 1
    assert (yield from reader.pull) == (payload,)
    assert ws.resume_count == 1


@testing.effect
def test_from_web_socket_counts_empty_frames_and_never_fails_a_pausable_socket():
    """counts empty frames toward the highWaterMark and never fails a pausable socket"""
    ws = PausableTestWebSocket(Latch(False))
    ws.ready_state = 1
    socket = from_web_socket(succeed(ws), high_water_mark=2)
    reader = yield from socket.reader

    ws.dispatch("message", WebSocketEvent(data=""))
    ws.dispatch("message", WebSocketEvent(data=""))
    assert ws.pause_count == 1
    # frames already in flight when the transport paused
    ws.dispatch("message", WebSocketEvent(data="abc"))

    assert (yield from reader.pull) == ("", "", "abc")
    assert ws.resume_count == 1
    assert ws.closes == []


_OVERFLOW_CLOSE = (1008, "Inbound message buffer limit exceeded")


@pytest.mark.parametrize(
    ("high_water_mark", "frames", "retained", "rejects_close_code", "closes"),
    [
        pytest.param(2, ["a", "b", "c", "d"], 3, False, [_OVERFLOW_CLOSE], id="byte frames"),
        pytest.param(2, ["", "", "", ""], 3, False, [_OVERFLOW_CLOSE], id="empty frames"),
        # "€" is 3 bytes, so it is the frame that takes the queue above the mark
        pytest.param(
            3,
            ["a", "€", "b", "c"],
            2,
            False,
            [_OVERFLOW_CLOSE],
            id="a multibyte frame crossing the mark",
        ),
        pytest.param(
            2, ["abc", "d"], 1, False, [_OVERFLOW_CLOSE], id="a single frame larger than the mark"
        ),
        pytest.param(
            2, ["a", "b", "c", "d"], 3, True, [()], id="a transport rejecting close code 1008"
        ),
    ],
)
@testing.effect
def test_from_web_socket_fails_without_pause_once_the_high_water_mark_is_exceeded(
    high_water_mark: int,
    frames: list[str],
    retained: int,
    rejects_close_code: bool,
    closes: list[tuple[object, ...]],
):
    """fails a socket without pause once the highWaterMark is exceeded: %s"""
    ws = TestWebSocket(Latch(False))
    ws.ready_state = 1
    ws.rejects_close_code = rejects_close_code
    socket = from_web_socket(succeed(ws), high_water_mark=high_water_mark)
    reader = yield from socket.reader

    for data in frames:
        ws.dispatch("message", WebSocketEvent(data=data))

    assert (yield from reader.pull) == tuple(frames[:retained])
    error = yield from reader.pull.flip()
    assert isinstance(error.reason, SocketReadError)
    assert str(error.reason.cause) == f"Socket highWaterMark of {high_water_mark} bytes exceeded"
    assert ws.closes == closes
