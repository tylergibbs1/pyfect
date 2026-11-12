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

import socket
import ssl
import threading
from collections.abc import Iterator

import pytest

import pyfect as fx
from pyfect.http import httpx_client
from pyfect.http.client import HttpClient


@pytest.fixture
def silent_server() -> Iterator[tuple[int, list[socket.socket]]]:
    """A TCP server that accepts connections and never answers the handshake."""
    listener = socket.create_server(("127.0.0.1", 0))
    accepted: list[socket.socket] = []

    def accept() -> None:
        while True:
            try:
                connection, _ = listener.accept()
            except OSError:
                return
            accepted.append(connection)

    threading.Thread(target=accept, daemon=True).start()
    yield listener.getsockname()[1], accepted
    listener.close()
    for connection in accepted:
        connection.close()


def _closed_by_the_client(connection: socket.socket) -> bool:
    connection.settimeout(2)
    try:
        while connection.recv(65536):
            pass  # the ClientHello
    except TimeoutError:
        return False
    return True


def test_a_request_interrupted_in_the_handshake_closes_its_connection(
    silent_server: tuple[int, list[socket.socket]],
) -> None:
    port, accepted = silent_server

    @fx.fn
    def program():
        client = yield from HttpClient()
        for _ in range(5):
            cut = client.get(f"https://127.0.0.1:{port}/").timeout("50 millis").exit()
            exit_ = yield from cut
            assert isinstance(exit_, fx.Failure)

    verify = ssl.create_default_context()
    fx.run_blocking(program().pipe(fx.provide(httpx_client.layer_with(verify=verify))))
    assert len(accepted) == 5
    assert [_closed_by_the_client(c) for c in accepted] == [True] * 5
