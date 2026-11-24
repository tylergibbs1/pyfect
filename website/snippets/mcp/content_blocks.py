import base64
from typing import TypedDict

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.ai import mcp_client, mcp_protocol, mcp_schema, mcp_server, tool, toolkit
from pyfect.http import live_server, router


class ChartParams(TypedDict):
    title: str


class Chart(TypedDict):
    title: str
    png: bytes


Render = tool.make(
    "render_chart",
    parameters=S.Struct(ChartParams),
    success=S.Struct(Chart, png=S.BytesFromBase64),
)
Charts = toolkit.make(Render)
Handlers = Charts.to_layer(
    Render.handler(lambda params, _: fx.succeed(Chart(title=params["title"], png=b"\x89PNG")))
)


# The mapper gets the decoded success and returns the call's MCP content blocks.
def chart_blocks(chart: Chart) -> list[mcp_schema.ContentBlock]:
    data = base64.b64encode(chart["png"]).decode("ascii")
    return [
        {"type": "text", "text": chart["title"]},
        {"type": "image", "data": data, "mimeType": "image/png"},
    ]


Registration = mcp_server.toolkit(
    Charts, content=[mcp_server.tool_content(Render, chart_blocks)]
).pipe(layer.provide(Handlers))
Server = mcp_server.layer_http(
    name="charts",
    version="1.0.0",
    path="/mcp",
    protocols=(mcp_protocol.v2025_11_25,),
    registrations=Registration,
)
Served = router.serve(Server, disable_logger=True, disable_listen_log=True)


@fx.fn
def program():
    client = yield from mcp_client.McpClient()
    [listed] = yield from client.list_tools()
    print("output schema", listed.get("outputSchema"))
    result = yield from client.call_tool(listed, {"title": "Sales"}, timeout="10 seconds")
    print("content", result["content"])
    print("structured", result.get("structuredContent"))


Client = mcp_client.layer_http(
    name="docs", version="1.0.0", url="/mcp", protocol=mcp_protocol.v2025_11_25
)

fx.run_main(
    program()
    .pipe(fx.provide(Client))
    .pipe(fx.provide(Served))
    .pipe(fx.provide(live_server.layer_test()))
)
