"""Ports of the framed HTTP response titles of Effect's ``rpc/RpcServer.test.ts``
(each docstring is the Effect test title). The in-memory client stands in for
``HttpRouter.toWebHandler``: both leave a response's body unread until asked."""

from __future__ import annotations

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
import json
from typing import Any, TypedDict, cast

import pytest

import pyfect as fx
from pyfect import effect, layer, stream, testing
from pyfect import schema as S
from pyfect.deferred import Deferred
from pyfect.exit import Failure, Success
from pyfect.http import request as R
from pyfect.http import router, server_request
from pyfect.http.server_request import HttpServerRequest
from pyfect.http.server_response import to_client_response
from pyfect.queue import Queue
from pyfect.rpc import RpcGroup, make
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server
from pyfect.scheduler import CurrentScheduler
from pyfect.scope import CloseableScope, Scope

from ._custom_scheduler import counting_rounds


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


# --- a framed batch dispatched while its response drains (Effect #10424) ------------------


def _unknown(request_id: int) -> str:
    return f'{{"_tag":"Request","id":{request_id},"tag":"unknown","payload":{{}},"headers":[]}}\n'


def _framed_server(group: type[RpcGroup], handlers: Any) -> Any:
    return (
        rpc_server.layer_http(group, path="/rpc", protocol="http", stream_buffer_size=1)
        .pipe(layer.provide(handlers))
        .pipe(layer.provide(rs.layer_ndjson))
    )


def _post_text(body: str) -> Any:
    return R.post("http://test/rpc").body_text(body, "application/x-ndjson")


def _start_server(client: Any) -> fx.Effect[None, Any]:
    """Effect's first request, which starts the server's message loop. Here the loop is a fiber
    the layer forked, which runs once the test yields."""
    return client.execute(_post_text("")).flat_map(lambda r: r.text).and_then(effect.yield_now())


class Ping(RpcGroup):
    ping = make("ping")


@testing.effect
def test_drains_framed_http_responses_while_dispatching_a_batch_larger_than_the_buffer():
    """RpcServer / drains framed HTTP responses while dispatching a batch larger than the buffer"""
    server = _framed_server(
        Ping, Ping.to_layer(Ping.handlers().handle(Ping.ping)(lambda _: effect.void))
    )
    client = yield from router.in_memory_client(server)
    yield from _start_server(client)
    response = yield from client.execute(_post_text(_unknown(1) + _unknown(2)))
    body = yield from response.text
    assert [json.loads(line)["requestId"] for line in body.strip().split("\n")] == [1, 2]


@pytest.mark.parametrize("buffer", [1, 2, 3])
@pytest.mark.parametrize("size", [1, 4, 9])
def test_a_framed_http_batch_of_any_size_is_answered_in_full(buffer: int, size: int) -> None:
    """Whatever the batch and the buffer, dispatching never waits on the response it fills:
    every request is answered, in order."""
    server = (
        rpc_server.layer_http(Ping, path="/rpc", protocol="http", stream_buffer_size=buffer)
        .pipe(
            layer.provide(Ping.to_layer(Ping.handlers().handle(Ping.ping)(lambda _: effect.void)))
        )
        .pipe(layer.provide(rs.layer_ndjson))
    )

    @testing.effect
    def body():
        client = yield from router.in_memory_client(server)
        yield from _start_server(client)
        batch = "".join(_unknown(i) for i in range(1, size + 1))
        text = yield from client.execute(_post_text(batch)).flat_map(lambda r: r.text)
        ids = [json.loads(line)["requestId"] for line in text.strip().split("\n")]
        assert ids == list(range(1, size + 1))

    body()


class _NoFields(TypedDict):
    pass


class _BoomFields(TypedDict):
    value: str


class Wait(RpcGroup):
    wait = make("wait", payload=S.Struct(_NoFields))


@testing.effect
def test_terminates_a_framed_http_request_that_reuses_an_active_request_id():
    """RpcServer / terminates a framed HTTP request that reuses an active request id"""
    finalized = Deferred[Any]()
    handlers = Wait.to_layer(
        Wait.handlers().handle(Wait.wait)(
            lambda _: effect.never.on_exit(lambda exit: finalized.succeed(exit).as_void())
        )
    )
    client = yield from router.in_memory_client(_framed_server(Wait, handlers))
    yield from _start_server(client)
    wait = '{"_tag":"Request","id":100,"tag":"wait","payload":{},"headers":[]}\n'
    # Effect checks for a failed status or an incomplete body; the in-memory client fails either.
    sent = client.execute(_post_text(_unknown(1) + _unknown(2) + wait + wait))
    outcome = yield from sent.flat_map(lambda r: r.text).exit()
    assert isinstance(outcome, Failure)
    exit = yield from finalized.wait()
    assert isinstance(exit, Failure)
    assert exit.cause.has_interrupts


class _DecodeDefect(Exception):
    pass


def _dying_default(defect: Exception) -> Any:
    """A missing key decoded by dying with ``defect``."""
    return S.with_decoding_default_key(effect.die(defect))


@testing.effect
def test_fails_a_framed_http_request_with_its_dispatch_defect():
    """RpcServer / fails a framed HTTP request with its dispatch defect"""
    defect = _DecodeDefect("decode defect")

    class Boom(RpcGroup):
        boom = make(
            "boom",
            # The default dies, so its type says nothing; the struct is typed by hand.
            payload=cast(
                "S.Codec[_BoomFields, Any]",
                S.Struct(_BoomFields, value=S.String.pipe(_dying_default(defect))),
            ),
        )

    handlers = Boom.to_layer(Boom.handlers().handle(Boom.boom)(lambda _: effect.void))
    client = yield from router.in_memory_client(_framed_server(Boom, handlers))
    yield from _start_server(client)
    boom = '{"_tag":"Request","id":100,"tag":"boom","payload":{},"headers":[]}\n'
    # The in-memory client dies with what a web handler answers with a 500.
    alone = yield from client.execute(_post_text(boom)).exit()
    assert isinstance(alone, Failure)
    assert alone.cause.squash() is defect
    streamed = yield from client.execute(_post_text(_unknown(1) + _unknown(2) + _unknown(3) + boom))
    read = yield from streamed.text.exit()
    assert isinstance(read, Failure)
    assert defect in _chain(read.cause.squash())


def _chain(error: object) -> list[object]:
    """``error`` and its causes."""
    found: list[object] = []
    while error is not None and error not in found:
        found.append(error)
        error = getattr(error, "cause", None) or getattr(error, "__cause__", None)
    return found


class Echo(RpcGroup):
    echo = make("echo", success=S.String)


@testing.live
def test_answers_a_framed_http_request_before_a_scheduler_round_runs():
    """Effect's #10753, which covers this path without a test of its own: the
    server's answer reaches the response at once, not a scheduler round later."""
    scheduler, rounds = counting_rounds()
    # Waits, and a timer of the run, not a round of the server's scheduler, resumes it.
    handlers = Echo.to_layer(
        Echo.handlers().handle(Echo.echo)(lambda _: fx.sleep("1 millis").as_("hi"))
    )
    client = yield from router.in_memory_client(_framed_server(Echo, handlers))
    yield from _start_server(client)

    def call(request_id: int) -> fx.Effect[Any, Any]:
        line = f'{{"_tag":"Request","id":{request_id},"tag":"echo","payload":null,"headers":[]}}\n'
        # The routes' services come from the request (``router.in_memory_client``).
        return client.execute(_post_text(line)).pipe(
            fx.provide_service(CurrentScheduler, scheduler)
        )

    # Serve one request before measuring, and let the rounds it left run.
    yield from call(1).flat_map(lambda r: r.text)
    yield from effect.yield_now()
    before = rounds[0]
    response = yield from call(2)
    assert rounds[0] == before
    text = yield from response.text
    assert [json.loads(line) for line in text.splitlines()] == [
        {"_tag": "Exit", "requestId": 2, "exit": {"_tag": "Success", "value": "hi"}}
    ]
