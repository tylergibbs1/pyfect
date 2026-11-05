"""MCP Streamable HTTP sessions are bounded: by count, by idle time, and by
the size of the message that opens them. Any Origin-less peer can open a
session, so none of these may grow without limit."""

from __future__ import annotations

import json
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.errors import IllegalArgumentError
from pyfect.http import request as R
from pyfect.http.client import HttpClientService
from pyfect.http.response import HttpClientResponse
from pyfect.result import Err

URL = "http://localhost/mcp"
CLIENT_INFO = {"name": "client", "version": "1"}


def _initialize(**extra: object) -> dict[str, Any]:
    params = {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": CLIENT_INFO}
    return {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {**params, **extra}}


def _http(**options: Any) -> fx.Effect[HttpClientService[Any, Any], Any, Any]:
    from pyfect.http.router import in_memory_client

    app = M.layer_http(name="t", version="1", path="/mcp", protocols=(P.v2025_11_25,), **options)
    return in_memory_client(app)


def _post(
    http: HttpClientService[Any, Any], body: object, session: str | None = None
) -> fx.Effect[HttpClientResponse, Any]:
    headers = {"accept": "application/json, text/event-stream"}
    if session is not None:
        headers |= {"mcp-session-id": session, "mcp-protocol-version": "2025-11-25"}
    request = R.post(URL).set_headers(headers).body_text(json.dumps(body), "application/json")
    return http.execute(request)


def _ping(http: HttpClientService[Any, Any], session: str) -> fx.Effect[HttpClientResponse, Any]:
    return _post(http, {"jsonrpc": "2.0", "id": 2, "method": "ping"}, session)


@testing.effect
def test_sessions_are_capped_by_default():
    http = yield from _http()
    opened = 0
    for _ in range(1000):
        opened += (yield from _post(http, _initialize())).status == 200
    assert opened == 1000
    assert (yield from _post(http, _initialize())).status == 503


@testing.effect
def test_a_full_table_still_serves_its_sessions():
    http = yield from _http(max_sessions=2)
    first = (yield from _post(http, _initialize())).headers["mcp-session-id"]
    yield from _post(http, _initialize())
    assert (yield from _post(http, _initialize())).status == 503
    assert (yield from _ping(http, first)).status == 200


@testing.effect
def test_idle_sessions_expire():
    http = yield from _http(max_sessions=1)
    session = (yield from _post(http, _initialize())).headers["mcp-session-id"]
    yield from testing.adjust(29 * 60)
    assert (yield from _ping(http, session)).status == 200
    yield from testing.adjust(29 * 60)
    assert (yield from _ping(http, session)).status == 200  # each request renews it
    yield from testing.adjust(30 * 60 + 1)
    assert (yield from _ping(http, session)).status == 404
    # Its slot is free again.
    assert (yield from _post(http, _initialize())).status == 200


@testing.effect
def test_expired_sessions_free_their_slots_for_new_ones():
    http = yield from _http(max_sessions=1, session_idle_timeout=10)
    yield from _post(http, _initialize())
    assert (yield from _post(http, _initialize())).status == 503
    yield from testing.adjust(11)
    assert (yield from _post(http, _initialize())).status == 200


@testing.effect
def test_message_size_is_bounded_by_default():
    http = yield from _http()
    big = yield from _post(http, _initialize(pad="A" * (4 * 1024 * 1024)))
    assert big.status == 413
    small = yield from _post(http, _initialize(pad="A" * 1024))
    assert small.status == 200


@testing.effect
def test_message_size_is_configurable():
    http = yield from _http(max_message_bytes=2048)
    assert (yield from _post(http, _initialize(pad="A" * 4096))).status == 413
    assert (yield from _post(http, _initialize(pad="A" * 512))).status == 200


@testing.effect
def test_limits_are_validated():
    for options in (
        {"max_sessions": 0},
        {"session_idle_timeout": 0},
        {"session_idle_timeout": float("nan")},
        {"max_message_bytes": 0},
    ):
        result = yield from _http(**options).result()
        assert isinstance(result, Err), options
        assert isinstance(result.error, IllegalArgumentError), options
