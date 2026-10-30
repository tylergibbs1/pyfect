"""Ports of Effect's ``socket/DatagramSocket.test.ts``.

Each test's docstring is the Effect test title. ``TestHandle`` is the
test's ``BackingSocket``; packets are pushed through the events the core
handed it.

Adapted: "resumes an already-parked pull before the native packet callback
returns" checks that the pull completes on the next scheduler turn. Packets
arrive from the platform's thread, and pyfect wakes a parked fiber to retry
through its scheduler rather than resuming it inside the callback (the
runtime rules in CLAUDE.md), so nothing can run before the callback
returns.
"""

from collections.abc import Callable, Sequence
from ipaddress import IPv4Address
from typing import Any, Never

from pyfect import testing
from pyfect._core import Effect
from pyfect.deferred import Deferred
from pyfect.effect import callback, provide_service, succeed, sync, yield_now
from pyfect.exit import Exit, Failure, Success
from pyfect.net.net_address import InetAddress, IpAddress, inet_address_from_native_unsafe
from pyfect.result import Ok
from pyfect.scope import CloseableScope, Scope, scoped
from pyfect.socket.datagram import (
    BackingAddress,
    BackingEvents,
    BackingSocket,
    Datagram,
    DatagramSocketClosedError,
    DatagramSocketError,
    DatagramSocketReadError,
    DatagramSocketService,
    DatagramSocketWriteError,
    Leave,
    OutgoingDatagram,
    ReceiveBuffer,
    SendDone,
    SendManyDone,
    make_from_backing_socket,
)

ADDRESS = inet_address_from_native_unsafe("127.0.0.1", 1234)


def failure() -> DatagramSocketError:
    return DatagramSocketError(DatagramSocketReadError("Unknown", Exception("read")))


class TestHandle:
    __test__ = False

    def __init__(self) -> None:
        self.address = BackingAddress("127.0.0.1", 1234)
        self.scope_ids: dict[str, int] = {}
        self.peer: BackingAddress | None = None
        self.connected = False
        self.events: BackingEvents | None = None
        self.sends: list[tuple[bytes, BackingAddress | None]] = []
        self.closes = 0
        self.leaves = 0
        self.joins = 0
        self.fail_at = 0
        self.send_count = 0
        self.defer_sends = False
        self.pending: list[Callable[[], None]] = []

    def send(self, payload: bytes, destination: BackingAddress | None, done: SendDone) -> None:
        self.sends.append((payload, destination))
        done(None)

    def send_many(
        self,
        payloads: Sequence[bytes],
        destinations: Sequence[BackingAddress | None],
        done: SendManyDone,
    ) -> None:
        error: DatagramSocketError | None = None
        index: int | None = None
        for i, payload in enumerate(payloads):
            self.send_count += 1
            if self.send_count == self.fail_at:
                error = DatagramSocketError(DatagramSocketWriteError("Unknown", Exception("send")))
                index = i
                break
            self.sends.append((payload, destinations[i]))
        if self.defer_sends:
            self.pending.append(lambda: done(error, index))
        else:
            done(error, index)

    def join_multicast(
        self, group: IpAddress, interface: IPv4Address | int | None, source: IpAddress | None
    ) -> Effect[Leave, DatagramSocketError]:
        def join() -> Leave:
            self.joins += 1
            return lambda: sync(self._leave)

        return sync(join)

    def _leave(self) -> None:
        self.leaves += 1

    def close(self) -> None:
        self.closes += 1

    def packet(self, text: str, host: str = "127.0.0.1", port: int = 9876) -> None:
        assert self.events is not None
        self.events.on_packet(text.encode(), host, port)

    def error(self, error: DatagramSocketError | None = None) -> None:
        assert self.events is not None
        self.events.on_read_error(error or failure())


def fixture(
    buffer: ReceiveBuffer | None = None,
) -> Effect[tuple[DatagramSocketService, list[TestHandle]]]:
    handles: list[TestHandle] = []

    def open(events: BackingEvents) -> Effect[BackingSocket, DatagramSocketError]:
        def make() -> BackingSocket:
            handle = TestHandle()
            handle.events = events
            handles.append(handle)
            return handle

        return sync(make)

    return make_from_backing_socket(open, receive_buffer=buffer).map(lambda s: (s, handles))


def texts(batch: Sequence[Datagram]) -> list[str]:
    return [packet.payload.decode() for packet in batch]


def error_of(exit: Exit[Any, DatagramSocketError]) -> DatagramSocketError:
    assert isinstance(exit, Failure)
    found = exit.cause.find_error()
    assert isinstance(found, Ok)
    return found.value


def write_reason(error: DatagramSocketError) -> DatagramSocketWriteError:
    assert isinstance(error.reason, DatagramSocketWriteError)
    return error.reason


@testing.effect
def test_waits_for_orphaned_open():
    """waits for an orphaned open before rebinding"""
    first_started: Deferred[None] = yield from Deferred[None].make()
    second_started: Deferred[None] = yield from Deferred[None].make()
    pending: list[Callable[[TestHandle], None]] = []

    def open(events: BackingEvents) -> Effect[BackingSocket, DatagramSocketError]:
        def register(resume: Callable[[Effect[BackingSocket, Never]], None]) -> None:
            def resolve(handle: TestHandle) -> None:
                handle.events = events
                resume(succeed(handle))

            pending.append(resolve)
            started = first_started if len(pending) == 1 else second_started
            started.done_unsafe(Success(None))

        return callback(register)

    socket = yield from make_from_backing_socket(open)
    first = yield from socket.reader.fork(start_immediately=True)
    yield from first_started.wait()
    interrupted = yield from first.interrupt().fork(start_immediately=True)
    yield from yield_now()
    assert interrupted.poll_unsafe() is not None, "interruption must finish before open resolves"
    second = yield from scoped(socket.reader.as_void()).fork(start_immediately=True)
    yield from yield_now()
    assert len(pending) == 1, "a retry must not overlap an orphaned open"
    old = TestHandle()
    pending[0](old)
    yield from second_started.wait()
    assert len(pending) == 2
    assert old.closes == 1
    pending[1](TestHandle())
    yield from second.join()


@testing.effect
def test_resumes_parked_pull():
    """resumes an already-parked pull before the native packet callback returns"""
    socket, handles = yield from fixture()
    reader = yield from socket.reader
    received: list[str] = []
    pull = yield from reader.pull.tap(
        lambda batch: sync(lambda: received.extend(texts(batch)))
    ).fork(start_immediately=True)
    yield from yield_now()
    assert pull.poll_unsafe() is None, "the pull must be parked before delivery"
    handles[0].packet("inline")
    yield from yield_now()
    assert received == ["inline"]
    assert texts((yield from pull.join())) == ["inline"]


@testing.effect
def test_fails_every_parked_pull_on_scope_close():
    """fails every parked pull on scope close"""
    socket, handles = yield from fixture()
    scope = CloseableScope()
    reader = yield from socket.reader.pipe(provide_service(Scope, scope))
    first = yield from reader.pull.exit().fork(start_immediately=True)
    yield from yield_now()
    second = yield from reader.pull.exit().fork(start_immediately=True)
    yield from yield_now()
    yield from scope.close(Success(None))
    assert handles[0].closes == 1
    yield from yield_now()
    assert first.poll_unsafe() is not None, "scope close must wake the first waiter"
    assert second.poll_unsafe() is not None, "scope close must wake the second waiter"
    for fiber in (first, second):
        exit = yield from fiber.join()
        assert isinstance(exit, Failure)
        error = error_of(exit)
        assert isinstance(error, DatagramSocketError)
        assert isinstance(error.reason, DatagramSocketClosedError)


@testing.effect
def test_fails_slot_and_queued_waiters():
    """fails the slot and queued waiters with the same terminal read error"""
    socket, handles = yield from fixture()
    reader = yield from socket.reader
    first = yield from reader.pull.exit().fork(start_immediately=True)
    yield from yield_now()
    assert first.poll_unsafe() is None, "the first pull occupies the waiter slot"
    second = yield from reader.pull.exit().fork(start_immediately=True)
    yield from yield_now()
    assert second.poll_unsafe() is None, "the second pull waits behind the slot"
    handles[0].error(failure())
    yield from yield_now()
    assert first.poll_unsafe() is not None, "read error must wake the first waiter"
    assert second.poll_unsafe() is not None, "read error must wake the second waiter"
    a = yield from first.join()
    b = yield from second.join()
    assert isinstance(a, Failure)
    assert a == b
    assert (yield from reader.pull.exit()) == a
    error = error_of(a)
    assert isinstance(error, DatagramSocketError)
    assert isinstance(error.reason, DatagramSocketReadError)


@testing.effect
def test_keeps_fifo_order():
    """keeps FIFO order when a waiting pull is promoted"""
    socket, handles = yield from fixture()
    reader = yield from socket.reader
    cancelled = yield from reader.pull.fork(start_immediately=True)
    yield from yield_now()
    first = yield from reader.pull.fork(start_immediately=True)
    yield from yield_now()
    second = yield from reader.pull.fork(start_immediately=True)
    yield from yield_now()
    yield from cancelled.interrupt()
    third = yield from reader.pull.fork(start_immediately=True)
    yield from yield_now()
    handle = handles[0]
    handle.packet("first")
    assert texts((yield from first.join())) == ["first"]
    assert second.poll_unsafe() is None
    assert third.poll_unsafe() is None
    handle.packet("second")
    assert texts((yield from second.join())) == ["second"]
    handle.packet("third")
    assert texts((yield from third.join())) == ["third"]


def _overflow(strategy: Any, expected: list[str]):
    def body():
        socket, handles = yield from fixture(ReceiveBuffer(2, strategy))
        reader = yield from socket.reader
        handle = handles[0]
        handle.packet("retained", "127.0.0.2", 1001)
        (retained,) = yield from reader.pull
        handle.packet("a")
        handle.packet("b")
        handle.packet("c")
        assert texts((yield from reader.pull)) == expected
        assert reader.dropped() == 1
        assert texts([retained]) == ["retained"]
        assert retained.address.port == 1001

    return body


@testing.effect
def test_overflow_dropping():
    """overflow using dropping"""
    yield from _overflow("dropping", ["a", "b"])()


@testing.effect
def test_overflow_sliding():
    """overflow using sliding"""
    yield from _overflow("sliding", ["b", "c"])()


@testing.effect
def test_delivers_queued_packets_before_sticky_error():
    """delivers queued packets before a sticky read error"""
    socket, handles = yield from fixture()
    reader = yield from socket.reader
    events = handles[0].events
    assert events is not None
    events.on_packet(b"queued", "127.0.0.1", 9876)
    events.on_read_error(failure())
    assert texts((yield from reader.pull)) == ["queued"]
    assert isinstance((yield from reader.pull.exit()), Failure)
    assert (yield from reader.pull.exit()) == (yield from reader.pull.exit())


@testing.effect
def test_rejects_write_without_destination():
    """rejects a write with no destination and no peer before sending"""
    socket, handles = yield from fixture()
    yield from socket.reader
    writer = yield from socket.writer
    handle = handles[0]
    single = write_reason((yield from writer.write(OutgoingDatagram("one")).flip()))
    assert single.address is None
    assert "no peer" in str(single.cause)
    batch = write_reason(
        (
            yield from writer.write_all(
                [OutgoingDatagram("a", ADDRESS), OutgoingDatagram("b")]
            ).flip()
        )
    )
    assert batch.address is None
    assert handle.sends == []
    # with a peer, the same writes go out
    handle.peer = BackingAddress("10.0.0.1", 53)
    yield from writer.write(OutgoingDatagram("one"))
    yield from writer.write_all([OutgoingDatagram("a", ADDRESS), OutgoingDatagram("b")])
    assert [d.port if d else None for _, d in handle.sends] == [53, 1234, 53]


@testing.effect
def test_rejects_explicit_address_on_connected_socket():
    """rejects an explicit address on a connected socket and sends the rest without one"""
    socket, handles = yield from fixture()
    reader = yield from socket.reader
    writer = yield from socket.writer
    handle = handles[0]
    handle.connected = True
    handle.peer = BackingAddress("10.0.0.1", 53)
    single = write_reason((yield from writer.write(OutgoingDatagram("one", ADDRESS)).flip()))
    assert single.address == ADDRESS
    batch = write_reason(
        (
            yield from writer.write_all(
                [OutgoingDatagram("a"), OutgoingDatagram("b", ADDRESS)]
            ).flip()
        )
    )
    assert batch.address == ADDRESS
    assert handle.sends == []
    handle.packet("hello", "127.0.0.2", 3000)
    (packet,) = yield from reader.pull
    yield from writer.write(OutgoingDatagram("one"))
    yield from writer.write(OutgoingDatagram(packet.payload, packet))
    yield from writer.write_all([OutgoingDatagram("a"), OutgoingDatagram("b", packet)])
    assert len(handle.sends) == 4
    assert all(destination is None for _, destination in handle.sends)


@testing.effect
def test_resumes_parked_write_all():
    """resumes a parked writeAll and reports a deferred batch failure's destination"""
    socket, handles = yield from fixture()
    yield from socket.reader
    writer = yield from socket.writer
    handle = handles[0]
    handle.defer_sends = True
    first = (
        yield from writer.write_all(
            [OutgoingDatagram("a", ADDRESS), OutgoingDatagram("b", ADDRESS)]
        )
        .exit()
        .fork(start_immediately=True)
    )
    yield from yield_now()
    assert first.poll_unsafe() is None, "writeAll must wait for the runtime to report the batch"
    assert len(handle.pending) == 1
    handle.pending.pop(0)()
    assert isinstance((yield from first.join()), Success)
    handle.fail_at = 4
    destination: InetAddress = inet_address_from_native_unsafe("127.0.0.2", 2345)
    second = (
        yield from writer.write_all(
            [
                OutgoingDatagram("c", ADDRESS),
                OutgoingDatagram("d", destination),
                OutgoingDatagram("not sent", ADDRESS),
            ]
        )
        .exit()
        .fork(start_immediately=True)
    )
    yield from yield_now()
    assert second.poll_unsafe() is None
    handle.pending.pop(0)()
    exit: Exit[None, DatagramSocketError] = yield from second.join()
    assert isinstance(exit, Failure)
    error = error_of(exit)
    assert isinstance(error, DatagramSocketError)
    assert write_reason(error).address == destination
    assert len(handle.sends) == 3, "the batch must stop at the first failure"


@testing.effect
def test_leaves_multicast_group():
    """leaves a multicast group when its scope closes"""
    socket, handles = yield from fixture()
    reader = yield from socket.reader
    yield from scoped(reader.join_multicast(IPv4Address("224.0.0.1")))
    assert handles[0].joins == 1
    assert handles[0].leaves == 1
