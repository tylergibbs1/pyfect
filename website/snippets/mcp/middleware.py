from typing import Any

import pyfect as fx
from pyfect import layer
from pyfect import schema as S
from pyfect.ai import mcp_protocol, mcp_server, mcp_test, tool, toolkit
from pyfect.context import Tag


class CurrentUser(Tag[str], key="app/CurrentUser"):
    pass


# Middleware provides the user to the handlers inside it; the visibility reads it.
user = {"name": "guest"}
Auth = mcp_server.middleware(
    lambda effect, _: effect.pipe(fx.provide_service(CurrentUser, user["name"])),
    provides=CurrentUser,
)
AdminOnly = mcp_server.visibility(lambda _: CurrentUser().map(lambda name: name == "admin"))

WhoAmI = tool.make("who_am_i", success=S.String, dependencies=[CurrentUser])
Admin = toolkit.make(WhoAmI)
Handlers = Admin.to_layer(WhoAmI.handler(lambda _, __: CurrentUser()))

# The visibility runs inside Auth, so Auth's user is what it checks.
Registrations = (
    mcp_server.toolkit(Admin)
    .pipe(layer.provide(AdminOnly.combine(Auth).layer))
    .pipe(layer.provide(Handlers))
)


@fx.fn
def program():
    client = yield from mcp_test.make_client(Registrations, protocols=(mcp_protocol.v2025_11_25,))
    for name in ("guest", "admin"):
        user["name"] = name
        tools = yield from client.list_tools()
        called: Any = yield from client.call_tool({"name": "who_am_i"}).match(
            on_failure=lambda error: error.message,
            on_success=lambda result: result["content"][0],
        )
        print(name, [t["name"] for t in tools["tools"]], called)


fx.run_main(program().pipe(fx.scoped))
