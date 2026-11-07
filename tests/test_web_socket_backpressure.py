"""WebSocket writes wait for the peer: a writer suspends while more than
the high-water mark of bytes is still unsent, on the ``websockets`` server
and over ASGI, so a peer that stops reading cannot grow server memory."""

from __future__ import annotations

import asyncio
import base64
import os
import socket
from typing import Any

import pytest
from _pyfect_modules import modules

pytest.importorskip("websockets")

import pyfect as fx
from pyfect.effect import blocking, gen
from pyfect.http import asgi, server_response
from pyfect.http.asgi import Message, Scope
from pyfect.http.server_request import HttpServerRequest, ServerRequest
from pyfect.http.server_response import HttpServerResponse
from pyfect.net.net_address import InetAddressV4
from pyfect.scope import scoped
from pyfect.socket import SocketService
from pyfect.socket import ws as ws_platform
from pyfect.socket._web_socket import DEFAULT_HIGH_WATER_MARK

_CHUNK = b"x" * (64 * 1024)
_WRITES = 400


def _writer_counting(written: list[int]) -> Any:
    """A handler that writes ``_WRITES`` chunks, counting each finished one."""

    def handler(sock: SocketService) -> fx.Effect[None, Any, Any]:
        def body():
            yield from sock.reader
            writer = yield from sock.writer
            for _ in range(_WRITES):
                yield from writer.write(_CHUNK)
                written[0] += 1

        return scoped(gen(body)).ignore()

    return handler


def _silent_client(port: int) -> socket.socket:
    """A client that completes the WebSocket handshake, then never reads
    (with a small receive buffer, so the kernel holds little)."""
    client = socket.socket()
    client.setsockopt(socket.SOL_SOCKET, socket.SO_RCVBUF, 16 * 1024)
    client.connect(("127.0.0.1", port))
    key = base64.b64encode(os.urandom(16)).decode()
    client.sendall(
        (
            f"GET / HTTP/1.1\r\nHost: 127.0.0.1:{port}\r\nUpgrade: websocket\r\n"
            f"Connection: Upgrade\r\nSec-WebSocket-Key: {key}\r\n"
            "Sec-WebSocket-Version: 13\r\n\r\n"
        ).encode()
    )
    head = b""
    while b"\r\n\r\n" not in head:
        head += client.recv(1)
    assert head.startswith(b"HTTP/1.1 101"), head
    return client


@fx.testing.live(timeout="20 seconds")
def test_a_server_write_waits_while_the_peer_does_not_read():
    written = [0]
    srv = yield from ws_platform.make_server(0, "127.0.0.1")
    yield from srv.run(_writer_counting(written)).fork_scoped()
    address = srv.address
    assert isinstance(address, InetAddressV4)
    client = yield from blocking(lambda: _silent_client(address.port))
    yield from fx.sleep("1 second")
    stalled = written[0]
    client.close()
    assert stalled < _WRITES // 4, f"{stalled} writes of 64 KiB finished unread"


class _StalledPeer:
    """An ASGI server whose sends of data never finish until released."""

    def __init__(self) -> None:
        self.inbox: asyncio.Queue[Message] = asyncio.Queue()
        self.inbox.put_nowait({"type": "websocket.connect"})
        self.release = asyncio.Event()
        self.sent: list[str] = []

    async def receive(self) -> Message:
        return await self.inbox.get()

    async def send(self, message: Message) -> None:
        self.sent.append(message["type"])
        if message["type"] == "websocket.send":
            await self.release.wait()


def test_an_asgi_write_waits_while_the_server_has_not_sent():
    written = [0]

    def handler(request: ServerRequest) -> fx.Effect[HttpServerResponse, Any, Any]:
        return request.upgrade.flat_map(_writer_counting(written)).as_(server_response.empty())

    app = asgi.to_asgi(HttpServerRequest().flat_map(handler))

    async def main() -> int:
        peer = _StalledPeer()
        scope: Scope = {
            "type": "websocket",
            "asgi": {"version": "3.0"},
            "scheme": "ws",
            "path": "/ws",
            "raw_path": b"/ws",
            "root_path": "",
            "query_string": b"",
            "headers": [(b"host", b"test")],
            "client": ("10.0.0.1", 1234),
            "server": ("test", 80),
            "subprotocols": [],
            "extensions": {},
        }
        call = asyncio.ensure_future(app(scope, peer.receive, peer.send))
        await asyncio.sleep(0.5)
        stalled = written[0]
        peer.release.set()
        peer.inbox.put_nowait({"type": "websocket.disconnect", "code": 1000})
        await asyncio.wait_for(call, 10)
        return stalled

    stalled = asyncio.run(main())
    assert stalled * len(_CHUNK) <= 2 * DEFAULT_HIGH_WATER_MARK


def test_every_web_socket_in_pyfect_reports_its_unsent_bytes() -> None:
    """A guard: a ``WebSocketLike`` without ``buffered_amount`` and
    ``when_drained`` makes ``from_web_socket``'s writes fire and forget."""
    import inspect

    found: dict[str, bool] = {}
    for module in modules():
        for name, value in vars(module).items():
            if (
                inspect.isclass(value)
                and value.__module__ == module.__name__
                and not getattr(value, "_is_protocol", False)
                and all(hasattr(value, a) for a in ("send", "add_event_listener", "ready_state"))
            ):
                found[f"{module.__name__}.{name}"] = all(
                    hasattr(value, a) for a in ("buffered_amount", "when_drained")
                )
    assert "pyfect.socket.ws.WsWebSocket" in found
    assert "pyfect.http.asgi._web_socket.AsgiWebSocket" in found
    assert [name for name, drainable in found.items() if not drainable] == []
