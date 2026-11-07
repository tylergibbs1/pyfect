"""A socket that cannot open keeps where it was going and why, as ``target``
and ``cause``; its message is Effect's whatever they are."""

from __future__ import annotations

import socket

import pytest

import pyfect as fx
from pyfect import socket as pyfect_socket
from pyfect.scope import scoped
from pyfect.socket import (
    Socket,
    SocketError,
    SocketOpenError,
    SocketService,
    make_net,
    make_tls,
    make_unix,
    make_web_socket,
    ws,
)

pytest.importorskip("websockets")


def _free_port() -> int:
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        return probe.getsockname()[1]


def _open_failure(make: fx.Effect[SocketService] | SocketService) -> SocketError:
    @fx.fn
    def pull(sock: SocketService):
        reader = yield from sock.reader
        return (yield from reader.pull)

    opened = make if isinstance(make, fx.Effect) else fx.succeed(make)
    error = fx.run_blocking(scoped(opened.flat_map(pull)).flip().timeout("10 seconds").or_die())
    assert isinstance(error, SocketError)
    assert isinstance(error.reason, SocketOpenError)
    return error


def _reason(error: SocketError) -> SocketOpenError:
    assert isinstance(error.reason, SocketOpenError)
    return error.reason


def test_a_refused_web_socket_keeps_the_url_and_the_refusal() -> None:
    url = f"ws://127.0.0.1:{_free_port()}/rpc"
    error = _open_failure(Socket().pipe(fx.provide(ws.layer_web_socket(url))))
    assert error.message == "An error occurred during Open"
    assert str(error) == error.message
    assert _reason(error).target == url


def test_a_refused_tcp_socket_keeps_the_address_and_the_refusal() -> None:
    port = _free_port()
    reason = _reason(_open_failure(make_net(port, "127.0.0.1")))
    assert reason.target == f"127.0.0.1:{port}"
    assert isinstance(reason.cause, ConnectionRefusedError)


def test_an_open_timeout_keeps_the_target() -> None:
    # A listener that never answers the upgrade: the WebSocket never opens.
    with socket.socket() as silent:
        silent.bind(("127.0.0.1", 0))
        silent.listen()
        url = f"ws://127.0.0.1:{silent.getsockname()[1]}/rpc"
        layer = ws.layer_web_socket(url, open_timeout="200 millis")
        error = _open_failure(Socket().pipe(fx.provide(layer)))
    assert _reason(error).kind == "Timeout"
    assert error.message == 'timeout waiting for "open"'
    assert _reason(error).target == url


def test_the_message_is_effects_whatever_the_target_and_cause() -> None:
    for target in (None, "ws://x"):
        for cause in (None, OSError("no route")):
            assert SocketOpenError("Unknown", cause, target).message == (
                "An error occurred during Open"
            )
            assert SocketOpenError("Timeout", cause, target).message == (
                'timeout waiting for "open"'
            )


def _refused_url() -> str:
    return f"ws://127.0.0.1:{_free_port()}/rpc"


type _Client = tuple[fx.Effect[SocketService] | SocketService, str]


def _net() -> _Client:
    port = _free_port()
    return make_net(port, "127.0.0.1"), f"127.0.0.1:{port}"


def _tls() -> _Client:
    port = _free_port()
    return make_tls(port, "127.0.0.1"), f"127.0.0.1:{port}"


def _unix() -> _Client:
    return make_unix("/nonexistent/pyfect.sock"), "/nonexistent/pyfect.sock"


def _web_socket() -> _Client:
    url = _refused_url()
    return make_web_socket(url).pipe(fx.provide(ws.layer_web_socket_constructor)), url


# Every client constructor in pyfect.socket: one that cannot open, and the
# target its error must name. The others wrap one of these.
_CLIENTS = {"make_net": _net, "make_tls": _tls, "make_unix": _unix, "make_web_socket": _web_socket}
_WRAPPERS = {
    "make",
    "make_channel",
    "make_net_channel",
    "make_tls_channel",
    "make_web_socket_channel",
    "layer_net",
    "layer_tls",
    "layer_web_socket",
}


def test_every_client_constructor_is_covered() -> None:
    constructors = {n for n in pyfect_socket.__all__ if n.startswith(("make", "layer_"))}
    assert constructors == set(_CLIENTS) | _WRAPPERS


@pytest.mark.parametrize("name", sorted(_CLIENTS))
def test_a_client_that_cannot_open_keeps_its_target(name: str) -> None:
    make, target = _CLIENTS[name]()
    assert _reason(_open_failure(make)).target == target
