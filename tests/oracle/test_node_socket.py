"""Ports of Effect's ``platform-node/test/NodeSocket.test.ts`` against the
live sockets of ``pyfect.socket`` and ``pyfect.socket.server``, on
localhost.

Node's in-memory ``Duplex``/``PassThrough`` become one end of a
``socket.socketpair()`` given to ``from_socket``; the other end plays the
peer. Node ``tls.createServer`` echo servers become a stdlib ``ssl`` echo
server on a thread. Each test's docstring is the Effect test title.

"closes with a pending pre-run WebSocket" and the ``WebSocket`` group are
in ``test_node_socket_web_socket.py`` (they need the ``websockets`` extra).

Omitted:
- the ``TransformStream`` group: it builds a socket from web streams
  (``ReadableStream``/``WritableStream``), which Python does not have.
- "destroys a pending TCP connection on open timeout" and "destroys a
  pending TLS connection on open timeout": they spy on Node's
  ``destroy``/``destroySoon`` through ``vi.mock``; the connection is aborted
  through the same path the "gracefully closes" port checks.
- "preserves omitted client TLS upgrade servername": it inspects the
  options handed to a mocked ``tls.connect``; "upgrades a makeNet client
  connection to TLS" covers the default name, and the explicit name is
  checked through a real handshake below.
"""

import gc
import socket
import ssl
import threading
from collections.abc import Iterator
from pathlib import Path
from typing import Never

import pytest

from pyfect import stream, testing
from pyfect._core import Effect
from pyfect.effect import gen, never, provide_service, succeed, sync, void
from pyfect.exit import Success
from pyfect.net.net_address import InetAddressV4, InetAddressV6
from pyfect.redacted import Redacted
from pyfect.scope import CloseableScope, Scope, acquire_release, scoped
from pyfect.socket import (
    Reader,
    SocketCloseError,
    SocketError,
    SocketOpenError,
    SocketService,
    SocketUpgradeError,
    TlsUpgradeOptions,
    from_socket,
    make_net,
    make_net_channel,
    make_tls,
    make_tls_channel,
    reader_bytes,
    server,
)

FIXTURES = Path(__file__).parent / "fixtures" / "tls"
CERT = (FIXTURES / "cert.pem").read_text()
KEY = (FIXTURES / "key.pem").read_text()

live = testing.live(timeout="10 seconds")

# A connection nobody closes is a bug: collect garbage after each test so a
# leaked transport's "unclosed" warning fails the test that leaked it.
pytestmark = pytest.mark.filterwarnings(
    "error::ResourceWarning", "error::pytest.PytestUnraisableExceptionWarning"
)


@pytest.fixture(autouse=True)
def collect_leaks() -> Iterator[None]:
    yield
    gc.collect()


def port_of(srv: server.SocketServerService) -> int:
    address = srv.address
    assert isinstance(address, InetAddressV4 | InetAddressV6)
    return address.port


def echo_handler(sock: SocketService, upgrade: TlsUpgradeOptions | None = None) -> Effect[None]:
    def body():
        writer = yield from sock.writer
        reader = yield from sock.reader
        if upgrade is not None:
            yield from reader.upgrade(upgrade)
        while True:
            yield from writer.write_all((yield from reader.pull))

    return scoped(gen(body)).catch_all(lambda _: void)


def send_hello_world(
    sock: SocketService, upgrade: TlsUpgradeOptions | None = None
) -> Effect[str, SocketError]:
    def body():
        writer = yield from sock.writer
        reader = yield from sock.reader
        if upgrade is not None:
            yield from reader.upgrade(upgrade)
        yield from writer.write_all(["Hello", "World"])
        text = ""
        while len(text) < 10:
            for chunk in (yield from reader.pull):
                text += chunk if isinstance(chunk, str) else chunk.decode()
        return text

    return scoped(gen(body))


def make_server(
    host: str = "127.0.0.1",
) -> Effect[server.SocketServerService, server.SocketServerError, Scope]:
    def body():
        srv = yield from server.make(0, host)
        yield from srv.run(echo_handler).fork_scoped()
        return srv

    return gen(body)


def decode(batch: tuple[bytes | str, ...]) -> str:
    return "".join(c if isinstance(c, str) else c.decode() for c in batch)


type Pair = tuple[socket.socket, socket.socket]


def socket_pair() -> Effect[Pair, Never, Scope]:
    """A connected pair: the first end opened for ``from_socket`` (taken
    over by it), the second the peer, closed with the scope."""
    return acquire_release(sync(socket.socketpair), lambda pair, _: sync(pair[1].close))


def pair_socket(pair: Pair, *, tls_server: bool = False) -> SocketService:
    return from_socket(succeed(pair[0]), tls_server=tls_server)


def parked_pull():
    """A socketpair-backed reader with one pull parked, waiting for bytes."""
    pair = yield from socket_pair()
    reader = yield from pair_socket(pair).reader
    parked = yield from reader.pull.fork(start_immediately=True)
    return pair[1], reader.pull, parked


@pytest.fixture
def tls_echo_port() -> Iterator[int]:
    """A stdlib TLS echo server (Node's ``tls.createServer`` + ``pipe``)."""
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(FIXTURES / "cert.pem", FIXTURES / "key.pem")
    listener = socket.create_server(("127.0.0.1", 0))
    conns: list[socket.socket] = []

    def serve(conn: socket.socket) -> None:
        try:
            with context.wrap_socket(conn, server_side=True) as tls:
                conns.append(tls)
                while data := tls.recv(65536):
                    tls.sendall(data)
        except OSError:
            pass

    def accept() -> None:
        while True:
            try:
                conn, _ = listener.accept()
            except OSError:
                return
            threading.Thread(target=serve, args=(conn,), daemon=True).start()

    threading.Thread(target=accept, daemon=True).start()
    yield listener.getsockname()[1]
    listener.close()
    for conn in conns:
        conn.close()


@live
def test_ipv6_listener_address():
    """preserves a native IPv6 listener address"""
    srv = yield from server.make(0, "::1")
    assert isinstance(srv.address, InetAddressV6)
    assert str(srv.address.address) == "::1"
    assert srv.address.port != 0


@live
def test_closes_with_pending_pre_run_socket():
    """closes with a pending pre-run socket"""
    scope = CloseableScope()
    srv = yield from server.make(0, "127.0.0.1").pipe(provide_service(Scope, scope))
    conn = socket.create_connection(("127.0.0.1", port_of(srv)))
    try:
        exit = yield from scope.close(Success(None)).timeout("1 second").exit()
    finally:
        conn.close()
    assert isinstance(exit, Success)


@live
def test_open():
    """open"""
    srv = yield from make_server()
    output = yield from (
        stream.make("Hello", "World")
        .encode_text()
        .pipe_through_channel(make_net_channel(port_of(srv), "127.0.0.1"))
        .catch_if(lambda e: isinstance(e.reason, SocketCloseError), lambda _: stream.empty)
        .decode_text()
        .run_collect()
    )
    assert "".join(output) == "HelloWorld"


@live
def test_pull_batches():
    """pull batches"""
    srv = yield from make_server()
    sock = make_net(port_of(srv), "127.0.0.1")

    def body():
        writer = yield from sock.writer
        pull = yield from reader_bytes(sock)
        yield from writer.write_all(["Hello", "World"])
        received = b""
        while len(received) < 10:
            received += b"".join((yield from pull))
        return received

    assert (yield from scoped(gen(body))) == b"HelloWorld"


@live
def test_pull_drains_buffered():
    """pull drains every buffered duplex chunk"""
    pair = yield from socket_pair()
    pair[1].sendall(b"aa")
    pair[1].sendall(b"bb")
    reader = yield from pair_socket(pair).reader
    received = b""
    while len(received) < 4:
        received += b"".join((yield from reader_bytes_of(reader)))
    assert received == b"aabb"


def reader_bytes_of(reader: Reader) -> Effect[tuple[bytes, ...], SocketError]:
    return reader.pull.map(lambda batch: tuple(map(encode, batch)))


def encode(chunk: bytes | str) -> bytes:
    return chunk.encode() if isinstance(chunk, str) else chunk


@live
def test_reader_scope_closure_during_parked_pull():
    """handles reader scope closure during a parked pull read"""
    pair = yield from socket_pair()
    sock = pair_socket(pair)
    read_scope = CloseableScope()
    reader = yield from sock.reader.pipe(provide_service(Scope, read_scope))
    parked = yield from reader.pull.fork(start_immediately=True)
    yield from read_scope.close(Success(None))
    error = yield from parked.join().flip().timeout("1 second")
    assert isinstance(error.reason, SocketCloseError)
    assert error.reason.code == 1006


@live
def test_parked_pull_interrupted_keeps_chunk():
    """preserves a chunk when a parked pull is interrupted during read"""
    peer, pull, parked = yield from parked_pull()
    yield from parked.interrupt()
    peer.sendall(b"hello")
    assert decode((yield from pull.timeout("1 second"))) == "hello"


@live
def test_retained_chunk_then_eof():
    """drains a retained chunk when EOF follows parked pull interruption"""
    peer, pull, parked = yield from parked_pull()
    yield from parked.interrupt()
    exit = yield from parked.await_exit()
    assert not isinstance(exit, Success) and exit.cause.has_interrupts
    peer.sendall(b"hello")
    peer.shutdown(socket.SHUT_WR)
    received = ""
    while len(received) < 5:
        received += decode((yield from pull.timeout("1 second")))
    assert received == "hello"
    error = yield from pull.flip().timeout("1 second")
    assert isinstance(error.reason, SocketCloseError)
    assert error.reason.code == 1000


@live
def test_replaced_parked_pull_keeps_order():
    """preserves order when a parked pull is replaced synchronously during read"""
    peer, pull, parked = yield from parked_pull()
    yield from parked.interrupt()
    peer.sendall(b"first")
    replacement = yield from pull.fork(start_immediately=True)
    peer.sendall(b"second")
    received = decode((yield from replacement.join().timeout("1 second")))
    while len(received) < len("firstsecond"):
        received += decode((yield from pull.timeout("1 second")))
    assert received == "firstsecond"


@live
def test_zero_open_timeout():
    """respects a zero open timeout"""
    sock = from_socket(never, open_timeout=0)

    error = yield from scoped(sock.reader.as_void()).flip().timeout("1 second")
    assert isinstance(error.reason, SocketOpenError)
    assert error.reason.kind == "Timeout"


@live
def test_graceful_close():
    """gracefully closes an established TCP connection"""
    listener = socket.create_server(("127.0.0.1", 0))
    sock = make_net(listener.getsockname()[1], "127.0.0.1")

    yield from scoped(sock.reader.as_void())
    conn, _ = listener.accept()
    conn.settimeout(5)
    # A graceful close ends the stream (FIN); an abort would reset it.
    assert conn.recv(1) == b""
    conn.close()
    listener.close()


@live
def test_tls_open(tls_echo_port: int):
    """open"""
    channel = make_tls_channel(tls_echo_port, "127.0.0.1", tls=TlsUpgradeOptions(ca=[CERT]))
    output = yield from (
        stream.make("Hello", "World")
        .encode_text()
        .pipe_through_channel(channel)
        .catch_if(lambda e: isinstance(e.reason, SocketCloseError), lambda _: stream.empty)
        .decode_text()
        .run_collect()
    )
    assert "".join(output) == "HelloWorld"


@live
def test_tls_echo(tls_echo_port: int):
    """echoes over the reader and writer"""
    sock = make_tls(tls_echo_port, "127.0.0.1", tls=TlsUpgradeOptions(ca=[CERT]))
    assert (yield from send_hello_world(sock)) == "HelloWorld"


@live
def test_tls_untrusted(tls_echo_port: int):
    """fails to open against an untrusted certificate"""
    sock = make_tls(tls_echo_port, "127.0.0.1")

    error = yield from scoped(sock.reader.as_void()).flip()
    assert isinstance(error.reason, SocketOpenError)
    assert error.reason.kind == "Unknown"
    cause = error.reason.cause
    assert isinstance(cause, ssl.SSLCertVerificationError)
    assert cause.verify_code == 18  # X509_V_ERR_DEPTH_ZERO_SELF_SIGNED_CERT


@live
def test_tls_server_echo():
    """echoes through a NodeSocketServer.makeTls server"""
    srv = yield from server.make_tls(cert=CERT, key=Redacted(KEY), host="127.0.0.1")
    yield from srv.run(echo_handler).fork_scoped()
    sock = make_tls(port_of(srv), "127.0.0.1", tls=TlsUpgradeOptions(ca=[CERT]))
    assert (yield from send_hello_world(sock)) == "HelloWorld"


@live
def test_upgrade_server_connection():
    """upgrades a plain NodeSocketServer connection to TLS"""
    srv = yield from server.make(0, "127.0.0.1")
    options = TlsUpgradeOptions(cert=CERT, key=Redacted(KEY))
    yield from srv.run(lambda s: echo_handler(s, options)).fork_scoped()
    sock = make_tls(port_of(srv), "127.0.0.1", tls=TlsUpgradeOptions(ca=[CERT]))
    assert (yield from send_hello_world(sock)) == "HelloWorld"


@live
def test_upgrade_client_connection():
    """upgrades a makeNet client connection to TLS"""
    srv = yield from server.make_tls(cert=CERT, key=Redacted(KEY), host="127.0.0.1")
    yield from srv.run(echo_handler).fork_scoped()
    sock = make_net(port_of(srv), "127.0.0.1")
    options = TlsUpgradeOptions(ca=[CERT], reject_unauthorized=True)
    assert (yield from send_hello_world(sock, options)) == "HelloWorld"


@live
def test_upgrade_servername():
    """forwards explicit client TLS upgrade servername"""
    srv = yield from server.make_tls(cert=CERT, key=Redacted(KEY), host="127.0.0.1")
    yield from srv.run(lambda _: never).fork_scoped()
    sock = make_net(port_of(srv), "127.0.0.1")
    options = TlsUpgradeOptions(ca=[CERT], reject_unauthorized=True, servername="mail.example.test")

    def body():
        reader = yield from sock.reader
        return (yield from reader.upgrade(options).flip())

    error = yield from scoped(gen(body))
    assert isinstance(error.reason, SocketUpgradeError)
    cause = error.reason.cause
    # The certificate names localhost, so the forwarded name fails the check.
    assert isinstance(cause, ssl.SSLCertVerificationError)
    assert "mail.example.test" in str(cause)


def upgrade_error_of(
    sock: SocketService, options: TlsUpgradeOptions | None = None
) -> Effect[SocketError, SocketError | None]:
    def body():
        reader = yield from sock.reader
        return (yield from reader.upgrade(options).flip())

    return scoped(gen(body))


@live
def test_server_upgrade_requires_credentials():
    """requires both key and cert for server TLS upgrades"""
    pair = yield from socket_pair()
    error = yield from upgrade_error_of(pair_socket(pair, tls_server=True))
    assert isinstance(error.reason, SocketUpgradeError)
    assert str(error.reason.cause) == "server TLS upgrade requires both key and cert"


@live
def test_incomplete_client_credentials():
    """rejects incomplete client credentials"""
    pair = yield from socket_pair()
    error = yield from upgrade_error_of(pair_socket(pair), TlsUpgradeOptions(cert=CERT))
    assert isinstance(error.reason, SocketUpgradeError)
    assert str(error.reason.cause) == "TLS upgrade credentials must include both key and cert"


@live
def test_interrupted_upgrade_fails_pulls():
    """fails pulls after an interrupted TLS upgrade"""
    pair = yield from socket_pair()
    sock = pair_socket(pair)

    def body():
        reader = yield from sock.reader
        upgrading = yield from reader.upgrade().fork(start_immediately=True)
        yield from upgrading.interrupt()
        return (yield from reader.pull.flip().timeout("1 second"))

    error = yield from scoped(gen(body))
    assert isinstance(error.reason, SocketCloseError)


@live
def test_second_upgrade_rejected():
    """rejects a second TLS upgrade"""
    srv = yield from server.make_tls(cert=CERT, key=Redacted(KEY), host="127.0.0.1")

    def hold(s: SocketService) -> Effect[Never, SocketError]:

        return scoped(s.reader.and_then(never))

    yield from srv.run(hold).fork_scoped()
    sock = make_net(port_of(srv), "127.0.0.1")
    options = TlsUpgradeOptions(cert=CERT, key=Redacted(KEY), ca=[CERT], reject_unauthorized=True)

    def body():
        reader = yield from sock.reader
        yield from reader.upgrade(options)
        return (yield from reader.upgrade(options).flip().timeout("1 second"))

    error = yield from scoped(gen(body))
    assert isinstance(error.reason, SocketUpgradeError)


@live
def test_handshake_failure():
    """reports TLS handshake failures as SocketUpgradeError"""
    srv = yield from server.make_tls(cert=CERT, key=Redacted(KEY), host="127.0.0.1")
    yield from srv.run(lambda _: never).fork_scoped()
    sock = make_net(port_of(srv), "127.0.0.1")
    options = TlsUpgradeOptions(cert=CERT, key=Redacted(KEY), reject_unauthorized=True)
    error = yield from upgrade_error_of(sock, options)
    assert isinstance(error.reason, SocketUpgradeError)
    cause = error.reason.cause
    assert isinstance(cause, ssl.SSLCertVerificationError)
    assert cause.verify_code == 18
