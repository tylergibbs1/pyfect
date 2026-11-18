"""``pyfect.http.hypercorn_server``: HTTP/2, which Effect's ``NodeHttpServer``
serves when given ``node:http2``'s ``createServer``."""

import base64
import contextlib
import os
import socket
import struct
import threading
from dataclasses import dataclass
from typing import Any, Literal

import httpx
from _threaded_server import serving
from _timing import wait_until

import pyfect as fx
from pyfect import effect
from pyfect.duration import Input as DurationInput
from pyfect.http import hypercorn_server, router, server, server_response
from pyfect.http.server_request import HttpServerRequest
from pyfect.net.net_address import InetAddressV4
from pyfect.scope import scoped
from pyfect.socket import reader_bytes


def _speak_http2(port: int) -> tuple[str, str]:
    with httpx.Client(http1=False, http2=True) as client:
        response = client.get(f"http://127.0.0.1:{port}/hello")
        return response.http_version, response.text


def test_serves_http_2_in_cleartext() -> None:
    @fx.fn
    def program():
        running = yield from server.HttpServer()
        assert isinstance(running.address, InetAddressV4)
        at = running.address.port
        return (yield from effect.blocking(lambda: _speak_http2(at)))

    routes: fx.Layer[Any, Any, Any] = router.add("GET", "/hello", server_response.text("hi"))
    served = program().pipe(fx.provide(router.serve(routes, disable_logger=True)))
    provided = scoped(served).pipe(fx.provide(hypercorn_server.layer_test()))
    assert fx.run_blocking(provided.or_die()) == ("HTTP/2", "hi")


def test_the_server_stops_when_its_scope_closes() -> None:
    @fx.fn
    def program():
        running = yield from server.HttpServer()
        assert isinstance(running.address, InetAddressV4)
        return running.address.port

    at = fx.run_blocking(scoped(program()).pipe(fx.provide(hypercorn_server.layer_test())).or_die())
    with httpx.Client() as client:
        try:
            client.get(f"http://127.0.0.1:{at}/", timeout=1)
        except httpx.TransportError:
            return
    raise AssertionError("the server still accepts connections")


def _upgrade(port: int) -> tuple[socket.socket, str]:
    conn = socket.create_connection(("127.0.0.1", port), timeout=10)
    key = base64.b64encode(os.urandom(16)).decode()
    conn.sendall(
        f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
        "Connection: Upgrade\r\nSec-WebSocket-Version: 13\r\n"
        f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Extensions: permessage-deflate\r\n\r\n".encode()
    )
    reply = b""
    while b"\r\n\r\n" not in reply:
        reply += conn.recv(4096)
    return conn, reply.split(b"\r\n\r\n")[0].decode().lower()


def _frame(opcode: int, payload: bytes, *, fin: bool) -> bytes:
    size = len(payload)
    head = bytes([(0x80 if fin else 0) | opcode])
    if size < 126:
        head += bytes([0x80 | size])
    elif size < 65536:
        head += bytes([0x80 | 126]) + size.to_bytes(2, "big")
    else:
        head += bytes([0x80 | 127]) + size.to_bytes(8, "big")
    return head + b"\0\0\0\0" + payload  # a zero mask leaves the payload as it is


@dataclass(frozen=True)
class _Sent:
    """What a client sending an oversized message saw."""

    head: str
    """The handshake's reply."""
    sent_all: bool
    """Every frame went out: the server never reset the connection mid-send."""
    ended: Literal["eof", "reset", "open"]
    """How reading ended: the server's FIN, a reset, or still open after 5 s."""
    got: bytes
    """What the server sent after the handshake."""


def _too_large(port: int, frames: int, keep_sending: bool) -> _Sent:
    conn, head = _upgrade(port)
    with conn:
        conn.settimeout(5)
        sent_all = True
        try:
            conn.sendall(_frame(2, b"x" * 4096, fin=False))
            for _ in range(frames):
                conn.sendall(_frame(0, b"x" * 4096, fin=False))
        except TimeoutError:
            return _Sent(head, False, "open", b"")
        except OSError:
            sent_all = False  # reset; what the server sent first is still to be read
        got = b""
        try:
            while chunk := conn.recv(4096):
                got += chunk
        except TimeoutError:
            return _Sent(head, sent_all, "open", got)
        except OSError:
            return _Sent(head, sent_all, "reset", got)
        if keep_sending:
            # Never end our side: send until the server drops the connection.
            def dropped() -> bool:
                try:
                    conn.sendall(_frame(0, b"x" * 4096, fin=False))
                except OSError:
                    return True
                return False

            wait_until(dropped, what="the server to drop a client that keeps sending")
            return _Sent(head, sent_all, "reset", got)
        return _Sent(head, sent_all, "eof", got)


def _serve_too_large(
    frames: int, *, keep_sending: bool = False, close_timeout: DurationInput = "30 seconds"
) -> _Sent:
    @fx.fn
    def hold():
        request = yield from HttpServerRequest()
        ws = yield from request.upgrade
        pull = yield from reader_bytes(ws)
        while True:
            yield from pull

    @fx.fn
    def program():
        running = yield from server.HttpServer()
        assert isinstance(running.address, InetAddressV4)
        at = running.address.port
        return (yield from effect.blocking(lambda: _too_large(at, frames, keep_sending)))

    routes: fx.Layer[Any, Any, Any] = router.add("GET", "/ws", hold())
    served = program().pipe(fx.provide(router.serve(routes, disable_logger=True)))
    engine = hypercorn_server.layer_test(
        websocket_close_timeout=close_timeout, config={"websocket_max_message_size": 8192}
    )
    return fx.run_blocking(scoped(served).pipe(fx.provide(engine)).or_die())


def test_web_sockets_refuse_compression_and_close_after_a_too_large_message() -> None:
    """Effect's ``ws`` server leaves permessage-deflate off and closes the
    socket on a too-large message: an inflated frame has no size bound."""
    sent = _serve_too_large(8)
    assert "101" in sent.head.splitlines()[0]
    assert "permessage-deflate" not in sent.head
    assert sent.ended != "open"
    assert b"\x88\x02\x03\xf1" in sent.got  # the 1009 close


def test_a_client_still_sending_gets_the_1009_close_without_a_reset() -> None:
    """As ``ws``: after the 1009 close the server ends its side and reads and
    drops the rest of the message (8 MiB here, more than the socket buffers
    hold), so the client sends it all, then reads the close and the end."""
    sent = _serve_too_large(2048)
    assert sent.sent_all
    assert sent.ended == "eof"
    assert sent.got == b"\x88\x02\x03\xf1"


def _close_then_reset(conn: socket.socket, _stopping: threading.Event) -> None:
    """Answers the handshake, reads the start of a message, sends the 1009 close and leaves
    ``serving`` to close the connection with ``SO_LINGER`` 0: a reset, dropping the bytes
    the client is still sending."""
    conn.settimeout(5)
    request = b""
    while b"\r\n\r\n" not in request:
        request += conn.recv(4096)
    conn.sendall(b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\n\r\n")
    conn.recv(4096)
    conn.sendall(b"\x88\x02\x03\xf1")
    conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))


def test_a_reset_mid_message_keeps_the_close_received_before_it() -> None:
    """``_too_large`` reads what the server sent before a reset: a server that resets the
    connection while the client is still sending (16 MiB, more than the socket buffers
    hold) fails the client's send, and the 1009 close it already received is still read
    (Linux and macOS keep received bytes through a reset). Reading stopped at the failed
    send before, and the close was lost."""
    with serving(_close_then_reset) as fake:
        sent = _too_large(fake.port, 4096, keep_sending=False)
    assert not sent.sent_all
    assert sent.got == b"\x88\x02\x03\xf1"
    assert sent.ended in ("eof", "reset")


def test_a_client_that_never_ends_its_side_is_dropped_after_the_close_timeout() -> None:
    """As ``ws``'s ``closeTimeout``: once the server has closed, a client that
    keeps sending is dropped once ``websocket_close_timeout`` has passed."""
    sent = _serve_too_large(8, keep_sending=True, close_timeout="200 millis")
    assert sent.got == b"\x88\x02\x03\xf1"
    assert sent.ended == "reset"


def test_a_graceful_shutdown_drops_a_connection_still_draining() -> None:
    """As Effect's ``NodeHttpServer``: ``server.close`` waits for an upgraded
    socket ``ws`` is still draining for at most ``gracefulShutdownTimeout``,
    then destroys it, without waiting out ``ws``'s ``closeTimeout``. Here the
    close timeout is an hour: waiting it out would trip the per-test alarm."""
    held: list[socket.socket] = []

    def oversized(port: int) -> None:
        conn, _ = _upgrade(port)
        held.append(conn)
        conn.settimeout(5)
        conn.sendall(_frame(2, b"x" * 4096, fin=False))
        for _ in range(8):
            conn.sendall(_frame(0, b"x" * 4096, fin=False))
        got = b""
        while chunk := conn.recv(4096):  # the 1009 close, then the server's end
            got += chunk
        assert got == b"\x88\x02\x03\xf1"  # the connection is draining; shutdown starts

    @fx.fn
    def hold():
        request = yield from HttpServerRequest()
        ws = yield from request.upgrade
        pull = yield from reader_bytes(ws)
        while True:
            yield from pull

    @fx.fn
    def program():
        running = yield from server.HttpServer()
        assert isinstance(running.address, InetAddressV4)
        at = running.address.port
        return (yield from effect.blocking(lambda: oversized(at)))

    routes: fx.Layer[Any, Any, Any] = router.add("GET", "/ws", hold())
    served = program().pipe(fx.provide(router.serve(routes, disable_logger=True)))
    engine = hypercorn_server.layer_test(
        graceful_shutdown_timeout="500 millis",
        websocket_close_timeout="1 hour",
        config={"websocket_max_message_size": 8192},
    )
    try:
        # Returns after the 0.5 s graceful timeout and pyfect's 0.5 s abort grace period.
        fx.run_blocking(scoped(served).pipe(fx.provide(engine)).or_die())
        with contextlib.suppress(OSError):  # dropped with a reset
            assert held[0].recv(1) == b""
    finally:
        for conn in held:
            conn.close()
