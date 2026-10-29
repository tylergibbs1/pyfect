"""Ports of Effect's rpc/RpcClient.test.ts. Each test's docstring is the
Effect test title, prefixed by its describe blocks.

A protocol is a ``ClientProtocolService``; messages are the encoded
``dict``s Effect's protocols carry. Effect dies with strings; here with a
``DecodedDefect`` of the string.

Omitted:
- "releases pending calls when connection defect delivery is interrupted
  and the client closes", "does not fail a new request started
  synchronously during protocol error delivery": they interrupt a fiber
  delivering responses from inside a caller's recovery, an ordering that
  rests on JS's synchronous ``interruptUnsafe`` of a running fiber.
- "decodes responses with the ParseOptions annotation": pyfect has no
  request resolvers inside schema transformations.
- "preserves RpcClientError failures from a reloaded module copy": Python
  has no module copies with their own classes.
"""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownParameterType=false, reportMissingParameterType=false

import json
from collections.abc import Callable
from typing import Any, Never, TypedDict

import pytest

import pyfect as fx
from pyfect import effect, layer, schedule, stream, testing
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.clock import Clock, ClockService
from pyfect.context import Reference
from pyfect.deferred import Deferred
from pyfect.duration import Seconds
from pyfect.http import client as http_client
from pyfect.http import response as http_response
from pyfect.http import router, uvicorn_server
from pyfect.http.client import HttpClient
from pyfect.latch import Latch
from pyfect.option import Some
from pyfect.queue import Queue
from pyfect.rpc import RpcClientDefect, RpcClientError, RpcGroup, make, rpc_schema
from pyfect.rpc import client as rpc_client
from pyfect.rpc import serialization as rs
from pyfect.rpc import server as rpc_server
from pyfect.rpc.client import ClientOptions, ClientProtocol, ClientProtocolService
from pyfect.rpc.message import Request
from pyfect.schema import DecodedDefect
from pyfect.schema import transformation as T
from pyfect.scope import CloseableScope, Scope
from pyfect.socket import (
    Reader,
    Socket,
    SocketCloseError,
    SocketError,
    SocketOpenError,
    SocketReadError,
    Writer,
)
from pyfect.socket import make as socket_make
from pyfect.tracer import CurrentTracer, NativeSpan, SpanRequest, Tracer
from pyfect.workers.worker import Spawner, Worker, WorkerPlatform, WorkerPlatformService
from pyfect.workers.worker_error import WorkerError, WorkerReceiveError


class TestGroup(RpcGroup):
    ping = make("Ping", success=S.String)
    events = make("Events", success=rpc_schema.Stream(S.String, S.Never))


class ChunkGroup(RpcGroup):
    bad = make("Bad", success=rpc_schema.Stream(S.Number, S.Never))
    good = make("Good", success=rpc_schema.Stream(S.String, S.Never))
    unary = make("Unary", success=S.String)


def _run(body: Callable[[], Any]) -> Any:
    return fx.run_sync(fx.scoped(effect.gen(body)).timeout(10).or_die())


type Handle = Callable[[dict[str, Any]], Effect[None]]


def _chunk_protocol(before_interrupt: Effect[None] | None = None):
    """Effect's ``makeChunkProtocol``: a client of ``ChunkGroup`` whose
    protocol records what it sends and hands out its response handler."""
    received = Deferred[Handle]()
    sent = yield from Queue[dict[str, Any]].unbounded()

    def run(_client_id: int, handle: Handle) -> Effect[Any]:
        return received.succeed(handle).flat_map(lambda _: effect.never)

    def send(_client_id: int, message: Any) -> Effect[None]:
        first = (
            before_interrupt
            if before_interrupt is not None and message["_tag"] == "Interrupt"
            else effect.succeed(None)
        )
        return first.flat_map(lambda _: sent.offer(dict(message)).as_void())

    protocol = ClientProtocolService(run, send, False, rs.json.codec_for)
    client = yield from rpc_client.make(ChunkGroup).pipe(
        effect.provide_service(ClientProtocol, protocol)
    )
    handle = yield from received.wait()
    return client, handle, sent


def _request_id(message: dict[str, Any]) -> Any:
    assert message["_tag"] == "Request"
    return message["id"]


def _current() -> fx.Fiber[Any, Any]:
    fiber = fx.Fiber.get_current()
    assert fiber is not None
    return fiber


def _squash_message(exit: Exit.Exit[Any, Any]) -> object:
    assert isinstance(exit, Exit.Failure)
    found = exit.cause.squash()
    return found.value if isinstance(found, DecodedDefect) else found


def test_does_not_fail_a_new_request_started_during_connection_defect_delivery() -> None:
    """RpcClient / does not fail a new request started synchronously during connection defect delivery"""  # noqa: E501

    def body():
        client, handle, sent = yield from _chunk_protocol()
        caller = yield from client.unary().catch_defect(lambda _: client.unary()).exit().fork()
        _request_id((yield from sent.take()))
        yield from effect.yield_now()
        yield from handle({"_tag": "Defect", "defect": "connection defect"})
        retry = _request_id((yield from sent.take()))
        yield from handle(
            {"_tag": "Exit", "requestId": retry, "exit": {"_tag": "Success", "value": "ok"}}
        )
        assert (yield from caller.join()) == Exit.succeed("ok")

    _run(body)


def test_ignores_late_replies_after_terminal_failures() -> None:
    """RpcClient / ignores late replies after terminal failures"""
    decoded_replies = [0]

    def count(value: str) -> str:
        decoded_replies[0] += 1
        return value

    success = S.String.pipe(S.decode_to(S.String, T.transform(decode=count, encode=lambda v: v)))

    class Group(RpcGroup):
        ping = make("Ping", success=success)

    def body():
        received = Deferred[Handle]()
        sent = yield from Queue[dict[str, Any]].unbounded()
        fail_send = [True]
        error = RpcClientError(RpcClientDefect("send failed"))

        def send(_client_id: int, message: Any) -> Effect[None, RpcClientError]:
            offered = sent.offer(dict(message))
            return offered.flat_map(
                lambda _: effect.fail(error) if fail_send[0] else effect.succeed(None)
            )

        protocol = ClientProtocolService(
            lambda _id, handle: received.succeed(handle).flat_map(lambda _: effect.never),
            send,
            False,
            rs.json.codec_for,
        )
        client = yield from rpc_client.make(Group).pipe(
            effect.provide_service(ClientProtocol, protocol)
        )
        handle = yield from received.wait()
        assert (yield from client.ping().flip()) is error
        failed = _request_id((yield from sent.take()))
        yield from handle(
            {"_tag": "Exit", "requestId": failed, "exit": {"_tag": "Success", "value": "late"}}
        )
        assert decoded_replies[0] == 0

        fail_send[0] = False
        terminals: list[dict[str, Any]] = [
            {"_tag": "Defect", "defect": "connection defect"},
            {"_tag": "ClientProtocolError", "error": error},
        ]
        for terminal in terminals:
            caller = yield from client.ping().fork()
            request_id = _request_id((yield from sent.take()))
            yield from effect.yield_now()
            yield from handle(terminal)
            # Resumes go through the scheduler: let the caller run.
            yield from effect.yield_now()
            exit = caller.unsafe_poll()
            assert exit is not None, f"{terminal['_tag']} delivery must complete the caller"
            expected = "connection defect" if terminal["_tag"] == "Defect" else error
            assert _squash_message(exit) == expected
            yield from handle(
                {
                    "_tag": "Exit",
                    "requestId": request_id,
                    "exit": {"_tag": "Success", "value": "late"},
                }
            )
            assert decoded_replies[0] == 0, f"{terminal['_tag']} must release the response decoder"

    _run(body)


def test_isolates_a_malformed_stream_chunk_and_interrupts_its_server_request() -> None:
    """RpcClient / isolates a malformed stream chunk and interrupts its server request"""

    def body():
        client, handle, sent = yield from _chunk_protocol()
        bad = yield from client.bad().run_drain().exit().fork()
        bad_id = _request_id((yield from sent.take()))
        good = yield from client.good().run_collect().fork()
        good_id = _request_id((yield from sent.take()))
        unary = yield from client.unary().fork()
        unary_id = _request_id((yield from sent.take()))

        yield from handle({"_tag": "Chunk", "requestId": bad_id, "values": ["not a number"]})
        bad_exit = yield from bad.join()
        assert isinstance(bad_exit, Exit.Failure)
        assert not bad_exit.cause.has_interrupts_only
        assert (yield from sent.take()) == {"_tag": "Interrupt", "requestId": bad_id}

        yield from handle({"_tag": "Chunk", "requestId": good_id, "values": ["alive"]})
        yield from handle(
            {"_tag": "Exit", "requestId": good_id, "exit": {"_tag": "Success", "value": None}}
        )
        yield from handle(
            {"_tag": "Exit", "requestId": unary_id, "exit": {"_tag": "Success", "value": "ok"}}
        )
        assert list((yield from good.join())) == ["alive"]
        assert (yield from unary.join()) == "ok"

    _run(body)


def test_preserves_cancellation_and_the_server_interrupt_during_chunk_failure_cleanup() -> None:
    """RpcClient / preserves cancellation and the server Interrupt during chunk failure cleanup"""

    def body():
        sending_interrupt = Deferred[None]()
        release_interrupt = Deferred[None]()
        client, handle, sent = yield from _chunk_protocol(
            sending_interrupt.succeed(None).flat_map(lambda _: release_interrupt.wait())
        )
        reader = yield from client.bad().run_drain().fork()
        request_id = _request_id((yield from sent.take()))
        observed = [False]

        def mark() -> None:
            observed[0] = True

        receiver = yield from (
            handle({"_tag": "Chunk", "requestId": request_id, "values": ["not a number"]})
            .on_interrupt(effect.sync(mark))
            .fork()
        )
        yield from sending_interrupt.wait()
        assert isinstance((yield from reader.await_exit()), Exit.Failure)

        me = yield from effect.fiber_id()
        receiver.unsafe_interrupt_as(me)
        yield from release_interrupt.succeed(None)
        receive_exit = yield from receiver.await_exit()
        assert (yield from sent.clear()) == [{"_tag": "Interrupt", "requestId": request_id}]
        assert isinstance(receive_exit, Exit.Failure)
        assert receive_exit.cause.has_interrupts_only
        assert observed[0]

    _run(body)


def test_releases_a_chunk_blocked_on_a_full_buffer_when_its_consumer_is_interrupted() -> None:
    """RpcClient / releases a chunk blocked on a full buffer when its stream consumer is interrupted"""  # noqa: E501

    def body():
        consuming = Deferred[None]()
        client, handle, sent = yield from _chunk_protocol()
        reader = yield from (
            client.good(stream_buffer_size=1)
            .run_for_each(lambda _: consuming.succeed(None).flat_map(lambda _: effect.never))
            .fork()
        )
        request_id = _request_id((yield from sent.take()))
        receiver = yield from handle(
            {"_tag": "Chunk", "requestId": request_id, "values": ["a", "b", "c"]}
        ).fork()
        yield from consuming.wait()
        assert receiver.unsafe_poll() is None
        yield from reader.interrupt()
        assert isinstance((yield from receiver.await_exit()), Exit.Success)
        assert (yield from sent.take()) == {"_tag": "Interrupt", "requestId": request_id}

    _run(body)


def test_does_not_send_interrupt_when_a_failed_streaming_send_closes_its_scope() -> None:
    """RpcClient / does not send Interrupt when a failed streaming send closes its scope"""

    def body():
        sent: list[str] = []

        def on_from_client(options: rpc_client.OnFromClient) -> Effect[None]:
            sent.append(type(options.message).__name__)
            if isinstance(options.message, Request):
                return effect.die(DecodedDefect("send failed"))
            return effect.succeed(None)

        client, _core = yield from rpc_client.make_no_serialization(TestGroup, on_from_client)
        exit = yield from (
            client.events(as_queue=True).flat_map(lambda queue: queue.take()).pipe(fx.scoped).exit()
        )
        assert _squash_message(exit) == "send failed"
        assert sent == ["Request"]

    _run(body)


@pytest.mark.parametrize("consumer", ["queue", "stream"])
def test_releases_the_consumer_when_the_request_write_is_interrupted(consumer: str) -> None:
    """RpcClient / releases the ${consumer} consumer when the request write is interrupted"""

    def body():
        writing = Deferred[fx.Fiber[Any, Any]]()
        sent: list[str] = []

        def on_from_client(options: rpc_client.OnFromClient) -> Effect[None]:
            sent.append(type(options.message).__name__)
            if isinstance(options.message, Request):
                return effect.suspend(
                    lambda: writing.succeed(_current()).flat_map(lambda _: effect.never)
                )
            return effect.succeed(None)

        client, _core = yield from rpc_client.make_no_serialization(TestGroup, on_from_client)
        read: Effect[Any, Any, Any] = (
            client.events(as_queue=True).flat_map(lambda queue: queue.take()).as_void()
            if consumer == "queue"
            else client.events().run_drain()
        )
        reader = yield from read.pipe(fx.scoped).fork()
        writer = yield from writing.wait()
        yield from writer.interrupt()
        read_exit = yield from reader.await_exit()
        assert isinstance(read_exit, Exit.Failure)
        assert read_exit.cause.has_interrupts_only
        assert sent == ["Request", "Interrupt"]

    _run(body)


# --- HTTP ------------------------------------------------------------------------------


def _http_protocol(serialization: Any, body: str) -> Any:
    def send(request: Any, *_: object) -> Effect[Any]:
        return effect.succeed(http_response.make(request, body))

    return (
        rpc_client.layer_protocol_http("http://localhost/rpc")
        .pipe(layer.provide_merge(serialization))
        .pipe(layer.provide_merge(layer.succeed(HttpClient, http_client.make(send))))
    )


@pytest.mark.parametrize(
    ("serialization", "body"),
    [(rs.layer_json, "[]"), (rs.layer_ndjson, "")],
    ids=["unframed", "framed"],
)
def test_fails_request_on_empty_http_response(serialization: Any, body: str) -> None:
    """RpcClient / fails request on empty HTTP response for ${unframed/framed} serialization"""

    def program():
        client = yield from rpc_client.make(TestGroup).pipe(
            fx.provide(_http_protocol(serialization, body))
        )
        exit = yield from client.ping().timeout(1).exit()
        error = _squash_message(exit)
        assert isinstance(error, RpcClientError)
        assert isinstance(error.reason, RpcClientDefect)
        assert error.reason.message == "Received empty HTTP response from RPC server"

    _run(program)


def test_defects_request_when_framed_http_response_closes_before_request_completes() -> None:
    """RpcClient / defects request when framed HTTP response closes before request completes"""
    body = json.dumps({"_tag": "Chunk", "requestId": "0", "values": ["event"]}) + "\n"

    def program():
        client = yield from rpc_client.make(
            TestGroup, ClientOptions(generate_request_id=lambda: "0")
        ).pipe(fx.provide(_http_protocol(rs.layer_ndjson, body)))
        exit = yield from client.events().run_drain().timeout(1).exit()
        error = _squash_message(exit)
        assert isinstance(error, RpcClientError)
        assert isinstance(error.reason, RpcClientDefect)
        assert error.reason.message == "HTTP response ended before RPC request completed"

    _run(program)


# --- tracing ---------------------------------------------------------------------------


class SpanGroup(RpcGroup):
    ping = make("Echo.Ping", success=S.String)
    events = make("Echo.Events", success=rpc_schema.Stream(S.String, S.Never))


def _traced_call(method: str, **options: Any) -> list[NativeSpan]:
    spans: list[NativeSpan] = []

    def span(request: SpanRequest) -> NativeSpan:
        made = NativeSpan(request)
        spans.append(made)
        return made

    def body():
        cores: list[rpc_client.ClientCore] = []
        server = yield from rpc_server.make_no_serialization(
            SpanGroup,
            lambda response: cores[0].write(response),  # noqa: PLW0108 (made below)
            rpc_server.ServerOptions(**options),
        )
        client, core = yield from rpc_client.make_no_serialization(
            SpanGroup,
            lambda sent: server.write(0, sent.message),
            ClientOptions(supports_ack=True, **options),
        )
        cores.append(core)
        if method == "Ping":
            yield from client.ping()
        else:
            yield from client.events().run_drain()

    handlers = SpanGroup.to_layer(
        SpanGroup.handlers()
        .handle(SpanGroup.ping)(lambda _: effect.succeed("pong"))
        .handle(SpanGroup.events)(lambda _: stream.make("event"))
    )
    program = (
        fx.scoped(effect.gen(body))
        .pipe(fx.provide(handlers))
        .pipe(effect.provide_service(CurrentTracer, Tracer.make(span)))
    )
    fx.run_sync(program.timeout(10).or_die())
    return spans


def test_records_rpc_span_defaults_for_streaming_calls() -> None:
    """RpcClient / tracing / records RPC span defaults for streaming calls"""
    spans = _traced_call("Events")
    assert sorted(span.kind for span in spans) == ["client", "server"]
    for span in spans:
        assert span.name == "Echo.Events"
        assert span.attributes.get("rpc.system.name") == "effect_rpc"
        assert span.attributes.get("rpc.method") == "Echo.Events"


def test_uses_span_prefix_and_span_attributes_for_unary_calls() -> None:
    """RpcClient / tracing / uses spanPrefix and spanAttributes for unary calls"""
    spans = _traced_call(
        "Ping",
        span_prefix="Custom",
        span_attributes={"rpc.system.name": "custom_rpc", "rpc.method": "custom_method"},
    )
    assert sorted(span.kind for span in spans) == ["client", "server"]
    for span in spans:
        assert span.name == "Custom.Echo.Ping"
        assert span.attributes.get("rpc.system.name") == "custom_rpc"
        assert span.attributes.get("rpc.method") == "custom_method"


# --- sockets ---------------------------------------------------------------------------


def _socket(
    pull: Effect[tuple[Any, ...], SocketError],
    write: Callable[[Any], Effect[None, Any]] | None = None,
    *,
    reader: Effect[Reader, SocketError, Any] | None = None,
) -> Any:
    write_one = write or (lambda _data: effect.succeed(None))
    return socket_make(
        reader if reader is not None else effect.succeed(Reader(pull)),
        effect.succeed(Writer(write_one, lambda chunks: write_one(chunks[0]))),
    )


def _frames_socket():
    """Effect's ``makeSocketProtocol``: a JSON socket protocol reading the
    frames offered to a queue."""
    frames = yield from Queue[str].unbounded()
    socket = _socket(frames.take().map(lambda frame: (frame,)))
    protocol = yield from (
        rpc_client.make_protocol_socket()
        .pipe(effect.provide_service(Socket, socket))
        .pipe(effect.provide_service(rs.RpcSerialization, rs.json))
    )
    return protocol, frames


def _routing_client(protocol: ClientProtocolService, client_id: int):
    received = yield from Queue[Any].unbounded()
    yield from protocol.run(client_id, lambda message: received.offer(message).as_void()).fork(
        start_immediately=True
    )
    return received


def _late_and_healthy() -> tuple[dict[str, Any], dict[str, Any]]:
    late = {"_tag": "Exit", "requestId": "old", "exit": {"_tag": "Success", "value": "late"}}
    healthy = {"_tag": "Exit", "requestId": "healthy", "exit": {"_tag": "Success", "value": "ok"}}
    return late, healthy


def _ping_request(request_id: str, payload: object = None) -> dict[str, Any]:
    return {"_tag": "Request", "id": request_id, "tag": "Ping", "payload": payload, "headers": []}


@testing.effect
def test_releases_socket_routing_after_an_encoding_defect():
    """RpcClient / releases socket routing after an encoding defect"""
    protocol, frames = yield from _frames_socket()
    received = yield from _routing_client(protocol, 2)
    exit = yield from protocol.send(1, _ping_request("old", object())).exit()
    assert isinstance(exit, Exit.Failure)
    assert exit.cause.has_dies
    yield from protocol.send(2, _ping_request("healthy"))
    late, healthy = _late_and_healthy()
    yield from frames.offer(json.dumps([late, healthy]))
    assert (yield from received.take()) == late
    assert (yield from received.take()) == healthy


@testing.effect
def test_releases_socket_routing_after_a_connection_defect():
    """RpcClient / releases socket routing after a connection defect"""
    protocol, frames = yield from _frames_socket()
    received = yield from _routing_client(protocol, 2)
    yield from protocol.send(1, _ping_request("old"))
    defect = {"_tag": "Defect", "defect": "boom"}
    yield from frames.offer(json.dumps(defect))
    assert (yield from received.take()) == defect
    yield from protocol.send(2, _ping_request("healthy"))
    late, healthy = _late_and_healthy()
    yield from frames.offer(json.dumps([late, healthy]))
    assert (yield from received.take()) == late
    assert (yield from received.take()) == healthy


@testing.effect
def test_does_not_deliver_an_earlier_socket_defect_to_a_client_registered_during_delivery():
    """RpcClient / does not deliver an earlier socket defect to a client registered during delivery"""  # noqa: E501
    protocol, frames = yield from _frames_socket()
    received = yield from Queue[Any].unbounded()

    def first(message: Any) -> Effect[None]:
        if message["_tag"] != "Defect":
            return effect.succeed(None)
        second = protocol.run(2, lambda response: received.offer(response).as_void())
        return second.fork(start_immediately=True).as_void()

    yield from protocol.run(1, first).fork(start_immediately=True)
    reply = {"_tag": "Exit", "requestId": "new", "exit": {"_tag": "Success", "value": "ok"}}
    yield from frames.offer(json.dumps([{"_tag": "Defect", "defect": "boom"}, reply]))
    assert (yield from received.take()) == reply


def _settle():
    """Let the reconnect loop run before moving the clock. Effect resumes a
    callback at once; pyfect resumes through the scheduler, so a retry takes
    more turns than the one ``adjust`` gives before it moves time."""
    for _ in range(50):
        yield from effect.yield_now()


def _open_error() -> SocketError:
    return SocketError(SocketOpenError("Unknown", RuntimeError("connection refused")))


def _failing_after_request(
    on_pull: Effect[None] | None = None,
) -> tuple[Any, Deferred[None]]:
    """A socket whose reads fail to open once the first write happened."""
    request_sent = Deferred[None]()
    before = on_pull or effect.succeed(None)
    pull = (
        request_sent.wait()
        .flat_map(lambda _: before)
        .flat_map(lambda _: effect.fail(_open_error()))
    )
    socket = _socket(pull, lambda _data: request_sent.succeed(None).as_void())
    return socket, request_sent


def _socket_client(socket: Any, options: rpc_client.SocketOptions | None = None, **kwargs: Any):
    protocol = (
        yield from rpc_client.make_protocol_socket(options)
        .pipe(effect.provide_service(Socket, socket))
        .pipe(fx.provide(rs.layer_ndjson))
    )
    return (
        yield from rpc_client.make(TestGroup, ClientOptions(**kwargs)).pipe(
            effect.provide_service(ClientProtocol, protocol)
        )
    )


@testing.effect
def test_reports_transient_socket_open_errors_without_failing_in_flight_streams():
    """RpcClient / reports transient socket open errors without failing in-flight streams"""
    three = Deferred[None]()
    errors: list[RpcClientError] = []
    socket, _sent = _failing_after_request()

    def on_transient(error: RpcClientError) -> Effect[None]:
        def record() -> Effect[None]:
            errors.append(error)
            return three.succeed(None).as_void() if len(errors) == 3 else effect.succeed(None)

        return effect.suspend(record)

    options = rpc_client.SocketOptions(
        retry_transient_errors=True,
        retry_policy=schedule.spaced(0.001),
        on_transient_error=on_transient,
    )
    client = yield from _socket_client(socket, options)
    stream_fiber = yield from client.events().run_drain().fork()
    yield from testing.adjust(0.002)
    yield from three.wait().timeout(1)
    assert len(errors) == 3
    for error in errors:
        assert isinstance(error.reason, SocketOpenError)
    assert stream_fiber.unsafe_poll() is None


@testing.effect
def test_fails_in_flight_streams_on_a_missed_pong_while_retrying_socket_errors():
    """RpcClient / fails in-flight streams on a missed pong while retrying socket errors"""
    request_sent = Deferred[None]()
    writes = [0]

    def write(_data: Any) -> Effect[None]:
        def count() -> None:
            writes[0] += 1

        return effect.sync(count).flat_map(lambda _: request_sent.succeed(None)).as_void()

    socket = _socket(effect.never, write)
    options = rpc_client.SocketOptions(
        retry_transient_errors=True, retry_policy=schedule.spaced(3600)
    )
    client = yield from _socket_client(socket, options)
    stream_fiber = yield from client.events().run_drain().timeout(11).flip().fork()
    yield from request_sent.wait()
    yield from testing.adjust(11)
    error = yield from stream_fiber.join()
    assert writes[0] >= 2
    assert isinstance(error, RpcClientError)
    assert isinstance(error.reason, SocketReadError)


@testing.effect
def test_keeps_in_flight_streams_alive_on_non_pong_frames_without_any_pongs():
    """RpcClient / keeps in-flight streams alive on non-pong frames without any pongs"""
    request_sent = Deferred[None]()
    frames = yield from Queue[str].unbounded()
    events = yield from Queue[str].unbounded()
    socket = _socket(
        frames.take().map(lambda frame: (frame,)),
        lambda _data: request_sent.succeed(None).as_void(),
    )
    client = yield from _socket_client(socket, None, generate_request_id=lambda: "0")
    stream_fiber = yield from client.events().run_for_each(events.offer).fork()
    yield from request_sent.wait()
    for event in ["first", "second", "third"]:
        yield from testing.adjust(4)
        assert stream_fiber.unsafe_poll() is None
        chunk = {"_tag": "Chunk", "requestId": "0", "values": [event]}
        yield from frames.offer(json.dumps(chunk) + "\n")
        assert (yield from events.take()) == event
    yield from testing.adjust(4)
    assert stream_fiber.unsafe_poll() is None


@testing.effect
def test_allows_a_delayed_pong_within_a_custom_ping_timeout_but_fails_after_silence():
    """RpcClient / allows a delayed pong within a custom ping timeout but fails after silence"""
    request_sent = Deferred[None]()
    frame_read = Deferred[None]()
    frames = yield from Queue[str].unbounded()
    socket = _socket(
        frames.take().tap(lambda _: frame_read.succeed(None)).map(lambda frame: (frame,)),
        lambda _data: request_sent.succeed(None).as_void(),
    )
    options = rpc_client.SocketOptions(
        ping_interval=2, ping_timeout=15, retry_policy=schedule.spaced(3600)
    )
    client = yield from _socket_client(socket, options)
    stream_fiber = yield from client.events().run_drain().exit().fork()
    yield from request_sent.wait()
    yield from testing.adjust(12)
    assert stream_fiber.unsafe_poll() is None
    yield from frames.offer(json.dumps({"_tag": "Pong"}) + "\n")
    yield from frame_read.wait()
    yield from testing.adjust(14)
    assert stream_fiber.unsafe_poll() is None
    yield from testing.adjust(2)
    assert stream_fiber.unsafe_poll() is not None
    exit = yield from stream_fiber.join()
    error = _squash_message(exit)
    assert isinstance(error, RpcClientError)
    assert isinstance(error.reason, SocketReadError)


def _hooks(record: Callable[[str], Effect[None]]) -> rpc_client.ConnectionHooksService:
    return rpc_client.ConnectionHooksService(record("connect"), record("disconnect"))


@testing.effect
def test_runs_on_ping_timeout_only_when_a_ping_timeout_drops_the_socket():
    """RpcClient / runs onPingTimeout only when a ping timeout drops the socket"""
    request_sent = Deferred[None]()
    events: list[str] = []

    def record(event: str) -> Effect[None]:
        return effect.sync(lambda: events.append(event))

    close_error = SocketError(SocketCloseError(1006))
    connections = [0]

    def open_reader() -> Reader:
        connections[0] += 1
        if connections[0] == 1:
            return Reader(request_sent.wait().flat_map(lambda _: effect.fail(close_error)))
        return Reader(effect.never)

    socket = _socket(
        effect.never,
        lambda _data: request_sent.succeed(None).as_void(),
        reader=effect.sync(open_reader),
    )
    options = rpc_client.SocketOptions(
        retry_policy=schedule.spaced(20), on_ping_timeout=record("ping timeout")
    )
    protocol = yield from (
        rpc_client.make_protocol_socket(options)
        .pipe(effect.provide_service(Socket, socket))
        .pipe(effect.provide_service(rpc_client.ConnectionHooks, _hooks(record)))
        .pipe(fx.provide(rs.layer_ndjson))
    )
    client = yield from rpc_client.make(TestGroup).pipe(
        effect.provide_service(ClientProtocol, protocol)
    )
    closed = yield from (yield from client.events().run_drain().flip().fork()).join()
    assert isinstance(closed.reason, SocketCloseError)

    yield from testing.adjust(20)
    assert events == ["connect", "disconnect", "connect"]

    stream_fiber = yield from (
        client.events().run_drain().tap_error(lambda _: record("stream failed")).flip().fork()
    )
    yield from testing.adjust(10)
    timed_out = yield from stream_fiber.join()
    assert isinstance(timed_out.reason, SocketReadError)
    assert events == [
        "connect",
        "disconnect",
        "connect",
        "ping timeout",
        "disconnect",
        "stream failed",
    ]


@testing.effect
def test_does_not_run_on_ping_timeout_when_the_ping_timeout_fires_before_the_socket_opens():
    """RpcClient / does not run onPingTimeout when the ping timeout fires before the socket opens"""
    events: list[str] = []

    def record(event: str) -> Effect[None]:
        return effect.sync(lambda: events.append(event))

    socket = _socket(effect.never, reader=effect.never)
    options = rpc_client.SocketOptions(
        retry_policy=schedule.spaced(3600), on_ping_timeout=record("ping timeout")
    )
    protocol = yield from (
        rpc_client.make_protocol_socket(options)
        .pipe(effect.provide_service(Socket, socket))
        .pipe(effect.provide_service(rpc_client.ConnectionHooks, _hooks(record)))
        .pipe(fx.provide(rs.layer_ndjson))
    )
    client = yield from rpc_client.make(TestGroup).pipe(
        effect.provide_service(ClientProtocol, protocol)
    )
    stream_fiber = yield from client.events().run_drain().flip().fork()
    yield from testing.adjust(11)
    error = yield from stream_fiber.join()
    assert isinstance(error.reason, SocketReadError)
    assert events == ["disconnect"]


@testing.effect
def test_fails_in_flight_streams_when_transient_retries_are_exhausted():
    """RpcClient / fails in-flight streams when transient retries are exhausted"""
    socket, _sent = _failing_after_request()
    options = rpc_client.SocketOptions(retry_transient_errors=True, retry_policy=schedule.recurs(2))
    client = yield from _socket_client(socket, options)
    stream_fiber = yield from client.events().run_drain().timeout(1).flip().fork()
    yield from _settle()
    yield from testing.adjust(1)
    error = yield from stream_fiber.join()
    assert isinstance(error, RpcClientError)
    assert isinstance(error.reason, SocketOpenError)


@testing.effect
def test_continues_retrying_when_the_transient_error_hook_defects():
    """RpcClient / continues retrying when the transient error hook defects"""
    attempts = [0]

    def count() -> None:
        attempts[0] += 1

    socket, _sent = _failing_after_request(effect.sync(count))
    options = rpc_client.SocketOptions(
        retry_transient_errors=True,
        retry_policy=schedule.recurs(2),
        on_transient_error=lambda _: effect.die(DecodedDefect("hook defect")),
    )
    client = yield from _socket_client(socket, options)
    stream_fiber = yield from client.events().run_drain().timeout(1).flip().fork()
    yield from _settle()
    yield from testing.adjust(1)
    error = yield from stream_fiber.join()
    assert attempts[0] == 3
    assert isinstance(error, RpcClientError)
    assert isinstance(error.reason, SocketOpenError)


class _LateClock:
    """A clock whose sleeps resume 1ms late (scheduler overhead, made
    deterministic)."""

    def __init__(self, clock: ClockService) -> None:
        self._clock = clock

    def unsafe_now(self) -> float:
        return self._clock.unsafe_now()

    def unsafe_monotonic(self) -> float:
        return self._clock.unsafe_monotonic()

    def unsafe_now_nanos(self) -> int:
        return self._clock.unsafe_now_nanos()

    def unsafe_monotonic_nanos(self) -> int:
        return self._clock.unsafe_monotonic_nanos()

    def sleep(self, seconds: Seconds) -> Effect[None]:
        return self._clock.sleep(Seconds(seconds + 0.001))


@testing.effect
def test_keeps_a_slow_unary_request_alive_when_default_ping_ticks_run_slightly_late():
    """RpcClient / keeps a slow unary request alive when default ping ticks run slightly late"""
    clock = yield from Clock()
    request_sent = Deferred[None]()
    frames = yield from Queue[str].unbounded()
    pings = [0]

    def write(data: Any) -> Effect[None]:
        message = json.loads(data if isinstance(data, str) else data.decode())
        if message["_tag"] == "Ping":
            pings[0] += 1
            return frames.offer(json.dumps({"_tag": "Pong"}) + "\n").as_void()
        if message["_tag"] == "Request":
            return request_sent.succeed(None).as_void()
        return effect.succeed(None)

    socket = _socket(frames.take().map(lambda frame: (frame,)), write)
    protocol = yield from (
        rpc_client.make_protocol_socket()
        .pipe(effect.provide_service(Socket, socket))
        .pipe(fx.provide(rs.layer_ndjson))
        .pipe(effect.provide_service(Clock, _LateClock(clock)))
    )
    client = yield from rpc_client.make(
        TestGroup, ClientOptions(generate_request_id=lambda: "0")
    ).pipe(effect.provide_service(ClientProtocol, protocol))
    response = yield from client.ping().exit().fork()
    yield from request_sent.wait()
    yield from testing.adjust(12)
    exit_message = {"_tag": "Exit", "requestId": "0", "exit": {"_tag": "Success", "value": "slow"}}
    yield from frames.offer(json.dumps(exit_message) + "\n")
    assert (yield from response.join()) == Exit.succeed("slow")
    assert pings[0] >= 2


@testing.effect
def test_closes_the_client_scope_when_a_malformed_chunk_arrives_as_the_socket_closes():
    """RpcClient / closes the client scope when a malformed chunk arrives as the socket closes for good"""  # noqa: E501
    frames = yield from Queue[str, SocketError].unbounded()
    writes = yield from Queue[str].unbounded()
    # Like a disconnected WebSocket, writes wait for a reconnect that never happens.
    open_ = Latch(False)
    connections = [0]

    def reader() -> Effect[Reader]:
        connections[0] += 1
        if connections[0] > 1:
            return effect.never
        open_.unsafe_open()
        return effect.succeed(Reader(frames.take().map(lambda frame: (frame,))))

    socket = _socket(
        effect.never,
        lambda data: open_.when_open(writes.offer(data).as_void()),
        reader=effect.suspend(reader),
    )
    scope = CloseableScope()
    protocol = yield from (
        rpc_client.make_protocol_socket()
        .pipe(effect.provide_service(Socket, socket))
        .pipe(effect.provide_service(rs.RpcSerialization, rs.json))
        .pipe(effect.provide_service(Scope, scope))
    )
    client = yield from (
        rpc_client.make(ChunkGroup)
        .pipe(effect.provide_service(ClientProtocol, protocol))
        .pipe(effect.provide_service(Scope, scope))
    )
    bad = yield from client.bad().run_drain().exit().fork()
    request_id = json.loads((yield from writes.take()))["id"]

    def drop() -> None:
        frames.unsafe_offer(
            json.dumps({"_tag": "Chunk", "requestId": request_id, "values": [None]})
        )
        open_.unsafe_close()
        frames.unsafe_fail_cause(Exit.fail(SocketError(SocketCloseError(1012))).cause)

    yield from effect.sync(drop)
    assert isinstance((yield from bad.join()), Exit.Failure)

    closing = yield from scope.close(Exit.succeed(None)).fork_daemon()
    closed = yield from closing.await_exit().timeout_option(1).fork()
    yield from _settle()
    yield from testing.adjust(1)
    assert isinstance((yield from closed.join()), Some)


# --- HTTP batching ---------------------------------------------------------------------


class EchoValue(TypedDict):
    value: str


class EchoGroup(RpcGroup):
    echo = make("Echo", payload=S.Struct(EchoValue), success=S.String)


def _batching(
    serialization: Any,
    batch: rpc_client.Batch,
    body: Callable[[EchoGroup, Callable[[], int]], Any],
    before_request: Effect[None] | None = None,
) -> Any:
    """Effect's ``makeBatchingClient``: a batching HTTP client of a real
    server, counting the HTTP requests between them."""
    requests = [0]

    def counted(request: Any) -> Effect[Any]:
        def count() -> Effect[Any]:
            requests[0] += 1
            return (before_request or effect.succeed(None)).as_(request)

        return effect.suspend(count)

    handlers = EchoGroup.to_layer(
        EchoGroup.handlers().handle(EchoGroup.echo)(lambda r: effect.succeed(r.payload["value"]))
    )
    server = router.serve(
        rpc_server.layer(EchoGroup)
        .pipe(layer.provide(handlers))
        .pipe(layer.provide_merge(rpc_server.layer_protocol_http("/rpc")))
        .pipe(layer.provide(serialization)),
        disable_logger=True,
        disable_listen_log=True,
    )
    protocol = (
        rpc_client.layer_protocol_http(
            "",
            transform_client=lambda c: c.map_request(
                lambda r: r.append_url("/rpc")
            ).map_request_effect(counted),
            batch=batch,
        )
        .pipe(layer.provide_merge(server))
        .pipe(layer.provide(uvicorn_server.layer_test()))
        .pipe(layer.provide(serialization))
    )

    def program():
        client = yield from rpc_client.make(EchoGroup)
        return (yield from body(client, lambda: requests[0]))

    return fx.run_sync(
        fx.scoped(effect.gen(program)).pipe(fx.provide(protocol)).timeout(10).or_die()
    )


@pytest.mark.parametrize("serialization", [rs.layer_json, rs.layer_ndjson], ids=["json", "ndjson"])
def test_sends_requests_made_within_the_batch_window_as_one_http_request(
    serialization: Any,
) -> None:
    """RpcClient / HTTP batching / sends ${name} requests made within the batch window as one HTTP request"""  # noqa: E501

    def body(client: EchoGroup, http_requests: Callable[[], int]):
        results = yield from fx.all(
            client.echo({"value": "first"}),
            client.echo({"value": "second"}),
            concurrency="unbounded",
        )
        assert results == ("first", "second")
        assert http_requests() == 1

    _batching(serialization, rpc_client.Batch(window=0.05), body)


def test_sends_a_batch_as_soon_as_it_reaches_max_size() -> None:
    """RpcClient / HTTP batching / sends a batch as soon as it reaches maxSize"""

    def body(client: EchoGroup, http_requests: Callable[[], int]):
        results = yield from fx.all(
            client.echo({"value": "first"}),
            client.echo({"value": "second"}),
            concurrency="unbounded",
        )
        assert results == ("first", "second")
        assert http_requests() == 1

    _batching(rs.layer_json, rpc_client.Batch(window=3600, max_size=2), body)


def test_keeps_a_batch_in_flight_when_one_of_its_callers_is_interrupted() -> None:
    """RpcClient / HTTP batching / keeps a batch in flight when one of its callers is interrupted"""
    release = Deferred[None]()

    def body(client: EchoGroup, http_requests: Callable[[], int]):
        interrupted = yield from client.echo({"value": "interrupted"}).fork()
        kept = yield from client.echo({"value": "kept"}).fork()
        yield from fx.sleep(0.05)
        yield from interrupted.interrupt()
        yield from release.succeed(None)
        assert (yield from kept.join()) == "kept"
        assert http_requests() == 1

    _batching(rs.layer_json, rpc_client.Batch(window=0.01), body, release.wait())


class EchoEncodeGate(Reference[Effect[None]], key="RpcClientTest/EchoEncodeGate"):
    """Runs while the client encodes an Echo payload, so a test can hold it."""

    @classmethod
    def default(cls) -> Effect[None]:
        return effect.succeed(None)


def _gated(value: str, _options: object) -> Effect[str]:
    return EchoEncodeGate().flat_map(lambda gate: gate).as_(value)


class GatedValue(TypedDict):
    value: str


class GatedEcho(RpcGroup):
    echo = make(
        "Echo",
        payload=S.Struct(
            GatedValue,
            value=S.String.pipe(
                S.decode_to(
                    S.String,
                    T.transform_effect(decode=lambda v, _o: effect.succeed(v), encode=_gated),
                )
            ),
        ),
        success=S.String,
    )


@testing.effect
def test_interrupts_batches_started_while_the_client_is_shutting_down():
    """RpcClient / HTTP batching / interrupts batches started while the client is shutting down"""
    release = Deferred[None]()
    cleanup_started = Deferred[None]()
    encode_release = Deferred[None]()
    interrupted: list[int] = []
    started = [0]

    # The first HTTP request holds shutdown open while it is interrupted.
    def before_request(request: Any) -> Effect[Any]:
        def run() -> Effect[Any]:
            started[0] += 1
            number = started[0]

            def cleanup() -> Effect[None]:
                first = (
                    cleanup_started.succeed(None).flat_map(lambda _: release.wait())
                    if number == 1
                    else effect.succeed(None)
                )
                return first.flat_map(lambda _: effect.sync(lambda: interrupted.append(number)))

            return effect.never.on_interrupt(effect.suspend(cleanup))

        return effect.suspend(run)

    unreachable = http_client.make(
        lambda *_: effect.die(AssertionError("no request reaches the server"))
    )
    protocol = (
        rpc_client.layer_protocol_http(
            "http://localhost/rpc",
            transform_client=lambda c: c.map_request_effect(before_request),
            batch=rpc_client.Batch(window=0.005),
        )
        .pipe(layer.provide_merge(rs.layer_json))
        .pipe(layer.provide_merge(layer.succeed(HttpClient, unreachable)))
    )
    scope = CloseableScope()
    client = yield from (
        rpc_client.make(GatedEcho)
        .pipe(fx.provide(protocol))
        .pipe(effect.provide_service(Scope, scope))
    )
    yield from client.echo({"value": "first"}).fork()
    # admitted before shutdown, but still encoding its payload
    yield from (
        client.echo({"value": "encoding"})
        .pipe(effect.provide_service(EchoEncodeGate, encode_release.wait()))
        .fork()
    )
    yield from testing.adjust(0.005)
    closing = yield from scope.close(Exit.succeed(None)).fork()
    yield from cleanup_started.wait()
    yield from client.echo({"value": "second"}).fork()
    yield from encode_release.succeed(None)
    yield from testing.adjust(0.005)
    yield from release.succeed(None)
    yield from closing.join()
    # every HTTP request that started was interrupted by the shutdown
    assert len(interrupted) == started[0]


@testing.effect
def test_releases_a_worker_pool_slot_when_the_worker_run_fails():
    """RpcClient / releases a worker pool slot when the worker run fails"""
    run_failure = yield from Deferred[Never, WorkerError].make()
    first_request_sent = yield from Deferred[None].make()
    second_request_sent = yield from Deferred[None].make()
    protocol_error_received = yield from Deferred[None].make()
    sent_request_ids: list[object] = []
    run_count = [0]
    sent_for = {1: first_request_sent, 2: second_request_sent}

    def send(message: Any, _transfers: Any) -> Effect[None, WorkerError]:
        if message["_tag"] != "Request":
            return effect.succeed(None)
        sent_request_ids.append(message["id"])
        found = sent_for.get(message["id"])
        return effect.succeed(None) if found is None else found.succeed(None).as_void()

    def run(_handler: Any, _on_spawn: Any) -> Effect[Never, Any, Any]:
        run_count[0] += 1
        return run_failure.wait() if run_count[0] == 1 else effect.never

    backing = Worker[Any, Any](send=send, run=run)
    platform = WorkerPlatformService(lambda _: effect.succeed(backing))
    protocol = yield from (
        rpc_client.make_protocol_worker(size=1, concurrency=1)
        .pipe(effect.provide_service(WorkerPlatform, platform))
        .pipe(effect.provide_service(Spawner, lambda _: None))
    )
    yield from protocol.run(
        0,
        lambda response: (
            protocol_error_received.succeed(None).as_void()
            if response["_tag"] == "ClientProtocolError"
            else effect.succeed(None)
        ),
    ).fork_scoped()

    def request(id: int) -> dict[str, Any]:
        return {"_tag": "Request", "id": id, "tag": "Test", "payload": None, "headers": []}

    first = yield from protocol.send(0, request(1)).fork()
    yield from first_request_sent.wait()
    yield from run_failure.fail(WorkerError(reason=WorkerReceiveError(message="worker exited")))
    yield from protocol_error_received.wait()

    first_completed = yield from first.join().timeout(1).fork()
    yield from testing.adjust(1)
    yield from first_completed.join()

    second = yield from protocol.send(0, request(2)).fork()
    second_sent = yield from second_request_sent.wait().timeout(1).fork()
    yield from testing.adjust(1)
    yield from second_sent.join()
    yield from second.interrupt()
    assert sent_request_ids == [1, 2]
