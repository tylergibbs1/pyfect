from typing import Never, TypedDict, cast

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.ai import mcp_client, mcp_protocol, mcp_schema, mcp_server, tool, toolkit
from pyfect.http import live_server, router


class AddParams(TypedDict):
    a: int
    b: int


class Sum(TypedDict):
    total: int


Add = tool.make("add", parameters=S.Struct(AddParams), success=S.Struct(Sum))
Erase = tool.make("erase", success=S.String)
Tools = toolkit.make(Add.annotate(tool.Readonly, True), Erase)
Handlers = Tools.to_layer(
    Add.handler(lambda params, _: fx.succeed(Sum(total=params["a"] + params["b"]))),
    Erase.handler(lambda _, __: fx.succeed("erased")),
)
Server = mcp_server.layer_http(
    name="calculator",
    version="1.0.0",
    path="/mcp",
    protocols=(mcp_protocol.v2026_07_28,),
    registrations=mcp_server.toolkit(Tools).pipe(layer.provide(Handlers)),
)
Served = router.serve(Server, disable_logger=True, disable_listen_log=True)


# Ask for approval of every tool that the server does not call read-only.
def approve_writes(
    remote: mcp_client.RemoteTool[mcp_schema.CallToolResult, Never],
    descriptor: mcp_schema.Tool,
) -> mcp_client.RemoteTool[mcp_schema.CallToolResult, Never]:
    hints = descriptor.get("annotations", {})
    return remote.set_needs_approval(hints.get("readOnlyHint") is not True)


@fx.fn
def program():
    client = yield from mcp_client.McpClient()
    print("capabilities", client.capabilities)
    approved = yield from client.list_tools()
    kit = yield from mcp_client.toolkit(
        client,
        "calc__",
        tools=approved,
        result_mode="complete",
        failure_mode="return",
        timeout="10 seconds",
        transform_tool=approve_writes,
    )
    approval = {name: t.needs_approval for name, t in kit.tools.items()}
    assert approval == {"calc__add": False, "calc__erase": True}
    print("approval", approval)
    results = yield from kit.handle("calc__add", {"a": 2, "b": 3})
    [output] = yield from results.run_collect()
    # The complete result, as the server sent it (with its 2026-07-28 ``_meta``).
    result = cast("mcp_schema.CallToolResult", output.result)
    assert result.get("isError") is False
    assert result["content"] == [{"type": "text", "text": '{"total":5}'}]
    assert result.get("structuredContent") == {"total": 5}
    print("model sees", output.model_output)


Client = mcp_client.layer_http(
    name="docs", version="1.0.0", url="/mcp", protocol=mcp_protocol.v2026_07_28
)

fx.run_main(
    program()
    .pipe(fx.provide(Client))
    .pipe(fx.provide(Served))
    .pipe(fx.provide(live_server.layer_test()))
)
