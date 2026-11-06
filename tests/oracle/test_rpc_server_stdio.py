"""Ports of the stdio titles of Effect's ``rpc/RpcServer.test.ts`` (each
docstring is the Effect test title)."""

from __future__ import annotations

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
import json
from typing import Any, TypedDict

import pyfect as fx
from pyfect import effect, layer, sink, stream, testing
from pyfect import schema as S
from pyfect.deferred import Deferred
from pyfect.exit import Failure, Success
from pyfect.exit import succeed as succeed_exit
from pyfect.queue import Queue
from pyfect.rpc import RpcGroup, make
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server
from pyfect.rpc.message import Ack, ClientEnd, Eof, Interrupt, Request, ResponseExit
from pyfect.stdio import layer_test


class Wait(RpcGroup):
    wait = make("wait", success=S.String)


class Hello(RpcGroup):
    hello = make("hello", success=S.String)


class Empty(RpcGroup):
    pass


def _line(tag: str) -> bytes:
    return (
        json.dumps({"_tag": "Request", "id": 1, "tag": tag, "payload": None, "headers": []}) + "\n"
    ).encode()


def _output_into(lines: list[str], *then: Any) -> Any:
    def stdout(*, end_on_done: bool = False) -> Any:
        def write(data: str | bytes) -> Any:
            lines.append(data if isinstance(data, str) else data.decode())
            return then[0] if then else effect.void

        return sink.for_each(write)

    return stdout


def _messages(lines: list[str]) -> list[Any]:
    return [json.loads(line) for line in "".join(lines).strip().split("\n") if line]


def _server(group: type[RpcGroup], handlers: Any, stdio: Any) -> Any:
    served = rpc_server.layer(group)
    if handlers is not None:
        served = served.pipe(layer.provide(handlers))
    return (
        served.pipe(layer.provide(rpc_server.layer_protocol_stdio))
        .pipe(layer.provide(rs.layer_ndjson))
        .pipe(layer.provide(stdio))
    )


@testing.effect
def test_should_drain_the_response_when_stdin_ends_during_request_startup():
    """RpcServer / should drain the response when stdin ends during request startup"""
    started = Deferred[None]()
    finish = Deferred[None]()
    output: list[str] = []
    handlers = Wait.to_layer(
        Wait.handlers().handle(Wait.wait)(
            lambda _: started.succeed(None).flat_map(lambda _: finish.wait()).map(lambda _: "done")
        )
    )
    stdio = layer_test(
        stdin=stream.make(_line("wait")).concat(stream.from_effect_drain(started.wait())),
        stdout=_output_into(output),
    )
    server = yield from _server(Wait, handlers, stdio).launch().fork_scoped()
    yield from started.wait()
    yield from finish.succeed(None)
    yield from server.await_exit()
    assert _messages(output) == [
        {"_tag": "Exit", "requestId": 1, "exit": {"_tag": "Success", "value": "done"}}
    ]


@testing.effect
def test_should_shut_down_when_stdin_ends_after_the_stdio_response_is_written():
    """RpcServer / should shut down when stdin ends after the STDIO response is written"""
    written = Deferred[None]()
    close_stdin = Deferred[None]()
    output: list[str] = []
    handlers = Hello.to_layer(
        Hello.handlers().handle(Hello.hello)(lambda _: effect.succeed("world"))
    )
    stdio = layer_test(
        stdin=stream.make(_line("hello")).concat(stream.from_effect_drain(close_stdin.wait())),
        stdout=_output_into(output, written.succeed(None).as_void()),
    )
    server = yield from _server(Hello, handlers, stdio).launch().fork_scoped()
    yield from written.wait()
    assert _messages(output) == [
        {"_tag": "Exit", "requestId": 1, "exit": {"_tag": "Success", "value": "world"}}
    ]
    yield from close_stdin.succeed(None)
    yield from server.await_exit()


@testing.effect
def test_should_wait_for_a_blocked_stdio_write_before_shutting_down():
    """RpcServer / should wait for a blocked STDIO write before shutting down"""
    write_started = Deferred[None]()
    finish_write = Deferred[None]()
    output: list[str] = []

    def stdout(*, end_on_done: bool = False) -> Any:
        def write(data: str | bytes) -> Any:
            def done(_: object) -> None:
                output.append(data if isinstance(data, str) else data.decode())

            return write_started.succeed(None).flat_map(lambda _: finish_write.wait()).map(done)

        return sink.for_each(write)

    stdio = layer_test(stdin=stream.make(b'{"_tag":"Ping"}\n'), stdout=stdout)
    server = yield from _server(Empty, None, stdio).launch().fork_scoped()
    yield from write_started.wait()
    yield from effect.yield_now()
    assert server.poll_unsafe() is None
    yield from finish_write.succeed(None)
    yield from server.await_exit()
    assert _messages(output) == [{"_tag": "Pong"}]


@testing.effect
def test_should_backpressure_stdio_sends_when_the_output_buffer_is_full():
    """RpcServer / should backpressure STDIO sends when the output buffer is full"""
    ready = Deferred[Any]()
    first_started = Deferred[None]()
    release_first = Deferred[None]()
    overflow_done = Deferred[None]()
    writes = [0]

    def stdout(*, end_on_done: bool = False) -> Any:
        def write(_: object) -> Any:
            index = writes[0]
            writes[0] += 1
            if index == 0:
                return first_started.succeed(None).flat_map(lambda _: release_first.wait())
            return effect.void

        return sink.for_each(write)

    @effect.gen
    def serve():
        protocol = yield from rpc_server.make_protocol_stdio()
        yield from ready.succeed(protocol)
        return (yield from protocol.run(lambda _client, _message: effect.void))

    yield from (
        serve.pipe(fx.provide(layer_test(stdin=stream.never, stdout=stdout)))
        .pipe(fx.provide(rs.layer_json_rpc()))
        .fork_scoped()
    )
    protocol = yield from ready.wait()
    first = yield from protocol.send(0, {"_tag": "Pong"}).fork_scoped()
    yield from first_started.wait()
    for _ in range(8):
        yield from protocol.send(0, {"_tag": "Pong"})
    overflow = yield from (
        protocol.send(0, {"_tag": "Pong"})
        .flat_map(lambda _: overflow_done.succeed(None))
        .fork_scoped()
    )
    yield from effect.yield_now()
    assert writes[0] == 1
    assert not (yield from overflow_done.is_done())
    yield from release_first.succeed(None)
    yield from first.join()
    yield from overflow.join()
    assert writes[0] == 10


class BlockingPayload(TypedDict):
    block: bool


class Blocking(RpcGroup):
    wait = make("wait", payload=S.Struct(BlockingPayload), success=S.String)


@testing.effect
def test_should_accept_cancellation_of_an_active_request_and_reject_new_requests_when_client_input_has_ended():  # noqa: E501
    """RpcServer / should accept cancellation of an active request and reject new requests when client input has ended"""  # noqa: E501
    entered = Deferred[None]()
    interrupted = Deferred[None]()
    release_other = Deferred[None]()
    messages = yield from Queue[Any].unbounded()

    def wait(request: Any) -> Any:
        if request.payload["block"]:
            return (
                entered.succeed(None)
                .flat_map(lambda _: effect.never)
                .on_interrupt(interrupted.succeed(None))
            )
        return release_other.wait().map(lambda _: "kept")

    handlers = Blocking.to_layer(Blocking.handlers().handle(Blocking.wait)(wait))
    server = yield from rpc_server.make_no_serialization(
        Blocking, lambda message: messages.offer(message).as_void()
    ).pipe(fx.provide(handlers))

    def request(request_id: str, *, block: bool) -> Request:
        return Request(request_id, "wait", {"block": block})

    yield from server.write(1, request("same", block=True))
    yield from server.write(2, request("same", block=False))
    yield from entered.wait()
    yield from server.write(1, Eof())
    yield from server.write(2, Eof())
    for message in (
        request("new", block=True),
        Ack("unknown"),
        Eof(),
        Interrupt("unknown"),
    ):
        assert isinstance((yield from server.write(1, message).exit()), Failure)
    assert isinstance((yield from server.write(1, Interrupt("same")).exit()), Success)
    yield from interrupted.wait()
    cancelled = yield from messages.take()
    assert isinstance(cancelled, ResponseExit)
    assert cancelled.client_id == 1
    assert isinstance(cancelled.exit, Failure)
    assert (yield from messages.take()) == ClientEnd(1)
    yield from release_other.succeed(None)
    kept = yield from messages.take()
    assert isinstance(kept, ResponseExit)
    assert (kept.client_id, kept.request_id, kept.exit) == (2, "same", succeed_exit("kept"))
    assert (yield from messages.take()) == ClientEnd(2)
