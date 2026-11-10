from typing import Any

import pyfect as fx
from pyfect import layer
from pyfect.ai import mcp_protocol, mcp_server
from pyfect.rpc import serialization, server

METADATA: dict[str, Any] = {
    "io.modelcontextprotocol/protocolVersion": "2026-07-28",
    "io.modelcontextprotocol/clientCapabilities": {},
    "io.modelcontextprotocol/clientInfo": {"name": "client", "version": "1.0.0"},
}


# A transport that queues what the server sends and cannot write to a client unasked.
@fx.fn
def queue_transport(sent: fx.Queue[Any], ready: fx.Deferred[server.WriteRequest]):
    disconnects = fx.Queue[int]()

    def parts(write: server.WriteRequest) -> fx.Effect[server.ProtocolParts]:
        return ready.succeed(write).as_(
            server.ProtocolParts(
                disconnects=disconnects,
                send=lambda _client, message: sent.offer(message).as_void(),
                end=lambda _client: fx.void,
                supports_ack=False,
                supports_span_propagation=False,
                codec_for=serialization.json.codec_for,
                supports_notifications=False,
            )
        )

    return (yield from server.with_run(parts))


def tool(name: str) -> mcp_server.ToolEntry:
    return mcp_server.ToolEntry(
        {"name": name, "inputSchema": {"type": "object"}},
        fx.Context.empty(),
        lambda _: fx.succeed({"content": []}),
    )


@fx.fn
def program():
    sent = fx.Queue[Any]()
    ready = fx.Deferred[server.WriteRequest]()
    transport = yield from queue_transport(sent, ready)
    served = mcp_server.layer_rpc_protocol(
        name="custom", version="1.0.0", protocols=(mcp_protocol.v2026_07_28,)
    ).pipe(layer.provide(layer.succeed(server.ServerProtocol, transport)))
    context = yield from served.build()
    yield from context.get(mcp_server.McpServer).add_tool(tool("search"))
    write = yield from ready.wait()
    listen = {"notifications": {"toolsListChanged": True}}
    for id, method, params in [(1, "server/discover", {}), (2, "subscriptions/listen", listen)]:
        payload = {"_meta": METADATA, **params}
        yield from write(
            0, {"_tag": "Request", "id": id, "tag": method, "payload": payload, "headers": []}
        )
        exit = (yield from sent.take())["exit"]
        if exit["_tag"] == "Success":
            print(method, exit["value"]["capabilities"]["tools"])
        else:
            print(method, exit["cause"][0]["error"]["message"])


fx.run_main(fx.scoped(program()))
