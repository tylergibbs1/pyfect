"""A request interrupted during its TLS handshake closes the connection it was opening.

The soak test (tests/soak) found the httpx client's open sockets rising by about one a
minute: every request a timeout cut off while its connection was still in the TLS
handshake left that TCP connection open for good, on both ends. httpcore (1.0.9) closes
the stream when a handshake fails, but not when it is cancelled (``except Exception``),
and nothing above it holds the stream yet. The client now gives its connection pools a
network backend that closes the stream whatever ends the handshake (making a client
fails loudly if a new httpx or httpcore moves the pools it is installed on).
"""

from __future__ import annotations

import queue
import socket
import ssl
import threading
from collections.abc import Iterator

import pytest
from _threaded_server import serving

import pyfect as fx
from pyfect.http import httpx_client
from pyfect.http.client import HttpClient


class _Silent:
    """What a server that never answers the handshake saw: each connection, then whether
    the client closed it (before the server did)."""

    def __init__(self) -> None:
        self.accepted = 0
        self.closed_by_the_client: queue.Queue[bool] = queue.Queue()

    def handle(self, connection: socket.socket, stopping: threading.Event) -> None:
        self.accepted += 1
        while connection.recv(65536):
            pass  # the ClientHello
        self.closed_by_the_client.put(not stopping.is_set())


@pytest.fixture
def silent_server() -> Iterator[tuple[int, _Silent]]:
    """A TCP server that accepts connections and never answers the handshake."""
    silent = _Silent()
    with serving(silent.handle) as server:
        yield server.port, silent


def test_a_request_interrupted_in_the_handshake_closes_its_connection(
    silent_server: tuple[int, _Silent],
) -> None:
    port, silent = silent_server

    @fx.fn
    def program():
        client = yield from HttpClient()
        for _ in range(5):
            cut = client.get(f"https://127.0.0.1:{port}/").timeout("50 millis").exit()
            exit_ = yield from cut
            assert isinstance(exit_, fx.Failure)

    verify = ssl.create_default_context()
    fx.run_blocking(program().pipe(fx.provide(httpx_client.layer_with(verify=verify))))
    assert [silent.closed_by_the_client.get(timeout=2) for _ in range(5)] == [True] * 5
    assert silent.accepted == 5
