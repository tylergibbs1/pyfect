"""Live socket behavior beyond the Effect ports."""

import asyncio
import gc
import socket
from collections.abc import Callable, Iterator
from pathlib import Path

import pytest

from pyfect import testing
from pyfect._core import Effect
from pyfect.effect import gen, succeed, sync, void
from pyfect.net.net_address import InetAddressV4
from pyfect.redacted import Redacted
from pyfect.scope import acquire_release, scoped
from pyfect.socket import (
    SocketCloseError,
    SocketService,
    TlsUpgradeOptions,
    from_socket,
    make_net,
    reader_string,
    server,
)
from pyfect.socket._accepted import Accepted
from pyfect.socket._connection import Connection
from pyfect.socket._loop import get_loop
from pyfect.socket.server import _NetIncoming  # pyright: ignore[reportPrivateUsage]

FIXTURES = Path(__file__).parent / "oracle" / "fixtures" / "tls"
CERT = (FIXTURES / "cert.pem").read_text()
KEY = (FIXTURES / "key.pem").read_text()

pytestmark = pytest.mark.filterwarnings(
    "error::ResourceWarning", "error::pytest.PytestUnraisableExceptionWarning"
)


@pytest.fixture(autouse=True)
def collect_leaks() -> Iterator[None]:
    yield
    gc.collect()


def adopted(on_made: Callable[[Connection], None]) -> tuple[Connection, socket.socket]:
    """A live connection over one end of a socketpair, and the peer end;
    ``on_made`` runs when it is made, as it would for an accepted one."""
    ours, peer = socket.socketpair()
    conn = Connection(on_made)

    async def adopt() -> None:
        await get_loop().connect_accepted_socket(lambda: conn, ours)

    asyncio.run_coroutine_threadsafe(adopt(), get_loop()).result(timeout=5)
    return conn, peer


def test_connection_made_after_server_close_is_aborted():
    # The loop can make an accepted connection after the server closed (its
    # connection_made was queued behind the close); nothing would take it.
    accepted = Accepted()
    accepted.close()
    conn, peer = adopted(lambda c: accepted.add(_NetIncoming(c)))
    peer.settimeout(5)
    try:
        assert peer.recv(1) == b""
    except ConnectionResetError:
        pass
    finally:
        peer.close()
    assert not accepted.has_pending()
    assert conn.transport is not None and conn.transport.is_closing()


@testing.live(timeout=10)
def test_writes_after_the_peer_ends_its_stream():
    # The peer's end-of-stream ends the read side only: the connection stays
    # half-open until the writer is released.
    pair = yield from acquire_release(sync(socket.socketpair), lambda p, _: sync(p[1].close))
    ours, peer = pair
    sock = from_socket(acquire_release(sync(lambda: ours), lambda _s, _e: sync(lambda: None)))
    reader = yield from sock.reader
    writer = yield from sock.writer
    peer.sendall(b"x")
    peer.shutdown(socket.SHUT_WR)
    received = b""
    while not received:
        received += b"".join(
            c if isinstance(c, bytes) else c.encode() for c in (yield from reader.pull)
        )
    assert received == b"x"
    error = yield from reader.pull.flip()
    assert isinstance(error.reason, SocketCloseError) and error.reason.code == 1000
    yield from writer.write_all([b"y"])
    peer.settimeout(5)
    assert peer.recv(1) == b"y"


def _pair_socket() -> tuple[SocketService, socket.socket]:
    ours, peer = socket.socketpair()
    return from_socket(succeed(ours)), peer


@testing.live(timeout=10)
def test_reader_string_drops_a_byte_order_mark():
    # TextDecoder("utf-8") drops a leading BOM, again after each flush.
    sock, peer = _pair_socket()
    yield from acquire_release(sync(lambda: peer), lambda p, _: sync(p.close))
    pull = yield from reader_string(sock)
    peer.sendall(b"\xef\xbb\xbfhi")
    assert "".join((yield from pull)) == "hi"


@testing.live(timeout=10)
def test_text_with_a_lone_surrogate_is_written_as_text_encoder_does():
    sock, peer = _pair_socket()
    yield from acquire_release(sync(lambda: peer), lambda p, _: sync(p.close))
    writer = yield from sock.writer
    yield from sock.reader
    yield from writer.write("a\ud800")
    yield from writer.write_all(["\udc00b"])
    peer.settimeout(5)
    received = b""
    while len(received) < 8:
        received += peer.recv(16)
    assert received == b"a\xef\xbf\xbd\xef\xbf\xbdb"


@testing.live(timeout=10)
def test_writes_during_a_tls_upgrade_are_sent_encrypted():
    # Node writes to the TLS socket as soon as the upgrade starts, so a
    # write made while the handshake runs is encrypted once it is done.
    srv = yield from server.make_tls(cert=CERT, key=Redacted(KEY), host="127.0.0.1")
    yield from srv.run(_echo).fork_scoped()
    address = srv.address
    assert isinstance(address, InetAddressV4)
    client = make_net(address.port, "127.0.0.1")
    writer = yield from client.writer
    reader = yield from client.reader
    upgrading = yield from reader.upgrade(TlsUpgradeOptions(ca=[CERT])).fork(start_immediately=True)
    yield from writer.write("hello")
    yield from upgrading.join()
    received = b""
    while len(received) < 5:
        received += b"".join(
            c if isinstance(c, bytes) else c.encode() for c in (yield from reader.pull)
        )
    assert received == b"hello"


def _echo(sock: SocketService) -> Effect[None]:
    def body():
        writer = yield from sock.writer
        reader = yield from sock.reader
        while True:
            yield from writer.write_all((yield from reader.pull))

    return scoped(gen(body)).catch_all(lambda _: void)
