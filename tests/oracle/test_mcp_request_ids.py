"""JSON-RPC request ids as Effect's ``McpSchema.RequestId`` reads them: a
string or a finite number. Anything else names no request (QA ai-workflow
MCP-1, MCP-2, MCP-5)."""

from __future__ import annotations

import json
from typing import Any

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.deferred import Deferred
from pyfect.http import request as R

from ._mcp import CLIENT_INFO, in_memory_http, stdio_harness

Wait = T.make("Wait", parameters=T.EMPTY_PARAMS, success=S.String)
_kit = K.make(Wait)


def _waiting(gate: Deferred[None]) -> fx.Effect[None, Any, Any]:
    handlers = _kit.to_layer(Wait.handler(lambda _, __: gate.wait().as_("done")))
    return M.register_toolkit(_kit).pipe(fx.provide(handlers))


def _call(id: object) -> dict[str, Any]:
    params: dict[str, object] = {"name": "Wait", "arguments": {}}
    return {"jsonrpc": "2.0", "id": id, "method": "tools/call", "params": params}


def _cancel(request_id: object) -> dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": "notifications/cancelled",
        "params": {"requestId": request_id},
    }


@testing.effect
def test_a_cancel_with_a_list_or_object_id_is_ignored_over_stdio():
    """A ``notifications/cancelled`` whose ``requestId`` is a list or an
    object cancels nothing and the server keeps reading."""
    gate = Deferred[None]()
    harness = yield from stdio_harness(P.v2025_11_25, None, _waiting(gate))
    yield from harness.initialize()
    yield from harness.send(_call(1))
    yield from harness.send(_cancel([1]))
    yield from harness.send(_cancel({"a": 1}))
    pong = yield from harness.send_request("ping", {}, id=2)
    assert pong == {"jsonrpc": "2.0", "id": 2, "result": {}}
    yield from gate.succeed(None)
    answered = yield from harness.response_to(1)
    assert answered["result"]["content"] == [{"type": "text", "text": "done"}]


@testing.effect
def test_a_boolean_cancel_id_does_not_cancel_request_one():
    """``requestId: true`` is no id: request ``1`` still gets its answer."""
    gate = Deferred[None]()
    harness = yield from stdio_harness(P.v2025_11_25, None, _waiting(gate))
    yield from harness.initialize()
    yield from harness.send(_call(1))
    yield from harness.send(_cancel(True))
    yield from harness.send_request("ping", {}, id=2)
    yield from gate.succeed(None)
    answered = yield from harness.response_to(1)
    assert answered["result"]["content"] == [{"type": "text", "text": "done"}]


@testing.effect
def test_a_fractional_request_id_is_answered_and_echoed():
    """A finite fractional id is a request id: answered with it."""
    harness = yield from stdio_harness(P.v2025_11_25)
    yield from harness.initialize()
    pong = yield from harness.send_request("ping", {}, id=6.5)
    assert pong == {"jsonrpc": "2.0", "id": 6.5, "result": {}}


@testing.effect
def test_a_boolean_request_id_is_an_invalid_request():
    harness = yield from stdio_harness(P.v2025_11_25)
    yield from harness.initialize()
    yield from harness.send({"jsonrpc": "2.0", "id": True, "method": "ping"})
    answer = yield from harness.receive()
    assert answer["id"] is None and answer["error"]["code"] == -32600


@testing.effect
def test_a_cancel_with_an_object_id_gets_202_over_http():
    http = yield from in_memory_http(
        M.layer_http(name="test-server", version="1.0.0", path="/mcp", protocols=(P.v2025_11_25,))
    )

    def post(body: object, headers: dict[str, str]) -> fx.Effect[Any, Any]:
        request = (
            R.post("http://localhost/mcp")
            .set_headers({"accept": "application/json, text/event-stream", **headers})
            .body_text(json.dumps(body), "application/json")
        )
        return http.execute(request)

    initialize = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {"protocolVersion": "2025-11-25", "capabilities": {}, "clientInfo": CLIENT_INFO},
    }
    session = (yield from post(initialize, {})).headers.get("mcp-session-id")
    assert session is not None
    headers = {"mcp-session-id": session, "mcp-protocol-version": "2025-11-25"}
    cancelled = yield from post(_cancel({"a": [1]}), headers)
    assert cancelled.status == 202
