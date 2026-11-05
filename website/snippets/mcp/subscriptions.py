import json
from typing import Any

import pyfect as fx
from pyfect.ai import mcp_protocol, mcp_server
from pyfect.http import HttpClient, live_server, router
from pyfect.http import request as R

METADATA: dict[str, Any] = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}
Server = mcp_server.layer_http(
    name="watched",
    version="1.0.0",
    path="/mcp",
    protocols=(mcp_protocol.v2026_07_28,),
)
Served = router.serve(Server, disable_logger=True, disable_listen_log=True)


def tool(name: str) -> mcp_server.ToolEntry:
    return mcp_server.ToolEntry(
        {"name": name, "inputSchema": {"type": "object"}},
        fx.Context.empty(),
        lambda _: fx.succeed({"content": []}),
    )


listen = (
    R.post("/mcp")
    .body_text(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "tools-watch",
                "method": "subscriptions/listen",
                "params": {"notifications": {"toolsListChanged": True}, "_meta": METADATA},
            }
        ),
        "application/json",
    )
    .set_headers(
        {
            "accept": "application/json, text/event-stream",
            "mcp-protocol-version": "2026-07-28",
            "mcp-method": "subscriptions/listen",
        }
    )
)


# The stream's events, as they arrive: its acknowledgment, then the changes it asked for.
@fx.fn
def program():
    server = yield from mcp_server.McpServer()
    yield from server.add_tool(tool("first"))
    client = yield from HttpClient()
    response = yield from client.execute(listen)
    pull = yield from response.stream.to_pull()

    @fx.fn
    def event():
        chunks = yield from pull
        text = b"".join(chunks).decode()
        message = json.loads(text.removeprefix("data: "))
        print(message["method"], message["params"].get("notifications", ""))

    yield from event()
    yield from server.add_tool(tool("second"))
    yield from event()


fx.run_main(
    program().pipe(fx.scoped).pipe(fx.provide(Served)).pipe(fx.provide(live_server.layer_test()))
)
