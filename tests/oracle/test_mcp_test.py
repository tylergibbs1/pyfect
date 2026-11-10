"""Ports of Effect's ``test/ai/McpServer/McpTest.test.ts``: ``mcp_test.make_client``,
an in-memory client of a server built from registration layers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, cast

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
from pyfect.errors import IllegalArgumentError
from pyfect.layer import provide

from ._held_scheduler import held_scheduler


class CurrentUser(Tag[str], key="test/CurrentUser"):
    pass


@dataclass(eq=False)
class Unauthorized(MS.McpError):
    _tag: ClassVar[str] = "Unauthorized"
    CODE: ClassVar[int] = -32001


# The tool depends on a user service discharged by middleware and on the
# transport built-in ``McpServerClient``, so a call proves both are supplied.
WhoAmI = T.make("WhoAmI", success=S.String, dependencies=[CurrentUser, MS.McpServerClient])
WHO_AM_I = K.make(WhoAmI)


@fx.fn
def _who_am_i(_: object, __: object):
    user = yield from CurrentUser()
    client = yield from MS.McpServerClient()
    return f"{user}@{client.protocol_version}"


HANDLERS = WHO_AM_I.to_layer(WhoAmI.handler(_who_am_i))
GREETING = M.resource(uri="test://greeting", name="greeting", content=fx.succeed("hello"))


@testing.effect
def test_calls_tools_over_a_negotiated_session():
    """McpTest / calls tools over a negotiated session"""
    auth = M.middleware(
        lambda effect, _: effect.pipe(fx.provide_service(CurrentUser, "alice")),
        provides=CurrentUser,
    )
    registrations = M.toolkit(WHO_AM_I).pipe(provide(auth.layer)).pipe(provide(HANDLERS))
    client = yield from mcp_test.make_client(registrations, protocols=(P.v2025_11_25,))

    assert client.protocol_version == "2025-11-25"
    tools = yield from client.list_tools()
    assert [tool["name"] for tool in tools["tools"]] == ["WhoAmI"]
    result = yield from client.call_tool({"name": "WhoAmI"})
    assert result["content"] == [{"type": "text", "text": "alice@2025-11-25"}]


@testing.effect
def test_fails_with_the_mcp_error_a_middleware_returns():
    """McpTest / fails with the MCP error a middleware returns"""
    reject = M.middleware(
        lambda _, __: fx.fail(Unauthorized("Unauthorized")),
        provides=CurrentUser,
    )
    registrations = M.toolkit(WHO_AM_I).pipe(provide(reject.layer)).pipe(provide(HANDLERS))
    client = yield from mcp_test.make_client(registrations, protocols=(P.v2025_11_25,))

    error = yield from client.call_tool({"name": "WhoAmI"}).flip()
    assert (error.code, error.message) == (-32001, "Unauthorized")


@testing.effect
def test_delivers_server_notifications():
    """McpTest / delivers server notifications"""
    client = yield from mcp_test.make_client(GREETING, protocols=(P.v2025_11_25,))

    yield from client.subscribe({"uri": "test://greeting"})
    yield from client.server.notify("notifications/resources/updated", {"uri": "test://greeting"})
    notification = yield from client.notifications.take()
    assert notification.method == "notifications/resources/updated"
    assert notification.payload["uri"] == "test://greeting"


@testing.effect
def test_excludes_notifications_emitted_before_the_handshake():
    """McpTest / excludes notifications emitted before the handshake"""
    held = yield from held_scheduler()
    # The registration's list change goes out only after the handshake.
    registrations = GREETING.pipe(provide(layer.succeed(fx.CurrentScheduler, held)))
    client = yield from mcp_test.make_client(registrations, protocols=(P.v2025_11_25,))
    yield from held.release

    yield from client.subscribe({"uri": "test://greeting"})
    yield from client.server.notify("notifications/resources/updated", {"uri": "test://greeting"})
    notification = yield from client.notifications.take()
    assert notification.method == "notifications/resources/updated"


@testing.effect
def test_rejects_server_to_client_requests_with_method_not_found():
    """McpTest / rejects server-to-client requests with method not found"""
    roots = T.make("Roots", success=S.String, dependencies=[MS.McpServerClient])
    kit = K.make(roots)

    @fx.fn
    def list_roots(_: object, __: object):
        server = yield from MS.McpServerClient()
        client = yield from server.get_client

        def failed(error: Any) -> str:
            assert isinstance(error, MS.McpReverseOperationError)
            cause = cast("dict[str, Any]", error.cause)
            return f"{type(error).__name__} {cause['code']} {cause['message']}"

        return (
            yield from client.list_roots().match(
                on_success=lambda _: "listed roots", on_failure=failed
            )
        )

    registrations = M.toolkit(kit).pipe(provide(kit.to_layer(roots.handler(list_roots))))
    # Advertise roots so the server sends the request instead of refusing it itself.
    client = yield from mcp_test.make_client(
        registrations, protocols=(P.v2025_11_25,), client_capabilities={"roots": {}}
    )

    result = yield from client.call_tool({"name": "Roots"})
    assert result["content"] == [
        {"type": "text", "text": "McpReverseOperationError -32601 Method not found: roots/list"}
    ]


@testing.effect
def test_rejects_a_protocol_version_outside_the_protocols():
    """(pyfect) ``make_client`` fails with ``IllegalArgumentError`` for a
    ``protocol_version`` that is not among ``protocols``, as Effect does."""
    error = yield from mcp_test.make_client(
        GREETING, protocols=(P.v2025_11_25,), protocol_version="2025-06-18"
    ).flip()
    assert isinstance(error, IllegalArgumentError)
    assert str(error) == "MCP protocol 2025-06-18 is not in the configured protocols"


@testing.effect
def test_sends_request_metadata_on_the_stateless_revision():
    """(pyfect) A 2026-07-28 client has no handshake: each request carries
    the client's ``_meta``, so a tool sees the client info."""
    client = yield from mcp_test.make_client(GREETING, protocols=(P.v2026_07_28,))
    assert client.protocol_version == "2026-07-28"
    result = yield from client.read_resource({"uri": "test://greeting"})
    assert result["contents"] == [{"uri": "test://greeting", "text": "hello"}]
