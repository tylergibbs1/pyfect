"""``_threaded_server.serving``: a connection's socket is closed by its own thread, after its
handler returns, and closing the server wakes and waits for every handler first."""

from __future__ import annotations

import contextlib
import socket
import ssl
import threading
from pathlib import Path

import pytest
from _threaded_server import drain, serving

FIXTURES = Path(__file__).parent / "oracle" / "fixtures" / "tls"


def _blocked_reader(seen: list[int], reading: threading.Event):
    def handle(conn: socket.socket, stopping: threading.Event) -> None:
        reading.set()
        with contextlib.suppress(OSError):
            conn.recv(1)
        seen.append(conn.fileno())

    return handle


def test_closing_wakes_a_blocked_handler_before_closing_its_socket():
    seen: list[int] = []
    reading = threading.Event()
    with (
        serving(_blocked_reader(seen, reading)) as server,
        socket.create_connection(server.address),
    ):
        assert reading.wait(5)
    assert len(seen) == 1
    assert seen[0] != -1, "the socket was closed under its handler"


def test_closing_wakes_a_blocked_tls_handler_before_closing_its_socket():
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(FIXTURES / "cert.pem", FIXTURES / "key.pem")
    client_context = ssl.create_default_context(cafile=FIXTURES / "cert.pem")
    seen: list[int] = []
    reading = threading.Event()
    with (
        serving(_blocked_reader(seen, reading), tls=context) as server,
        client_context.wrap_socket(
            socket.create_connection(server.address), server_hostname="localhost"
        ),
    ):
        assert reading.wait(5)
    assert len(seen) == 1
    assert seen[0] != -1, "the socket was closed under its handler"


def test_drop_hangs_up_on_the_clients():
    with serving(drain) as server, socket.create_connection(server.address) as client:
        client.settimeout(5)
        client.sendall(b"ignored")
        assert server.connected.wait(5)
        server.drop()
        assert client.recv(1) == b""


def test_a_handler_that_ignores_the_shutdown_fails_the_close():
    release = threading.Event()

    def stuck(conn: socket.socket, stopping: threading.Event) -> None:
        release.wait()

    with (
        pytest.raises(AssertionError, match="test-server-"),
        serving(stuck, join_seconds=0.1) as server,
        socket.create_connection(server.address),
    ):
        assert server.connected.wait(5)
    release.set()
