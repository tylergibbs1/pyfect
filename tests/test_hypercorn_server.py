"""``pyfect.http.hypercorn_server``: HTTP/2, which Effect's ``NodeHttpServer``
serves when given ``node:http2``'s ``createServer``."""

import base64
import os
import socket
from typing import Any

import httpx

import pyfect as fx
from pyfect import effect
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


def _too_large(port: int, frames: int = 8) -> tuple[str, bytes]:
    """The handshake's reply, then what the server sends after an oversized
    message until it closes the connection (``b"open"`` if it stays open)."""
    conn, head = _upgrade(port)
    with conn:
        conn.sendall(_frame(2, b"x" * 4096, fin=False))
        conn.settimeout(5)
        got = b""
        try:
            for _ in range(frames):
                conn.sendall(_frame(0, b"x" * 4096, fin=False))
        except TimeoutError:
            return head, b"open"
        except OSError:
            # The server closed before reading the rest (a reset): what it sent
            # first is still to be read.
            pass
        try:
            while chunk := conn.recv(4096):
                got += chunk
        except TimeoutError:
            return head, b"open"
        except OSError:
            pass  # the reset, after the bytes before it
        return head, got


def _serve_too_large(frames: int) -> tuple[str, bytes]:
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
        return (yield from effect.blocking(lambda: _too_large(at, frames)))

    routes: fx.Layer[Any, Any, Any] = router.add("GET", "/ws", hold())
    served = program().pipe(fx.provide(router.serve(routes, disable_logger=True)))
    engine = hypercorn_server.layer_test(config={"websocket_max_message_size": 8192})
    return fx.run_blocking(scoped(served).pipe(fx.provide(engine)).or_die())


def test_web_sockets_refuse_compression_and_close_after_a_too_large_message() -> None:
    """Effect's ``ws`` server leaves permessage-deflate off and closes the
    socket on a too-large message: an inflated frame has no size bound."""
    head, after = _serve_too_large(8)
    assert "101" in head.splitlines()[0]
    assert "permessage-deflate" not in head
    assert after != b"open"
    assert b"\x88\x02\x03\xf1" in after  # the 1009 close


def test_the_1009_close_reaches_a_client_still_sending() -> None:
    """The server closes while the client is still sending its message (8 MiB
    here, more than the socket buffers hold), so the client's send fails with
    a reset; the 1009 close it already received is still there to read."""
    _, after = _serve_too_large(2048)
    assert b"\x88\x02\x03\xf1" in after
