"""graphql-transport-ws transport behavior beyond Effect's tests: an
answered keep-alive keeps the connection, and an operation started during
the idle timeout restarts it."""

from typing import Any

from oracle._graphql import IssueUpdated, WsServer

import pyfect as fx
from pyfect import testing
from pyfect.effect import Effect
from pyfect.graphql.protocol import (
    GraphQLProtocolService,
    GraphQLRequest,
    WebSocketOptions,
    make_web_socket,
)
from pyfect.scope import Scope

REQUEST = GraphQLRequest(
    kind="subscription",
    query=IssueUpdated.document,
    operation_name="IssueUpdated",
    variables={"id": "A"},
)


def protocol(server: WsServer, **options: Any) -> Effect[GraphQLProtocolService, Any, Scope]:
    return make_web_socket(WebSocketOptions[Any](url="ws://localhost", **options)).pipe(
        fx.provide(server.layer)
    )


@testing.effect
def test_an_answered_keep_alive_ping_keeps_the_connection():
    server = WsServer()
    transport = yield from protocol(server, keep_alive=10)
    fiber = yield from transport.subscribe(REQUEST).run_drain().exit().fork()
    accepted = yield from server.accept
    connection = accepted.connection
    yield from connection.received.take()

    for _ in range(3):
        yield from testing.adjust(10)
        assert (yield from connection.received.take()) == {"type": "ping"}
        yield from connection.send({"type": "pong"})

    assert fiber.poll_unsafe() is None
    assert not (yield from connection.closed.is_done())


@testing.effect
def test_an_operation_during_the_idle_timeout_restarts_it():
    server = WsServer()
    transport = yield from protocol(server, idle_timeout=30, keep_alive=False)

    def one_operation() -> Effect[Any, Any, Any]:
        def body():
            fiber = yield from transport.subscribe(REQUEST).run_collect().fork()
            return fiber

        return fx.gen(body)

    first = yield from one_operation()
    accepted = yield from server.accept
    connection = accepted.connection
    subscribe = yield from connection.received.take()
    yield from connection.send({"id": subscribe["id"], "type": "complete"})
    yield from first.join()

    yield from testing.adjust(10)
    second = yield from one_operation()
    subscribe = yield from connection.received.take()
    yield from testing.adjust(10)
    yield from connection.send({"id": subscribe["id"], "type": "complete"})
    yield from second.join()

    # The first idle timer (due at 30s) no longer applies; the second is
    # due 30s after the second operation ended, at 50s.
    yield from testing.adjust(29)
    assert not (yield from connection.closed.is_done())
    yield from testing.adjust(1)
    assert (yield from connection.closed.wait()) == 1000
