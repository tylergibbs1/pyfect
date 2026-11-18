"""A WebSocket message is its own turn, as each browser and Node message event is: one that
arrives while the reader is still handling the last waits behind the tasks queued before it.

pyfect's sockets get their messages on another thread, so the next one can be in the buffer
before the reader has finished the last. Taken at once, a stream RPC whose client acks each
chunk on receipt kept the server producing: the reader acked chunk after chunk while the
consumer that had its five, woken by a queued task, waited for the reader's step budget
(``take(5)`` saw the server make 7-31 items on Linux; Effect makes 5 or 6)."""

import pyfect as fx
from pyfect import testing
from pyfect.effect import gen, succeed, sync
from pyfect.queue import Queue
from pyfect.scope import scoped
from pyfect.socket import Listener, WebSocketEvent, WebSocketEventType, from_web_socket


class _AckedServer:
    """An open WebSocket whose server sends the next item as soon as an ack for the last
    arrives: its reply lands while the reader is still handling the item it acked."""

    def __init__(self) -> None:
        self.ready_state = 1
        self.listeners: dict[WebSocketEventType, list[Listener]] = {}
        self.produced = 0
        self.stopped = False

    def add_event_listener(
        self, type: WebSocketEventType, listener: Listener, *, once: bool = False
    ) -> None:
        self.listeners.setdefault(type, []).append(listener)

    def remove_event_listener(self, type: WebSocketEventType, listener: Listener) -> None:
        self.listeners[type] = [
            entry for entry in self.listeners.get(type, []) if entry is not listener
        ]

    def produce(self) -> None:
        if self.stopped:
            return
        self.produced += 1
        for listener in list(self.listeners.get("message", [])):
            listener(WebSocketEvent(type="message", data=str(self.produced)))

    def close(self, code: int | None = None, reason: str | None = None) -> None:
        pass

    def send(self, data: bytes | str) -> None:
        if data == "ack":
            self.produce()


@testing.effect
def test_a_message_that_came_while_the_reader_ran_waits_for_the_tasks_queued_before_it():
    ws = _AckedServer()
    socket = from_web_socket(succeed(ws))
    items = yield from Queue[str].bounded(16)

    def read():
        reader = yield from socket.reader
        writer = yield from socket.writer
        while True:
            for chunk in (yield from reader.pull):
                assert isinstance(chunk, str)
                yield from items.offer(chunk)
                yield from writer.write("ack")

    yield from scoped(gen(read)).fork(start_immediately=True)
    yield from sync(ws.produce)
    got = yield from fx.stream.from_queue(items).take(5).run_collect()
    ws.stopped = True
    assert list(got) == ["1", "2", "3", "4", "5"]
    # The consumer's wake, queued with item 5, runs before the reply to its ack is read.
    assert ws.produced <= 6, ws.produced
