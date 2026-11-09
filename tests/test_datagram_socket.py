"""pyfect-specific behaviour of ``pyfect.socket.datagram``: boundary
validation, the live adapter's options and errors, and the reader/writer
handover on real sockets."""

import gc
import socket
from collections.abc import Iterator
from ipaddress import IPv4Address, IPv6Address

import pytest

from pyfect import testing
from pyfect._core import Effect
from pyfect.clock import sleep
from pyfect.effect import gen, yield_now
from pyfect.exit import Failure
from pyfect.net.net_address import InetAddressV4
from pyfect.run import run_blocking_exit
from pyfect.scope import Scope, scoped
from pyfect.socket.datagram import (
    BackingEvents,
    BackingSocket,
    Bind,
    Connect,
    Datagram,
    DatagramSocketError,
    DatagramSocketOpenError,
    DatagramSocketReadError,
    HostPort,
    Multicast,
    Options,
    OutgoingDatagram,
    Peer,
    Reader,
    ReceiveBuffer,
    Writer,
    make_from_backing_socket,
    make_udp,
)

live = testing.live(timeout="10 seconds")

pytestmark = pytest.mark.filterwarnings(
    "error::ResourceWarning", "error::pytest.PytestUnraisableExceptionWarning"
)


@pytest.fixture(autouse=True)
def collect_leaks() -> Iterator[None]:
    yield
    gc.collect()


LOOPBACK = Bind("127.0.0.1")


def open_udp(options: Options) -> Effect[tuple[Reader, Writer], DatagramSocketError, Scope]:
    def body():
        sock = yield from make_udp(options)
        return (yield from sock.reader), (yield from sock.writer)

    return gen(body)


def pull_text(reader: Reader) -> Effect[list[str], Exception]:
    return reader.pull.timeout("2 seconds").map(lambda batch: [d.payload.decode() for d in batch])


def pull_texts(reader: Reader, count: int) -> Effect[list[str], Exception]:
    """Pulls until ``count`` datagrams arrived: two sends may land in
    separate batches."""

    def body():
        texts: list[str] = []
        while len(texts) < count:
            texts += yield from pull_text(reader)
        return texts

    return gen(body)


def _never_open(_: BackingEvents) -> Effect[BackingSocket, DatagramSocketError]:
    raise AssertionError("a socket with an invalid buffer is never made")


@pytest.mark.parametrize("capacity", [0, -1])
def test_a_receive_buffer_below_one_dies_when_the_socket_is_made(capacity: int):
    """Effect throws inside ``withFiber``: a defect when it runs, not at the call."""
    buffer = ReceiveBuffer(capacity)
    exit = run_blocking_exit(make_from_backing_socket(_never_open, receive_buffer=buffer))
    assert isinstance(exit, Failure)
    assert "must be a positive integer" in str(exit.cause.squash())


@live
def test_join_multicast_rejects_a_unicast_group():
    reader, _ = yield from open_udp(Options(bind=LOOPBACK))
    with pytest.raises(ValueError, match="not a multicast address"):
        reader.join_multicast(IPv4Address("127.0.0.1"))


@live
def test_a_write_waits_for_a_reader():
    server, _ = yield from open_udp(Options(bind=LOOPBACK))
    client = yield from make_udp(Options(bind=LOOPBACK))
    writer = yield from client.writer
    pending = yield from writer.write(OutgoingDatagram("late", server.address)).fork()
    yield from yield_now()
    assert pending.poll_unsafe() is None
    yield from client.reader
    yield from pending.join()
    assert (yield from pull_text(server)) == ["late"]


@live
def test_a_second_reader_waits_for_the_first_to_close():
    udp = yield from make_udp(Options(bind=LOOPBACK))
    first_scope_open = [True]

    def first():
        yield from udp.reader
        yield from sleep("100 millis")
        first_scope_open[0] = False

    running = yield from scoped(gen(first)).fork()
    yield from yield_now()
    yield from udp.reader
    assert not first_scope_open[0]
    yield from running.join()


@live
def test_a_hand_built_datagram_is_a_destination():
    server, _ = yield from open_udp(Options(bind=LOOPBACK))
    _, writer = yield from open_udp(Options(bind=LOOPBACK))
    yield from writer.write(Datagram(b"echo", server.address))
    yield from writer.write(OutgoingDatagram("reply", Datagram(b"", server.address)))
    assert (yield from pull_texts(server, 2)) == ["echo", "reply"]


@live
def test_write_all_of_nothing_sends_nothing():
    _, writer = yield from open_udp(Options(bind=LOOPBACK))
    yield from writer.write_all([])


@live
def test_ipv6_round_trip():
    server, _ = yield from open_udp(Options(bind=Bind(IPv6Address("::1"))))
    client, writer = yield from open_udp(Options(remote=Peer(server.address)))
    assert isinstance(client.address.address, IPv6Address)
    yield from writer.write(OutgoingDatagram("six"))
    assert (yield from pull_text(server)) == ["six"]


@live
def test_a_connected_socket_reports_refused_packets_to_on_error():
    errors: list[DatagramSocketError] = []
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    probe.bind(("127.0.0.1", 0))
    closed_port = probe.getsockname()[1]
    probe.close()
    _, writer = yield from open_udp(
        Options(remote=Connect(HostPort("127.0.0.1", closed_port)), on_error=errors.append)
    )
    yield from writer.write(OutgoingDatagram("anyone?"))
    for _ in range(100):
        if errors:
            break
        yield from sleep("20 millis")
    assert errors
    reason = errors[0].reason
    assert isinstance(reason, DatagramSocketReadError)
    assert reason.kind == "ConnectionRefused"


@live
def test_a_connected_socket_rejects_an_explicit_address():
    server, _ = yield from open_udp(Options(bind=LOOPBACK))
    _, writer = yield from open_udp(Options(remote=Connect(server.address)))
    error = yield from writer.write(OutgoingDatagram("x", server.address)).flip()
    assert "connected" in str(error.cause)
    yield from writer.write(OutgoingDatagram("ok"))
    assert (yield from pull_text(server)) == ["ok"]


@live
def test_binding_a_port_in_use_fails_with_address_in_use():
    server, _ = yield from open_udp(Options(bind=LOOPBACK))
    error = yield from open_udp(Options(bind=Bind("127.0.0.1", server.address.port))).flip()
    reason = error.reason
    assert isinstance(reason, DatagramSocketOpenError)
    assert reason.kind == "AddressInUse"


@live
def test_a_failed_lookup_fails_with_address_not_available(monkeypatch: pytest.MonkeyPatch):
    def unresolvable(*_args: object, **_kwargs: object) -> object:
        raise socket.gaierror(socket.EAI_NONAME, "not known")

    monkeypatch.setattr(socket, "getaddrinfo", unresolvable)
    error = yield from open_udp(Options(remote=Peer(HostPort("nowhere.invalid", 9)))).flip()
    reason = error.reason
    assert isinstance(reason, DatagramSocketOpenError)
    assert reason.kind == "AddressNotAvailable"


@live
def test_multicast_on_the_loopback_interface():
    group = IPv4Address("239.255.0.1")
    receiver, _ = yield from open_udp(Options(bind=Bind("0.0.0.0"), reuse_address=True))
    yield from receiver.join_multicast(group, interface=IPv4Address("127.0.0.1"))
    _, writer = yield from open_udp(
        Options(
            remote=Peer(InetAddressV4(group, receiver.address.port)),
            multicast=Multicast(interface=IPv4Address("127.0.0.1"), ttl=1, loopback=True),
        )
    )
    yield from writer.write(OutgoingDatagram("hello"))
    assert (yield from pull_text(receiver)) == ["hello"]
