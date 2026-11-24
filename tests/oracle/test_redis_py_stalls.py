"""Ports of Effect's ``platform-node/test/NodeRedis.test.ts`` on ``redis_py``
(Effect's ``NodeRedis``): a loopback peer that accepts connections and
answers only what the test lets it, so a handshake, a command, a
subscriber or a reserved connection stalls, and interrupting it must end
within two seconds and close its socket.

Each test's docstring is the Effect test title. Adapted: the peers answer
redis-py's ``CLIENT SETINFO`` like any other command (Effect turns
node-redis' off with ``disableClientInfo``), and its ``HELLO 3`` as a
server does (redis-py speaks RESP3 by default). ``layer`` also opens a
connection of its own to check the server before it is built; it answers
like the shared client, so the stalling peer's "connection 0" is that
probe.
"""

from __future__ import annotations

import asyncio
import contextlib
import re
import socket
import threading
from collections.abc import Callable, Generator
from typing import Any

import pytest
from _threaded_server import serving

pytest.importorskip("redis")

import pyfect as fx
from pyfect.persistence import redis_py
from pyfect.persistence.redis import Redis, RedisError

_COMMAND = re.compile(rb"\*\d+\r\n\$\d+\r\n(\w+)\r\n")
_WAIT = 10.0
"""How long the test waits for the peer to see something, in seconds."""


def _answer(command: bytes) -> bytes:
    """A server's reply to ``command``: ``HELLO`` gets a map naming the
    protocol, which redis-py checks from 8.2 on, and the rest ``+OK``."""
    if command.upper() == b"HELLO":
        return b"%1\r\n+proto\r\n:3\r\n"
    return b"+OK\r\n"


class _Peer:
    """A loopback server: each connection's data goes to ``on_data`` (which
    may reply on the socket); ``received`` is set at the first data,
    ``closed`` when a connection ``watch`` marked closes."""

    def __init__(self, on_data: Callable[[_Peer, socket.socket, bytes], None] | None = None):
        self._on_data = on_data
        self.received = threading.Event()
        self.closed = threading.Event()
        self.stalled = threading.Event()
        self.order: dict[socket.socket, int] = {}
        self._open = 0
        self._all_closed = threading.Condition()
        self._watched: set[socket.socket] = set()
        self._lock = threading.Lock()
        self._stack = contextlib.ExitStack()
        self.port: int = self._stack.enter_context(serving(self._serve)).port

    def watch(self, connection: socket.socket) -> None:
        with self._lock:
            self._watched.add(connection)

    def all_closed(self, timeout: float) -> bool:
        """Whether every connection made so far closes within ``timeout`` seconds."""
        with self._all_closed:
            return self._all_closed.wait_for(lambda: self._open == 0, timeout)

    def _serve(self, connection: socket.socket, stopping: threading.Event) -> None:
        with self._all_closed:
            self._open += 1
        try:
            self._receive(connection)
        finally:
            with self._all_closed:
                self._open -= 1
                self._all_closed.notify_all()

    def _receive(self, connection: socket.socket) -> None:
        while True:
            try:
                data = connection.recv(65536)
            except OSError:
                data = b""
            if not data:
                break
            self.received.set()
            with self._lock:
                self.order.setdefault(connection, len(self.order))
            if self._on_data is not None:
                self._on_data(self, connection, data)
        with self._lock:
            watched = connection in self._watched or not self._watched
        if watched:
            self.closed.set()

    def close(self) -> None:
        self._stack.close()


def _stalling(stall: Callable[[int, str], bool]) -> _Peer:
    """A peer answering each command (see ``_answer``) but those ``stall`` takes
    (by connection number, in the order connections first send data, and
    command name), which never get a reply."""

    def on_data(peer: _Peer, connection: socket.socket, data: bytes) -> None:
        for match in _COMMAND.finditer(data):
            command = match.group(1).decode().upper()
            if stall(peer.order[connection], command):
                peer.watch(connection)
                peer.stalled.set()
            else:
                connection.sendall(_answer(match.group(1)))

    return _Peer(on_data)


def _awaited(event: threading.Event) -> fx.Effect[None]:
    def wait() -> None:
        assert event.wait(_WAIT), "the peer never saw it"

    return fx.blocking(wait)


def _seen_by_peer(event: threading.Event, fiber: fx.Fiber[Any, Any]) -> fx.Effect[None]:
    """``_awaited(event)``, failing with the program's exit if it ends first
    (a reply the client rejects ends it instead of stalling it)."""

    def ended(exit: fx.Exit[Any, Any]) -> fx.Effect[None]:
        return fx.die(AssertionError(f"the program ended before the peer saw it: {exit}"))

    return _awaited(event).race_first(fiber.await_exit().flat_map(ended))


def _layer(port: int, **options: Any) -> fx.Layer[Any, Any]:
    return redis_py.layer(host="127.0.0.1", port=port, **options)


def _interrupt_within_two_seconds(fiber: fx.Fiber[Any, Any]) -> fx.Effect[None, Any]:
    """Interrupts ``fiber``, which must end within two seconds, and by the
    interrupt: a program that ended on its own was never stalled."""

    def interrupted(exit: fx.Exit[Any, Any]) -> None:
        assert isinstance(exit, fx.Failure) and exit.cause.has_interrupts_only, (
            f"the program ended on its own: {exit}"
        )

    return (
        fiber.interrupt()
        .timeout("2 seconds")
        .flat_map(lambda _: fiber.await_exit())
        .map(interrupted)
    )


def _run(peer: _Peer, body: Callable[[], Generator[Any, Any]]) -> None:
    try:
        fx.run_blocking(fx.scoped(fx.gen(body)))
    finally:
        peer.close()


@pytest.mark.parametrize("tls", [False, True], ids=["Redis", "TLS"])
def test_interrupts_a_stalled_handshake(tls: bool) -> None:
    """NodeRedis / interrupts a stalled ${tls ? "TLS" : "Redis"} handshake"""
    peer = _Peer()

    def body():
        # ``db=1`` sends ``SELECT``, a handshake whatever the version.
        build = fx.scoped(_layer(peer.port, db=1, ssl=tls).build())
        fiber = yield from build.fork()
        yield from _seen_by_peer(peer.received, fiber)
        yield from _interrupt_within_two_seconds(fiber)
        yield from _awaited(peer.closed)

    _run(peer, body)


def test_bounds_shutdown_while_a_command_is_stalled() -> None:
    """NodeRedis / bounds shutdown while a command is stalled"""

    def on_data(peer: _Peer, connection: socket.socket, data: bytes) -> None:
        # Answer the handshake, never PING.
        for match in _COMMAND.finditer(data):
            if match.group(1).upper() == b"PING":
                peer.watch(connection)
                peer.stalled.set()
            else:
                connection.sendall(_answer(match.group(1)))

    peer = _Peer(on_data)

    def body():
        def ping():
            redis = yield from Redis()
            yield from redis.send("PING")

        fiber = yield from fx.gen(ping).pipe(fx.provide(_layer(peer.port))).fork()
        yield from _seen_by_peer(peer.stalled, fiber)
        yield from _interrupt_within_two_seconds(fiber)
        yield from _awaited(peer.closed)

    _run(peer, body)


@pytest.mark.parametrize("command", ["SELECT", "SUBSCRIBE"])
def test_interrupts_a_subscriber_stalled_on(command: str) -> None:
    """NodeRedis / interrupts a subscriber stalled on ${command}"""
    peer = _stalling(lambda connection, received: connection > 0 and received == command)

    def body():
        def subscribe():
            redis = yield from Redis()
            yield from redis.subscribe("channel")

        program = fx.scoped(fx.gen(subscribe)).pipe(fx.provide(_layer(peer.port, db=1)))
        fiber = yield from program.fork()
        yield from _seen_by_peer(peer.stalled, fiber)
        yield from _interrupt_within_two_seconds(fiber)
        yield from _awaited(peer.closed)

    _run(peer, body)


def test_subscribe_returns_once_the_server_confirmed_it() -> None:
    """Adapted: node-redis' ``subscribe`` resolves at the server's reply, so
    a message published once it returned is delivered. The peer holds that
    reply until ``subscribe`` returns (or a second passes): a ``subscribe``
    that returns at the send finds it unsent."""
    returned = threading.Event()
    confirmed = threading.Event()

    def on_data(peer: _Peer, connection: socket.socket, data: bytes) -> None:
        for match in _COMMAND.finditer(data):
            if match.group(1).upper() != b"SUBSCRIBE":
                connection.sendall(_answer(match.group(1)))
                continue
            returned.wait(1.0)
            confirmed.set()
            connection.sendall(b">3\r\n$9\r\nsubscribe\r\n$7\r\nchannel\r\n:1\r\n")

    peer = _Peer(on_data)

    def body():
        redis = yield from Redis()
        yield from redis.subscribe("channel")
        seen = confirmed.is_set()
        returned.set()
        assert seen, "subscribe returned before the server confirmed SUBSCRIBE"

    def run():
        yield from fx.gen(body).pipe(fx.provide(_layer(peer.port)))

    _run(peer, run)


def test_interrupts_a_stalled_reserved_connection() -> None:
    """NodeRedis / interrupts a stalled reserved connection"""
    peer = _stalling(lambda connection, received: connection > 0 and received == "SELECT")

    def body():
        def reserve():
            redis = yield from Redis()
            yield from redis.reserve

        program = fx.scoped(fx.gen(reserve)).pipe(fx.provide(_layer(peer.port, db=1)))
        fiber = yield from program.fork()
        yield from _seen_by_peer(peer.stalled, fiber)
        yield from _interrupt_within_two_seconds(fiber)
        # The connection attempt is aborted rather than left to open later.
        yield from _awaited(peer.closed)

    _run(peer, body)


def test_a_subscriber_outliving_its_client_does_not_reconnect() -> None:
    """Adapted: a subscription made in a scope that outlives the layer's.
    Closing the client closes its subscriber's connection, and redis-py's
    ``PubSub`` reconnects (and subscribes again) inside its retry; a
    reconnected connection then sleeps in the retry's backoff, where
    stopping the loop leaves it open (the unclosed ``Connection`` of the
    0.6.25 release run). The client's close here waits for a second
    ``SUBSCRIBE``, as a loop stopping late on a busy machine would: none
    may come, and the peer sees every connection closed."""
    resubscribed = threading.Event()
    subscribes = [0]

    def on_data(peer: _Peer, connection: socket.socket, data: bytes) -> None:
        for match in _COMMAND.finditer(data):
            if match.group(1).upper() != b"SUBSCRIBE":
                connection.sendall(_answer(match.group(1)))
                continue
            subscribes[0] += 1
            if subscribes[0] > 1:
                resubscribed.set()
            connection.sendall(b">3\r\n$9\r\nsubscribe\r\n$7\r\nchannel\r\n:1\r\n")

    peer = _Peer(on_data)

    def body():
        redis = yield from Redis()
        service = yield from redis_py.RedisPy()
        client: Any = service.client
        close = client.aclose

        async def aclose_late(*args: Any, **kwargs: Any) -> None:
            await close(*args, **kwargs)
            await asyncio.to_thread(resubscribed.wait, 0.5)

        client.aclose = aclose_late
        yield from redis.subscribe("channel")

    def run():
        # The subscription's scope is this one, closed after the layer's.
        yield from fx.gen(body).pipe(fx.provide(_layer(peer.port)))

    try:
        fx.run_blocking(fx.scoped(fx.gen(run)))
        assert not resubscribed.is_set(), "the subscriber reconnected after its client closed"
        assert peer.all_closed(_WAIT), "a connection was left open"
    finally:
        peer.close()


def test_a_reservation_outliving_its_client_does_not_hold_up_shutdown() -> None:
    """Adapted: a reserved connection made in a scope that outlives the
    layer's. The layer's pool waits for the connections it lent, and this one
    returns only when its scope closes, after the layer's: the layer closes
    it instead, a later command on it fails, and the peer sees every
    connection closed."""
    peer = _stalling(lambda _connection, _command: False)

    def body():
        redis = yield from Redis()
        connection = yield from redis.reserve
        assert (yield from connection.send("PING")) == "OK"
        return connection

    def run():
        # The reservation's scope is this one, closed after the layer's.
        connection = yield from fx.gen(body).pipe(fx.provide(_layer(peer.port))).or_die()
        exit_ = yield from connection.send("PING").exit()
        assert isinstance(exit_, fx.Failure) and isinstance(exit_.cause.squash(), RedisError)

    try:
        # Hung before: the run's close waited for the reservation for good.
        fx.run_blocking(fx.scoped(fx.gen(run)))
        assert peer.all_closed(_WAIT), "a connection was left open"
    finally:
        peer.close()
