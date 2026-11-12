"""A request that reaches ``uvicorn_server`` or ``hypercorn_server`` before an app is served
waits for it, as one reaching Effect's ``NodeHttpServer`` before ``serve`` adds its
``request`` listener stays pending. The socket is bound when the server is made, so a client
that connects while the app's layers are still building must not get an answer meanwhile
(it used to get an empty 503: FINDINGS-lantern #3)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import effect
from pyfect.clock import sleep
from pyfect.http import hypercorn_server, server, server_response, uvicorn_server
from pyfect.http.client import HttpClient
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
