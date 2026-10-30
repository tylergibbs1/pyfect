"""Ports of Effect's graphql/GraphQLProtocol.webSocket.test.ts. Each test's
docstring is the Effect test title, prefixed by its describe block; the
invalid-message table is one parametrized test."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from dataclasses import dataclass
from typing import Any

import pytest

import pyfect as fx
from pyfect import effect, layer, stream, testing
from pyfect.duration import Duration
from pyfect.effect import Effect
from pyfect.exit import Success
from pyfect.graphql import GraphQLGroup, GraphQLMiddleware, Implementation, client
from pyfect.graphql.client_error import ResponseError, TransportError
from pyfect.graphql.middleware import ExecuteOptions, SubscribeOptions
from pyfect.graphql.protocol import (
    Answer,
    GraphQLProtocolService,
    GraphQLRequest,
    WebSocketOptions,
    layer_web_socket,
    make_web_socket,
)
from pyfect.ref import Ref
from pyfect.scope import CloseableScope, Scope
from pyfect.stream import Stream

from ._graphql import (
    IssueUpdated,
    RepoIssues,
    Viewer,
    WsConnection,
    WsMessage,
    WsServer,
    expect_reason,
)

URL = "ws://localhost/graphql"


def event(title: str) -> dict[str, Any]:
    return {"data": {"issueUpdated": {"title": title}}}


def subscription(id: str) -> GraphQLRequest:
    return GraphQLRequest(
        kind="subscription",
        query=IssueUpdated.document,
        operation_name="IssueUpdated",
        variables={"id": id},
    )


def make_protocol(
    server: WsServer,
    *,
    connection_params: Effect[Any, Any] | None = None,
    connection_ack_timeout: Duration | None = None,
    keep_alive: Duration | bool | None = None,
    idle_timeout: Duration | None = None,
) -> Effect[GraphQLProtocolService, Any, Scope]:
    options = WebSocketOptions[Any](
        url=URL,
        connection_params=connection_params,
        connection_ack_timeout=connection_ack_timeout,
        keep_alive=False if keep_alive is False else None if keep_alive is True else keep_alive,
        idle_timeout=idle_timeout,
    )
    return make_web_socket(options).pipe(fx.provide(server.layer))


@dataclass(frozen=True)
class Subscribed:
    fiber: Any
    connection: WsConnection
    subscribe: WsMessage


def accepted_subscription(server: WsServer, **options: Any) -> Effect[Subscribed, Any, Scope]:
    """Starts a subscription and accepts its connection, returning the
    failure fiber."""

    def body():
        protocol = yield from make_protocol(server, **options)
        fiber = yield from protocol.subscribe(subscription("A")).run_drain().flip().fork()
        accepted = yield from server.accept
        subscribe = yield from accepted.connection.received.take()
        return Subscribed(fiber, accepted.connection, subscribe)

    return effect.gen(body)


@testing.effect
def test_subscribes_only_after_connection_ack():
    """GraphQLProtocol.makeWebSocket / subscribes only after connection_ack and routes events by operation id"""  # noqa: E501
    server = WsServer()
    protocol = yield from make_protocol(server, connection_params=effect.succeed({"token": "t1"}))
    a = yield from protocol.subscribe(subscription("A")).run_collect().fork()
    b = yield from protocol.subscribe(subscription("B")).run_collect().fork()

    connection = yield from server.connections.take()
    assert connection.options.protocols == "graphql-transport-ws"
    assert (yield from connection.received.take()) == {
        "type": "connection_init",
        "payload": {"token": "t1"},
    }
    yield from testing.adjust(1)
    assert (yield from connection.received.size()) == 0

    yield from connection.send({"type": "connection_ack"})
    ids: dict[str, str] = {}
    for _ in range(2):
        message = yield from connection.received.take()
        assert message["type"] == "subscribe"
        ids[message["payload"]["variables"]["id"]] = message["id"]

    yield from connection.send({"id": ids["B"], "type": "next", "payload": event("b")})
    yield from connection.send({"id": ids["A"], "type": "next", "payload": event("a")})
    yield from connection.send({"id": ids["A"], "type": "complete"})
    yield from connection.send({"id": ids["B"], "type": "complete"})
    assert (yield from a.join()) == [Answer(body=event("a"))]
    assert (yield from b.join()) == [Answer(body=event("b"))]


@testing.effect
def test_a_missing_connection_ack_is_a_transport_error():
    """GraphQLProtocol.makeWebSocket / a missing connection_ack is a TransportError"""
    server = WsServer()
    protocol = yield from make_protocol(server, connection_ack_timeout=5)
    fiber = yield from protocol.subscribe(subscription("A")).run_drain().flip().fork()
    yield from server.connections.take()
    yield from testing.adjust(5)
    assert isinstance((yield from fiber.join()), TransportError)


@testing.effect
def test_a_close_while_connection_params_is_pending():
    """GraphQLProtocol.makeWebSocket / a close while connectionParams is pending fails the waiting operation"""  # noqa: E501
    server = WsServer()
    protocol = yield from make_protocol(server, connection_params=effect.never)
    fiber = yield from protocol.subscribe(subscription("A")).run_drain().flip().fork()
    connection = yield from server.connections.take()
    yield from connection.close(1006)
    yield from testing.adjust(60)
    assert fiber.poll_unsafe() is not None
    assert (yield from fiber.join()).close_code == 1006


# Shape is checked before the id lookup, so an unknown id does not excuse it.
INVALID_MESSAGES: list[WsMessage] = [
    {"type": "not-a-graphql-message"},
    {"type": "next", "id": "unknown", "payload": []},
]


@pytest.mark.parametrize("invalid", INVALID_MESSAGES)
@testing.effect
def test_an_invalid_message_closes_the_connection_with_4400(invalid: WsMessage):
    """GraphQLProtocol.makeWebSocket / an invalid message ${JSON.stringify(invalid)} closes the connection with 4400"""  # noqa: E501
    server = WsServer()
    subscribed = yield from accepted_subscription(server)
    yield from subscribed.connection.send(invalid)
    error = yield from subscribed.fiber.join()
    assert error.close_code == 4400
    assert not error.is_retryable
    assert (yield from subscribed.connection.closed.wait()) == 4400


@testing.effect
def test_1002_is_a_fatal_close():
    """GraphQLProtocol.makeWebSocket / 1002 is a fatal close"""
    server = WsServer()
    subscribed = yield from accepted_subscription(server)
    yield from subscribed.connection.close(1002)
    error = yield from subscribed.fiber.join()
    assert error.close_code == 1002
    assert not error.is_retryable


@testing.effect
def test_answers_ping_with_pong_and_pings_every_keep_alive():
    """GraphQLProtocol.makeWebSocket / answers ping with pong, pings every keepAlive and treats a missed frame as a retryable close"""  # noqa: E501
    server = WsServer()
    subscribed = yield from accepted_subscription(server, keep_alive=10)
    connection = subscribed.connection
    yield from connection.send({"type": "ping"})
    assert (yield from connection.received.take()) == {"type": "pong"}

    yield from testing.adjust(10)
    assert (yield from connection.received.take()) == {"type": "ping"}
    yield from testing.adjust(10)
    assert (yield from subscribed.fiber.join()).is_retryable


@testing.effect
def test_interrupting_a_subscription_sends_a_client_complete():
    """GraphQLProtocol.makeWebSocket / interrupting a subscription sends a client complete"""
    server = WsServer()
    subscribed = yield from accepted_subscription(server)
    yield from subscribed.fiber.interrupt()
    assert (yield from subscribed.connection.received.take()) == {
        "id": subscribed.subscribe["id"],
        "type": "complete",
    }


@testing.effect
def test_a_lost_connection_fails_in_flight_queries_and_reconnects():
    """GraphQLProtocol.makeWebSocket / a lost connection fails in-flight queries, and the next operation reconnects with fresh connectionParams"""  # noqa: E501
    server = WsServer()
    tokens = yield from Ref.make(0)
    protocol = yield from make_protocol(
        server,
        connection_params=tokens.update_and_get(lambda n: n + 1).map(lambda n: {"token": n}),
    )
    query = GraphQLRequest(
        kind="query", query=Viewer.document, operation_name="Viewer", variables={}
    )

    in_flight = yield from protocol.execute(query).flip().fork()
    first = yield from server.accept
    assert first.init["payload"] == {"token": 1}
    yield from first.connection.received.take()
    yield from first.connection.close(1006)
    assert (yield from in_flight.join()).is_retryable

    retried = yield from protocol.execute(query).fork()
    second = yield from server.accept
    assert second.init["payload"] == {"token": 2}
    subscribe = yield from second.connection.received.take()
    data = {"data": {"viewer": {"login": "tim"}}}
    yield from second.connection.send({"id": subscribe["id"], "type": "next", "payload": data})
    yield from second.connection.send({"id": subscribe["id"], "type": "complete"})
    assert (yield from retried.join()) == Answer(body=data)


@testing.effect
def test_an_operation_started_after_the_scope_closed_fails():
    """GraphQLProtocol.makeWebSocket / an operation started after the scope closed fails with a non-retryable TransportError"""  # noqa: E501
    server = WsServer()
    scope = CloseableScope()
    protocol = yield from make_protocol(server).pipe(fx.provide_service(Scope, scope))
    yield from scope.close(Success(None))
    fiber = yield from protocol.subscribe(subscription("A")).run_drain().flip().timeout(5).fork()
    yield from testing.adjust(5)
    error = yield from fiber.join()
    assert isinstance(error, TransportError)
    assert not error.is_retryable


@testing.effect
def test_connects_on_the_first_operation_and_closes_idle_timeout_after_the_last():
    """GraphQLProtocol.makeWebSocket / connects on the first operation and closes idleTimeout after the last one"""  # noqa: E501
    server = WsServer()
    protocol = yield from make_protocol(server, idle_timeout=30, keep_alive=False)
    yield from testing.adjust(60)
    assert (yield from server.connections.size()) == 0

    fiber = yield from protocol.subscribe(subscription("A")).run_collect().fork()
    accepted = yield from server.accept
    connection = accepted.connection
    subscribe = yield from connection.received.take()
    yield from connection.send({"id": subscribe["id"], "type": "complete"})
    yield from fiber.join()

    yield from testing.adjust(29)
    assert not (yield from connection.closed.is_done())
    yield from testing.adjust(1)
    assert (yield from connection.closed.wait()) == 1000


class Count(GraphQLMiddleware): ...


@testing.effect
def test_a_retryable_close_resubscribes_through_the_middleware_chain():
    """GraphQLProtocol.layerWebSocket with GraphQLClient / a retryable close resubscribes through the middleware chain; a server error is a ResponseError"""  # noqa: E501
    subscribes = yield from Ref.make(0)

    def counted(options: SubscribeOptions) -> Stream[Any, Any]:
        return stream.unwrap(subscribes.update(lambda n: n + 1).as_(options.next(options.request)))

    def passed(options: ExecuteOptions) -> Effect[Any, Any]:
        return options.next(options.request)

    count_live = layer.succeed(Count, Implementation(execute=passed, subscribe=counted))
    server = WsServer()

    class CountedIssues(GraphQLGroup[Count]):
        repo_issues = RepoIssues
        issue_updated = IssueUpdated

    context = yield from layer.merge(
        layer_web_socket(WebSocketOptions(url=URL)).pipe(layer.provide(server.layer)), count_live
    ).build()
    api = yield from client.make(CountedIssues).pipe(fx.provide_context(context))
    fiber = yield from (
        api.issue_updated({"id": "I_1"}).run_collect().pipe(expect_reason(ResponseError)).fork()
    )

    first = yield from server.accept
    yield from first.connection.received.take()
    yield from first.connection.close(1006)
    # The client's default schedule waits 500ms before resubscribing.
    yield from testing.adjust(0.5)

    second = yield from server.accept
    subscribe = yield from second.connection.received.take()
    yield from second.connection.send(
        {"id": subscribe["id"], "type": "error", "payload": [{"message": "denied"}]}
    )
    reason = yield from fiber.join()
    assert reason.errors == ({"message": "denied"},)
    assert (yield from subscribes.get()) == 2
