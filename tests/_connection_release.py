"""Counting the sockets HTTP client responses leave open, against a real
server and the httpx client.

``open_after(send)`` runs ``send(client, url)`` several times with Python's
cycle collector off and returns how many file descriptors are still open
once the client has had time to close what it released. A response must
let go of its connection when the program drops it (Effect releases it
when the response is garbage collected), so a response kept alive by a
reference cycle shows up here as an open socket rather than as a leak that
waits for the next cycle collection, or forever.
"""

from __future__ import annotations

import gc
import os
import threading
import time
from collections.abc import Callable, Generator
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pyfect as fx
from pyfect import layer
from pyfect.http import httpx_client
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.persistence import circuit_breaker as cb
from pyfect.persistence import rate_limiter as rl

type Send = Callable[[HttpClientService[HttpClientError], str], fx.Effect[object, Any, Any]]
"""Use the client on the server at ``url`` (``/``: 200, ``/redirect``: 302
to ``/``, ``/error``: 500)."""


class _Handler(BaseHTTPRequestHandler):
    """HTTP/1.0: the server closes each connection after its response, so
    only a response the client has not released keeps a socket open."""

    def log_message(self, format: str, *args: object) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("location", "/")
        else:
            self.send_response(500 if self.path == "/error" else 200)
        self.send_header("content-length", "2")
        self.end_headers()
        self.wfile.write(b"ok")


class _Server(ThreadingHTTPServer):
    daemon_threads = True

    def handle_error(self, request: object, client_address: object) -> None:
        """A client closing an unread response hangs up mid-write."""


@contextmanager
def _server() -> Generator[str]:
    server = _Server(("127.0.0.1", 0), _Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@contextmanager
def _without_cycle_collection() -> Generator[None]:
    enabled = gc.isenabled()
    gc.disable()
    try:
        yield
    finally:
        if enabled:
            gc.enable()


def open_fds() -> int:
    return len(os.listdir("/dev/fd"))


def _settled(baseline: int, timeout: float = 2.0) -> int:
    """Open descriptors over ``baseline``, once closing has settled."""
    deadline = time.monotonic() + timeout
    while (left := open_fds() - baseline) > 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    return left


_SERVICES = layer.merge(
    rl.layer.pipe(layer.provide(rl.layer_store_memory)), cb.layer_store_memory()
)


def open_after(send: Send, *, times: int = 5) -> int:
    """The sockets left open after ``times`` runs of ``send``."""

    @fx.gen
    def program():
        client = yield from HttpClient()
        baseline = open_fds()
        for _ in range(times):
            yield from send(client, url).ignore()
        # Leave the run the last send's fibers resumed this one in.
        yield from fx.yield_now()
        return _settled(baseline)

    with _server() as url, _without_cycle_collection():
        run = fx.scoped(program).pipe(fx.provide(httpx_client.layer)).pipe(fx.provide(_SERVICES))
        return fx.run_sync(run)
