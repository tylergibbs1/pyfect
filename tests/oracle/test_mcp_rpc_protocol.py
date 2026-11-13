"""Ports of the custom-transport titles of Effect's
``test/ai/McpServer/McpServer.test.ts``: ``McpServer.layer`` over an
``RpcServer.Protocol`` the test builds (``mcp_server.layer_rpc_protocol``
over ``rpc.server.ServerProtocol``).

Adapted, with the reason:
- ``should release disconnected clients when a reverse request is cancelled
  without a reply`` holds ``WeakRef`` s to each client's ``clientInfo``; a
  Python dict takes no weak reference, so after collecting garbage this looks
  for the clients' sessions (which hold their client info) among live objects.
"""

from __future__ import annotations

import gc
import json
from collections.abc import Callable
from typing import Any, TypedDict, cast

import pytest
from _gc_census import tracked_of

import pyfect as fx
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.ai import mcp_protocol as P
from pyfect.ai import mcp_schema as MS
from pyfect.ai import mcp_server as M
from pyfect.ai import tool as T
from pyfect.ai import toolkit as K
from pyfect.ai._mcp.core import ToolEntry
from pyfect.ai._mcp.dispatch import Connection
from pyfect.context import Context
from pyfect.deferred import Deferred
from pyfect.http.router import HttpRouter
from pyfect.layer import provide, provide_merge
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server
from pyfect.scope import Scope

from ._mcp_http import http_harness
from ._mcp_rpc import CustomTransport, Message, custom_transport, request


class _Approval(TypedDict):
    approved: bool


def _served(
    transport: CustomTransport, protocols: list[P.AnyProtocolAdapter], name: str
) -> layer.Layer[M.McpServer, Any]:
    return M.layer_rpc_protocol(name=name, version="1.0.0", protocols=protocols).pipe(
        provide(layer.succeed(rpc_server.ServerProtocol, transport.protocol))
    )


def _built(app: layer.Layer[Any, Any, Any]) -> fx.Effect[Context[Any], Any, Scope]:
    """``app`` built for the test's scope (the request services its tools
    need come from each request)."""
    return cast("fx.Effect[Context[Any], Any, Scope]", app.build())


EMPTY: Any = {"content": []}


def _initialize(version: str, client: str, capabilities: Any = None) -> Message:
    return {
        "protocolVersion": version,
        "capabilities": {} if capabilities is None else capabilities,
        "clientInfo": {"name": client, "version": "1"},
    }


def _empty_tool(name: str, handle: Callable[[object], fx.Effect[Any, Any, Any]]) -> ToolEntry:
    return ToolEntry({"name": name, "inputSchema": {"type": "object"}}, Context.empty(), handle)


Approve = T.make("Approve", success=S.Struct(_Approval), dependencies=[MS.McpServerClient])


@testing.effect
def test_should_deliver_notifications_and_results_to_other_clients_when_one_client_stops_reading():
    """McpServer / should deliver notifications and results to other clients when one client stops reading"""  # noqa: E501
    blocked = Deferred[None]()
    release = Deferred[None]()

    def send(client_id: int, message: Message) -> fx.Effect[None]:
        payload = message.get("payload")
        if (
            client_id == 1
            and message["_tag"] == "Request"
            and isinstance(payload, dict)
            and cast("Message", payload).get("data") == "first"
        ):
            return blocked.succeed(None).and_then(release.wait())
        return fx.succeed(None)

    transport = yield from custom_transport(client_ids={1, 2}, send=send)
    context = yield from _served(transport, [P.v2025_11_25], name="NotificationIsolation").build()
    server = context.get(M.McpServer)

    def log(_: object) -> fx.Effect[Any, Any, Any]:
        @fx.gen
        def run():
            yield from fx.for_each(
                ["first", "second"],
                lambda data: server.notify(
                    "notifications/message", {"level": "error", "data": data}
                ),
                concurrency="unbounded",
            )
            if (yield from MS.McpRequestContext()).client_id == 2:
                yield from server.add_tool(_empty_tool("Dynamic", lambda _: fx.succeed(EMPTY)))
            return EMPTY

        return run

    yield from server.add_tool(_empty_tool("Log", log))

    def take(client_id: int) -> fx.Effect[Message]:
        return transport.outbound.take().map(
            lambda event: event[1] if event[0] == client_id else _wrong(event, client_id)
        )

    write = yield from transport.ready.wait()
    for client_id in [1, 2]:
        yield from write(
            client_id,
            request("initialize", "initialize", _initialize("2025-11-25", "client")),
        )
        reply = yield from take(client_id)
        assert reply["_tag"] == "Exit" and reply["requestId"] == "initialize"
        yield from write(client_id, request("", "notifications/initialized", {}, notification=True))
    log_request = request("log", "tools/call", {"name": "Log"})
    yield from write(1, log_request)
    yield from blocked.wait()
    yield from write(2, log_request)
    for data in ["first", "second"]:
        message = yield from take(2)
        assert message["_tag"] == "Request"
        assert message["tag"] == "notifications/message"
        assert message["payload"] == {"level": "error", "data": data}
    assert (yield from take(2))["tag"] == "notifications/tools/list_changed"
    result = yield from take(2)
    assert result["_tag"] == "Exit" and result["requestId"] == "log"
    yield from release.succeed(None)
    for data in ["first", "second"]:
        message = yield from take(1)
        assert message["tag"] == "notifications/message"
        assert message["payload"] == {"level": "error", "data": data}
    remaining = [(yield from take(1)), (yield from take(1))]
    exits = [m for m in remaining if m["_tag"] == "Exit"]
    assert len(exits) == 1 and exits[0]["requestId"] == "log"
    requests = [m for m in remaining if m["_tag"] == "Request"]
    assert requests[0]["tag"] == "notifications/tools/list_changed"


def _wrong(event: tuple[int, Message], client_id: int) -> Message:
    raise AssertionError(f"expected client {client_id}, got {event}")


@testing.effect
def test_should_suppress_cancelled_responses_when_a_custom_transport_handles_mcp_messages():
    """McpServer / should suppress cancelled responses when a custom transport handles MCP messages"""  # noqa: E501
    transport = yield from custom_transport(client_ids={1})
    context = yield from _served(transport, [P.v2025_03_26], name="CustomCancellation").build()
    entered = Deferred[None]()
    interrupted = Deferred[None]()
    yield from context.get(M.McpServer).add_tool(
        _empty_tool(
            "Wait",
            lambda _: (
                entered.succeed(None)
                .and_then(fx.never)
                .on_interrupt(interrupted.succeed(None).as_void())
            ),
        )
    )
    write = yield from transport.ready.wait()
    yield from write(1, request("initialize", "initialize", _initialize("2025-03-26", "client")))
    reply = (yield from transport.outbound.take())[1]
    assert reply["_tag"] == "Exit" and reply["requestId"] == "initialize"
    yield from write(1, request("wait", "tools/call", {"name": "Wait"}))
    yield from entered.wait()
    yield from write(
        1, request("", "notifications/cancelled", {"requestId": "wait"}, notification=True)
    )
    yield from interrupted.wait()
    yield from write(1, request("ping", "ping", {}))
    reply = (yield from transport.outbound.take())[1]
    assert reply["_tag"] == "Exit" and reply["requestId"] == "ping"


@testing.effect
def test_should_match_reverse_responses_to_their_originating_connection():
    """McpServer / should match reverse responses to their originating connection"""
    transport = yield from custom_transport(client_ids={1, 2})
    tools = K.make(Approve)
    handlers = tools.to_layer(
        Approve.handler(
            lambda _, __: M.elicit(message="Approve", schema=S.Struct(_Approval)).or_die()
        )
    )
    yield from _built(
        M.toolkit(tools)
        .pipe(provide(handlers))
        .pipe(provide(_served(transport, [P.v2025_11_25], name="ResponseOwnership")))
    )
    write = yield from transport.ready.wait()
    for client_id in [1, 2]:
        yield from write(
            client_id,
            request(
                client_id,
                "initialize",
                _initialize("2025-11-25", f"client-{client_id}", {"elicitation": {"form": {}}}),
            ),
        )
        assert (yield from transport.outbound.take())[1]["_tag"] == "Exit"
    yield from write(1, request(10, "tools/call", {"name": "Approve"}))
    reverse_client, reverse = yield from transport.outbound.take()
    assert reverse_client == 1
    assert reverse["_tag"] == "Request"
    assert reverse["tag"] == "elicitation/create"
    for client_id in [2, 1]:
        yield from write(
            client_id,
            {
                "_tag": "Exit",
                "requestId": reverse["id"],
                "exit": {
                    "_tag": "Success",
                    "value": {"action": "accept", "content": {"approved": client_id == 1}},
                },
            },
        )
    result_client, result = yield from transport.outbound.take()
    assert result_client == 1
    assert result["_tag"] == "Exit" and result["requestId"] == 10
    assert result["exit"]["_tag"] == "Success"
    assert result["exit"]["value"]["structuredContent"] == {"approved": True}


Probe = T.make("Probe", success=S.String, dependencies=[MS.McpServerClient])


@testing.effect
def test_should_release_disconnected_clients_when_a_reverse_request_is_cancelled_without_a_reply():
    """McpServer / should release disconnected clients when a reverse request is cancelled without a reply"""  # noqa: E501
    seen: set[int] = set()
    connected = {1, 2}
    cancelled = Deferred[None]()
    transport = yield from custom_transport(client_ids=connected)
    tools = K.make(Probe)

    def probe(_: Any, __: Any) -> fx.Effect[str, Any, Any]:
        @fx.gen
        def run():
            client = yield from MS.McpServerClient()
            seen.add(client.client_id)
            if client.client_id == 2:
                return "control"
            yield from (
                M.elicit(message="Approve", schema=S.Struct(_Approval))
                .or_die()
                .on_interrupt(cancelled.succeed(None).as_void())
            )
            return "done"

        return run

    context = yield from _built(
        M.toolkit(tools)
        .pipe(provide(tools.to_layer(Probe.handler(probe))))
        .pipe(provide_merge(_served(transport, [P.v2025_11_25], name="ReverseLifetime")))
    )
    server = context.get(M.McpServer)
    write = yield from transport.ready.wait()
    for client_id in [1, 2]:
        yield from write(
            client_id,
            request(
                client_id,
                "initialize",
                _initialize("2025-11-25", f"client-{client_id}", {"elicitation": {"form": {}}}),
            ),
        )
        assert (yield from transport.outbound.take())[1]["_tag"] == "Exit"
        yield from write(client_id, request(10 + client_id, "tools/call", {"name": "Probe"}))
        outbound = (yield from transport.outbound.take())[1]
        assert outbound["_tag"] == ("Request" if client_id == 1 else "Exit"), outbound
        if client_id == 1:
            assert outbound["tag"] == "elicitation/create"
            yield from write(
                client_id,
                request("", "notifications/cancelled", {"requestId": 11}, notification=True),
            )
            yield from cancelled.wait()
            cancellation = (yield from transport.outbound.take())[1]
            assert cancellation["_tag"] == "Request"
            assert cancellation["tag"] == "notifications/cancelled"
            assert cancellation["isNotification"] is True
            assert cancellation["payload"] == {"requestId": outbound["id"]}
        yield from write(client_id, {"_tag": "Eof"})
        connected.discard(client_id)
        yield from transport.disconnects.offer(client_id)
    yield from testing.adjust("11 seconds")
    gc.collect()
    sessions = {o.client_id for o in tracked_of(Connection) if o.server is server}
    assert seen == {1, 2}
    assert 2 not in sessions, "control client must be collectible"
    assert 1 not in sessions, "cancelled reverse client must be collectible"


@pytest.mark.parametrize("supports_notifications", [True, False])
@testing.effect
def test_a_transport_without_notifications_gets_answers_only(supports_notifications: bool):
    """Checked under Node: over a transport without ``supportsNotifications``
    a tool's log is not sent, only its answer; a client that leaves has its
    requests interrupted; ``Ping`` is answered ``Pong``."""
    transport = yield from custom_transport(
        client_ids={1}, supports_notifications=supports_notifications
    )
    context = yield from _served(transport, [P.v2025_11_25], name="N").build()
    server = context.get(M.McpServer)
    entered = Deferred[None]()
    interrupted = Deferred[None]()
    yield from server.add_tool(
        _empty_tool(
            "Log",
            lambda _: server.notify("notifications/message", {"level": "error", "data": "x"}).as_(
                EMPTY
            ),
        )
    )
    yield from server.add_tool(
        _empty_tool(
            "Wait",
            lambda _: (
                entered.succeed(None)
                .and_then(fx.never)
                .on_interrupt(interrupted.succeed(None).as_void())
            ),
        )
    )
    write = yield from transport.ready.wait()
    yield from write(1, request(1, "initialize", _initialize("2025-11-25", "c")))
    initialized = (yield from transport.outbound.take())[1]
    assert initialized["exit"]["value"]["capabilities"] == {
        "logging": {},
        "tools": {"listChanged": True},
        "completions": {},
    }
    yield from write(1, request("", "notifications/initialized", {}, notification=True))
    yield from write(1, request(2, "tools/call", {"name": "Log"}))
    if supports_notifications:
        assert (yield from transport.outbound.take())[1] == {
            "_tag": "Request",
            "id": "",
            "tag": "notifications/message",
            "payload": {"level": "error", "data": "x"},
            "headers": [],
            "isNotification": True,
        }
    assert (yield from transport.outbound.take())[1] == {
        "_tag": "Exit",
        "requestId": 2,
        "exit": {"_tag": "Success", "value": {"content": []}},
    }
    yield from write(1, request(4, "tools/call", {"name": "Wait"}))
    yield from entered.wait()
    yield from transport.disconnects.offer(1)
    yield from interrupted.wait()
    yield from write(1, {"_tag": "Ping"})
    assert (yield from transport.outbound.take())[1] == {"_tag": "Pong"}


@testing.effect
def test_drops_server_notifications_from_buffered_json_rpc_responses():
    """McpServer / drops server notifications from buffered JSON-RPC responses"""

    @fx.gen
    def serve():
        http_router = yield from HttpRouter()
        made = yield from rpc_server.make_protocol_with_http_effect()
        protocol = made.protocol

        def receive(client_id: int, message: Any) -> fx.Effect[None]:
            if message["_tag"] != "Request":
                return fx.succeed(None)
            notification = request(
                "", "notifications/message", {"level": "info"}, notification=True
            )
            exit = {
                "_tag": "Exit",
                "requestId": message["id"],
                "exit": {"_tag": "Success", "value": {"ok": True}},
            }
            return (
                protocol.send(client_id, notification)
                .and_then(protocol.send(client_id, exit))
                .and_then(protocol.end(client_id))
            )

        yield from protocol.run(receive).fork_scoped()
        yield from http_router.add("POST", "/mcp", made.http_effect)

    app = layer.effect_discard(serve).pipe(provide(rs.layer_json_rpc()))
    harness = yield from http_harness(app)

    response = yield from harness.post({"jsonrpc": "2.0", "method": "ping", "params": {}, "id": 1})

    assert response.status == 200
    assert json.loads((yield from response.text.or_die())) == {
        "jsonrpc": "2.0",
        "id": 1,
        "result": {"ok": True},
    }


@testing.effect
def test_discovery_and_listen_over_a_transport_without_notifications():
    """Checked under Node, message for message: 2026-07-28 discovery and a
    refused ``subscriptions/listen`` over a transport without
    ``supportsNotifications``, the server also speaking 2025-11-25."""
    transport = yield from custom_transport(client_ids={1}, supports_notifications=False)
    context = yield from _served(transport, [P.v2025_11_25, P.v2026_07_28], name="N").build()
    yield from context.get(M.McpServer).add_tool(_empty_tool("Log", lambda _: fx.succeed(EMPTY)))
    write = yield from transport.ready.wait()
    meta = {
        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
        "io.modelcontextprotocol/clientCapabilities": {},
        "io.modelcontextprotocol/clientInfo": {"name": "client", "version": "1.0.0"},
    }
    yield from write(1, request(90, "server/discover", {"_meta": meta}))
    assert (yield from transport.outbound.take())[1] == {
        "_tag": "Exit",
        "requestId": 90,
        "exit": {
            "_tag": "Success",
            "value": {
                "_meta": {"io.modelcontextprotocol/serverInfo": {"name": "N", "version": "1.0.0"}},
                "resultType": "complete",
                "ttlMs": 0,
                "cacheScope": "private",
                "supportedVersions": ["2025-11-25", "2026-07-28"],
                "capabilities": {
                    "logging": {},
                    "completions": {},
                    "tools": {"listChanged": False},
                },
            },
        },
    }
    listen = {"_meta": meta, "notifications": {"toolsListChanged": True}}
    yield from write(1, request(91, "subscriptions/listen", listen))
    assert (yield from transport.outbound.take())[1] == {
        "_tag": "Exit",
        "requestId": 91,
        "exit": {
            "_tag": "Failure",
            "cause": [
                {
                    "_tag": "Fail",
                    "error": {"code": -32601, "message": "Method not found: subscriptions/listen"},
                }
            ],
        },
    }


@testing.effect
def test_requests_still_running_end_with_the_server():
    """As Effect's ``RpcServer``, whose request fibers belong to the server:
    closing the server's scope interrupts a request still running."""
    transport = yield from custom_transport(client_ids={1})
    entered = Deferred[None]()
    interrupted = Deferred[None]()

    @fx.fn
    def served():
        context = yield from _served(transport, [P.v2025_03_26], name="Ends").build()
        yield from context.get(M.McpServer).add_tool(
            _empty_tool(
                "Wait",
                lambda _: (
                    entered.succeed(None)
                    .and_then(fx.never)
                    .on_interrupt(interrupted.succeed(None).as_void())
                ),
            )
        )
        write = yield from transport.ready.wait()
        yield from write(1, request("init", "initialize", _initialize("2025-03-26", "client")))
        yield from transport.outbound.take()
        yield from write(1, request("wait", "tools/call", {"name": "Wait"}))
        yield from entered.wait()

    yield from fx.scoped(served())
    yield from interrupted.wait().timeout("5 seconds").or_die()
