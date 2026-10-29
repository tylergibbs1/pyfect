"""An MCP server exposing a toolkit over stdio. An MCP client starts it as
a subprocess and talks newline-delimited JSON-RPC on its standard input
and output; it stops when its input ends.

Try it with: uv run examples/mcp_server.py < /dev/null"""

from typing import TypedDict

import pyfect as fx
from pyfect import layer, stdio
from pyfect import schema as S
from pyfect.ai import mcp_protocol, mcp_server, tool, toolkit


class AddParams(TypedDict):
    a: int
    b: int


class Sum(TypedDict):
    total: int


class ShoutParams(TypedDict):
    text: str


Add = tool.make(
    "add",
    description="Add two integers",
    parameters=S.Struct(AddParams),
    success=S.Struct(Sum),
).annotate(tool.Readonly, True)

Shout = tool.make(
    "shout",
    description="Upper-case some text",
    parameters=S.Struct(ShoutParams),
    success=S.String,
)

Calculator = toolkit.make(Add, Shout)

handlers = Calculator.to_layer(
    Add.handler(lambda params, _: fx.succeed(Sum(total=params["a"] + params["b"]))),
    Shout.handler(lambda params, _: fx.succeed(params["text"].upper())),
)

served = layer.merge(mcp_server.layer, mcp_server.toolkit(Calculator).pipe(layer.provide(handlers)))


@fx.fn
def main():
    io = yield from stdio.Stdio()
    if (yield from io.stdin_is_terminal):
        return print("start me from an MCP client: my standard input is its connection")
    return (
        yield from mcp_server.run_stdio(
            name="calculator",
            version="1.0.0",
            protocols=(mcp_protocol.v2025_11_25, mcp_protocol.v2026_07_28),
            instructions="Use add for sums and shout for emphasis.",
        )
    )


if __name__ == "__main__":
    fx.run_main(main().pipe(fx.provide(served)).pipe(fx.provide(stdio.layer)))
