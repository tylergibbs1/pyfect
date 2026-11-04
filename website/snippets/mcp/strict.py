from typing import TypedDict

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.ai import mcp_client, mcp_protocol, mcp_server, tool, toolkit
from pyfect.http import live_server, router


class Greeting(TypedDict):
    name: str


# A strict tool advertises a closed input schema and refuses unknown keys
# before its handler runs.
Greet = tool.make("greet", parameters=S.Struct(Greeting), success=S.String).annotate(
    tool.Strict, True
)
Greeter = toolkit.make(Greet)
Handlers = Greeter.to_layer(Greet.handler(lambda params, _: fx.succeed(f"hi {params['name']}")))

Server = layer.merge(
    mcp_server.layer_http(
        name="greeter", version="1.0.0", path="/mcp", protocols=(mcp_protocol.v2025_11_25,)
    ),
    mcp_server.toolkit(Greeter).pipe(layer.provide(Handlers)),
)
Served = router.serve(Server, disable_logger=True, disable_listen_log=True)


@fx.fn
def program():
    client = yield from mcp_client.McpClient()
    [greet] = yield from client.list_tools()
    print("additionalProperties", greet["inputSchema"].get("additionalProperties"))
    print((yield from client.call_tool(greet, {"name": "Ada"}))["content"])
    # A misspelt key is refused; on 2025-11-25 the refusal is an error result.
    typo = yield from client.call_tool(greet, {"name": "Ada", "nmae": "Ada"})
    assert typo.get("isError") is True
    [content] = typo["content"]
    print(content.get("text"))


Client = mcp_client.layer_http(
    name="docs", version="1.0.0", url="/mcp", protocol=mcp_protocol.v2025_11_25
)

fx.run_main(
    program()
    .pipe(fx.provide(Client))
    .pipe(fx.provide(Served))
    .pipe(fx.provide(live_server.layer_test()))
)
