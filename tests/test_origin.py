"""Cross-site WebSocket hijacking and RPC CSRF: a WebSocket upgrade (over
ASGI, on the live server, on the ``websockets`` server) and an RPC call
whose ``Origin`` is neither the server's own nor in ``AllowedOrigins`` are
refused with 403 before the app sees a socket."""

from __future__ import annotations

import asyncio
import base64
import os
import socket
from typing import Any

import pytest
from _pyfect_modules import modules
from oracle._live_http import exchange, port, run_live

import pyfect as fx
from pyfect import effect, layer, testing
from pyfect import schema as S
from pyfect.http import asgi, origin, router, server_response
from pyfect.http._authority import Authority, parse_authority
from pyfect.http.asgi import Message, Scope
from pyfect.http.origin import AllowedOrigins
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.http.web import WebRequest
from pyfect.net.net_address import InetAddressV4
from pyfect.rpc import RpcGroup, make
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server
from pyfect.scope import scoped
from pyfect.socket import SocketService

_EVIL = "https://evil.example"


# --- the policy ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("headers", "allowed"),
    [
        ({"host": "app.example"}, True),  # not from a browser page
        ({"host": "app.example", "origin": "https://app.example"}, True),
        ({"host": "App.Example:443", "origin": "https://app.example"}, True),
        ({"host": "app.example:8443", "origin": "https://app.example:8443"}, True),
        ({"host": "app.example", "origin": _EVIL}, False),
        ({"host": "app.example", "origin": "https://app.example.evil.example"}, False),
        ({"host": "app.example", "origin": "https://app.example:8443"}, False),
        ({"host": "app.example", "origin": "null"}, False),
        ({"host": "app.example", "origin": "https://app.example/path"}, False),
        ({"origin": "https://app.example"}, False),  # no host to compare with
    ],
)
def test_the_same_origin_policy(headers: dict[str, str], allowed: bool) -> None:
    own = parse_authority(headers.get("host", ""))
    assert origin.SAME_ORIGIN.allows(headers.get("origin"), own) is allowed


def test_listed_origins_and_any_origin() -> None:
    policy = origin.allow("https://App.example:443", "http://localhost:3000")
    assert policy.allows("https://app.example", Authority("api.example"))
    assert policy.allows("http://localhost:3000", Authority("api.example"))
    assert not policy.allows(_EVIL, Authority("api.example"))
    assert origin.ANY_ORIGIN.allows(_EVIL, Authority("api.example"))
    with pytest.raises(ValueError, match="not an origin"):
        origin.allow("app.example")


# --- ASGI ----------------------------------------------------------------------


def _upgrading(request: ServerRequest) -> fx.Effect[HttpServerResponse, Any, Any]:
    return scoped(request.upgrade.flat_map(lambda sock: sock.reader)).as_(server_response.empty())


def _asgi_handshake(origin_header: str | None, policy: origin.OriginPolicy | None) -> list[Any]:
    app_effect = HttpServerRequest().flat_map(_upgrading)
    if policy is not None:
        app_effect = app_effect.pipe(effect.provide_service(AllowedOrigins, policy))
    app = asgi.to_asgi(app_effect)

    async def main() -> list[Any]:
        inbox: asyncio.Queue[Message] = asyncio.Queue()
        inbox.put_nowait({"type": "websocket.connect"})
        sent: list[Any] = []

        async def send(message: Message) -> None:
            sent.append(message)
            if message["type"] in ("websocket.accept", "websocket.close"):
                inbox.put_nowait({"type": "websocket.disconnect", "code": 1000})

        headers = [(b"host", b"app.example")]
        if origin_header is not None:
            headers.append((b"origin", origin_header.encode()))
        scope: Scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "wss",
            "path": "/ws",
            "raw_path": b"/ws",
            "root_path": "",
            "query_string": b"",
            "headers": headers,
            "client": ("10.0.0.1", 1234),
            "server": ("app.example", 443),
            "subprotocols": [],
            "extensions": {"websocket.http.response": {}},
        }
        await asyncio.wait_for(app(scope, inbox.get, send), 5)
        return [m.get("status", m["type"]) for m in sent if m["type"] != "websocket.close"]

    return asyncio.run(main())


def test_an_asgi_websocket_from_another_origin_is_refused() -> None:
    assert _asgi_handshake(_EVIL, None) == [403, "websocket.http.response.body"]
    assert _asgi_handshake("https://app.example", None) == ["websocket.accept"]
    assert _asgi_handshake(None, None) == ["websocket.accept"]
    assert _asgi_handshake(_EVIL, origin.allow(_EVIL)) == ["websocket.accept"]


# --- the live server -------------------------------------------------------------


def test_a_live_server_upgrade_from_another_origin_is_refused() -> None:
    app = router.add("GET", "/ws", HttpServerRequest().flat_map(_upgrading))

    def handshake(sent_origin: str) -> bytes:
        @fx.fn
        def program():
            at = yield from port
            head = (
                f"GET /ws HTTP/1.1\r\nHost: 127.0.0.1:{at}\r\nConnection: Upgrade\r\n"
                "Upgrade: websocket\r\nSec-WebSocket-Key: dGhlIHNhbXBsZSBub25jZQ==\r\n"
                f"Sec-WebSocket-Version: 13\r\nOrigin: {sent_origin.format(at=at)}\r\n\r\n"
            )
            return (yield from exchange(at, [head.encode()]))

        return run_live(program().pipe(fx.provide(router.serve(app, disable_logger=True))))

    assert handshake(_EVIL).startswith(b"HTTP/1.1 403")
    assert handshake("http://127.0.0.1:{at}").startswith(b"HTTP/1.1 101")


# --- RPC over HTTP ----------------------------------------------------------------


class Counter(RpcGroup):
    bump = make("Bump", success=S.Int)


def test_an_rpc_post_from_another_origin_is_refused() -> None:
    bumps = [0]

    def bump(_: object) -> fx.Effect[int]:
        def run() -> int:
            bumps[0] += 1
            return bumps[0]

        return effect.sync(run)

    handlers = Counter.to_layer(Counter.handlers().handle(Counter.bump)(bump))
    app = (
        rpc_server.layer_http(Counter, path="/rpc", protocol="http")
        .pipe(layer.provide(handlers))
        .pipe(layer.provide(rs.layer_ndjson))
    )

    async def post(sent_origin: str) -> int:
        made = router.to_web_handler(app, disable_logger=True)
        try:
            body = '{"_tag":"Request","id":1,"tag":"Bump","payload":null,"headers":[]}\n'
            response = await made.handler(
                WebRequest(
                    "http://app.example/rpc",
                    method="POST",
                    body=body,
                    headers={"content-type": "text/plain", "origin": sent_origin},
                )
            )
            await response.read()
            return response.status
        finally:
            await made.dispose()

    assert asyncio.run(post(_EVIL)) == 403
    assert bumps == [0]
    assert asyncio.run(post("http://app.example")) == 200
    assert bumps == [1]


# --- the websockets server ---------------------------------------------------------


def _handshake(port_number: int, sent_origin: str | None) -> bytes:
    with socket.create_connection(("127.0.0.1", port_number), timeout=5) as client:
        key = base64.b64encode(os.urandom(16)).decode()
        lines = [
            "GET / HTTP/1.1",
            f"Host: 127.0.0.1:{port_number}",
            "Upgrade: websocket",
            "Connection: Upgrade",
            f"Sec-WebSocket-Key: {key}",
            "Sec-WebSocket-Version: 13",
        ]
        if sent_origin is not None:
            lines.append(f"Origin: {sent_origin}")
        client.sendall(("\r\n".join(lines) + "\r\n\r\n").encode())
        return client.recv(64)


@testing.live(timeout=10)
def test_a_websockets_server_handshake_from_another_origin_is_refused():
    from pyfect.socket import ws as ws_platform

    srv = yield from ws_platform.make_server(0, "127.0.0.1")

    def handler(sock: SocketService) -> fx.Effect[None, Any, Any]:
        return scoped(sock.reader).ignore()

    yield from srv.run(handler).fork_scoped()
    address = srv.address
    assert isinstance(address, InetAddressV4)
    at = address.port
    refused = yield from effect.blocking(lambda: _handshake(at, _EVIL))
    same = yield from effect.blocking(lambda: _handshake(at, f"http://127.0.0.1:{at}"))
    none = yield from effect.blocking(lambda: _handshake(at, None))
    assert refused.startswith(b"HTTP/1.1 403")
    assert same.startswith(b"HTTP/1.1 101")
    assert none.startswith(b"HTTP/1.1 101")


def test_every_server_request_upgrade_checks_the_origin() -> None:
    """A guard: each ``ServerRequest`` that can upgrade runs
    ``require_allowed_origin`` first, or hands the upgrade to the request
    it wraps; a new server's request class cannot skip the check."""
    import inspect

    from pyfect.http.server_request import ServerRequest as Base

    for _ in modules():
        pass

    def subclasses(cls: type[Base]) -> list[type[Base]]:
        return [c for sub in cls.__subclasses__() for c in (sub, *subclasses(sub))]

    unchecked = [
        cls.__qualname__
        for cls in subclasses(Base)
        if cls.__module__.startswith("pyfect.")
        and "upgrade_with" in vars(cls)
        and not any(
            needle in inspect.getsource(vars(cls)["upgrade_with"])
            for needle in ("require_allowed_origin(", ".inner.upgrade_with(")
        )
    ]
    assert unchecked == []
    # ``upgrade`` is ``upgrade_with()``: overriding it would skip the check.
    overridden = [
        cls.__qualname__
        for cls in subclasses(Base)
        if cls.__module__.startswith("pyfect.") and "upgrade" in vars(cls)
    ]
    assert overridden == []
