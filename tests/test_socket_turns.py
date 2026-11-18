"""Each arrival on a socket is its own turn, as each browser and Node message or data event is:
what arrives while the reader is still handling the last waits behind the tasks queued before it.

pyfect's sockets get their data on another thread, so the next item can be in the buffer before
the reader has finished the last. Taken at once, a stream RPC whose client acks each chunk on
receipt kept the server producing: the reader acked chunk after chunk while the consumer that
had its five, woken by a queued task, waited for the reader's step budget (``take(5)`` saw the
server make 7-35 items on Linux; Effect makes 5 or 6). Each reader here hands each item to a
consumer through a queue, and the next item arrives while it is still running."""

from collections.abc import Callable, Sequence
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.effect import Effect, gen, succeed, sync
from pyfect.queue import Queue
from pyfect.scope import scoped
from pyfect.socket import Listener, WebSocketEvent, WebSocketEventType, from_web_socket
from pyfect.socket._connection import Connection
from pyfect.socket._net import from_connection
from pyfect.socket._tls import client_side
from pyfect.socket.datagram import (
    BackingAddress,
    BackingEvents,
    BackingSocket,
    Datagram,
    DatagramSocketError,
    make_from_backing_socket,
)


class _Source:
    """Makes item after item when asked, until the consumer has what it wanted."""

    def __init__(self, deliver: Callable[[str], None]) -> None:
        self.deliver = deliver
        self.made = 0
        self.stopped = False

    def next(self) -> None:
        if not self.stopped:
            self.made += 1
            self.deliver(str(self.made))


def _take_five[C](
    pull: Effect[Sequence[C], Any],
    text: Callable[[C], str],
    then: Effect[None, Any],
    source: _Source,
) -> Effect[int, Any, fx.Scope]:
    """A reader offers each item it pulls to a queue, then runs ``then`` (in which the next item
    arrives); a consumer takes five. Gives how many items the source made."""

    def body():
        items = yield from Queue[str].bounded(16)

        def read():
            while True:
                for chunk in (yield from pull):
                    yield from items.offer(text(chunk))
                    yield from then

        yield from gen(read).fork(start_immediately=True)
        yield from sync(source.next)
        got = yield from fx.stream.from_queue(items).take(5).run_collect()
        source.stopped = True
        assert list(got) == ["1", "2", "3", "4", "5"]
        return source.made

    return gen(body)


def _text(chunk: bytes | str) -> str:
    return chunk if isinstance(chunk, str) else chunk.decode()


class _AckedWebSocket:
    """An open WebSocket whose server sends the next item as soon as an ack for the last
    arrives: its reply lands while the reader is still handling the item it acked."""

    def __init__(self) -> None:
        self.ready_state = 1
        self.listeners: dict[WebSocketEventType, list[Listener]] = {}
        self.source = _Source(self._message)

    def _message(self, data: str) -> None:
        for listener in list(self.listeners.get("message", [])):
            listener(WebSocketEvent(type="message", data=data))

    def add_event_listener(
        self, type: WebSocketEventType, listener: Listener, *, once: bool = False
    ) -> None:
        self.listeners.setdefault(type, []).append(listener)

    def remove_event_listener(self, type: WebSocketEventType, listener: Listener) -> None:
        self.listeners[type] = [
            entry for entry in self.listeners.get(type, []) if entry is not listener
        ]

    def close(self, code: int | None = None, reason: str | None = None) -> None:
        pass

    def send(self, data: bytes | str) -> None:
        if data == "ack":
            self.source.next()


@testing.effect
def test_a_web_socket_message_that_came_while_the_reader_ran_waits_for_queued_tasks():
    ws = _AckedWebSocket()
    socket = from_web_socket(succeed(ws))

    def body():
        reader = yield from socket.reader
        writer = yield from socket.writer
        return (yield from _take_five(reader.pull, _text, writer.write("ack"), ws.source))

    # The consumer's wake, queued with item 5, runs before the reply to its ack is read.
    made = yield from scoped(gen(body))
    assert made <= 6, made


@testing.effect
def test_tcp_bytes_that_came_while_the_reader_ran_wait_for_queued_tasks():
    conn = Connection()
    source = _Source(lambda data: conn.data_received(data.encode()))
    socket = from_connection(succeed(conn), upgrade_side=client_side(None))

    def body():
        reader = yield from socket.reader
        return (yield from _take_five(reader.pull, _text, sync(source.next), source))

    made = yield from scoped(gen(body))
    assert made <= 6, made


class _Handle:
    """A bound UDP socket whose sends go nowhere."""

    def __init__(self, events: BackingEvents) -> None:
        self.address = BackingAddress("127.0.0.1", 1234)
        self.scope_ids: dict[str, int] = {}
        self.peer: BackingAddress | None = None
        self.connected = False
        self.events = events

    def send(self, payload: bytes, destination: Any, done: Any) -> None:
        done(None)

    def send_many(self, payloads: Any, destinations: Any, done: Any) -> None:
        done(None, None)

    def join_multicast(self, group: Any, interface: Any, source: Any) -> Any:
        raise NotImplementedError

    def close(self) -> None:
        pass


@testing.effect
def test_udp_packets_that_came_while_the_reader_ran_wait_for_queued_tasks():
    handles: list[_Handle] = []

    def deliver(data: str) -> None:
        handles[0].events.on_packet(data.encode(), "127.0.0.1", 9876)

    def open(events: BackingEvents) -> Effect[BackingSocket, DatagramSocketError]:
        return sync(lambda: handles.append(_Handle(events)) or handles[0])

    source = _Source(deliver)
    socket = yield from make_from_backing_socket(open)

    def payload(packet: Datagram) -> str:
        return packet.payload.decode()

    def body():
        reader = yield from socket.reader
        return (yield from _take_five(reader.pull, payload, sync(source.next), source))

    made = yield from scoped(gen(body))
    assert made <= 6, made
