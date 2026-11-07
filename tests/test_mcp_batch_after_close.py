"""A batch still being read when its session is deleted: the requests it
reaches afterwards are not served. In Effect each batch item is its own
RpcServer request, and one whose session is gone dies in
``clientMiddleware`` (``Mcp-Session-Id does not exist``) before its handler
runs."""

from __future__ import annotations

import json
from typing import Any

from oracle._mcp import CLIENT_INFO, in_memory_http

import pyfect as fx
from pyfect import layer, testing
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai._mcp.core import ToolEntry
from pyfect.context import Context
from pyfect.http import request as R
from pyfect.http.client import HttpClientService
from pyfect.http.response import HttpClientResponse

URL = "http://localhost/mcp"
ACCEPT = "application/json, text/event-stream"
_CALLS = 400


@testing.live
def test_requests_a_batch_reaches_after_its_session_closed_are_not_served():
    runs: list[object] = []

    def count(_: object) -> fx.Effect[MS.CallToolResult]:
        return fx.sync(lambda: runs.append(None)).as_({"content": []})

    def register(server: M.McpServerService) -> fx.Effect[None]:
        entry = ToolEntry(
            {"name": "count", "inputSchema": {"type": "object"}}, Context.empty(), count
        )
        return server.add_tool(entry)

    app = M.layer_http(
        name="test-server",
        version="1.0.0",
        path="/mcp",
        protocols=(P.v2025_03_26,),
        allow_session_termination=True,
    )
    registered = layer.effect_discard(M.McpServer().flat_map(register)).pipe(layer.provide(M.layer))
    http: HttpClientService[Any, Any] = yield from in_memory_http(layer.merge(app, registered))

    def post(body: object, headers: dict[str, str]) -> fx.Effect[Any]:
        request = (
            R.post(URL)
            .set_headers({"accept": ACCEPT, **headers})
            .body_text(json.dumps(body), "application/json")
        )
        return http.execute(request)

    params = {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": CLIENT_INFO}
    initialize = {"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": params}
    opened = yield from post(initialize, {})
    headers = {
        "mcp-session-id": opened.headers["mcp-session-id"],
        "mcp-protocol-version": "2025-03-26",
    }
    call: dict[str, Any] = {"name": "count", "arguments": {}}
    calls: list[dict[str, Any]] = [
        {"jsonrpc": "2.0", "id": index, "method": "tools/call", "params": call}
        for index in range(1, _CALLS + 1)
    ]

    def run() -> Any:
        batch = yield from post(calls, headers).fork()
        # With a budget of one step the batch's reader and its calls take
        # turns with this fiber, so the session ends partway through it.
        while len(runs) < 10:
            yield from fx.yield_now()
        deleted = yield from http.execute(R.make("DELETE", URL).set_headers(headers))
        assert deleted.status == 204
        response: HttpClientResponse = yield from batch.join()
        return (yield from response.text)

    text: str = yield from fx.gen(run).pipe(fx.provide_service(fx.MaxOpsBeforeYield, 1))
    body = [line for line in text.splitlines() if line.startswith(("[", "data: ["))][-1]
    replies = json.loads(body.removeprefix("data: "))
    served = [reply for reply in replies if "result" in reply]
    refused = [reply for reply in replies if "error" in reply]
    assert len(runs) == len(served) < _CALLS
    assert refused
    assert {reply["error"]["code"] for reply in refused} == {-32603}
