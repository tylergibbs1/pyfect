"""The HTTP client beyond Effect's tests: ``layer_test``, aborting unread
responses, and the httpx backend cancelling requests."""

import gc
import sys
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import SplitResult

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.http import client as c
from pyfect.http import request as req
from pyfect.http import response as res
from pyfect.http.abort import AbortSignal
from pyfect.http.error import HttpClientError


def _run[A](eff: fx.Effect[A, object]) -> A:
    return fx.run_sync(eff.or_die())


@testing.effect
def test_layer_test_answers_with_the_handler():
    def handle(
        request: req.HttpClientRequest,
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        return fx.succeed(res.make(request, f"{request.method} {request.url}"))

    text = (
        yield from c.get("http://test/path")
        .flat_map(lambda r: r.text)
        .pipe(fx.provide(c.layer_test(handle)))
    )
    assert text == "GET http://test/path"


def test_unread_response_is_aborted_when_collected() -> None:
    signals: list[AbortSignal] = []

    def send(
        request: req.HttpClientRequest, _url: SplitResult, signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        signals.append(signal)
        return fx.succeed(res.make(request, "unread"))

    _run(c.make(send).get("http://test/").as_void())
    gc.collect()
    assert signals[0].aborted


class _Hanging(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    closed = threading.Event()

    def log_message(self, format: str, *args: Any) -> None:
        pass

    def do_GET(self) -> None:
        if self.path == "/body":
            self.send_response(200)
            self.send_header("content-length", "4")
            self.end_headers()
            self.wfile.write(b"test")
            return
        self.connection.recv(1)
        type(self).closed.set()
        self.close_connection = True


@pytest.fixture
def hanging_server() -> Iterator[str]:
    _Hanging.closed.clear()
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Hanging)
    server.daemon_threads = True
    threading.Thread(target=server.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{server.server_address[1]}"
    server.shutdown()
    server.server_close()


def test_httpx_interrupt_closes_the_connection(hanging_server: str) -> None:
    pytest.importorskip("httpx")
    from pyfect.http import httpx_client

    timed_out = _run(
        c.get(f"{hanging_server}/hang").timeout(0.2).option().pipe(fx.provide(httpx_client.layer))
    )
    assert timed_out is None
    assert _Hanging.closed.wait(2)


def _wait_for_loop_threads() -> None:
    for thread in threading.enumerate():
        if thread.name == "pyfect-httpx":
            thread.join(2)


def test_httpx_unread_response_after_the_layer_closed(hanging_server: str) -> None:
    pytest.importorskip("httpx")
    from pyfect.http import httpx_client

    unraisable: list[Any] = []
    previous = sys.unraisablehook
    sys.unraisablehook = unraisable.append
    try:
        response = _run(c.get(f"{hanging_server}/body").pipe(fx.provide(httpx_client.layer)))
        assert response.status == 200
        _wait_for_loop_threads()
        del response
        gc.collect()
    finally:
        sys.unraisablehook = previous
    assert unraisable == []


def _never_sending(
    signals: list[AbortSignal],
) -> c.HttpClientService[HttpClientError]:
    def send(
        _request: req.HttpClientRequest, _url: SplitResult, signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        signals.append(signal)
        return fx.never

    return c.make(send)


def test_interrupting_a_request_aborts_its_signal() -> None:
    signals: list[AbortSignal] = []
    assert _run(_never_sending(signals).get("http://test/").timeout(0.01).option()) is None
    assert signals[0].aborted


def test_interrupting_a_body_read_aborts_the_request() -> None:
    signals: list[AbortSignal] = []

    def send(
        request: req.HttpClientRequest, _url: SplitResult, signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        signals.append(signal)
        return fx.succeed(res.make(request, fx.stream.never))

    reading = c.make(send).get("http://test/").flat_map(lambda r: r.text.timeout(0.01).option())
    assert _run(reading) is None
    assert signals[0].aborted


def test_with_scope_ties_only_its_own_request_to_the_scope() -> None:
    """Effect keys the scope's controller on the request ``with_scope``
    sends: a request another client makes meanwhile keeps its own."""
    signals: list[AbortSignal] = []
    kept: list[res.HttpClientResponse] = []

    def send(
        request: req.HttpClientRequest, _url: SplitResult, signal: AbortSignal, _fiber: Any
    ) -> fx.Effect[res.HttpClientResponse, HttpClientError]:
        signals.append(signal)
        return fx.succeed(res.make(request, "body"))

    other = c.make(send)
    scoped = c.make(send).tap(lambda _r: other.get("http://other/").map(kept.append)).with_scope()
    _run(fx.scoped(scoped.get("http://test/")))
    assert signals[0].aborted
    assert not signals[1].aborted
    assert _run(kept[0].text) == "body"


def test_transient_statuses_are_effects_list_not_every_5xx() -> None:
    request = req.get("http://test/")
    transient = {s for s in range(100, 600) if c.is_transient_response(res.make(request, status=s))}
    assert transient == {408, 429, 500, 502, 503, 504}
