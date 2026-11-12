"""A request that reaches ``uvicorn_server`` or ``hypercorn_server`` before an app is served
waits for it, as one reaching Effect's ``NodeHttpServer`` before ``serve`` adds its
``request`` listener stays pending. The socket is bound when the server is made, so a client
that connects while the app's layers are still building must not get an answer meanwhile
(it used to get an empty 503: FINDINGS-lantern #3)."""

from __future__ import annotations

import logging
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx
import pytest

import pyfect as fx
from pyfect import effect
from pyfect.clock import sleep
from pyfect.http import hypercorn_server, server, server_response, uvicorn_server
from pyfect.http.client import HttpClient
from pyfect.net.net_address import InetAddressV4
from pyfect.scope import Scope, scoped

type MakeLayer = Callable[[], fx.Layer[Any, Any, Any]]

SERVERS: dict[str, MakeLayer] = {
    "uvicorn": uvicorn_server.layer_test,
    "hypercorn": hypercorn_server.layer_test,
}


def _get(path: str) -> fx.Effect[tuple[int, str], Any, HttpClient]:
    @fx.fn
    def body():
        client = yield from HttpClient()
        response = yield from client.get(path)
        return response.status, (yield from response.text)

    return body()


@fx.fn
def _serve_late():
    early = yield from _get("/").fork()
    yield from sleep("300 millis")
    answered_before_serve = (yield from effect.sync(early.poll_unsafe)) is not None
    running = yield from server.HttpServer()
    yield from running.serve(effect.succeed(server_response.text("ready")), None)
    return (yield from early.join()), answered_before_serve


@pytest.mark.parametrize("name", sorted(SERVERS))
def test_a_request_before_the_app_is_served_waits_for_it(name: str) -> None:
    program: fx.Effect[Any, Any, Scope | Any] = _serve_late()
    provided = scoped(program).pipe(fx.provide(SERVERS[name]()))
    response, answered_before_serve = fx.run_blocking(provided.or_die())
    assert not answered_before_serve
    assert response == (200, "ready")


def test_every_server_on_the_shared_asgi_listener_is_checked_here() -> None:
    http = Path(server.__file__).parent
    listeners = {
        path.stem.removesuffix("_server")
        for path in http.glob("*_server.py")
        if "make_listener" in path.read_text()
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
def test_a_request_still_waiting_when_the_server_closes_is_released_at_once(
    name: str, caplog: pytest.LogCaptureFixture
) -> None:
    """Closing a server that never served an app answers the requests waiting for one with an
    empty 503 instead of waiting out the engine's graceful timeout (20 s), which then
    cancelled them with a logged traceback."""
    outcome: list[object] = []
    threads: list[threading.Thread] = []

    @fx.fn
    def program():
        running = yield from server.HttpServer()
        assert isinstance(running.address, InetAddressV4)
        threads.append(_request_in_thread(running.address.port, outcome))
        yield from sleep("300 millis")

    started = time.monotonic()
    with caplog.at_level(logging.INFO):
        fx.run_blocking(program().pipe(fx.provide(SERVERS[name]())).or_die())
    closed_in = time.monotonic() - started
    threads[0].join(10)
    assert closed_in < 5, closed_in
    assert outcome == [503]
    assert not [r for r in caplog.records if r.levelno >= logging.WARNING], caplog.text
