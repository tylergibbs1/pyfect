"""A request that reaches ``uvicorn_server`` or ``hypercorn_server`` before an app is served
is answered at once with the 503 ``live_server`` gives, as one reaching Effect's
``NodeHttpServer`` before ``serve`` is (Effect #10786); once the app is served it answers.
(Until 0.7.0 such a request waited for the app.)"""

from __future__ import annotations

import logging
import socket
import threading
from collections.abc import Callable
from typing import Any

import _source
import httpx
import pytest

import pyfect as fx
from pyfect import effect
from pyfect.clock import sleep
from pyfect.http import hypercorn_server, live_server, server, server_response, uvicorn_server
from pyfect.http.client import HttpClient
from pyfect.net.net_address import InetAddressV4
from pyfect.scope import Scope, scoped

type MakeLayer = Callable[[], fx.Layer[Any, Any, Any]]

SERVERS: dict[str, MakeLayer] = {
    "uvicorn": uvicorn_server.layer_test,
    "hypercorn": hypercorn_server.layer_test,
}

type Answer = tuple[int, str | None, str | None, str]


def _get(path: str) -> fx.Effect[Answer, Any, HttpClient]:
    @fx.fn
    def body():
        client = yield from HttpClient()
        response = yield from client.get(path)
        headers = response.headers
        text = yield from response.text
        return response.status, headers.get("cache-control"), headers.get("retry-after"), text

    return body()


@fx.fn
def _before_and_after_serve():
    early = yield from _get("/")
    running = yield from server.HttpServer()
    yield from running.serve(effect.succeed(server_response.text("ready")), None)
    return early, (yield from _get("/"))


def _answers(make: MakeLayer) -> tuple[Answer, Answer]:
    program: fx.Effect[Any, Any, Scope | Any] = _before_and_after_serve()
    provided = scoped(program).pipe(fx.provide(make()))
    return fx.run_blocking(provided.timeout("10 seconds").or_die())


@pytest.mark.parametrize("name", sorted(SERVERS))
def test_a_request_before_the_app_is_served_gets_the_live_server_503(name: str) -> None:
    live_early, _ = _answers(live_server.layer_test)
    assert live_early == (503, "no-store", "1", "service unavailable")
    early, served = _answers(SERVERS[name])
    assert early == live_early
    assert served == (200, None, None, "ready")


def _upgrade_status(port: int) -> int:
    with socket.create_connection(("127.0.0.1", port), timeout=10) as conn:
        conn.sendall(
            b"GET / HTTP/1.1\r\nhost: localhost\r\nupgrade: websocket\r\n"
            b"connection: Upgrade\r\nsec-websocket-key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
            b"sec-websocket-version: 13\r\n\r\n"
        )
        return int(conn.recv(4096).split(b" ", 2)[1])


@pytest.mark.parametrize("name", sorted(SERVERS))
def test_a_websocket_upgrade_before_the_app_is_served_gets_503(name: str) -> None:
    """As Node, which hands an upgrade with no ``upgrade`` listener to the ``request``
    listeners, and so to the 503 of ``live_server``."""
    statuses: list[int] = []

    @fx.fn
    def program():
        running = yield from server.HttpServer()
        assert isinstance(running.address, InetAddressV4)
        port = running.address.port
        statuses.append((yield from effect.blocking(lambda: _upgrade_status(port))))

    for make in (live_server.layer_test, SERVERS[name]):
        fx.run_blocking(program().pipe(fx.provide(make())).timeout("10 seconds").or_die())
    assert statuses == [503, 503]


def test_every_server_on_the_shared_asgi_listener_is_checked_here() -> None:
    http = _source.SRC / "http"
    listeners = {
        path.stem.removesuffix("_server")
        for path in _source.files(http, "*_server.py", recursive=False)
        if "make_listener" in _source.text(path)
    }
    assert listeners == set(SERVERS)


def _request_in_thread(port: int, outcome: list[object]) -> threading.Thread:
    def send() -> None:
        try:
            outcome.append(httpx.get(f"http://127.0.0.1:{port}/", timeout=30).status_code)
        except httpx.HTTPError as error:
            outcome.append(error)

    thread = threading.Thread(target=send, daemon=True)
    thread.start()
    return thread


@pytest.mark.parametrize("name", sorted(SERVERS))
def test_a_server_that_never_serves_answers_503_and_closes_quietly(
    name: str, caplog: pytest.LogCaptureFixture
) -> None:
    """A request to a server that never served an app gets the 503 at once, and closing the
    server neither waits out the engine's graceful timeout (20 s) nor logs a traceback."""
    outcome: list[object] = []
    threads: list[threading.Thread] = []

    @fx.fn
    def program():
        running = yield from server.HttpServer()
        assert isinstance(running.address, InetAddressV4)
        threads.append(_request_in_thread(running.address.port, outcome))
        yield from sleep("300 millis")

    # Waiting out the engine's 20 s graceful timeout would outlast the test's time limit.
    with caplog.at_level(logging.INFO):
        fx.run_blocking(program().pipe(fx.provide(SERVERS[name]())).or_die())
    threads[0].join(10)
    assert outcome == [503]
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], caplog.text
