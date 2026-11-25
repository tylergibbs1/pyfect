"""platform-node's ``NodeHttpServer.test.ts`` WebSocket titles against the
live server, whose ``Upgrade: websocket`` requests speak RFC 6455 as
Node's ``ws`` does. Each Effect test's docstring is its title; the titles
the uvicorn port already has run here again with the live server.

The rest pin ``ws``'s server behaviour, as its source (ws 8) defines it:
the ``Sec-WebSocket-Accept`` key, the first offered subprotocol, pings
answered, fragmented messages joined, a message over the size limit
closed with 1009, an unmasked client frame closed with 1002, and the
client's close code reaching the handler's pull.

"websocket options are forwarded to the WebSocketServer" is
``websocket_per_message_deflate``: the live server takes ``permessage-deflate``
offers as ``ws``'s server does with ``perMessageDeflate`` (its negotiation is
checked against Node's ``ws`` 8.22 in ``tests/test_ws_deflate.py``).
"""

from __future__ import annotations

import os
import socket
import struct
import threading
from collections.abc import Callable
from typing import Any

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect
from websockets.typing import Subprotocol

import pyfect as fx
from pyfect import effect
from pyfect.deferred import Deferred
from pyfect.exit import Exit, Failure, Success
from pyfect.http import live_server, router, server_response
from pyfect.http.live_server import PerMessageDeflate
from pyfect.http.live_server._exchange import Exchange
from pyfect.http.live_server._websocket import _Session  # pyright: ignore[reportPrivateUsage]
from pyfect.http.server_request import HttpServerRequest
from pyfect.scope import scoped
from pyfect.socket import SocketCloseError, SocketError, to_stream
from pyfect.socket._connection import Connection

from . import test_uvicorn_http_server as uv
from ._live_http import TIMEOUT, port, run_live


@pytest.fixture(autouse=True)
def _serve_live(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(uv, "run_uvicorn", run_live)


# --- titles shared with the uvicorn port ------------------------------------------

test_logs_and_traces_status_101_after_an_upgraded_websocket_closes = (
    uv.test_logs_and_traces_status_101_after_an_upgraded_websocket_closes
)
test_logs_the_fallback_status_when_an_upgrade_fails = (
    uv.test_logs_the_fallback_status_when_an_upgrade_fails
)
test_closes_a_websocket_with_the_handlers_code = uv.test_closes_a_websocket_with_the_handlers_code
test_an_upgrade_connection_reset_by_the_peer_does_not_crash_the_process = (
    uv.test_an_upgrade_connection_reset_by_the_peer_does_not_crash_the_process
)
test_does_not_write_the_http_response_to_an_upgraded_websocket = (
    uv.test_does_not_write_the_http_response_to_an_upgraded_connection
)


def _routed(handler: fx.Effect[Any, Any, Any], program: fx.Effect[Any, Any, Any], **options: Any):
    routes = router.add("GET", "/ws", scoped(handler))
    served = program.pipe(fx.provide(router.serve(routes, disable_logger=True)))
    return run_live(served.timeout(fx.duration.seconds(TIMEOUT)), **options)


def test_fails_refused_websocket_handshakes_without_hanging_shutdown() -> None:
    """fails refused websocket handshakes without hanging shutdown"""
    outcome: Deferred[object] = Deferred()

    @fx.fn
    def handler():
        request = yield from HttpServerRequest()
        sock = yield from request.upgrade
        error = yield from scoped(sock.reader).match(
            on_failure=lambda e: e, on_success=lambda _: None
        )
        yield from outcome.succeed(error)
        return server_response.empty()

    @fx.fn
    def program():
        at = yield from port

        def raw() -> bytes:
            with socket.create_connection(("127.0.0.1", at), timeout=TIMEOUT) as conn:
                conn.sendall(
                    b"GET /ws HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: Upgrade\r\n"
                    b"Upgrade: websocket\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                    b"Sec-WebSocket-Version: 12\r\n\r\n"
                )
                received = bytearray()
                while chunk := conn.recv(65536):
                    received += chunk
                return bytes(received)

        received = yield from effect.blocking(raw)
        return received, (yield from outcome.wait())

    received, error = _routed(handler(), program())
    assert received.startswith(b"HTTP/1.1 400 Bad Request\r\n")
    assert b"Sec-WebSocket-Version: 13, 8\r\n" in received
    assert isinstance(error, SocketError)


# --- ws's server behaviour ----------------------------------------------------------


@fx.fn
def _echo():
    """Echo every message until the client closes; the close is the result."""
    request = yield from HttpServerRequest()
    sock = yield from request.upgrade

    @fx.fn
    def run():
        reader = yield from sock.reader
        writer = yield from sock.writer
        while True:
            chunks = yield from reader.pull
            yield from writer.write_all(chunks)

    result = yield from scoped(run()).match(on_failure=lambda e: e, on_success=lambda _: None)
    return server_response.text(str(result))


def _client(
    at: int, *, subprotocols: list[Subprotocol] | None = None, max_size: int | None = 2**20
) -> ClientConnection:
    return connect(
        f"ws://127.0.0.1:{at}/ws",
        open_timeout=TIMEOUT,
        subprotocols=subprotocols,
        max_size=max_size,
    )


def _handshake(at: int, extra: str = "") -> tuple[socket.socket, bytes]:
    conn = socket.create_connection(("127.0.0.1", at), timeout=TIMEOUT)
    conn.sendall(
        (
            "GET /ws HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: Upgrade\r\nUpgrade: websocket\r\n"
            "Sec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            f"Sec-WebSocket-Version: 13\r\n{extra}\r\n"
        ).encode()
    )
    head = b""
    while b"\r\n\r\n" not in head:
        head += conn.recv(1)
    return conn, head


def _masked(opcode: int, payload: bytes, *, fin: bool = True) -> bytes:
    mask = os.urandom(4)
    masked = bytes(byte ^ mask[i % 4] for i, byte in enumerate(payload))
    first = (0x80 if fin else 0) | opcode
    assert len(payload) < 126
    return struct.pack("!BB", first, 0x80 | len(payload)) + mask + masked


def _parse_frames(data: bytearray) -> list[tuple[int, bytes]]:
    """The whole frames at the start of ``data``, taken from it."""
    frames: list[tuple[int, bytes]] = []
    while len(data) >= 2:
        first, second = data[0], data[1]
        assert not second & 0x80, "server frames are unmasked"
        size, offset = second & 0x7F, 2
        if size == 126:
            (size,) = struct.unpack_from("!H", data, 2)
            offset = 4
        if len(data) < offset + size:
            break
        frames.append((first & 0x0F, bytes(data[offset : offset + size])))
        del data[: offset + size]
    return frames


def _read_frames(conn: socket.socket, count: int) -> list[tuple[int, bytes]]:
    """The server's next ``count`` frames (sent one per frame here)."""
    data = bytearray()
    frames: list[tuple[int, bytes]] = []
    while len(frames) < count:
        data += conn.recv(1)
        frames += _parse_frames(data)
    return frames


def _frames(conn: socket.socket) -> list[tuple[int, bytes]]:
    """The server's frames until it closes the connection."""
    data = bytearray()
    while chunk := conn.recv(65536):
        data += chunk
    return _parse_frames(data)


def test_answers_the_handshake_with_the_sec_websocket_accept_key() -> None:
    @fx.fn
    def program():
        at = yield from port

        def talk() -> bytes:
            conn, head = _handshake(at)
            conn.close()
            return head

        return (yield from effect.blocking(talk))

    head = _routed(_echo(), program())
    assert head == (
        b"HTTP/1.1 101 Switching Protocols\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
        b"Sec-WebSocket-Accept: s3pPLMBiTxaQ9kYGzzhZRbK+xOo=\r\n\r\n"
    )


def test_echoes_text_and_binary_messages() -> None:
    @fx.fn
    def program():
        at = yield from port

        def talk() -> list[object]:
            with _client(at) as ws:
                ws.send("héllo")
                text = ws.recv(timeout=TIMEOUT)
                ws.send(b"\x00\xff")
                data = ws.recv(timeout=TIMEOUT)
                big = "x" * 300_000
                ws.send(big)
                return [text, data, ws.recv(timeout=TIMEOUT) == big]

        return (yield from effect.blocking(talk))

    assert _routed(_echo(), program()) == ["héllo", b"\x00\xff", True]


def test_chooses_the_first_offered_subprotocol() -> None:
    @fx.fn
    def program():
        at = yield from port

        def talk() -> str | None:
            with _client(at, subprotocols=[Subprotocol("b"), Subprotocol("a")]) as ws:
                return ws.subprotocol

        return (yield from effect.blocking(talk))

    assert _routed(_echo(), program()) == "b"


def test_answers_a_ping_with_a_pong_and_joins_fragments() -> None:
    @fx.fn
    def program():
        at = yield from port

        def talk() -> list[tuple[int, bytes]]:
            conn, _ = _handshake(at)
            with conn:
                conn.sendall(_masked(0x9, b"hi"))
                conn.sendall(_masked(0x1, b"fra", fin=False))
                conn.sendall(_masked(0x0, b"gment"))
                received = _read_frames(conn, 2)
                conn.sendall(_masked(0x8, struct.pack("!H", 4000) + b"bye"))
                return received + _frames(conn)

        return (yield from effect.blocking(talk))

    frames = _routed(_echo(), program())
    assert frames == [(0xA, b"hi"), (0x1, b"fragment"), (0x8, struct.pack("!H", 4000) + b"bye")]


def test_a_client_close_fails_the_pull_with_its_code() -> None:
    closed: Deferred[object] = Deferred()

    @fx.fn
    def handler():
        request = yield from HttpServerRequest()
        sock = yield from request.upgrade
        error = yield from to_stream(sock).run_drain().flip()
        yield from closed.succeed(error)
        return server_response.empty()

    @fx.fn
    def program():
        at = yield from port

        def talk() -> None:
            with _client(at) as ws:
                ws.close(4321, "done")

        yield from effect.blocking(talk)
        return (yield from closed.wait())

    error = _routed(handler(), program())
    assert isinstance(error, SocketError)
    assert (getattr(error.reason, "code", None), getattr(error.reason, "close_reason", None)) == (
        4321,
        "done",
    )


@fx.fn
def _write_only():
    """Take the reader, then only write, never pulling (stockroom finding 14)."""
    request = yield from HttpServerRequest()
    sock = yield from request.upgrade

    @fx.fn
    def run():
        yield from sock.reader
        writer = yield from sock.writer
        while True:
            yield from writer.write("tick")
            yield from fx.sleep("20 millis")

    yield from scoped(run()).match(on_failure=lambda e: e, on_success=lambda _: None)
    return server_response.empty()


def test_answers_a_ping_and_a_close_while_the_handler_only_writes() -> None:
    """As ``ws`` reads on while nothing pulls (up to Effect's 64 KiB high-water
    mark), a ping is answered and the client's close is answered and ends the
    connection, so the client is not left waiting for the server's close."""

    @fx.fn
    def program():
        at = yield from port

        def talk() -> list[int]:
            conn, _ = _handshake(at)
            with conn:
                conn.sendall(_masked(0x9, b"hi"))
                opcodes = [opcode for opcode, _ in _read_frames(conn, 1)]
                while 0xA not in opcodes:
                    opcodes += [opcode for opcode, _ in _read_frames(conn, 1)]
                conn.sendall(_masked(0x8, struct.pack("!H", 1000)))
                rest = [opcode for opcode, _ in _frames(conn)]
                return [0xA, *[opcode for opcode in rest if opcode != 0x1]]

        return (yield from effect.blocking(talk))

    assert _routed(_write_only(), program()) == [0xA, 0x8]


def test_messages_sent_while_nothing_pulls_all_arrive_in_order() -> None:
    """Past the 64 KiB high-water mark the server stops reading, and nothing
    is lost: a handler that starts pulling late gets every message."""
    received: Deferred[list[str]] = Deferred()
    messages = [f"{i:04d}" + "x" * 4096 for i in range(50)]

    @fx.fn
    def handler():
        request = yield from HttpServerRequest()
        sock = yield from request.upgrade

        @fx.fn
        def run():
            reader = yield from sock.reader
            yield from fx.sleep("300 millis")
            got: list[str] = []
            while len(got) < len(messages):
                got += [str(chunk) for chunk in (yield from reader.pull)]
            yield from received.succeed(got)

        yield from scoped(run())
        return server_response.empty()

    @fx.fn
    def program():
        at = yield from port

        def talk() -> None:
            with _client(at) as ws:
                for message in messages:
                    ws.send(message)

        yield from effect.blocking(talk).fork()
        return (yield from received.wait())

    assert _routed(handler(), program()) == messages


def _pulled_after_the_connection_is_lost(
    client_ends: Callable[[socket.socket], None],
) -> Exit[tuple[list[str], SocketError | None], object]:
    """The handler's exit when it pulls only once the connection is lost: the client
    sends "hi", then ends with ``client_ends``."""
    outcome: Deferred[Exit[tuple[list[str], SocketError | None], object]] = Deferred()

    @fx.fn
    def handler():
        request = yield from HttpServerRequest()
        exchange = request.source
        assert isinstance(exchange, Exchange)
        sock = yield from request.upgrade

        @fx.fn
        def run():
            reader = yield from sock.reader
            yield from exchange.conn.closed()
            # A step after the loss, where an interrupt it caused would land.
            yield from effect.yield_now()
            got = yield from reader.pull
            error = yield from reader.pull.match(on_failure=lambda e: e, on_success=lambda _: None)
            return [str(chunk) for chunk in got], error

        yield from scoped(run()).on_exit(outcome.succeed)
        return server_response.empty()

    @fx.fn
    def program():
        at = yield from port

        def talk() -> None:
            conn, _ = _handshake(at)
            with conn:
                conn.sendall(_masked(0x1, b"hi"))
                client_ends(conn)

        yield from effect.blocking(talk).fork()
        return (yield from outcome.wait())

    return _routed(handler(), program())


def _assert_pulled(exit: Exit[tuple[list[str], SocketError | None], object], code: int) -> None:
    assert isinstance(exit, Success), exit
    got, error = exit.value
    assert got == ["hi"]
    assert isinstance(error, SocketError)
    assert isinstance(error.reason, SocketCloseError)
    assert error.reason.code == code


def test_the_connection_closing_after_the_close_is_answered_does_not_interrupt_the_handler() -> (
    None
):
    """Effect interrupts an upgrade's handler when the connection closes only while the
    server's side is open (``writableEnded``). Once the client's close is answered and
    the server's side ended, the handler still pulls the message sent before the close,
    then the close."""

    def close(conn: socket.socket) -> None:
        conn.sendall(_masked(0x8, struct.pack("!H", 1000)))
        _frames(conn)

    _assert_pulled(_pulled_after_the_connection_is_lost(close), 1000)


def test_a_client_ending_without_a_close_does_not_interrupt_the_handler() -> None:
    """``ws`` ends the server's side when the client ends its own (``socketOnEnd``), so
    the handler still pulls what came first, then a 1006."""

    def end(conn: socket.socket) -> None:
        conn.shutdown(socket.SHUT_WR)
        _frames(conn)

    _assert_pulled(_pulled_after_the_connection_is_lost(end), 1006)


def test_a_connection_reset_interrupts_the_handler_as_a_client_abort() -> None:
    """A reset loses the connection with the server's side still open: a client abort."""

    def reset(conn: socket.socket) -> None:
        # SO_LINGER 0: close with a reset.
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER, struct.pack("ii", 1, 0))

    exit = _pulled_after_the_connection_is_lost(reset)
    assert isinstance(exit, Failure) and exit.cause.has_interrupts, exit


def test_closes_with_1009_a_message_over_the_max_message_size() -> None:
    @fx.fn
    def program():
        at = yield from port

        def talk() -> tuple[int, str] | None:
            with _client(at) as ws:
                ws.send("x" * 2048)
                try:
                    ws.recv(timeout=TIMEOUT)
                except ConnectionClosed as error:
                    return None if error.rcvd is None else (error.rcvd.code, error.rcvd.reason)
            return None

        return (yield from effect.blocking(talk))

    assert _routed(_echo(), program(), websocket_max_message_size=1024) == (1009, "")


def test_takes_messages_up_to_16_mib_by_default() -> None:
    @fx.fn
    def program():
        at = yield from port

        def talk() -> int:
            with _client(at, max_size=None) as ws:
                ws.send(b"x" * (2 * 1024 * 1024))
                return len(ws.recv(timeout=TIMEOUT))

        return (yield from effect.blocking(talk))

    assert _routed(_echo(), program()) == 2 * 1024 * 1024


def test_closes_with_1002_an_unmasked_client_frame() -> None:
    @fx.fn
    def program():
        at = yield from port

        def talk() -> list[tuple[int, bytes]]:
            conn, _ = _handshake(at)
            with conn:
                conn.sendall(b"\x81\x02hi")
                return _frames(conn)

        return (yield from effect.blocking(talk))

    # ws's receiverOnError closes with the code alone, no reason.
    assert _routed(_echo(), program()) == [(0x8, struct.pack("!H", 1002))]


def test_refuses_custom_response_headers_on_a_websocket_upgrade() -> None:
    @fx.fn
    def handler():
        request = yield from HttpServerRequest()
        result = yield from request.upgrade_with(headers={"x-extra": "1"}).exit()
        assert isinstance(result, Failure)
        return server_response.text(str(result.cause.squash()))

    @fx.fn
    def program():
        at = yield from port

        def talk() -> bytes:
            conn, head = _handshake(at)
            with conn:
                rest = bytearray()
                while chunk := conn.recv(65536):
                    rest += chunk
                return head + bytes(rest)

        return (yield from effect.blocking(talk))

    received = _routed(handler(), program())
    assert received.startswith(b"HTTP/1.1 200 ")
    assert b"WebSocket upgrades do not support custom response headers" in received


# --- permessage-deflate -----------------------------------------------------------


def test_websocket_options_are_forwarded_to_the_websocket_server() -> None:
    """websocket options are forwarded to the WebSocketServer"""

    @fx.fn
    def program():
        at = yield from port

        def connect_both() -> tuple[list[str], list[str]]:
            with connect(f"ws://127.0.0.1:{at}/ws", open_timeout=TIMEOUT) as compressed:
                offered = [str(e.name) for e in compressed.protocol.extensions]
            with connect(
                f"ws://127.0.0.1:{at}/ws", open_timeout=TIMEOUT, compression=None
            ) as plain:
                return offered, [str(e.name) for e in plain.protocol.extensions]

        return (yield from effect.blocking(connect_both))

    compressed, plain = _routed(_echo(), program(), websocket_per_message_deflate=True)
    assert "permessage-deflate" in compressed
    assert "permessage-deflate" not in plain


def test_ignores_permessage_deflate_offers_unless_enabled() -> None:
    """``ws``'s server takes no extension unless ``perMessageDeflate`` is set."""

    @fx.fn
    def program():
        at = yield from port

        def run() -> list[str]:
            with _client(at) as client:
                client.send("x" * 4096)
                assert client.recv(timeout=TIMEOUT) == "x" * 4096
                return [str(e.name) for e in client.protocol.extensions]

        return (yield from effect.blocking(run))

    assert _routed(_echo(), program()) == []


def test_echoes_compressed_messages_with_context_takeover() -> None:
    """Messages round-trip compressed in both directions, many over one context, and
    a message under the threshold goes uncompressed."""
    messages: list[str | bytes] = ["a" * 5000, b"\x00\x01" * 3000, "short", "b" * 70000, "a" * 5000]

    @fx.fn
    def program():
        at = yield from port

        def run() -> list[str | bytes]:
            with _client(at, max_size=None) as client:
                received: list[str | bytes] = []
                for message in messages:
                    client.send(message)
                    received.append(client.recv(timeout=TIMEOUT))
                return received

        return (yield from effect.blocking(run))

    assert _routed(_echo(), program(), websocket_per_message_deflate=True) == messages


@pytest.mark.parametrize(
    ("options", "header"),
    [
        (
            PerMessageDeflate(server_no_context_takeover=True, client_no_context_takeover=True),
            "permessage-deflate; server_no_context_takeover; client_no_context_takeover",
        ),
        (
            PerMessageDeflate(server_max_window_bits=9, client_max_window_bits=10),
            "permessage-deflate; client_max_window_bits=10; server_max_window_bits=9",
        ),
    ],
)
def test_applies_the_negotiated_parameters(options: PerMessageDeflate, header: str) -> None:
    """The ``101`` carries the accepted parameters, and messages compressed under them
    round-trip."""

    @fx.fn
    def program():
        at = yield from port

        def run() -> tuple[str, list[str]]:
            with _client(at, max_size=None) as client:
                response = client.response
                assert response is not None
                accepted = response.headers["Sec-WebSocket-Extensions"]
                received: list[str] = []
                for size in (3000, 3000, 40000):
                    client.send("c" * size)
                    reply = client.recv(timeout=TIMEOUT)
                    assert isinstance(reply, str)
                    received.append(reply)
                return accepted, received

        return (yield from effect.blocking(run))

    accepted, received = _routed(_echo(), program(), websocket_per_message_deflate=options)
    assert accepted == header
    assert received == ["c" * 3000, "c" * 3000, "c" * 40000]


def test_refuses_an_unacceptable_extension_offer() -> None:
    """``ws`` answers a malformed or unacceptable ``Sec-WebSocket-Extensions`` with 400."""

    @fx.fn
    def program():
        at = yield from port

        def run() -> bytes:
            conn, head = _handshake(at, "Sec-WebSocket-Extensions: permessage-deflate; foo\r\n")
            with conn:
                return head

        return (yield from effect.blocking(run))

    head = _routed(_echo(), program(), websocket_per_message_deflate=True)
    assert head.startswith(b"HTTP/1.1 400 Bad Request\r\n")


def test_closes_with_1009_when_a_compressed_message_inflates_past_the_limit() -> None:
    """The size limit counts the inflated bytes (``ws``'s ``maxPayload``)."""
    import zlib

    @fx.fn
    def program():
        at = yield from port

        def run() -> list[tuple[int, bytes]]:
            conn, head = _handshake(at, "Sec-WebSocket-Extensions: permessage-deflate\r\n")
            with conn:
                assert b"Sec-WebSocket-Extensions: permessage-deflate\r\n" in head
                deflate = zlib.compressobj(9, zlib.DEFLATED, -15)
                payload = (deflate.compress(b"z" * 100_000) + deflate.flush(zlib.Z_SYNC_FLUSH))[:-4]
                conn.sendall(_masked_compressed(payload))
                return _frames(conn)

        return (yield from effect.blocking(run))

    frames = _routed(
        _echo(), program(), websocket_per_message_deflate=True, websocket_max_message_size=1024
    )
    assert frames[-1] == (0x8, struct.pack("!H", 1009))


def _masked_compressed(payload: bytes) -> bytes:
    frame = bytearray(_masked(0x2, payload))
    frame[0] |= 0x40  # RSV1: compressed
    return bytes(frame)


def test_closes_with_1002_for_a_compressed_frame_without_the_extension() -> None:
    """Without ``permessage-deflate`` a frame with RSV1 set breaks the protocol."""

    @fx.fn
    def program():
        at = yield from port

        def run() -> list[tuple[int, bytes]]:
            conn, _head = _handshake(at)
            with conn:
                conn.sendall(_masked_compressed(b"abc"))
                return _frames(conn)

        return (yield from effect.blocking(run))

    assert _routed(_echo(), program())[-1] == (0x8, struct.pack("!H", 1002))


def test_compresses_messages_from_the_threshold() -> None:
    """``ws`` sets RSV1 on messages of at least ``threshold`` bytes (1024) and sends
    shorter ones as they are."""
    import zlib

    @fx.fn
    def program():
        at = yield from port

        def run() -> list[tuple[int, bytes]]:
            conn, _head = _handshake(at, "Sec-WebSocket-Extensions: permessage-deflate\r\n")
            with conn:
                conn.sendall(_masked(0x1, b"hi"))
                deflate = zlib.compressobj(9, zlib.DEFLATED, -15)
                payload = deflate.compress(b"a" * 2000) + deflate.flush(zlib.Z_SYNC_FLUSH)
                conn.sendall(_masked_compressed(payload[:-4]))
                data = bytearray()
                frames: list[tuple[int, bytes]] = []
                while len(frames) < 2:
                    data += conn.recv(65536)
                    # Both replies are short enough for a one-byte length.
                    while len(data) >= 2 and len(data) >= 2 + data[1]:
                        frames.append((data[0], bytes(data[2 : 2 + data[1]])))
                        del data[: 2 + data[1]]
                return frames

        return (yield from effect.blocking(run))

    [small, big] = _routed(_echo(), program(), websocket_per_message_deflate=True)
    assert small == (0x81, b"hi")
    assert big[0] == 0xC2  # FIN, RSV1, binary
    assert zlib.decompressobj(-15).decompress(big[1] + b"\x00\x00\xff\xff") == b"a" * 2000


# --- shutdown -----------------------------------------------------------------------


@pytest.mark.parametrize("unresponsive", [False, True])
def test_shuts_down_websockets(unresponsive: bool) -> None:
    """shuts down WebSockets (unresponsive: %s)

    Shutdown sends 1001 at once. A client that answers the close ends the handler's pull, so
    the handler finishes uninterrupted; one that never reads is destroyed after the
    graceful shutdown timeout."""
    drained: list[fx.Exit[None, SocketError]] = []

    @fx.fn
    def handler():
        request = yield from HttpServerRequest()
        sock = yield from request.upgrade
        drained.append((yield from to_stream(sock).run_drain().exit()))
        return server_response.empty()

    clients: list[ClientConnection | socket.socket] = []

    @fx.fn
    def program():
        at = yield from port
        client = yield from effect.blocking(
            lambda: _handshake(at)[0] if unresponsive else _client(at)
        )
        clients.append(client)

    timeout = "250 millis" if unresponsive else "10 seconds"
    _routed(handler(), program(), graceful_shutdown_timeout=timeout)
    [client] = clients
    if isinstance(client, socket.socket):
        with client:
            assert _frames(client)[0] == (8, struct.pack("!H", 1001))
        return
    with client:
        # The client's own thread handles the close frame, so wait for it rather than read
        # ``close_code`` while the closing handshake may still be under way.
        with pytest.raises(ConnectionClosed) as closed:
            client.recv(timeout=TIMEOUT)
        assert closed.value.rcvd is not None
        assert closed.value.rcvd.code == 1001
    [exit] = drained
    assert isinstance(exit, Failure)
    assert not exit.cause.has_interrupts


def test_shutdown_ends_other_upgraded_connections_at_once() -> None:
    """Not an Effect title: the other half of "shuts down WebSockets". Shutdown ends the
    server's side of a raw upgrade at once, so a client that closes in turn ends the
    handler's read before the graceful shutdown timeout interrupts it."""
    drained: list[fx.Exit[None, SocketError]] = []

    @fx.fn
    def handler():
        request = yield from HttpServerRequest()
        sock = yield from request.upgrade
        drained.append((yield from to_stream(sock).run_drain().exit()))
        return server_response.empty()

    switched = threading.Event()
    received: list[bytes] = []

    def client(at: int) -> None:
        with socket.create_connection(("127.0.0.1", at), timeout=TIMEOUT) as conn:
            conn.sendall(
                b"GET /ws HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: Upgrade\r\n"
                b"Upgrade: tcp\r\n\r\n"
            )
            data = b""
            while chunk := conn.recv(65536):
                data += chunk
                switched.set()
            received.append(data)

    @fx.fn
    def program():
        at = yield from port
        yield from effect.blocking(lambda: client(at)).fork_daemon()
        yield from effect.blocking(lambda: switched.wait(TIMEOUT))

    _routed(handler(), program(), graceful_shutdown_timeout="10 seconds")
    assert received[0].startswith(b"HTTP/1.1 101 ")
    [exit] = drained
    assert not (isinstance(exit, Failure) and exit.cause.has_interrupts)


def _raw_client(at: int, switched: threading.Event, ended: threading.Event) -> None:
    with socket.create_connection(("127.0.0.1", at), timeout=TIMEOUT) as conn:
        conn.sendall(
            b"GET /ws HTTP/1.1\r\nHost: 127.0.0.1\r\nConnection: Upgrade\r\nUpgrade: tcp\r\n\r\n"
        )
        head = b""
        while chunk := conn.recv(65536):
            head += chunk
            switched.set()
        ended.set()
        assert head.startswith(b"HTTP/1.1 101 ")


def _ws_client(at: int, switched: threading.Event, ended: threading.Event) -> None:
    conn, _head = _handshake(at)
    with conn:
        switched.set()
        going_away = b"\x88\x02" + struct.pack("!H", 1001)
        received = b""
        while going_away not in received and (chunk := conn.recv(65536)):
            received += chunk
        ended.set()
        assert going_away in received


@pytest.mark.parametrize("client", [_raw_client, _ws_client], ids=["raw", "websocket"])
def test_shutdown_ends_an_upgrade_whose_switch_is_still_being_written(
    monkeypatch: pytest.MonkeyPatch, client: Any
) -> None:
    """Not an Effect title. The client can see the 101 and shutdown can begin before the
    server's write of it has returned, so shutdown must already know how to end the
    connection: here the write of the 101 returns only once the client has seen the end."""
    switched, ended = threading.Event(), threading.Event()
    original = Connection.write_with

    def write_with(self: Connection, make: Any) -> fx.Effect[None, SocketError]:
        switches: list[bytes] = []

        def made() -> tuple[bytes, ...]:
            chunks = make()
            switches.extend(chunk for chunk in chunks if chunk.startswith(b"HTTP/1.1 101 "))
            return chunks

        def returned(_: None) -> fx.Effect[None]:
            return (
                effect.blocking(lambda: ended.wait(TIMEOUT)).as_void() if switches else effect.void
            )

        return original(self, made).flat_map(returned)

    monkeypatch.setattr(Connection, "write_with", write_with)
    drained: list[fx.Exit[None, SocketError]] = []

    @fx.fn
    def handler():
        request = yield from HttpServerRequest()
        sock = yield from request.upgrade
        drained.append((yield from to_stream(sock).run_drain().exit()))
        return server_response.empty()

    @fx.fn
    def program():
        at = yield from port
        finished = yield from effect.blocking(lambda: client(at, switched, ended)).fork_daemon()
        yield from effect.blocking(lambda: switched.wait(TIMEOUT))
        return finished

    finished = _routed(handler(), program(), graceful_shutdown_timeout="10 seconds")
    fx.run_blocking(finished.join())
    [exit] = drained
    assert not (isinstance(exit, Failure) and exit.cause.has_interrupts)


def test_a_websocket_high_water_mark_pauses_the_peer_instead_of_closing_it(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """a websocket highWaterMark pauses the peer instead of closing it"""
    frames = [str(i % 10) for i in range(100)]
    # 100 bytes stay below the 64 KiB default, so only the configured mark pauses.
    paused = threading.Event()
    checked = threading.Event()
    # The handler's end closes the socket: it waits until the client has read its state.
    looked = threading.Event()
    room = _Session._room  # pyright: ignore[reportPrivateUsage]

    def spied(session: _Session) -> bool:
        has_room = room(session)
        if not has_room:
            paused.set()
        return has_room

    monkeypatch.setattr(_Session, "_room", spied)

    @fx.fn
    def handler():
        request = yield from HttpServerRequest()
        sock = yield from request.upgrade

        @fx.fn
        def run():
            reader = yield from sock.reader
            yield from effect.blocking(lambda: paused.wait(TIMEOUT))
            got: list[str] = []
            while len(got) < len(frames):
                got += [str(chunk) for chunk in (yield from reader.pull)]
            checked.set()
            yield from effect.blocking(lambda: looked.wait(TIMEOUT))
            return got

        got = yield from scoped(run())
        return server_response.text(",".join(got))

    @fx.fn
    def program():
        at = yield from port

        def talk() -> tuple[bool, bool]:
            with _client(at) as ws:
                for frame in frames:
                    ws.send(frame)
                caught_up = checked.wait(TIMEOUT)
                state = ws.protocol.state.name
                looked.set()
                return caught_up, state == "OPEN"

        return (yield from effect.blocking(talk))

    assert _routed(handler(), program(), websocket_high_water_mark=1) == (True, True)
    assert paused.is_set()


def test_an_empty_message_counts_as_a_byte_toward_the_high_water_mark(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """As in Effect's ``Socket.fromWebSocket``: empty messages alone fill the buffer."""
    paused = threading.Event()
    room = _Session._room  # pyright: ignore[reportPrivateUsage]

    def spied(session: _Session) -> bool:
        has_room = room(session)
        if not has_room:
            paused.set()
        return has_room

    monkeypatch.setattr(_Session, "_room", spied)

    @fx.fn
    def handler():
        request = yield from HttpServerRequest()
        sock = yield from request.upgrade

        @fx.fn
        def run():
            reader = yield from sock.reader
            yield from effect.blocking(lambda: paused.wait(TIMEOUT))
            got = 0
            while got < 3:
                got += len((yield from reader.pull))
            return got

        return server_response.text(str((yield from scoped(run()))))

    @fx.fn
    def program():
        at = yield from port

        def talk() -> bool:
            with _client(at) as ws:
                for _ in range(3):
                    ws.send(b"")
                return paused.wait(TIMEOUT)

        return (yield from effect.blocking(talk))

    assert _routed(handler(), program(), websocket_high_water_mark=2) is True


def test_a_high_water_mark_below_one_is_refused() -> None:
    with pytest.raises(ValueError, match="websocket_high_water_mark must be at least 1, got 0"):
        live_server.make(websocket_high_water_mark=0)
