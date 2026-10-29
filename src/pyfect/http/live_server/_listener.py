"""Listening for HTTP connections on the socket loop, and the graceful
shutdown Node's server does when its scope closes: stop accepting, close
idle connections, let the busy ones finish (they close once idle for the
keep-alive timeout) for ``graceful_shutdown_timeout``, then close every
connection."""

from __future__ import annotations

import asyncio
import ssl
import threading
from collections.abc import Callable
from typing import Any, Never

from pyfect._core import Effect
from pyfect.duration import Seconds
from pyfect.effect import gen, suspend, sync
from pyfect.exit import Success
from pyfect.http.live_server._timers import timeout_option
from pyfect.net.net_address import (
    SocketAddress,
    inet_address_from_native_unsafe,
    unix_path_address,
)
from pyfect.scope import CloseableScope, Scope, acquire_release, fork_in
from pyfect.socket._connection import Connection, Signal
from pyfect.socket._loop import get_loop, run
from pyfect.socket.server import SocketServerError, SocketServerOpenError

type Listen = Callable[[Callable[[], Connection]], Any]


class ConnectionState:
    """A connection the server tracks: ``idle`` between requests."""

    __slots__ = ("conn", "idle")

    def __init__(self, conn: Connection) -> None:
        self.conn = conn
        self.idle = True


class Listener:
    """Connections accepted and being served."""

    __slots__ = ("_closed", "_pending", "_serving", "address", "lock", "shutting_down", "signal")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.signal = Signal(self.lock)
        self._pending: list[Connection] = []
        self._serving: set[ConnectionState] = set()
        self._closed = False
        self.shutting_down = False
        self.address: SocketAddress | None = None

    # --- loop side ----------------------------------------------------------

    def made(self, conn: Connection) -> None:
        with self.lock:
            closed = self._closed
            if not closed:
                self._pending.append(conn)
            waiters = self.signal.notify_locked()
        if closed:
            conn.close(graceful=False)
        for wake in waiters:
            wake()

    # --- fiber side -----------------------------------------------------------

    def _take(self) -> list[ConnectionState]:
        with self.lock:
            taken, self._pending = self._pending, []
            states = [ConnectionState(conn) for conn in taken]
            self._serving.update(states)
        return states

    def done(self, state: ConnectionState) -> None:
        with self.lock:
            self._serving.discard(state)
            waiters = self.signal.notify_locked()
        for wake in waiters:
            wake()

    def run(
        self, serve: Callable[[ConnectionState], Effect[None]], shutdown_timeout: Seconds
    ) -> Effect[Never]:
        """Serve every connection, each on a fiber of a scope closed, after
        the graceful shutdown, when this is interrupted."""

        def loop(scope: CloseableScope) -> Effect[Never]:
            def fork_taken():
                for state in self._take():
                    conn = state.conn
                    fiber = yield from fork_in(serve(state), scope)
                    fiber.unsafe_add_observer(lambda _, s=state, c=conn: self._release(s, c))

            hand_over = gen(fork_taken).uninterruptible()

            def forever():
                while True:
                    yield from self.signal.wait(lambda: bool(self._pending))
                    yield from hand_over

            return gen(forever)

        def body():
            scope = CloseableScope()
            closed = self.shutdown(shutdown_timeout).flat_map(lambda _: scope.close(Success(None)))
            return (yield from loop(scope).ensuring(closed))

        return gen(body)

    def _release(self, state: ConnectionState, conn: Connection) -> None:
        conn.close(graceful=True)
        self.done(state)

    def close(self) -> None:
        """Close connections made from now on."""
        with self.lock:
            self._closed = True
            pending, self._pending = self._pending, []
        for conn in pending:
            conn.close(graceful=False)

    def shutdown(self, timeout: Seconds) -> Effect[None]:
        """Stop serving new requests: close the idle connections and wait
        up to ``timeout`` for the busy ones."""

        def start() -> None:
            with self.lock:
                self.shutting_down = True
                self._closed = True
                pending, self._pending = self._pending, []
                idle = [state.conn for state in self._serving if state.idle]
            for conn in pending + idle:
                conn.close(graceful=True)

        drained = timeout_option(self.signal.wait_until(lambda: not self._serving), timeout)
        return sync(start).flat_map(lambda _: drained).as_void()


def _address(server: asyncio.Server) -> SocketAddress:
    name: Any = server.sockets[0].getsockname()
    if isinstance(name, str):
        return unix_path_address(name)
    return inet_address_from_native_unsafe(name[0], name[1])


def listen(
    listen: Listen, tls: ssl.SSLContext | None
) -> Effect[Listener, SocketServerError, Scope]:
    """A listener that stops accepting when the scope closes; each run
    listens anew."""
    return suspend(lambda: _listen(Listener(), listen, tls))


def _listen(
    listener: Listener, listen: Listen, tls: ssl.SSLContext | None
) -> Effect[Listener, SocketServerError, Scope]:

    async def start() -> asyncio.Server:
        return await listen(lambda: Connection(listener.made, server_tls=tls))

    def stop(server: asyncio.Server, _exit: object) -> Effect[None]:
        async def close() -> None:
            loop = get_loop()
            for listening in server.sockets:
                loop.remove_reader(listening.fileno())
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            server.close()

        return run(close).ignore().flat_map(lambda _: sync(listener.close))

    def opened(server: asyncio.Server) -> Listener:
        listener.address = _address(server)
        return listener

    starting = run(start).map_error(lambda cause: SocketServerError(SocketServerOpenError(cause)))
    return acquire_release(starting, stop).map(opened)
