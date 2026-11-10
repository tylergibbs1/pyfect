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
from typing import Any

import pytest
from websockets.exceptions import ConnectionClosed
from websockets.sync.client import ClientConnection, connect
from websockets.typing import Subprotocol

import pyfect as fx
from pyfect import effect
from pyfect.deferred import Deferred
from pyfect.duration import Seconds
from pyfect.exit import Failure
from pyfect.http import router, server_response
from pyfect.http.live_server import PerMessageDeflate
from pyfect.http.server_request import HttpServerRequest
from pyfect.scope import scoped
from pyfect.socket import SocketError, to_stream

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
    return run_live(served.timeout(Seconds(TIMEOUT)), **options)


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
