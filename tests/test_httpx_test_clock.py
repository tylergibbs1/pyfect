"""An httpx response body waiting for its next chunk is an event, not work:
``TestClock.adjust`` does not wait for it (it used to wait ``warning_delay``
per adjust and warn)."""

import threading
import time
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.http import client as c
from pyfect.http.response import HttpClientResponse


class _Trickle(BaseHTTPRequestHandler):
    """Sends one chunk, then waits for ``release`` before ending the body."""

    protocol_version = "HTTP/1.1"
    release = threading.Event()

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        self.send_response(200)
        self.send_header("transfer-encoding", "chunked")
        self.end_headers()
        self.wfile.write(b"5\r\nfirst\r\n")
        self.wfile.flush()
        type(self).release.wait(10)
        self.wfile.write(b"0\r\n\r\n")
        self.close_connection = True


@pytest.fixture
def trickle_server() -> Iterator[str]:
    _Trickle.release.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Trickle)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    _Trickle.release.set()
    server.shutdown()
    server.server_close()


@pytest.mark.filterwarnings("error::pyfect.testing.BusyFiberWarning")
@testing.effect(warning_delay=0.5)
def test_an_idle_streaming_body_is_not_test_clock_work(trickle_server: str):
    pytest.importorskip("httpx")
    from pyfect.http import httpx_client

    chunks: list[bytes] = []

    def read() -> fx.Effect[None, object]:
        def body(response: HttpClientResponse) -> fx.Effect[None, object]:
            return response.stream.run_for_each(lambda chunk: fx.sync(lambda: chunks.append(chunk)))

        return c.get(trickle_server).flat_map(body).pipe(fx.provide(httpx_client.layer))

    reading = yield from fx.scoped(read()).fork()
    started = time.monotonic()
    for _ in range(3):
        yield from testing.adjust(1)
    elapsed = time.monotonic() - started
    _Trickle.release.set()
    yield from reading.join()
    assert chunks[0] == b"first"
    assert elapsed < 0.5, f"adjust waited {elapsed:.2f}s for an idle body"
