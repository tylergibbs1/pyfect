"""Ports of Effect's ``platform-node/test/NodeRedis.test.ts`` on ``redis_py``
(Effect's ``NodeRedis``): a loopback peer that accepts connections and
answers only what the test lets it, so a handshake, a command, a
subscriber or a reserved connection stalls, and interrupting it must end
within two seconds and close its socket.

Each test's docstring is the Effect test title. Adapted: the peers answer
redis-py's ``CLIENT SETINFO`` like any other command (Effect turns
node-redis' off with ``disableClientInfo``), and RESP2 is redis-py's
default. ``layer`` also opens a connection of its own to check the server
before it is built; it answers like the shared client, so the stalling
peer's "connection 0" is that probe.
"""

from __future__ import annotations

import re
import socket
import threading
from collections.abc import Callable, Generator
from typing import Any

import pytest

pytest.importorskip("redis")

import pyfect as fx
from pyfect.persistence import redis_py
from pyfect.persistence.redis import Redis

_COMMAND = re.compile(rb"\*\d+\r\n\$\d+\r\n(\w+)\r\n")
_WAIT = 10.0
"""How long the test waits for the peer to see something, in seconds."""


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
        self._watched: set[socket.socket] = set()
        self._sockets: list[socket.socket] = []
        self._lock = threading.Lock()
        self._server = socket.create_server(("127.0.0.1", 0))
        self.port: int = self._server.getsockname()[1]
        threading.Thread(target=self._accept, daemon=True).start()

    def watch(self, connection: socket.socket) -> None:
        with self._lock:
            self._watched.add(connection)

    def _accept(self) -> None:
        while True:
            try:
                connection, _ = self._server.accept()
            except OSError:
                return
            with self._lock:
                self._sockets.append(connection)
            threading.Thread(target=self._serve, args=(connection,), daemon=True).start()

    def _serve(self, connection: socket.socket) -> None:
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
        self._server.close()
        with self._lock:
            sockets = list(self._sockets)
        for connection in sockets:
            connection.close()


def _stalling(stall: Callable[[int, str], bool]) -> _Peer:
    """A peer answering ``+OK`` to each command but those ``stall`` takes
    (by connection number, in the order connections first send data, and
    command name), which never get a reply."""

    def on_data(peer: _Peer, connection: socket.socket, data: bytes) -> None:
        for match in _COMMAND.finditer(data):
            command = match.group(1).decode().upper()
            if stall(peer.order[connection], command):
                peer.watch(connection)
                peer.stalled.set()
            else:
                connection.sendall(b"+OK\r\n")

    return _Peer(on_data)


def _awaited(event: threading.Event) -> fx.Effect[None]:
    def wait() -> None:
        assert event.wait(_WAIT), "the peer never saw it"

    return fx.blocking(wait)


def _layer(port: int, **options: Any) -> fx.Layer[Any, Any]:
    return redis_py.layer(host="127.0.0.1", port=port, **options)


def _interrupt_within_two_seconds(fiber: fx.Fiber[Any, Any]) -> fx.Effect[None, Any]:
    return fiber.interrupt().timeout("2 seconds")


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
        yield from _awaited(peer.received)
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
                connection.sendall(b"+OK\r\n")

    peer = _Peer(on_data)

    def body():
        def ping():
            redis = yield from Redis()
            yield from redis.send("PING")

        fiber = yield from fx.gen(ping).pipe(fx.provide(_layer(peer.port))).fork()
        yield from _awaited(peer.stalled)
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
        yield from _awaited(peer.stalled)
        yield from _interrupt_within_two_seconds(fiber)
        yield from _awaited(peer.closed)

    _run(peer, body)


def test_interrupts_a_stalled_reserved_connection() -> None:
    """NodeRedis / interrupts a stalled reserved connection"""
    peer = _stalling(lambda connection, received: connection > 0 and received == "SELECT")

    def body():
        def reserve():
            redis = yield from Redis()
            yield from redis.reserve

        program = fx.scoped(fx.gen(reserve)).pipe(fx.provide(_layer(peer.port, db=1)))
        fiber = yield from program.fork()
        yield from _awaited(peer.stalled)
        yield from _interrupt_within_two_seconds(fiber)
        # The connection attempt is aborted rather than left to open later.
        yield from _awaited(peer.closed)

    _run(peer, body)
