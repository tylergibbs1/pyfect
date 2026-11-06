"""Ports of the framed HTTP response titles of Effect's ``rpc/RpcServer.test.ts``
(each docstring is the Effect test title). The in-memory client stands in for
``HttpRouter.toWebHandler``: both leave a response's body unread until asked."""

from __future__ import annotations

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
import json
from typing import Any

import pyfect as fx
from pyfect import effect, layer, stream, testing
from pyfect import schema as S
from pyfect.deferred import Deferred
from pyfect.exit import Success
from pyfect.http import request as R
from pyfect.http import router, server_request
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.server_response import to_client_response
from pyfect.queue import Queue
from pyfect.rpc import RpcGroup, make
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server
from pyfect.scope import CloseableScope, Scope


class Events(RpcGroup):
    events = make("events", success=S.Number, stream=True)


def _line(request_id: int) -> str:
    return f'{{"_tag":"Request","id":{request_id},"tag":"events","payload":null,"headers":[]}}\n'


def _produced(buffer: Any, serialization: Any, count: int) -> fx.Effect[int, Any, Any]:
    produced = [0]

    def next_value() -> int:
        produced[0] += 1
        return produced[0]

    handlers = Events.to_layer(
        Events.handlers().handle(Events.events)(
            lambda _: stream.from_effect_repeat(effect.sync(next_value)).take(count)
        )
    )
    options: dict[str, Any] = {} if buffer is None else {"stream_buffer_size": buffer}
    server = (
        rpc_server.layer_http(Events, path="/rpc", protocol="http", **options)
        .pipe(layer.provide(handlers))
        .pipe(layer.provide(serialization))
    )

    @fx.gen
    def run():
        client = yield from router.in_memory_client(server)
        request = R.post("http://test/rpc").body_text(_line(1), "application/x-ndjson")
        yield from client.execute(request)
        # Effect yields 100 times; here a fiber's turn is shorter, so more are needed.
        for _ in range(1000):
            yield from effect.yield_now()
        return produced[0]

    return run


@testing.effect
def test_applies_backpressure_to_framed_http_responses_by_default():
    """RpcServer / applies backpressure to framed HTTP responses by default"""
    assert 0 < (yield from _produced(None, rs.layer_ndjson, 10_000)) < 10_000


@testing.effect
def test_uses_the_configured_framed_http_response_buffer_size():
    """RpcServer / uses the configured framed HTTP response buffer size"""
    assert 0 < (yield from _produced(1, rs.layer_ndjson, 10_000)) < 16


@testing.effect
def test_allows_unbounded_framed_http_response_buffering():
    """RpcServer / allows unbounded framed HTTP response buffering"""
    assert (yield from _produced("unbounded", rs.layer_ndjson, 10_000)) == 10_000


@testing.effect
def test_keeps_non_framed_http_responses_unbounded():
    """RpcServer / keeps non-framed HTTP responses unbounded"""
    assert (yield from _produced(1, rs.layer_json, 100)) == 100


def _post(request_id: int) -> Any:
    return server_request.from_client_request(
        R.post("http://test/rpc").body_text(_line(request_id))
    )


@testing.effect
def test_should_continue_sending_to_other_clients_when_a_backpressured_http_client_disconnects():
    """RpcServer / should continue sending to other clients when a backpressured HTTP client disconnects"""  # noqa: E501
    made = yield from rpc_server.make_protocol_with_http_effect(stream_buffer_size=1).pipe(
        fx.provide(rs.layer_ndjson)
    )
    http_effect, protocol = made.http_effect, made.protocol
    connected = yield from Queue[int].unbounded()
    interrupted = yield from Queue[Any].unbounded()
    pong: Any = {"_tag": "Pong"}

    def on_message(client_id: int, message: Any) -> Any:
        if message["_tag"] == "Request":
            return connected.offer(client_id).flat_map(lambda _: protocol.send(client_id, pong))
        if message["_tag"] == "Interrupt":
            return interrupted.offer(message).as_void()
        return effect.void

    yield from protocol.run(on_message).fork_scoped()
    scope: CloseableScope = yield from Scope()
    first_scope = yield from scope.fork()
    yield from (
        http_effect.pipe(fx.provide_service(HttpServerRequest, _post(1))).pipe(
            fx.provide_service(Scope, first_scope)
        )
    )
    first_id = yield from connected.take()
    response = yield from http_effect.pipe(fx.provide_service(HttpServerRequest, _post(2)))
    second_id = yield from connected.take()
    yield from protocol.send(first_id, pong)
    delivered = Deferred[None]()
    sender = yield from (
        protocol.send(first_id, pong)
        .flat_map(lambda _: protocol.send(second_id, pong))
        .flat_map(lambda _: delivered.succeed(None))
        .fork_scoped()
    )
    yield from effect.yield_now()
    assert not (yield from delivered.is_done())
    yield from first_scope.close(Success(None))
    yield from effect.yield_now()
    assert (yield from delivered.is_done())
    yield from sender.join()
    assert (yield from interrupted.take()) == {"_tag": "Interrupt", "requestId": 1}
    yield from protocol.end(second_id)
    body = yield from to_client_response(response).text
    assert [json.loads(line) for line in body.strip().split("\n")] == [pong, pong]
