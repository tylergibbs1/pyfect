"""The longest WebSocket message: the ``websockets`` client takes what
pyfect's servers take (``DEFAULT_MAX_MESSAGE_SIZE``, 16 MiB, uvicorn's
``ws_max_size``), and each limit can be set."""

from __future__ import annotations

import inspect
from typing import Any

import pytest

pytest.importorskip("websockets")

import pyfect as fx
from pyfect import layer
from pyfect.http import live_server, router, server_response, uvicorn_server
from pyfect.http.server import HttpServer
from pyfect.http.server_request import HttpServerRequest
from pyfect.net.net_address import InetAddressV4
from pyfect.scope import scoped
from pyfect.socket import Socket, SocketCloseError, SocketError
from pyfect.socket import ws as ws_platform
from pyfect.socket._web_socket import DEFAULT_MAX_MESSAGE_SIZE

_SIZE = 2 * 1024 * 1024


@fx.fn
def _send_big():
    """Send one ``_SIZE``-byte message, then wait for the client to close."""
    request = yield from HttpServerRequest()
    sock = yield from request.upgrade

    @fx.fn
    def run():
        reader = yield from sock.reader
        writer = yield from sock.writer
        yield from writer.write(b"x" * _SIZE)
        while True:
            yield from reader.pull

    yield from scoped(run()).ignore()
    return server_response.empty()


def _first_message(**client_options: Any) -> object:
    """What the client's first pull gives, or its failure."""

    @fx.fn
    def pull():
        sock = yield from Socket()
        reader = yield from sock.reader
        chunks = yield from reader.pull
        return sum(map(len, chunks))

    def client(server: Any) -> fx.Layer[Socket]:
        address = server.address
        assert isinstance(address, InetAddressV4)
        url = f"ws://127.0.0.1:{address.port}/ws"
        return ws_platform.layer_web_socket(url, **client_options)

    socket_layer = layer.unwrap(HttpServer().map(client))
    routes = router.add("GET", "/ws", scoped(_send_big()))
    program = (
        scoped(pull())
        .match(on_failure=lambda e: e, on_success=lambda n: n)
        .pipe(fx.provide(socket_layer))
        .pipe(fx.provide(router.serve(routes, disable_logger=True)))
    )
    provided = scoped(program).pipe(fx.provide(live_server.layer_test()))
    return fx.run_sync(provided.timeout(10).or_die())


def test_the_client_takes_a_message_over_1_mib_by_default() -> None:
    assert _first_message() == _SIZE


def test_the_client_closes_past_its_max_message_size() -> None:
    error = _first_message(max_message_size=1024)
    assert isinstance(error, SocketError)
    assert isinstance(error.reason, SocketCloseError)
    # websockets fails the connection with 1009 and reports it as 1006.
    assert error.reason.code in (1006, 1009)


async def _no_app(_scope: Any, _receive: Any, _send: Any) -> None:
    pass


def _default(function: Any, name: str) -> object:
    return inspect.signature(function).parameters[name].default


def test_every_websocket_endpoint_defaults_to_the_same_limit() -> None:
    assert DEFAULT_MAX_MESSAGE_SIZE == 16 * 1024 * 1024
    assert _default(ws_platform.WsWebSocket.connect, "max_message_size") == DEFAULT_MAX_MESSAGE_SIZE
    assert _default(ws_platform.layer_web_socket, "max_message_size") == DEFAULT_MAX_MESSAGE_SIZE
    assert (
        _default(ws_platform.web_socket_constructor, "max_message_size") == DEFAULT_MAX_MESSAGE_SIZE
    )
    config = uvicorn_server._uvicorn(_no_app, {}).config  # pyright: ignore[reportPrivateUsage, reportArgumentType]
    assert config.ws_max_size == DEFAULT_MAX_MESSAGE_SIZE
