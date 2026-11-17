"""A caller may close the ``socket.socket`` it gave ``from_socket`` at any time: the socket
loop watches its own duplicate, so the next socket given the closed number still reads."""

import gc
import socket
from collections.abc import Iterator

import pytest

from pyfect import testing
from pyfect.clock import sleep
from pyfect.effect import sync
from pyfect.scope import scoped
from pyfect.socket import from_socket as stream_from_socket
from pyfect.socket.datagram import Bind, Options, OutgoingDatagram, make_udp
from pyfect.socket.datagram import from_socket as datagram_from_socket

live = testing.live(timeout="5 seconds")


@pytest.fixture(autouse=True)
def collect_leaks() -> Iterator[None]:
    yield
    gc.collect()


@live
def test_closing_an_adopted_datagram_socket_early_leaves_other_sockets_reading():
    native = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    native.bind(("127.0.0.1", 0))
    adopted = yield from datagram_from_socket(sync(lambda: native))
    yield from adopted.reader
    closed = native.fileno()
    native.close()

    other = yield from make_udp(Options(bind=Bind("127.0.0.1")))
    reader = yield from other.reader
    sender = yield from make_udp(Options(bind=Bind("127.0.0.1")))
    yield from sender.reader
    writer = yield from sender.writer
    yield from writer.write(OutgoingDatagram("hi", reader.address))
    batch = yield from reader.pull.timeout("2 seconds")
    assert [d.payload for d in batch] == [b"hi"], closed


@live
def test_closing_an_adopted_stream_socket_early_leaves_other_sockets_reading():
    ours, peer = socket.socketpair()
    adopted = stream_from_socket(sync(lambda: ours))
    yield from adopted.reader
    ours.close()

    theirs, other_peer = socket.socketpair()
    try:
        reader = yield from stream_from_socket(sync(lambda: theirs)).reader
        other_peer.sendall(b"hi")
        chunks = yield from reader.pull.timeout("2 seconds")
        assert b"".join(c if isinstance(c, bytes) else c.encode() for c in chunks) == b"hi"
    finally:
        peer.close()
        other_peer.close()


@live
def test_an_adopted_socket_is_still_closed_with_the_reader():
    native = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    native.bind(("127.0.0.1", 0))
    adopted = yield from datagram_from_socket(sync(lambda: native))
    yield from scoped(adopted.reader)
    ours, peer = socket.socketpair()
    yield from scoped(stream_from_socket(sync(lambda: ours)).reader)
    peer.close()
    for _ in range(200):
        if native.fileno() == -1 and ours.fileno() == -1:
            break
        yield from sleep("10 millis")
    assert native.fileno() == -1 and ours.fileno() == -1
