"""Port of effect/test/devtools/DevToolsClient.test.ts."""

from __future__ import annotations

import json
from collections.abc import Callable, Sequence
from typing import Any, Literal

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.deferred import Deferred
from pyfect.devtools import client as devtools_client
from pyfect.devtools import layer_socket
from pyfect.latch import Latch
from pyfect.socket import CloseEvent, Reader, Socket, SocketError, Writer
from pyfect.socket import make as make_socket
from pyfect.socket._errors import SocketCloseError, open_error

refused = fx.fail(open_error("connection refused"))


def _close_error(code: int) -> SocketError:
    return SocketError(SocketCloseError(code))


def connection(drop_after: float | None = None):
    """Sends a Pong, then stays idle until the reader scope closes or the
    connection drops."""

    def body():
        closed = Latch()
        yield from fx.add_finalizer(lambda _: closed.open())
        sent = [False]

        def pull() -> Any:
            if not sent[0]:
                sent[0] = True
                return fx.succeed(('{"_tag":"Pong"}\n',))
            disconnected = (
                closed.wait()
                if drop_after is None
                else fx.sleep(drop_after).race_first(closed.wait())
            )
            return disconnected.and_then(fx.fail(_close_error(1006)))

        return Reader(fx.suspend(pull))

    return fx.gen(body)


def _lines(chunk: bytes | str) -> list[Any]:
    text = chunk if isinstance(chunk, str) else chunk.decode()
    return [json.loads(line) for line in text.strip().split("\n") if line]


def _writer(write: Callable[[bytes | str | CloseEvent], fx.Effect[None, Any]]) -> Any:
    def write_all(chunks: Sequence[bytes | str]) -> Any:
        return fx.for_each(chunks, write).as_void()

    return fx.succeed(Writer(write, write_all))


@testing.effect
def test_builds_promptly_when_server_only_responds():
    """builds promptly when the server only responds to client messages"""
    ping = Deferred[None]()

    def write(chunk: bytes | str | CloseEvent) -> Any:
        if isinstance(chunk, CloseEvent):
            return fx.void
        if any(m["_tag"] == "Ping" for m in _lines(chunk)):
            return ping.succeed(None).as_void()
        return fx.void

    def reader():
        # Model asynchronous connection setup before waiting for the client Ping.
        yield from fx.sleep(0.001)
        yield from fx.add_finalizer(lambda _: ping.succeed(None))
        inner = yield from connection()
        return Reader(ping.wait().and_then(inner.pull))

    socket = make_socket(fx.gen(reader), _writer(write))
    built = Deferred[None]()
    yield from (
        layer_socket.build()
        .pipe(fx.provide_service(Socket, socket))
        .and_then(built.succeed(None))
        .fork_scoped()
    )
    yield from testing.adjust(0.1)
    assert (yield from built.is_done())


@testing.effect
def test_closes_scope_while_endpoint_unavailable():
    """closes its scope while the endpoint remains unavailable"""
    unavailable = [True]
    # Restore connectivity only for cleanup after observing shutdown.
    socket = make_socket(
        fx.suspend(lambda: refused if unavailable[0] else connection()),
        _writer(lambda _: fx.void),
    )
    closed = Deferred[None]()
    fiber = yield from (
        fx.scoped(devtools_client.make.pipe(fx.provide_service(Socket, socket)))
        .and_then(closed.succeed(None))
        .fork_scoped()
    )
    yield from testing.adjust(5)
    closed_during_outage = yield from closed.is_done()
    unavailable[0] = False
    yield from testing.adjust(2)
    yield from fiber.join()
    assert closed_during_outage


@pytest.mark.parametrize("scenario", ["healthy", "startup refusal", "connection loss"])
def test_sends_later_spans_after(
    scenario: Literal["healthy", "startup refusal", "connection loss"],
):
    """sends later spans after ${scenario}"""

    @testing.effect
    def run():
        spans: list[Any] = []
        first_connection = [True]

        def write(chunk: bytes | str | CloseEvent) -> Any:
            def record() -> None:
                if isinstance(chunk, CloseEvent):
                    return
                spans.extend(
                    m for m in _lines(chunk) if m["_tag"] == "Span" and m["name"] == "later"
                )

            return fx.sync(record)

        def reader() -> Any:
            first = first_connection[0]
            first_connection[0] = False
            if not first or scenario == "healthy":
                return connection()
            if scenario == "startup refusal":
                return refused
            return connection(drop_after=10)

        socket = make_socket(fx.suspend(reader), _writer(write))

        def program():
            yield from fx.sleep(60)
            yield from fx.void.with_span("later")
            # Allow delivery before closing the client layer.
            yield from fx.sleep(10)

        fiber = yield from (
            fx.gen(program)
            .pipe(
                fx.provide(
                    devtools_client.layer_tracer.pipe(
                        fx.layer.provide(fx.layer.succeed(Socket, socket))
                    )
                )
            )
            .fork_scoped()
        )
        yield from testing.adjust(120)
        yield from fiber.join()
        assert [s["status"]["_tag"] for s in spans] == ["Started", "Ended"]

    run()


@testing.effect
def test_sends_short_lived_span_once_in_each_state():
    """sends a short-lived span once in each state"""
    spans: list[Any] = []
    received = Deferred[None]()

    def write(chunk: bytes | str | CloseEvent) -> Any:
        def record() -> bool:
            if isinstance(chunk, CloseEvent):
                return False
            spans.extend(m for m in _lines(chunk) if m["_tag"] == "Span")
            return len(spans) >= 2

        return fx.sync(record).flat_map(
            lambda done: received.succeed(None).as_void() if done else fx.void
        )

    # Sends one message, then stays idle until the reader scope closes,
    # which fails the suspended pull as the reader contract requires.
    def reader():
        closed = Latch()
        yield from fx.add_finalizer(lambda _: closed.open())
        sent = [False]

        def pull() -> Any:
            if sent[0]:
                return closed.wait().and_then(fx.fail(_close_error(1000)))
            sent[0] = True
            return fx.succeed(('{"_tag":"Pong"}\n',))

        return Reader(fx.suspend(pull))

    socket = make_socket(fx.gen(reader), _writer(write))

    def program():
        yield from fx.void.with_span("child")
        yield from received.wait()

    yield from fx.gen(program).pipe(
        fx.provide(
            devtools_client.layer_tracer.pipe(fx.layer.provide(fx.layer.succeed(Socket, socket)))
        )
    )
    assert [s["status"]["_tag"] for s in spans] == ["Started", "Ended"]
