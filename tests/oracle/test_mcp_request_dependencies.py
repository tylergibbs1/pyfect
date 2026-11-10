"""Ports of Effect's ``test/ai/McpServer/RequestDependencies.test.ts``: MCP
middleware providing a request's services, provided locally (``.layer``),
globally (``.layer_global``) and combined (``.combine``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, TypedDict, cast

import pyfect as fx
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai import mcp_test
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.context import Tag
from pyfect.layer import provide

from ._mcp import stdio_harness

PROTOCOLS = (P.v2025_11_25,)


class CurrentUser(Tag[str], key="test/CurrentUser"):
    pass


class Tenant(Tag[str], key="test/Tenant"):
    pass


@dataclass(eq=False)
class Unauthorized(MS.McpError):
    _tag: ClassVar[str] = "Unauthorized"
    CODE: ClassVar[int] = -32001


WhoAmI = T.make("WhoAmI", success=S.String, dependencies=[CurrentUser])
WHO_AM_I = K.make(WhoAmI)
WHO_AM_I_HANDLERS = WHO_AM_I.to_layer(WhoAmI.handler(lambda _, __: CurrentUser()))

TENANT = M.middleware(
    lambda effect, _: effect.pipe(fx.provide_service(Tenant, "acme")), provides=Tenant
)
AUTH = M.middleware(
    lambda effect, _: Tenant().flat_map(
        lambda tenant: effect.pipe(fx.provide_service(CurrentUser, f"alice@{tenant}"))
    ),
    provides=CurrentUser,
)
AUDIT = M.middleware(lambda effect, _: effect)


def _recording(calls: list[str], name: str) -> M.Middleware:
    return M.middleware(lambda effect, _: fx.sync(lambda: calls.append(name)).and_then(effect))


@testing.effect
def test_provides_declared_dependencies_from_middleware_over_registration_time_values():
    """McpServer request-level dependencies / provides declared dependencies from middleware over registration-time values"""  # noqa: E501
    auth = M.middleware(
        lambda effect, _: effect.pipe(fx.provide_service(CurrentUser, "request")),
        provides=CurrentUser,
    )
    registrations = (
        M.toolkit(WHO_AM_I)
        .pipe(provide(auth.layer))
        .pipe(provide(WHO_AM_I_HANDLERS))
        .pipe(provide(layer.succeed(CurrentUser, "registration")))
    )
    client = yield from mcp_test.make_client(registrations, protocols=PROTOCOLS)

    result = yield from client.call_tool({"name": "WhoAmI", "arguments": {}})

    assert result["content"] == [{"type": "text", "text": "request"}]


@testing.effect
def test_sends_middleware_failures_as_json_rpc_errors():
    """McpServer request-level dependencies / sends middleware failures as JSON-RPC errors"""
    reject = M.middleware(lambda _, __: fx.fail(Unauthorized("Unauthorized")), provides=CurrentUser)
    registrations = M.toolkit(WHO_AM_I).pipe(provide(reject.layer)).pipe(provide(WHO_AM_I_HANDLERS))
    harness = yield from stdio_harness(P.v2025_11_25, layer=registrations)
    yield from harness.initialize()

    response = yield from harness.send_request("tools/call", {"name": "WhoAmI", "arguments": {}})

    assert response["error"] == {"code": -32001, "message": "Unauthorized"}


@testing.effect
def test_fails_calls_when_a_visibility_reads_a_service_from_middleware_provided_inside_it():
    """McpServer request-level dependencies / fails calls when a visibility reads a service from middleware provided inside it"""  # noqa: E501
    auth = M.middleware(
        lambda effect, _: effect.pipe(fx.provide_service(CurrentUser, "admin")),
        provides=CurrentUser,
    )
    admin_only = M.visibility(lambda _: CurrentUser().map(lambda user: user == "admin"))
    search = T.make("Search", success=S.String)
    kit = K.make(search)
    # The visibility's ``CurrentUser`` is left unmet: the types reject this order too.
    registrations: Any = (
        M.toolkit(kit)
        .pipe(provide(auth.layer))
        .pipe(provide(admin_only.layer))
        .pipe(provide(kit.to_layer(search.handler(lambda _, __: fx.succeed("found")))))
    )
    harness = yield from stdio_harness(P.v2025_11_25, layer=registrations)
    yield from harness.initialize()

    response = yield from harness.send_request("tools/call", {"name": "Search", "arguments": {}})

    assert response["error"] == {"code": -32603, "message": "Internal error"}


@testing.effect
def test_installs_only_its_own_middleware_globally():
    """McpServer request-level dependencies / installs only its own middleware globally"""
    calls: list[str] = []
    local = _recording(calls, "local")
    global_ = M.middleware(
        lambda effect, _: fx.sync(lambda: calls.append("global")).and_then(effect), global_=True
    )
    # Local is provided around the global middleware, but runs only for its registration.
    registrations = layer.merge(
        layer.merge(
            M.resource(uri="test://local", name="local", content=fx.succeed("local")), global_
        ).pipe(provide(local.layer)),
        M.resource(uri="test://other", name="other", content=fx.succeed("other")),
    )
    client = yield from mcp_test.make_client(registrations, protocols=PROTOCOLS)

    yield from client.read_resource({"uri": "test://local"})
    local_calls = calls[:]
    calls.clear()
    yield from client.read_resource({"uri": "test://other"})

    assert local_calls == ["global", "local"]
    assert calls == ["global"]


@testing.effect
def test_runs_middleware_provided_both_locally_and_globally_once():
    """McpServer request-level dependencies / runs middleware provided both locally and globally once"""  # noqa: E501
    calls: list[str] = []
    count = _recording(calls, "count")
    registrations = layer.merge(
        M.resource(uri="test://counted", name="counted", content=fx.succeed("counted")),
        count.layer_global,
    ).pipe(provide(count.layer))
    client = yield from mcp_test.make_client(registrations, protocols=PROTOCOLS)

    yield from client.read_resource({"uri": "test://counted"})

    assert calls == ["count"]


@testing.effect
def test_runs_middleware_provided_outside_a_combined_middleware_outside_all_of_it():
    """McpServer request-level dependencies / runs middleware provided outside a combined middleware outside all of it"""  # noqa: E501
    registrations = (
        M.toolkit(WHO_AM_I)
        .pipe(provide(AUDIT.combine(AUTH).layer))
        .pipe(provide(TENANT.layer))
        .pipe(provide(WHO_AM_I_HANDLERS))
    )
    client = yield from mcp_test.make_client(registrations, protocols=PROTOCOLS)

    result = yield from client.call_tool({"name": "WhoAmI", "arguments": {}})

    assert result["content"] == [{"type": "text", "text": "alice@acme"}]


@testing.effect
def test_runs_outer_middleware_outside_a_combined_one_whose_member_is_provided_further_out():
    """McpServer request-level dependencies / runs outer middleware outside a combined middleware when one of its members is also provided further out"""  # noqa: E501
    registrations = (
        M.toolkit(WHO_AM_I)
        .pipe(provide(AUDIT.combine(AUTH).layer))
        .pipe(provide(TENANT.layer))
        .pipe(provide(AUDIT.layer))
        .pipe(provide(WHO_AM_I_HANDLERS))
    )
    client = yield from mcp_test.make_client(registrations, protocols=PROTOCOLS)

    result = yield from client.call_tool({"name": "WhoAmI", "arguments": {}})

    assert result["content"] == [{"type": "text", "text": "alice@acme"}]


@testing.effect
def test_keeps_the_order_of_each_combined_middleware_when_siblings_share_one():
    """McpServer request-level dependencies / keeps the order of each combined middleware when siblings share one"""  # noqa: E501
    order: list[str] = []
    a, b, c, d = (_recording(order, name) for name in "abcd")
    registrations = M.resource(
        uri="test://shared", name="shared", content=fx.succeed("shared")
    ).pipe(provide(layer.merge(a.combine(b).layer, c.combine(b.combine(d)).layer)))
    client = yield from mcp_test.make_client(registrations, protocols=PROTOCOLS)

    yield from client.read_resource({"uri": "test://shared"})

    assert order.index("d") < order.index("b") < order.index("a")
    assert order.index("b") < order.index("c")


class _Number(TypedDict):
    a: float


@testing.effect
def test_a_handler_failure_inside_middleware_stays_a_tool_error():
    """(pyfect, checked under Node) A tool's invalid arguments under
    middleware are still the tool error result, not a JSON-RPC error: the
    middleware's own failures are told apart from the handler's."""
    add = T.make("Add", parameters=S.Struct(_Number), success=S.Finite)
    kit = K.make(add)
    registrations = (
        M.toolkit(kit)
        .pipe(provide(AUDIT.layer))
        .pipe(provide(kit.to_layer(add.handler(lambda params, _: fx.succeed(params["a"])))))
    )
    client = yield from mcp_test.make_client(registrations, protocols=PROTOCOLS)

    result = yield from client.call_tool({"name": "Add", "arguments": {"a": "nope"}})

    assert result.get("isError") is True
    text = cast("Any", result["content"][0])["text"]
    assert text.startswith("Invalid parameters for tool 'Add'")
