"""(pyfect) Every server pyfect exports bounds what one peer can make it hold, by default.

A peer that opens a connection chooses how large a body, a message, a form or an unread
backlog is; a server whose default lets that grow without bound ships a way to exhaust it.
Each public function that builds an HTTP, WebSocket, socket or MCP server is found by its
return type and must have an entry here, whose probe reads the defaults it actually serves
with (no options given). Every limit must be finite and positive, and every WebSocket server
must decline ``permessage-deflate`` unless asked (an inflated message costs the peer a
thousandth of its size). A new server without an entry fails this test.
"""

from __future__ import annotations

import inspect
import math
import re
from collections.abc import Callable, Mapping

import pytest
from _pyfect_modules import modules

from pyfect.ai._mcp import sessions as mcp_sessions
from pyfect.ai._mcp import stdio as mcp_stdio
from pyfect.http import multipart
from pyfect.http.incoming_message import MaxBodySize
from pyfect.http.live_server._serve import MAX_HEAD_SIZE
from pyfect.socket import _connection

type Limits = Mapping[str, float | bool | None]
"""A limit's name and its default: a number of bytes or items, or, for a
``*_declined`` flag, whether the risky feature is off."""

_SERVER_TYPE = re.compile(
    r"^(Effect|Layer)\[\s*(HttpServer|HttpServerService|SocketServer|SocketServerService|McpServer)\b"
)


def _http_app() -> Limits:
    """What every HTTP server's requests are read under (``incoming_message``, ``multipart``)."""
    return {
        "body_bytes": MaxBodySize.default(),
        "multipart_parts": multipart.MaxParts.default(),
        "multipart_field_bytes": multipart.MaxFieldSize.default(),
    }


def _live() -> Limits:
    from pyfect.http import live_server

    websocket = live_server._websocket_config({})  # pyright: ignore[reportPrivateUsage]
    return {
        **_http_app(),
        "head_bytes": MAX_HEAD_SIZE,
        "unread_bytes_per_connection": _connection.HIGH_WATER_MARK,
        "ws_message_bytes": websocket.max_message_size,
        "ws_deflate_declined": websocket.per_message_deflate is None,
    }


def _no_app(*_: object) -> None:
    return None


def _uvicorn() -> Limits:
    from pyfect.http import uvicorn_server

    config = uvicorn_server._uvicorn(_no_app, {}).config  # pyright: ignore[reportPrivateUsage, reportArgumentType]
    return {
        **_http_app(),
        "head_bytes": config.h11_max_incomplete_event_size or 16 * 1024,  # h11's default
        "ws_message_bytes": config.ws_max_size,
        "ws_deflate_declined": not config.ws_per_message_deflate,
    }


def _hypercorn() -> Limits:
    from pyfect.http import hypercorn_server

    config = hypercorn_server._Hypercorn(_no_app, {}).config  # pyright: ignore[reportPrivateUsage, reportArgumentType]
    return {
        **_http_app(),
        "head_bytes": config.h11_max_incomplete_size,
        "ws_message_bytes": config.websocket_max_message_size,
        "unread_messages_per_connection": config.max_app_queue_size,
        # Declined by pyfect's own handshake (tests/test_hypercorn_server.py).
        "ws_deflate_declined": hypercorn_server.WSStream.handle.__module__
        == hypercorn_server.__name__,
    }


def _socket_tcp() -> Limits:
    return {"unread_bytes_per_connection": _connection.HIGH_WATER_MARK}


def _socket_web_socket() -> Limits:
    from pyfect.socket import _ws_server

    options = _ws_server._serve_options({})  # pyright: ignore[reportPrivateUsage]
    return {
        "ws_message_bytes": options["max_size"],
        "unread_frames_per_connection": options["max_queue"],
        "ws_deflate_declined": options["compression"] is None,
    }


def _mcp_http() -> Limits:
    from pyfect import byte_size

    return {
        "message_bytes": byte_size.from_input(mcp_sessions.DEFAULT_MAX_MESSAGE_BYTES),
        "initialize_bytes": byte_size.from_input(mcp_sessions.DEFAULT_MAX_INITIALIZE_BYTES),
        "sessions": mcp_sessions.DEFAULT_MAX_SESSIONS,
        "body_bytes": MaxBodySize.default(),
    }


def _mcp_stdio() -> Limits:
    return {"line_bytes": mcp_stdio.DEFAULT_MAX_BUFFER_SIZE}


def _mcp_rpc_protocol() -> Limits:
    # Served over an RPC ``ServerProtocol``: its transport's limits are the protocol's.
    return {}


SERVERS: dict[str, Callable[[], Limits]] = {
    "pyfect.http.live_server.make": _live,
    "pyfect.http.live_server.make_unix": _live,
    "pyfect.http.live_server.make_tls": _live,
    "pyfect.http.live_server.layer_server": _live,
    "pyfect.http.live_server.layer": _live,
    "pyfect.http.live_server.layer_test": _live,
    "pyfect.http.uvicorn_server.make": _uvicorn,
    "pyfect.http.uvicorn_server.layer_server": _uvicorn,
    "pyfect.http.uvicorn_server.layer": _uvicorn,
    "pyfect.http.uvicorn_server.layer_test": _uvicorn,
    "pyfect.http.hypercorn_server.make": _hypercorn,
    "pyfect.http.hypercorn_server.layer_server": _hypercorn,
    "pyfect.http.hypercorn_server.layer": _hypercorn,
    "pyfect.http.hypercorn_server.layer_test": _hypercorn,
    "pyfect.socket.server.make": _socket_tcp,
    "pyfect.socket.server.make_unix": _socket_tcp,
    "pyfect.socket.server.make_tls": _socket_tcp,
    "pyfect.socket.server.layer": _socket_tcp,
    "pyfect.socket.server.layer_tls": _socket_tcp,
    "pyfect.socket.server.make_web_socket": _socket_web_socket,
    "pyfect.socket.server.layer_web_socket": _socket_web_socket,
    "pyfect.ai.mcp_server.layer_http": _mcp_http,
    "pyfect.ai.mcp_server.layer_http_request_scoped": _mcp_http,
    "pyfect.ai.mcp_server.layer_stdio": _mcp_stdio,
    "pyfect.ai.mcp_server.layer_rpc_protocol": _mcp_rpc_protocol,
}


def _servers() -> set[str]:
    found: set[str] = set()
    for module in modules(public=True, skip_missing_extras=True):
        for name, value in vars(module).items():
            if name.startswith("_") or not inspect.isfunction(value):
                continue
            if value.__module__ != module.__name__:
                continue
            returns = value.__annotations__.get("return")
            if isinstance(returns, str) and _SERVER_TYPE.match(" ".join(returns.split())):
                found.add(f"{module.__name__}.{name}")
    return found


def test_every_server_has_its_default_limits_checked():
    found = _servers()
    assert found - SERVERS.keys() == set(), "a server without default limits checked here"
    assert SERVERS.keys() - found == set(), "an entry for a server that is gone"


@pytest.mark.parametrize("name", sorted(SERVERS))
def test_default_limits_are_finite(name: str):
    for limit, value in SERVERS[name]().items():
        if limit.endswith("_declined"):
            assert value is True, (name, limit)
        else:
            assert isinstance(value, int | float), (name, limit, value)
            assert not isinstance(value, bool), (name, limit)
            assert 0 < value < math.inf, (name, limit, value)
