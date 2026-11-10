from typing import Never, TypedDict

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.ai import mcp_client, mcp_protocol, mcp_schema, mcp_server, tool, toolkit
from pyfect.ai.mcp_client_error import MCP_CLIENT_ERROR, McpClientError
from pyfect.http import live_server, router
from pyfect.schema import getter as G
from pyfect.schema import transformation as T


class CountryParams(TypedDict):
    code: str


Country = tool.make(
    "country",
    parameters=S.Struct(CountryParams),
    success=S.String,
    failure=S.String,
    failure_mode="return",
)
Tools = toolkit.make(Country)
Handlers = Tools.to_layer(
    Country.handler(lambda params, _: fx.fail(f"no country has the code {params['code']!r}"))
)
Server = mcp_server.layer_http(
    name="atlas",
    version="1.0.0",
    path="/mcp",
    protocols=(mcp_protocol.v2026_07_28,),
    registrations=mcp_server.toolkit(Tools).pipe(layer.provide(Handlers)),
)
Served = router.serve(Server, disable_logger=True, disable_listen_log=True)

# The model sees a failure as its encoding by the tool's failure schema. This one
# encodes an McpClientError as its message, which holds the tool's own text; the
# application still gets the McpClientError.
PlainText = S.String.pipe(
    S.decode_to(
        S.to_type(MCP_CLIENT_ERROR),
        T.Transformation(
            decode=G.forbidden(lambda _: "a plain-text failure cannot be decoded"),
            encode=G.transform(lambda error: error.message),
        ),
    )
)


def plain_failures(
    remote: mcp_client.RemoteTool[str, Never], _: mcp_schema.Tool
) -> mcp_client.RemoteTool[str, Never]:
    return remote.set_failure(PlainText)


@fx.fn
def program():
    client = yield from mcp_client.McpClient()
    kit = yield from mcp_client.toolkit(
        client,
        "atlas__",
        failure_mode="return",
        timeout="10 seconds",
        transform_tool=plain_failures,
    )
    results = yield from kit.handle("atlas__country", {"code": "XX"})
    [output] = yield from results.run_collect()
    assert output.is_failure
    assert isinstance(output.result, McpClientError)
    print("model sees", repr(output.encoded_result))


Client = mcp_client.layer_http(
    name="docs", version="1.0.0", url="/mcp", protocol=mcp_protocol.v2026_07_28
)

fx.run_main(
    program()
    .pipe(fx.provide(Client))
    .pipe(fx.provide(Served))
    .pipe(fx.provide(live_server.layer_test()))
)
