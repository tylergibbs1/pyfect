"""Ports of Effect's ``platform-node-shared/test/NodeDatagramSocket.test.ts``
against ``pyfect.socket.datagram``'s live UDP sockets, on localhost.

Each test's docstring is the Effect test title. Node's ``dns.lookup`` spy
becomes a counting wrapper around ``socket.getaddrinfo``; the adopted
``dgram.Socket`` is a bound ``socket.socket``.
"""

import gc
import socket
from collections.abc import Callable, Iterator, Sequence
from typing import Any

import pytest

from pyfect import testing
from pyfect._core import Effect
from pyfect.clock import sleep
from pyfect.effect import gen, sync
from pyfect.errors import TimeoutException
from pyfect.net.net_address import format_inet
from pyfect.scope import Scope, scoped
from pyfect.socket.datagram import (
    Bind,
    Datagram,
    DatagramSocketError,
    DatagramSocketWriteError,
    HostPort,
    Options,
    OutgoingDatagram,
    Peer,
    Reader,
    Writer,
    from_socket,
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
        reader = yield from sock.reader
        writer = yield from sock.writer
        return reader, writer

    return gen(body)


def pull_n(
    reader: Reader, count: int
) -> Effect[list[Datagram], DatagramSocketError | TimeoutException]:
    """Pull until ``count`` packets arrived; a lost packet fails the timeout
    instead of hanging the test."""

    def body():
        received: list[Datagram] = []
        while len(received) < count:
            received.extend((yield from reader.pull))
        return received

    return gen(body).timeout("2 seconds")


def text(datagrams: Sequence[Datagram]) -> list[str]:
    return [datagram.payload.decode() for datagram in datagrams]


@live
def test_ipv4_round_trip():
    """IPv4 round trip, replying through the received datagram"""
    server_reader, server_writer = yield from open_udp(Options(bind=LOOPBACK))
    client_reader, client_writer = yield from open_udp(Options(bind=LOOPBACK))
    yield from client_writer.write_all(
        [
            OutgoingDatagram("a", server_reader.address),
            OutgoingDatagram("b", server_reader.address),
        ]
    )
    received = yield from pull_n(server_reader, 2)
    assert text(received) == ["a", "b"]
    assert format_inet(received[0].address) == format_inet(client_reader.address)

    for datagram in received:
        yield from server_writer.write(OutgoingDatagram(datagram.payload, datagram))
    replies = yield from pull_n(client_reader, 2)
    assert text(replies) == ["a", "b"]
    assert format_inet(replies[0].address) == format_inet(server_reader.address)


@live
def test_resolves_hostname_peer_once(monkeypatch: pytest.MonkeyPatch):
    """resolves a hostname peer once per reader"""
    lookups: list[str] = []
    original = socket.getaddrinfo

    def counting(host: str | None, *args: Any, **kwargs: Any) -> Any:
        if host == "localhost":
            lookups.append(host)
        return original(host, *args, **kwargs)

    monkeypatch.setattr(socket, "getaddrinfo", counting)
    server_reader, _ = yield from open_udp(Options(bind=LOOPBACK))
    _, client_writer = yield from open_udp(
        Options(remote=Peer(HostPort("localhost", server_reader.address.port)))
    )
    for payload in ["a", "b", "c"]:
        yield from client_writer.write(OutgoingDatagram(payload))
    received = yield from pull_n(server_reader, 3)
    assert text(received) == ["a", "b", "c"]
    assert len(lookups) == 1


@live
def test_send_error_fails_write():
    """a send error fails the write with DatagramSocketWriteError"""
    server_reader, _ = yield from open_udp(Options(bind=LOOPBACK))
    _, client_writer = yield from open_udp(Options(bind=LOOPBACK))
    address = server_reader.address
    too_large = bytes(70_000)

    error = yield from client_writer.write(OutgoingDatagram(too_large, address)).flip()
    reason = error.reason
    assert isinstance(reason, DatagramSocketWriteError)
    assert reason.kind == "MessageTooLarge"
    assert reason.address is not None
    assert format_inet(reason.address) == format_inet(address)

    # a send error is not terminal
    yield from client_writer.write(OutgoingDatagram("b", address))
    received = yield from pull_n(server_reader, 1)
    assert text(received) == ["b"]


@live
def test_from_socket_adopts_bound_socket():
    """fromSocket adopts a bound socket and closes it with the reader"""
    server_reader, _ = yield from open_udp(Options(bind=LOOPBACK))
    adopted: list[socket.socket] = []

    def acquire() -> socket.socket:
        native = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        native.bind(("127.0.0.1", 0))
        adopted.append(native)
        return native

    udp = yield from from_socket(sync(acquire), peer=server_reader.address)

    def use():
        reader = yield from udp.reader
        writer = yield from udp.writer
        assert reader.address.port == adopted[0].getsockname()[1]
        yield from writer.write(OutgoingDatagram("a"))
        received = yield from pull_n(server_reader, 1)
        assert text(received) == ["a"]
        assert received[0].address.port == reader.address.port

    yield from scoped(gen(use))
    yield from wait_until(lambda: adopted[0].fileno() == -1)


def wait_until(ready: Callable[[], bool]) -> Effect[None, TimeoutException]:
    """Poll ``ready`` (closing happens on the socket loop's thread)."""

    def body():
        while not ready():
            yield from sleep("10 millis")

    return gen(body).timeout("2 seconds")
