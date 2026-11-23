"""(pyfect) A socket client counts a connection's silence from when it first opened.

The pinger starts with the protocol, so a socket that never opens still fails by ping timeout,
as in Effect. When the socket first opens, the pinger's interval restarts there: a request timed
out at twice the interval, from before the open, then ends before the connection is declared
silent, and its retry finds the connection's error rather than a fresh connection. (In Effect
the pinger starts a few milliseconds after the request's timer through scheduling; pyfect
makes the client in the same millisecond, so the two tied.)

Reconnects leave the ticks where they are, as in Effect, whose pinger ticks on from when it
started: two clients made together are declared silent together however long each takes to
reconnect, so a health check pinging two unreachable runners marks both in one round.
"""

from __future__ import annotations

from typing import Any

from pyfect import clock, effect, testing
from pyfect._core import Effect
from pyfect.errors import TimeoutException
from pyfect.queue import Queue
from pyfect.rpc import RpcClientError
from pyfect.rpc import client as rpc_client
from pyfect.rpc import serialization as rs
from pyfect.rpc.client import ClientProtocolService
from pyfect.socket import Reader, Socket, Writer
from pyfect.socket import make as socket_make

_OPENING = "1 millis"
"""How long the socket takes to open: a connect on localhost, made deterministic."""


def _silent_socket() -> Any:
    """A socket that never sends a frame. It opens after ``_OPENING`` the first time and at
    once after that, so a reconnect clears the connection's error as soon as it runs."""
    opened: list[bool] = []

    def open_reader() -> Effect[Reader]:
        first = not opened
        opened.append(True)
        return (clock.sleep(_OPENING) if first else effect.void).as_(Reader(effect.never))

    reader = effect.suspend(open_reader)
    return socket_make(
        reader,
        effect.succeed(Writer(lambda _: effect.succeed(None), lambda _: effect.succeed(None))),
    )


def _slow_to_reconnect_socket() -> Any:
    """A socket that never sends a frame, opens after ``_OPENING`` the first time and after
    ``_REOPENING`` each time after that: a reconnect on a loaded host."""
    opened: list[bool] = []

    def open_reader() -> Effect[Reader]:
        delay = _REOPENING if opened else _OPENING
        opened.append(True)
        return clock.sleep(delay).as_(Reader(effect.never))

    return socket_make(
        effect.suspend(open_reader),
        effect.succeed(Writer(lambda _: effect.succeed(None), lambda _: effect.succeed(None))),
    )


_REOPENING = "300 millis"


def _protocol(socket: Any = None):
    protocol: ClientProtocolService = yield from (
        rpc_client.make_protocol_socket()
        .pipe(effect.provide_service(Socket, socket or _silent_socket()))
        .pipe(effect.provide_service(rs.RpcSerialization, rs.json))
    )
    received = yield from Queue[Any].unbounded()
    yield from protocol.run(1, lambda message: received.offer(message).as_void()).fork(
        start_immediately=True
    )
    return protocol, received


def _request(request_id: str) -> dict[str, Any]:
    return {"_tag": "Request", "id": request_id, "tag": "Ping", "payload": None, "headers": []}


def _settle():
    """Let the forked fibers and the reconnect loop run before the clock moves."""
    for _ in range(50):
        yield from effect.yield_now()


@testing.effect
def test_a_connection_is_declared_silent_two_intervals_after_it_opens_not_after_it_was_made():
    _protocol_service, received = yield from _protocol()
    yield from _settle()
    yield from testing.adjust("10 seconds")
    yield from _settle()
    assert (yield from received.size()) == 0
    yield from testing.adjust(_OPENING)
    yield from _settle()
    message = yield from received.take()
    assert message["_tag"] == "ClientProtocolError"


@testing.effect
def test_a_retry_after_a_request_timeout_finds_the_connections_error():
    protocol, received = yield from _protocol()
    attempt = protocol.send(1, _request("1")).and_then(received.take()).timeout("10 seconds")
    first = yield from attempt.flip().fork()
    yield from _settle()
    yield from testing.adjust("10 seconds")
    yield from _settle()
    timed_out = yield from first.join()
    assert isinstance(timed_out, TimeoutException)
    yield from testing.adjust("500 millis")
    yield from _settle()
    error = yield from protocol.send(1, _request("2")).flip()
    assert isinstance(error, RpcClientError)


@testing.effect
def test_a_slow_reconnect_leaves_the_ping_ticks_where_they_were():
    _protocol_service, received = yield from _protocol(_slow_to_reconnect_socket())
    yield from _settle()
    # Opened at 1 ms: declared silent two intervals later, at 10.001 s.
    yield from testing.adjust("10001 millis")
    yield from _settle()
    first = yield from received.take()
    assert first["_tag"] == "ClientProtocolError"
    # The reconnect starts 500 ms later and opens 300 ms after that, at 10.801 s. The ticks
    # stay on 15.001 s (a ping) and 20.001 s (silent), not 10.801 s plus two intervals.
    yield from testing.adjust("10 seconds")
    yield from _settle()
    assert (yield from received.size()) == 1
    second = yield from received.take()
    assert second["_tag"] == "ClientProtocolError"
