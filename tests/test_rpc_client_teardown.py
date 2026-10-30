"""Closing an RPC client releases what a shared protocol holds for it, even
for calls still waiting in fibers outside the client's scope (audit #26):
the server is told to interrupt them, and responses that still arrive for
the closed client are dropped, not buffered for a client that never runs
again."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

import gc
import json
import weakref
from typing import Any, cast

import pyfect as fx
from pyfect import effect, layer, schedule, stream
from pyfect import schema as S
from pyfect.http import client as http_client
from pyfect.http import response as http_response
from pyfect.http.client import HttpClient
from pyfect.queue import Queue
from pyfect.rpc import RpcGroup, make, rpc_schema
from pyfect.rpc import client as rpc_client
from pyfect.rpc import serialization as rs
from pyfect.rpc.client import ClientOptions, ClientProtocol
from pyfect.scope import CloseableScope, Scope
from pyfect.socket import Reader, Socket, Writer
from pyfect.socket import make as socket_make


class Calls(RpcGroup):
    ping = make("Ping", success=S.String)
    events = make("Events", success=rpc_schema.Stream(S.String, S.Never))


class _Message(dict[str, Any]):
    """A server message the test can watch with a weak reference."""


class _Parser:
    """Decodes a frame to the message registered for it, handing the only
    strong reference to the protocol."""

    def __init__(self, messages: dict[str, _Message]) -> None:
        self._messages = messages

    def decode(self, data: Any) -> list[object]:
        key = data.decode() if isinstance(data, bytes) else data
        message = self._messages.pop(key, None)
        return [] if message is None else [message]

    def encode(self, response: object) -> str:
        return json.dumps(response)


def _serialization(messages: dict[str, _Message]) -> rs.RpcSerializationService:
    return rs.RpcSerializationService(
        make_unsafe=lambda: _Parser(messages),
        content_type="application/json",
        includes_framing=False,
        codec_for=rs.json.codec_for,
    )


def _late(messages: dict[str, _Message], frame: str, value: dict[str, Any]) -> weakref.ref[Any]:
    message = _Message(value)
    messages[frame] = message
    return weakref.ref(message)


def _socket_protocol(messages: dict[str, _Message]):
    frames = yield from Queue[str].unbounded()
    written = yield from Queue[dict[str, Any]].unbounded()
    socket = socket_make(
        effect.succeed(Reader(frames.take().map(lambda frame: (frame,)))),
        effect.succeed(
            Writer(
                lambda data: written.offer(json.loads(cast("str", data))).as_void(),
                lambda chunks: written.offer(json.loads(cast("str", chunks[0]))).as_void(),
            )
        ),
    )
    protocol = yield from (
        rpc_client.make_protocol_socket(rpc_client.SocketOptions(retry_policy=schedule.spaced(0)))
        .pipe(effect.provide_service(Socket, socket))
        .pipe(effect.provide_service(rs.RpcSerialization, _serialization(messages)))
    )
    return protocol, frames, written


def _written(written: Queue[dict[str, Any]], tag: str):
    while True:
        message = yield from written.take()
        if message.get("_tag") == tag:
            return message


def _close_client_with_waiting_calls(protocol: Any, written: Queue[dict[str, Any]]):
    """Make a client in its own scope, start a unary call and a stream in
    fibers outside it, and close the client's scope."""
    ids = iter(["unary", "stream"])
    client_scope = CloseableScope()
    client = (
        yield from rpc_client.make(Calls, ClientOptions(generate_request_id=lambda: next(ids)))
        .pipe(effect.provide_service(ClientProtocol, protocol))
        .pipe(effect.provide_service(Scope, client_scope))
    )
    yield from client.ping().ignore().fork()
    yield from _written(written, "Request")
    yield from client.events().run_drain().ignore().pipe(fx.scoped).fork()
    yield from _written(written, "Request")
    yield from client_scope.close(fx.exit.succeed(None))


def _late_responses(messages: dict[str, _Message]) -> tuple[list[str], list[weakref.ref[Any]]]:
    frames: list[str] = []
    refs: list[weakref.ref[Any]] = []
    for n in range(5):
        frames.append(f"chunk{n}")
        refs.append(
            _late(messages, f"chunk{n}", {"_tag": "Chunk", "requestId": "stream", "values": ["x"]})
        )
    frames.append("exit")
    refs.append(
        _late(
            messages,
            "exit",
            {"_tag": "Exit", "requestId": "unary", "exit": {"_tag": "Success", "value": "late"}},
        )
    )
    return frames, refs


def test_closing_a_client_interrupts_its_waiting_calls_on_the_server() -> None:
    def body():
        protocol, _frames, written = yield from _socket_protocol({})
        yield from _close_client_with_waiting_calls(protocol, written)
        interrupt = effect.gen(lambda: _written(written, "Interrupt")).timeout(1)
        first = yield from interrupt
        second = yield from interrupt
        return {first["requestId"], second["requestId"]}

    assert fx.run_sync(fx.scoped(effect.gen(body)).timeout(5).or_die()) == {"unary", "stream"}


def test_responses_for_a_closed_client_are_not_kept() -> None:
    messages: dict[str, _Message] = {}

    def body():
        protocol, frames, written = yield from _socket_protocol(messages)
        yield from _close_client_with_waiting_calls(protocol, written)
        names, refs = _late_responses(messages)
        for name in names:
            yield from frames.offer(name)
        for _ in range(50):
            yield from effect.yield_now()
        # Checked while the protocol is still open.
        gc.collect()
        return [ref() is not None for ref in refs]

    kept = fx.run_sync(fx.scoped(effect.gen(body)).timeout(5).or_die())
    assert kept == [False] * len(kept)


def test_http_responses_for_a_closed_client_are_not_kept() -> None:
    """An HTTP exchange started by a call outside the client's scope keeps
    writing what the server streams after the client closed; the protocol
    drops it (the HTTP transport has no ``Interrupt`` to stop the server)."""
    messages: dict[str, _Message] = {}

    def body():
        frames = yield from Queue[bytes].unbounded()
        posted = yield from Queue[None].unbounded()
        serialization = rs.RpcSerializationService(
            make_unsafe=lambda: _Parser(messages),
            content_type="application/json",
            includes_framing=True,
            codec_for=rs.json.codec_for,
        )

        def send(request: Any, *_: object) -> Any:
            chunks = stream.from_queue(frames)
            return posted.offer(None).as_(http_response.make(request, chunks))

        protocol = yield from ClientProtocol().pipe(
            fx.provide(
                rpc_client.layer_protocol_http("http://localhost/rpc")
                .pipe(layer.provide_merge(layer.succeed(rs.RpcSerialization, serialization)))
                .pipe(layer.provide_merge(layer.succeed(HttpClient, http_client.make(send))))
            )
        )
        client_scope = CloseableScope()
        client = (
            yield from rpc_client.make(Calls, ClientOptions(generate_request_id=lambda: "stream"))
            .pipe(effect.provide_service(ClientProtocol, protocol))
            .pipe(effect.provide_service(Scope, client_scope))
        )
        yield from client.events().run_drain().ignore().pipe(fx.scoped).fork()
        yield from posted.take()
        yield from client_scope.close(fx.exit.succeed(None))
        refs = [
            _late(messages, f"chunk{n}", {"_tag": "Chunk", "requestId": "stream", "values": ["x"]})
            for n in range(5)
        ]
        for n in range(5):
            yield from frames.offer(f"chunk{n}".encode())
        for _ in range(50):
            yield from effect.yield_now()
        gc.collect()
        return [ref() is not None for ref in refs]

    kept = fx.run_sync(fx.scoped(effect.gen(body)).timeout(5).or_die())
    assert kept == [False] * len(kept)
