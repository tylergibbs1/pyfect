"""Behaviors of Node's ``http.Server`` that the live server (Effect's
``NodeHttpServer`` runs on Node's) keeps, checked under Node 24: an idle
keep-alive connection is closed after ``keep_alive_timeout`` (advertised
as ``keep-alive: timeout=<seconds>``); a head that does not arrive within
``headers_timeout`` is answered with 408 if it started, else the
connection is closed; responses are ``HTTP/1.1`` whatever the request's
version; each build of a server layer listens anew; a client that
half-closes gets no response; and a head with a bare-LF line ending is a
400 at once (a bare LF before the request line is skipped)."""

from __future__ import annotations

import socket
import threading
import time
from typing import Any

import pytest

import pyfect as fx
from pyfect import effect
from pyfect.duration import Duration
from pyfect.http import live_server, server, server_response
from pyfect.http.server import HttpServer
from pyfect.http.server_request import HttpServerRequest
from pyfect.scope import Scope, scoped

from ._live_http import TIMEOUT, exchange, parse_responses, port, run_live, until_close, with_socket


def _serve_ok() -> fx.Effect[int, Any, HttpServer | Scope]:
    return server.serve_effect(fx.succeed(server_response.text("ok"))).flat_map(lambda _: port)


def _until_close(conn: socket.socket, started: float) -> tuple[bytes, float]:
    received = bytearray()
    while chunk := conn.recv(65536):
        received += chunk
    return bytes(received), time.monotonic() - started


def test_closes_an_idle_keep_alive_connection_after_the_keep_alive_timeout() -> None:
    def use(conn: socket.socket) -> tuple[bytes, float]:
        conn.sendall(b"GET / HTTP/1.1\r\nhost: x\r\n\r\n")
        return _until_close(conn, time.monotonic())

    @fx.fn
    def program():
        at = yield from _serve_ok()
        return (yield from with_socket(at, use))

    received, elapsed = run_live(program(), keep_alive_timeout="300 millis")
    [response] = parse_responses(received)
    assert response.status == 200
    assert response.header("connection") == "keep-alive"
    assert response.header("keep-alive") == "timeout=0"
    assert 0.25 < elapsed < TIMEOUT / 2


def test_advertises_the_keep_alive_timeout_in_whole_seconds() -> None:
    def use(conn: socket.socket) -> bytes:
        conn.sendall(b"GET / HTTP/1.1\r\nhost: x\r\nconnection: close\r\n\r\n")
        return _until_close(conn, time.monotonic())[0]

    @fx.fn
    def program():
        at = yield from _serve_ok()
        keep_alive = yield from with_socket(at, _first_response)
        closed = yield from with_socket(at, use)
        return keep_alive, closed

    keep_alive, closed = run_live(program(), keep_alive_timeout="7900 millis")
    assert keep_alive.header("keep-alive") == "timeout=7"
    [response] = parse_responses(closed)
    assert response.header("keep-alive") is None


def _first_response(conn: socket.socket):
    conn.sendall(b"GET / HTTP/1.1\r\nhost: x\r\n\r\n")
    received = bytearray()
    while not received.endswith(b"\r\n\r\nok"):
        received += conn.recv(65536)
    [response] = parse_responses(bytes(received))
    return response


def test_answers_a_head_that_does_not_arrive_within_the_headers_timeout_with_408() -> None:
    def use(conn: socket.socket) -> tuple[bytes, float]:
        conn.sendall(b"GET / HTTP/1.1\r\nho")
        return _until_close(conn, time.monotonic())

    @fx.fn
    def program():
        at = yield from _serve_ok()
        return (yield from with_socket(at, use))

    received, elapsed = run_live(program(), headers_timeout="300 millis")
    [response] = parse_responses(received)
    assert response.status == 408
    assert response.header("connection") == "close"
    assert 0.25 < elapsed < TIMEOUT / 2


def test_closes_a_connection_that_sends_nothing_within_the_headers_timeout() -> None:
    def use(conn: socket.socket) -> tuple[bytes, float]:
        return _until_close(conn, time.monotonic())

    @fx.fn
    def program():
        at = yield from _serve_ok()
        return (yield from with_socket(at, use))

    received, elapsed = run_live(program(), headers_timeout="300 millis")
    assert received == b""
    assert 0.25 < elapsed < TIMEOUT / 2


def test_a_slow_head_after_a_keep_alive_request_gets_the_headers_timeout() -> None:
    """Once the next head starts, the headers timeout applies, not the
    keep-alive one."""

    def use(conn: socket.socket) -> bytes:
        _first_response(conn)
        conn.sendall(b"GET / HTTP/1.1\r\n")
        time.sleep(0.4)
        conn.sendall(b"host: x\r\nconnection: close\r\n\r\n")
        return _until_close(conn, time.monotonic())[0]

    @fx.fn
    def program():
        at = yield from _serve_ok()
        return (yield from with_socket(at, use))

    received = run_live(program(), keep_alive_timeout="200 millis", headers_timeout="3 seconds")
    [response] = parse_responses(received)
    assert response.status == 200
    assert response.body == b"ok"


def test_a_server_layer_built_twice_serves_each_build() -> None:
    """A layer (or ``make`` effect) is a description: each build listens
    on a listener of its own."""
    served = live_server.layer(host="127.0.0.1")

    def use(conn: socket.socket) -> bytes:
        conn.sendall(b"GET / HTTP/1.1\r\nhost: x\r\nconnection: close\r\n\r\n")
        return _until_close(conn, time.monotonic())[0]

    @fx.fn
    def program():
        at = yield from _serve_ok()
        return (yield from with_socket(at, use))

    for _ in range(2):
        received = fx.run_blocking(scoped(program()).pipe(fx.provide(served)).or_die())
        [response] = parse_responses(received)
        assert response.body == b"ok"


def test_answers_an_http_1_0_request_with_an_http_1_1_status_line() -> None:
    def use(conn: socket.socket) -> bytes:
        conn.sendall(b"GET / HTTP/1.0\r\n\r\n")
        return _until_close(conn, time.monotonic())[0]

    @fx.fn
    def program():
        at = yield from _serve_ok()
        return (yield from with_socket(at, use))

    received = run_live(program())
    assert received.startswith(b"HTTP/1.1 200 OK\r\n")
    [response] = parse_responses(received)
    assert response.header("connection") == "close"
    assert response.body == b"ok"


def test_closes_a_connection_whose_client_stops_reading_when_the_shutdown_timeout_ends() -> None:
    """``graceful_shutdown_timeout`` bounds the shutdown even while a bytes
    body waits for a client that stopped reading (uvicorn exits on time)."""
    started = threading.Event()

    def stall(at: int) -> None:
        conn = socket.socket()
        conn.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 4096)
        conn.connect(("127.0.0.1", at))
        conn.sendall(b"GET / HTTP/1.1\r\nhost: x\r\n\r\n")
        conn.recv(1)
        started.set()
        time.sleep(TIMEOUT)
        conn.close()

    @fx.fn
    def serving():
        at = yield from server.serve_effect(
            fx.succeed(server_response.bytes_(b"z" * 20_000_000))
        ).flat_map(lambda _: port)
        yield from effect.blocking(lambda: stall(at)).fork_daemon()
        yield from effect.blocking(lambda: started.wait(TIMEOUT))

    layer_live = live_server.layer(host="127.0.0.1", graceful_shutdown_timeout="300 millis")
    program = scoped(serving()).pipe(fx.provide(layer_live))
    started_at = time.monotonic()
    fx.run_blocking(program.timeout(Duration(TIMEOUT)).or_die())
    assert time.monotonic() - started_at < 2.5


def test_aborts_a_streamed_body_still_open_when_the_shutdown_timeout_ends() -> None:
    """``NodeHttpServer``'s preemptive shutdown interrupts a request whose
    body never ends (an SSE stream) and destroys the response: the client
    has the chunks sent so far, no last chunk, and the connection closes
    (dogfood beacon #12)."""
    received: list[bytes] = []
    started = threading.Event()

    def read(at: int) -> None:
        with socket.create_connection(("127.0.0.1", at), timeout=TIMEOUT) as conn:
            conn.sendall(b"GET / HTTP/1.1\r\nhost: x\r\n\r\n")
            started.set()
            received.append(_until_close(conn, time.monotonic())[0])

    endless = fx.stream.make(b"data: 1\n\n").concat(fx.stream.never)

    @fx.fn
    def serving():
        sse = server_response.stream(endless, content_type="text/event-stream")
        at = yield from server.serve_effect(fx.succeed(sse)).flat_map(lambda _: port)
        reader = threading.Thread(target=read, args=(at,))
        reader.start()
        yield from effect.blocking(lambda: started.wait(TIMEOUT))
        yield from fx.sleep("100 millis")
        return reader

    layer_live = live_server.layer(host="127.0.0.1", graceful_shutdown_timeout="300 millis")
    program = scoped(serving()).pipe(fx.provide(layer_live))
    started_at = time.monotonic()
    reader = fx.run_blocking(program.timeout(Duration(TIMEOUT)).or_die())
    reader.join(TIMEOUT)
    assert time.monotonic() - started_at < 2.5
    [body] = received
    assert body.endswith(b"9\r\ndata: 1\n\n\r\n")


def test_writes_nothing_to_a_client_that_half_closed_before_the_response() -> None:
    """Node's server does not allow half-open connections: a client that
    ends its side aborts the request and gets no response (not a 499)."""

    @fx.fn
    def program():
        slow = fx.sleep("300 millis").as_(server_response.text("late"))
        at = yield from server.serve_effect(slow).flat_map(lambda _: port)
        return (yield from exchange(at, [b"GET / HTTP/1.1\r\nhost: x\r\n\r\n"]))

    assert run_live(program()) == b""


@pytest.mark.parametrize(
    "head",
    [
        b"GET / HTTP/1.1\nhost: x\nconnection: close\n\n",
        b"GET / HTTP/1.1\r\nhost: x\nconnection: close\r\n\r\n",
    ],
    ids=["every line", "one line"],
)
def test_answers_a_head_with_a_bare_lf_line_ending_with_400_at_once(head: bytes) -> None:
    @fx.fn
    def program():
        at = yield from _serve_ok()
        started = time.monotonic()
        received = yield from until_close(at, head)
        return received, time.monotonic() - started

    received, elapsed = run_live(program())
    [response] = parse_responses(received)
    assert response.status == 400
    assert elapsed < TIMEOUT / 2


def test_skips_a_bare_lf_before_the_request_line() -> None:
    @fx.fn
    def program():
        at = yield from _serve_ok()
        return (
            yield from until_close(at, b"\nGET / HTTP/1.1\r\nhost: x\r\nconnection: close\r\n\r\n")
        )

    [response] = parse_responses(run_live(program()))
    assert response.status == 200


@pytest.mark.parametrize(
    "body",
    [b"5\n", b"5\r\nhello\n", b"5\r\nhello\r\n0\r\nx: y\n"],
    ids=["size line", "data end", "trailer"],
)
def test_answers_a_chunked_body_with_a_bare_lf_line_ending_with_400_at_once(body: bytes) -> None:
    """llhttp fails a chunked body line ending in a bare LF at once
    (``HPE_CR_EXPECTED``), checked under Node 24."""

    @fx.fn
    def program():
        read = HttpServerRequest().flat_map(lambda request: request.text)
        yield from server.serve_effect(read.as_(server_response.text("ok")))
        at = yield from port
        head = b"POST / HTTP/1.1\r\nhost: x\r\ntransfer-encoding: chunked\r\n\r\n"
        started = time.monotonic()
        received = yield from until_close(at, head + body)
        return received, time.monotonic() - started

    received, elapsed = run_live(program())
    [response] = parse_responses(received)
    assert response.status == 400
    assert elapsed < TIMEOUT / 2
