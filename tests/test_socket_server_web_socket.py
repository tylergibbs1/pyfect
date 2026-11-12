"""``socket.server.make_web_socket`` / ``layer_web_socket`` (Effect's
``NodeSocketServer.makeWebSocket`` / ``layerWebSocket``): a ``SocketServer`` whose
connections are WebSockets, with the native socket as ``WebSocket`` and the upgrade request
as ``IncomingMessage``. The DevTools client speaks WebSocket, so a DevTools server needs one
(FINDINGS-lantern #10, which found only the TCP, TLS and Unix servers)."""

from __future__ import annotations

import warnings
from typing import Any

from websockets.sync.client import connect

import pyfect as fx
from pyfect import devtools, effect
from pyfect.devtools import server as devtools_server
from pyfect.net.net_address import InetAddressV4, SocketAddress
from pyfect.queue import Queue
from pyfect.scope import scoped
from pyfect.socket import SocketService
from pyfect.socket import server as socket_server
from pyfect.socket import ws as ws_platform
from pyfect.socket.server import IncomingMessage, SocketServer, layer_web_socket, make_web_socket


def _port(address: SocketAddress) -> int:
    assert isinstance(address, InetAddressV4)
    return address.port


def test_a_devtools_server_on_it_receives_the_default_clients_spans() -> None:
    @fx.fn
    def program():
        srv = yield from SocketServer()
        received = yield from Queue[str, Any].unbounded()

        def handle(client: devtools_server.Client) -> fx.Effect[Any]:
            def forward(request: devtools_server.RequestWithoutPing) -> fx.Effect[Any]:
                if request["_tag"] == "Span":
                    return received.offer(request["name"])
                return fx.void

            return client.queue.take().flat_map(forward).forever()

        yield from devtools_server.run(handle).fork_scoped()
        url = f"ws://127.0.0.1:{_port(srv.address)}"
        yield from fx.void.with_span("lantern.allocate").pipe(fx.provide(devtools.layer(url)))
        return (yield from received.take().timeout("5 seconds"))

    provided = scoped(program()).pipe(fx.provide(layer_web_socket(0, "127.0.0.1")))
    assert fx.run_blocking(provided.or_die()) == "lantern.allocate"


def _receive_one(url: str) -> str | bytes:
    with connect(url) as client:
        return client.recv(timeout=5)


def test_handlers_get_the_upgrade_request_as_incoming_message() -> None:
    @fx.fn
    def program():
        srv = yield from make_web_socket(0, "127.0.0.1")

        def handler(socket: SocketService) -> fx.Effect[Any, Any, Any]:
            @fx.fn
            def body():
                request = yield from IncomingMessage()
                yield from socket.reader  # writes wait for the reader, as in Effect
                writer = yield from socket.writer
                yield from writer.write(request.path)

            return scoped(body())

        yield from srv.run(handler).fork_scoped()
        url = f"ws://127.0.0.1:{_port(srv.address)}/apps/lantern?x=1"
        return (yield from effect.blocking(lambda: _receive_one(url)))

    assert fx.run_blocking(scoped(program()).or_die()) == "/apps/lantern?x=1"


def test_the_websockets_module_names_are_deprecated() -> None:
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        ws_platform.make_server(0, "127.0.0.1")  # pyright: ignore[reportDeprecated]
        ws_platform.layer_server(0, "127.0.0.1")  # pyright: ignore[reportDeprecated]
    messages = [str(w.message) for w in caught if issubclass(w.category, DeprecationWarning)]
    assert messages == [
        "Use pyfect.socket.server.make_web_socket; ws.make_server is removed in 0.7.0",
        "Use pyfect.socket.server.layer_web_socket; ws.layer_server is removed in 0.7.0",
    ]


def test_every_node_socket_server_export_is_in_socket_server() -> None:
    """Effect's ``NodeSocketServer`` exports, by their pyfect names; the WebSocket ones used to
    live only in ``pyfect.socket.ws`` under other names, where nobody looked for them."""
    effect_exports = {
        "make": "make",
        "layer": "layer",
        "makeTls": "make_tls",
        "layerTls": "layer_tls",
        "makeWebSocket": "make_web_socket",
        "layerWebSocket": "layer_web_socket",
        "IncomingMessage": "IncomingMessage",
    }
    assert set(effect_exports.values()) <= set(socket_server.__all__)
