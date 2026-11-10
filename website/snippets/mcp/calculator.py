from typing import TypedDict

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.ai import mcp_client, mcp_protocol, mcp_server, tool, toolkit
from pyfect.http import live_server, router


class AddParams(TypedDict):
    a: int
    b: int


class Sum(TypedDict):
    total: int


Add = tool.make(
    "add", description="Add two integers", parameters=S.Struct(AddParams), success=S.Struct(Sum)
).annotate(tool.Readonly, True)
Calculator = toolkit.make(Add)
Handlers = Calculator.to_layer(
    Add.handler(lambda params, _: fx.succeed(Sum(total=params["a"] + params["b"])))
)

# The server: the toolkit, served over MCP's Streamable HTTP transport at /mcp.
Server = mcp_server.layer_http(
    name="calculator",
    version="1.0.0",
    path="/mcp",
    protocols=(mcp_protocol.v2025_11_25, mcp_protocol.v2026_07_28),
    registrations=mcp_server.toolkit(Calculator).pipe(layer.provide(Handlers)),
)
Served = router.serve(Server, disable_logger=True, disable_listen_log=True)


# The client: connects, lists the server's tools and calls one.
@fx.fn
def program():
    client = yield from mcp_client.McpClient()
    print("server", client.server_info)
    tools = yield from client.list_tools()
    print("tools", [(t["name"], t.get("description")) for t in tools])
    total = yield from client.call_tool(tools[0], {"a": 2, "b": 3}, schema=S.Struct(Sum))
    print("add", total)


Client = mcp_client.layer_http(
    name="docs", version="1.0.0", url="/mcp", protocol=mcp_protocol.v2025_11_25
)

# layer_test: a server on a free local port, and an HttpClient sending to it.
fx.run_main(
    program()
    .pipe(fx.provide(Client))
    .pipe(fx.provide(Served))
    .pipe(fx.provide(live_server.layer_test()))
)
