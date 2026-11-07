import json
from typing import Any

import pyfect as fx
from pyfect.ai import mcp_protocol, mcp_server
from pyfect.http import HttpClient, live_server, router, server_response
from pyfect.http import request as R

URI = "note://today"
note = {"text": "draft"}

Server = mcp_server.layer_http(
    name="notes",
    version="1.0.0",
    path="/mcp",
    protocols=(mcp_protocol.v2026_07_28,),
)
Note = mcp_server.resource(uri=URI, name="today", content=fx.sync(lambda: note["text"]))


# The route takes the McpServer when the layer builds, not per request, so
# `provide_merge(Server)` below gives it the server built on the same router.
@fx.fn
def add_routes(routes: router.HttpRouterService):
    server = yield from mcp_server.McpServer()

    @fx.fn
    def save():
        note["text"] = "final"
        yield from server.notify("notifications/resources/updated", {"uri": URI})
        return (yield from server_response.json({"saved": True}))

    yield from routes.add("POST", "/notes", save())


Routes = router.use(add_routes).pipe(fx.layer.provide_merge(Server))
Served = router.serve(fx.layer.merge(Routes, Note), disable_logger=True, disable_listen_log=True)

METADATA: dict[str, Any] = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
}
listen = (
    R.post("/mcp")
    .body_text(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": "note-watch",
                "method": "subscriptions/listen",
                "params": {"notifications": {"resourceSubscriptions": [URI]}, "_meta": METADATA},
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


@fx.fn
def program():
    client = yield from HttpClient()
    response = yield from client.execute(listen)
    pull = yield from response.stream.to_pull()

    @fx.fn
    def event():
        chunks = yield from pull
        message = json.loads(b"".join(chunks).decode().removeprefix("data: "))
        params = message["params"]
        print(message["method"], params.get("uri", params.get("notifications")))

    yield from event()
    yield from client.execute(R.post("/notes"))
    yield from event()


fx.run_main(
    program().pipe(fx.scoped).pipe(fx.provide(Served)).pipe(fx.provide(live_server.layer_test()))
)
