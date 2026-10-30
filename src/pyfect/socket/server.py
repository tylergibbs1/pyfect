"""Socket servers (Effect's ``SocketServer`` and ``NodeSocketServer``):
listen on the socket loop, hand each connection to a handler.

Connections that arrive before ``run`` (or between runs) wait in a pending
list; ``run`` takes them, and every later one, and forks the handler for
each in a scope of its own, which closes when ``run`` is interrupted. The
loop only appends to the list and wakes ``run``: forking happens on the
running fiber.
"""

from __future__ import annotations

import asyncio
import ssl
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never

from pyfect._core import Effect
from pyfect.cause import Cause
from pyfect.context import Tag
from pyfect.effect import fail, gen, succeed, suspend, sync
from pyfect.errors import TaggedError
from pyfect.exit import Success
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.logger._log import log_unhandled
from pyfect.net.net_address import (
    SocketAddress,
    inet_address_from_native_unsafe,
    unix_path_address,
)
from pyfect.redacted import Redacted
from pyfect.scope import CloseableScope, Scope, acquire_release, fork_in
from pyfect.socket._accepted import Accepted, Handler
from pyfect.socket._connection import Connection
from pyfect.socket._loop import get_loop, run
from pyfect.socket._net import from_connection
from pyfect.socket._socket import PemInput, TlsUpgradeOptions
from pyfect.socket._tls import server_context


@dataclass(eq=False)
class SocketServerOpenError(TaggedError):
    cause: object

    @property
    def message(self) -> str:
        return "Open"


@dataclass(eq=False)
class SocketServerUnknownError(TaggedError):
    cause: object

    @property
    def message(self) -> str:
        return "Unknown"


type SocketServerErrorReason = SocketServerOpenError | SocketServerUnknownError


@dataclass(eq=False)
class SocketServerError(TaggedError):
    reason: SocketServerErrorReason

    def __post_init__(self) -> None:
        self.cause = self.reason.cause

    @property
    def message(self) -> str:
        return self.reason.message


class SocketServerService:
    """A listening server: ``address`` is where it listens; ``run`` hands
    every connection to ``handler`` until interrupted. A handler's failure
    is logged ("Unhandled error in SocketServer"), not propagated."""

    __slots__ = ("_accepted", "address")

    def __init__(self, address: SocketAddress, accepted: Accepted) -> None:
        self.address = address
        self._accepted = accepted

    def run[E, R = Never](self, handler: Handler[E, R]) -> Effect[Never, SocketServerError, R]:
        accepted = self._accepted

        def serve(scope: CloseableScope) -> Effect[Never, Never, R]:
            def fork_taken():
                for incoming in accepted.take():
                    fiber = yield from fork_in(incoming.handle(handler), scope)
                    # The fiber owns the connection even if it is interrupted
                    # before it starts, when the handler's own release never
                    # gets registered.
                    fiber.add_observer_unsafe(lambda _, i=incoming: i.release())

            # Taking and forking is one step: an interrupt between them would
            # drop the taken connections.
            hand_over = gen(fork_taken).uninterruptible()

            def loop():
                while True:
                    yield from accepted.signal.wait(accepted.has_pending)
                    yield from hand_over

            return gen(loop)

        def body():
            scope = CloseableScope()
            return (yield from serve(scope).ensuring(scope.close(Success(None))))

        return gen(body)


class SocketServer(Tag[SocketServerService], key="@effect/platform/SocketServer"):
    """The socket server service."""


def report_unhandled(cause: Cause[object]) -> Effect[None]:
    return log_unhandled("Unhandled error in SocketServer", cause)


class _NetIncoming:
    """An accepted stream connection."""

    __slots__ = ("_conn",)

    def __init__(self, conn: Connection) -> None:
        conn.open = True
        self._conn = conn

    def handle[E, R](self, handler: Handler[E, R]) -> Effect[None, Never, R]:
        opened = acquire_release(
            succeed(self._conn), lambda c, _: sync(lambda: c.close(graceful=True))
        )
        socket = from_connection(opened, tls_server=True)
        return handler(socket).as_void().catch_cause(report_unhandled)

    def release(self) -> None:
        self._conn.close(graceful=True)

    def abort(self) -> None:
        self._conn.close(graceful=False)


type Listen = Callable[[Callable[[], Connection]], Any]
"""Start listening, making each connection's protocol with the factory."""


def _address(server: asyncio.Server) -> SocketAddress:
    name: Any = server.sockets[0].getsockname()
    if isinstance(name, str):
        return unix_path_address(name)
    return inet_address_from_native_unsafe(name[0], name[1])


def _listen(
    listen: Listen, tls: ssl.SSLContext | None = None
) -> Effect[SocketServerService, SocketServerError, Scope]:
    """Each run listens anew, with connections accepted of its own."""
    return suspend(lambda: _listen_with(Accepted(), listen, tls))


def _listen_with(
    accepted: Accepted, listen: Listen, tls: ssl.SSLContext | None
) -> Effect[SocketServerService, SocketServerError, Scope]:

    def made(conn: Connection) -> None:
        accepted.add(_NetIncoming(conn))

    async def start() -> asyncio.Server:
        return await listen(lambda: Connection(made, server_tls=tls))

    def stop(server: asyncio.Server, _exit: object) -> Effect[None]:
        async def close() -> None:
            # Stop accepting, and let connections already accepted finish
            # being made, before closing: asyncio drops a connection whose
            # setup runs after the close, leaving its socket open.
            loop = get_loop()
            for listening in server.sockets:
                loop.remove_reader(listening.fileno())
            await asyncio.sleep(0)
            await asyncio.sleep(0)
            server.close()
            accepted.close()

        return run(close).ignore()

    def opened(server: asyncio.Server) -> SocketServerService:
        return SocketServerService(_address(server), accepted)

    starting = run(start).map_error(lambda cause: SocketServerError(SocketServerOpenError(cause)))
    return acquire_release(starting, stop).map(opened)


def make(
    port: int = 0, host: str | None = None
) -> Effect[SocketServerService, SocketServerError, Scope]:
    """A TCP server listening on ``host:port`` (port 0: any free port; no
    host: every interface), closed with the scope."""
    return _listen(lambda factory: get_loop().create_server(factory, host, port))


def make_unix(path: str) -> Effect[SocketServerService, SocketServerError, Scope]:
    """A server listening on the Unix socket at ``path``."""
    return _listen(lambda factory: get_loop().create_unix_server(factory, path))


def make_tls(
    *,
    cert: PemInput,
    key: Redacted[PemInput] | PemInput,
    port: int = 0,
    host: str | None = None,
    passphrase: Redacted[str] | None = None,
) -> Effect[SocketServerService, SocketServerError, Scope]:
    """A TLS server listening on ``host:port``; a connection reaches the
    handler once its handshake is done."""
    redacted_key = key if isinstance(key, Redacted) else Redacted(key)
    options = TlsUpgradeOptions(cert=cert, key=redacted_key, passphrase=passphrase)

    def body() -> Effect[SocketServerService, SocketServerError, Scope]:
        try:
            context = server_context(options)
        except (OSError, ValueError) as cause:
            return fail(SocketServerError(SocketServerOpenError(cause)))
        return _listen(lambda factory: get_loop().create_server(factory, host, port), context)

    return suspend(body)


def layer(port: int = 0, host: str | None = None) -> Layer[SocketServer, SocketServerError]:
    return layer_effect(SocketServer, make(port, host))


def layer_tls(
    *, cert: PemInput, key: Redacted[PemInput] | PemInput, port: int = 0, host: str | None = None
) -> Layer[SocketServer, SocketServerError]:
    return layer_effect(SocketServer, make_tls(cert=cert, key=key, port=port, host=host))


__all__ = [
    "Listen",
    "SocketServer",
    "SocketServerError",
    "SocketServerErrorReason",
    "SocketServerOpenError",
    "SocketServerService",
    "SocketServerUnknownError",
    "layer",
    "layer_tls",
    "make",
    "make_tls",
    "make_unix",
    "report_unhandled",
]
