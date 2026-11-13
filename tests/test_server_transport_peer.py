"""Every HTTP server adapter reports the transport peer: a request's
``remote_address``, ``peer_address`` and URL scheme come from the socket, as
Effect's ``NodeHttpServer`` takes ``socket.remoteAddress``, never from
``X-Forwarded-For`` / ``X-Forwarded-Proto`` a client chose. Trusting a proxy is
the app's choice (``x_forwarded_headers``). Clients connect to localhost only."""

from __future__ import annotations

import asyncio
import importlib
import json
import pkgutil
from typing import Any

import pytest

import pyfect as fx
import pyfect.http
from pyfect.http import (
    asgi,
    hypercorn_server,
    live_server,
    router,
    server_response,
    uvicorn_server,
)
from pyfect.http.asgi import Message
from pyfect.http.client import HttpClient
from pyfect.http.server_request import HttpServerRequest

SPOOF = {"x-forwarded-for": "203.0.113.9", "x-forwarded-proto": "https"}

ADAPTERS: dict[str, Any] = {
    "uvicorn_server": uvicorn_server,
    "hypercorn_server": hypercorn_server,
    "live_server": live_server,
}


def _seen(request: Any) -> dict[str, Any]:
    return {
        "remote": request.remote_address,
        "peer": request.peer_address,
        "url": request.original_url,
    }


@fx.fn
def _whoami():
    request = yield from HttpServerRequest()
    return server_response.text(json.dumps(_seen(request)))


@fx.fn
def _ask():
    http = yield from HttpClient()
    response = yield from http.get("/whoami", headers=SPOOF)
    return json.loads((yield from response.text))


def _served(server: fx.Layer[Any, Any]) -> dict[str, Any]:
    app = router.serve(
        router.add("GET", "/whoami", _whoami()), disable_logger=True, disable_listen_log=True
    )
    program = fx.scoped(_ask().pipe(fx.provide(app)).pipe(fx.provide(server)))
    return fx.run_blocking(program.or_die())


def _assert_transport_peer(seen: dict[str, Any]) -> None:
    assert seen["remote"] == "127.0.0.1"
    assert seen["peer"] == "127.0.0.1"
    assert str(seen["url"]).startswith("http://127.0.0.1:")


@pytest.mark.parametrize("name", sorted(ADAPTERS))
def test_forwarded_headers_from_a_loopback_peer_are_not_the_peer(
    name: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    _assert_transport_peer(_served(ADAPTERS[name].layer_test()))


def test_every_server_adapter_is_checked() -> None:
    """A new adapter (a module with ``make``, ``layer_server`` and
    ``layer_test``) must join ``ADAPTERS``."""
    found: set[str] = set()
    for info in pkgutil.iter_modules(pyfect.http.__path__):
        module = importlib.import_module(f"pyfect.http.{info.name}")
        if all(hasattr(module, f) for f in ("make", "layer_server", "layer_test")):
            found.add(info.name)
    assert found == set(ADAPTERS)


def test_uvicorn_trusts_proxy_headers_when_asked(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("FORWARDED_ALLOW_IPS", raising=False)
    seen = _served(uvicorn_server.layer_test(config={"proxy_headers": True}))
    assert seen["remote"] == "203.0.113.9"
    assert str(seen["url"]).startswith("https://")


def test_an_asgi_app_takes_the_peer_from_its_server_scope() -> None:
    """``to_asgi`` reads the peer and scheme the hosting server put in the
    scope; whether that server trusts a proxy is its own setting."""
    sent: list[Message] = []
    scope: dict[str, Any] = {
        "type": "http",
        "asgi": {"version": "3.0"},
        "http_version": "1.1",
        "method": "GET",
        "scheme": "http",
        "path": "/",
        "raw_path": b"/",
        "root_path": "",
        "query_string": b"",
        "headers": [(b"host", b"test"), *((k.encode(), v.encode()) for k, v in SPOOF.items())],
        "client": ("10.0.0.1", 5000),
        "server": ("test", 80),
    }

    async def receive() -> Message:
        return {"type": "http.request", "body": b"", "more_body": False}

    async def send(message: Message) -> None:
        sent.append(message)

    app = asgi.to_asgi(HttpServerRequest().map(lambda r: server_response.json_unsafe(_seen(r))))
    asyncio.run(app(scope, receive, send))
    body = b"".join(m.get("body", b"") for m in sent if m["type"] == "http.response.body")
    seen = json.loads(body)
    assert seen["remote"] == "10.0.0.1"
    assert seen["peer"] == "10.0.0.1"
    assert str(seen["url"]).startswith("http://test/")
