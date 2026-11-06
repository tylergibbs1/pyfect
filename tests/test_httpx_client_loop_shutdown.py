"""Releasing the httpx client closes every response body httpx left open
before its loop closes.

A body read in part leaves httpx's (and httpcore's) async generators open;
the fiber that drops the response finalizes them on its own thread, and
their close runs on the client's loop as a chain of tasks. A layer
released right after used to close the loop with that chain half done
("Task was destroyed but it is pending: <async_generator_athrow>",
"coroutine method 'aclose' of 'AsyncHTTP11Connection._receive_response_body'
was never awaited"), in about one round in twenty of two clients at once.
"""

from __future__ import annotations

import gc
import logging
import socket
import threading
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from typing import Any

import pytest

import pyfect as fx
from pyfect.exit import Exit, Success
from pyfect.http import httpx_client
from pyfect.http.client import HttpClient

_ROUNDS = 100
_CHUNK = b"HTTP/1.1 200 OK\r\ntransfer-encoding: chunked\r\n\r\n5\r\nhello\r\n"


def _answer(connection: socket.socket) -> None:
    """Each request gets a chunked body that never ends."""
    with connection:
        while connection.recv(65536):
            connection.sendall(_CHUNK)


@pytest.fixture
def url() -> Iterator[str]:
    server = socket.create_server(("127.0.0.1", 0))

    def accept() -> None:
        while True:
            try:
                connection, _ = server.accept()
            except OSError:
                return
            threading.Thread(target=_answer, args=(connection,), daemon=True).start()

    threading.Thread(target=accept, daemon=True).start()
    yield f"http://127.0.0.1:{server.getsockname()[1]}/"
    server.close()


def _read_part(url: str) -> Exit[Any, Any]:
    def program() -> Any:
        client = yield from HttpClient()
        return (yield from client.get(url).flat_map(lambda r: r.stream.take(1).run_collect()))

    return fx.run_blocking_exit(fx.scoped(fx.gen(program)).pipe(fx.provide(httpx_client.layer)))


def test_a_released_client_closes_the_bodies_it_left_open(
    url: str, caplog: pytest.LogCaptureFixture
) -> None:
    for _ in range(_ROUNDS):
        # A pool per round: a worker ending drops what its runs left behind.
        with ThreadPoolExecutor(2) as pool:
            exits = list(pool.map(_read_part, [url, url]))
        assert all(isinstance(exit_, Success) for exit_ in exits), exits
    for thread in threading.enumerate():
        if thread.name == "pyfect-httpx":
            thread.join(5)
    gc.collect()
    lost = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert lost == []
