"""Behaviors of Node's ``http.Server`` that the live server (Effect's
``NodeHttpServer`` runs on Node's) keeps, checked under Node 24: an idle
keep-alive connection is closed after ``keep_alive_timeout`` (advertised
as ``keep-alive: timeout=<seconds>``); a head that does not arrive within
``headers_timeout`` is answered with 408 if it started, else the
connection is closed; responses are ``HTTP/1.1`` whatever the request's
version; and each build of a server layer listens anew."""

from __future__ import annotations

import socket
import time
from typing import Any

import pyfect as fx
from pyfect.http import live_server, server, server_response
from pyfect.http.server import HttpServer
from pyfect.scope import Scope, scoped

from ._live_http import TIMEOUT, parse_responses, port, run_live, with_socket


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

    received, elapsed = run_live(program(), keep_alive_timeout=0.3)
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

    keep_alive, closed = run_live(program(), keep_alive_timeout=7.9)
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

    received, elapsed = run_live(program(), headers_timeout=0.3)
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

    received, elapsed = run_live(program(), headers_timeout=0.3)
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

    received = run_live(program(), keep_alive_timeout=0.2, headers_timeout=3)
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
        received = fx.run_sync(scoped(program()).pipe(fx.provide(served)).or_die())
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
