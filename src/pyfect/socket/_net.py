"""Live TCP and TLS sockets (Effect's ``NodeSocket``), on the socket loop.

``from_connection`` turns an effect opening a ``Connection`` into a
``SocketService``: each acquisition of its reader opens a connection, and
its writer writes to the connection the current reader opened, waiting for
one. ``make_net``/``make_unix``/``make_tls`` open new connections;
``from_socket`` adopts a connected ``socket.socket``.
"""

from __future__ import annotations

import math
import socket
import ssl
from collections.abc import Callable, Coroutine, Sequence
from typing import Any, Never

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect.channel import unwrap as unwrap_channel
from pyfect.duration import Input as DurationInput
from pyfect.effect import fail, gen, succeed, suspend, sync, void
from pyfect.exit import Exit
from pyfect.latch import Latch
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.scope import Scope, acquire_release
from pyfect.socket._connection import Connection
from pyfect.socket._errors import (
    CloseEvent,
    SocketError,
    close_error,
    open_error,
    read_error,
    upgrade_error,
)
from pyfect.socket._loop import get_loop, run
from pyfect.socket._socket import (
    Chunk,
    Reader,
    Socket,
    SocketChannel,
    SocketService,
    TlsUpgradeOptions,
    Writer,
    encode_chunk,
    make,
    to_channel,
)
from pyfect.socket._tls import (
    ServerSide,
    UpgradeSide,
    check_credentials,
    client_context,
    client_side,
    server_context,
)

type Connect = Callable[[Connection], Coroutine[Any, Any, object]]


class _Current:
    """The connection the current reader opened, which writers use."""

    __slots__ = ("connection", "latch")

    def __init__(self) -> None:
        self.connection: Connection | None = None
        self.latch = Latch(False)


DEFAULT_CHUNK_SIZE = 4096
"""The most chunks a socket's pull gives at once, unless told otherwise."""

_MAX_SAFE_INTEGER = 2**53 - 1


def _chunk_limit(chunk_size: float) -> int | None:
    """``chunk_size`` as a pull limit (``None``: unbounded for ``math.inf``); anything but a
    positive safe integer or infinity is the default, as in Effect."""
    if chunk_size == math.inf:
        return None
    if isinstance(chunk_size, int) and not isinstance(chunk_size, bool):
        if 0 < chunk_size <= _MAX_SAFE_INTEGER:
            return chunk_size
    elif chunk_size.is_integer() and 0 < chunk_size <= _MAX_SAFE_INTEGER:
        return int(chunk_size)
    return DEFAULT_CHUNK_SIZE


def from_connection(
    open: Effect[Connection, SocketError, Scope],
    *,
    upgrade_side: UpgradeSide,
    open_timeout: DurationInput | None = None,
    chunk_size: float = DEFAULT_CHUNK_SIZE,
    target: str | None = None,
) -> SocketService:
    """A socket over the connections ``open`` makes. TLS upgrades take
    ``upgrade_side``; ``open_timeout`` bounds the opening; each pull gives at
    most ``chunk_size`` buffered chunks (``math.inf`` for all of them);
    ``target`` (``host:port``, a path) is named when opening fails."""
    require_effect(open, "open")
    limit = _chunk_limit(chunk_size)
    current = _Current()
    opening = open
    if open_timeout is not None:
        timed_out = open_error(TimeoutError("Connection timed out"), "Timeout", target=target)
        opening = open.timeout_or_else(open_timeout, lambda: fail(timed_out))

    def reader():
        scope = yield from Scope()
        conn: Connection = yield from opening
        state = {"upgradable": True}

        def release(_: Exit[Any, Any]) -> Effect[None]:
            def run_release() -> None:
                # Resume a pull parked in another fiber before detaching.
                conn.fail(close_error(1006))
                current.latch.close_unsafe()
                current.connection = None
                state["upgradable"] = False

            return sync(run_release)

        yield from scope.add_finalizer(release)
        current.connection = conn
        current.latch.open_unsafe()

        def upgrade(options: TlsUpgradeOptions | None) -> Effect[None, SocketError]:
            def start() -> Effect[None, SocketError]:
                if not state["upgradable"]:
                    return fail(upgrade_error(RuntimeError("socket is already upgraded or closed")))
                return _upgrade(conn, options or TlsUpgradeOptions(), upgrade_side).map(
                    lambda _: state.update(upgradable=False)
                )

            return suspend(start)

        return Reader(conn.pull(limit), upgrade)

    def write(chunk: Chunk | CloseEvent) -> Effect[None, SocketError]:
        def start() -> Effect[None, SocketError]:
            conn = current.connection
            if conn is None:
                return current.latch.when_open(write(chunk))
            if isinstance(chunk, CloseEvent):
                if chunk.code > 1000:
                    conn.fail(read_error(ConnectionError(f"closed with code {chunk.code}")))
                conn.close(graceful=False)
                return void
            return conn.write((encode_chunk(chunk),))

        return suspend(start)

    def write_all(chunks: Sequence[Chunk]) -> Effect[None, SocketError]:
        def start() -> Effect[None, SocketError]:
            conn = current.connection
            if conn is None:
                return current.latch.when_open(write_all(chunks))
            return conn.write(tuple(map(encode_chunk, chunks)))

        return suspend(start)

    def end_writing(_writer: Writer, _exit: Exit[Any, Any]) -> Effect[None]:
        def run_end() -> None:
            if current.connection is not None:
                current.connection.end_writing()

        return sync(run_end)

    writer = acquire_release(succeed(Writer(write, write_all)), end_writing)
    return make(gen(reader), writer)


def _upgrade(
    conn: Connection, options: TlsUpgradeOptions, side: UpgradeSide
) -> Effect[None, SocketError]:
    server = isinstance(side, ServerSide)
    problem = check_credentials(options, server=server)
    if problem is not None:
        return fail(upgrade_error(ValueError(problem)))
    try:
        context = server_context(options) if server else client_context(options)
    except (ssl.SSLError, OSError, ValueError) as cause:
        return fail(upgrade_error(cause))
    hostname = None if isinstance(side, ServerSide) else options.servername or side.host

    def failed(cause: BaseException) -> Effect[None, SocketError]:
        error = upgrade_error(cause)
        conn.fail(error)
        conn.close(graceful=False)
        return fail(error)

    def interrupted() -> Effect[None]:
        def tear_down() -> None:
            conn.fail(close_error(1006))
            conn.close(graceful=False)

        return sync(tear_down)

    return (
        conn.upgrade(context, server_side=server, hostname=hostname)
        .catch_all(failed)
        .on_interrupt(interrupted())
    )


def connecting(
    connect: Connect, target: str | None = None
) -> Effect[Connection, SocketError, Scope]:
    """A connection ``connect`` makes on the loop (with the protocol it is
    given), closed with the scope: gracefully once open, at once before.
    A failure to connect names ``target``."""

    def body():
        conn = Connection()
        scope = yield from Scope()
        yield from scope.add_finalizer(lambda _: sync(lambda: conn.close(graceful=conn.open)))
        yield from run(lambda: connect(conn)).map_error(
            lambda cause: open_error(cause, target=target)
        )
        conn.open = True
        return conn

    return gen(body)


def make_net(
    port: int,
    host: str = "localhost",
    *,
    open_timeout: DurationInput | None = None,
    chunk_size: float = DEFAULT_CHUNK_SIZE,
) -> SocketService:
    """A TCP socket connecting to ``host:port``; each pull gives at most
    ``chunk_size`` chunks. A TLS upgrade without a ``servername`` checks the
    certificate against ``host``, or ``localhost`` for an IP literal."""

    async def connect(conn: Connection) -> object:
        return await get_loop().create_connection(lambda: conn, host, port)

    target = _address(host, port)
    return from_connection(
        connecting(connect, target),
        upgrade_side=client_side(host),
        open_timeout=open_timeout,
        chunk_size=chunk_size,
        target=target,
    )


def make_unix(path: str, *, open_timeout: DurationInput | None = None) -> SocketService:
    """A socket connecting to the Unix socket at ``path``."""

    async def connect(conn: Connection) -> object:
        return await get_loop().create_unix_connection(lambda: conn, path)

    return from_connection(
        connecting(connect, path),
        upgrade_side=client_side(None),
        open_timeout=open_timeout,
        target=path,
    )


def make_tls(
    port: int,
    host: str = "localhost",
    *,
    tls: TlsUpgradeOptions | None = None,
    open_timeout: DurationInput | None = None,
    chunk_size: float = DEFAULT_CHUNK_SIZE,
) -> SocketService:
    """A TLS socket connecting to ``host:port``; the certificate is checked
    against ``tls.servername``, else ``host``. Each pull gives at most ``chunk_size``
    chunks."""
    options = tls or TlsUpgradeOptions()

    async def connect(conn: Connection) -> None:
        context = client_context(options)
        await get_loop().create_connection(lambda: conn, host, port)
        await conn.start_tls(context, server_side=False, hostname=options.servername or host)

    target = _address(host, port)
    return from_connection(
        connecting(connect, target),
        upgrade_side=client_side(host),
        open_timeout=open_timeout,
        chunk_size=chunk_size,
        target=target,
    )


def _address(host: str, port: int) -> str:
    return f"[{host}]:{port}" if ":" in host else f"{host}:{port}"


def _adopt(sock: socket.socket) -> Effect[Connection, SocketError, Scope]:
    async def connect(conn: Connection) -> object:
        return await get_loop().connect_accepted_socket(lambda: conn, sock)

    return connecting(connect)


def from_socket(
    open: Effect[socket.socket, SocketError, Scope],
    *,
    tls_server: bool = False,
    open_timeout: DurationInput | None = None,
    chunk_size: float = DEFAULT_CHUNK_SIZE,
) -> SocketService:
    """A socket over the connected ``socket.socket`` each acquisition of
    the reader gets from ``open`` (Effect's ``fromDuplex``); the socket is
    taken over and closed with the reader's scope. ``tls_server`` makes TLS
    upgrades take the server side; each pull gives at most ``chunk_size`` chunks."""
    require_effect(open, "open")
    return from_connection(
        open.flat_map(_adopt),
        upgrade_side=ServerSide() if tls_server else client_side(None),
        open_timeout=open_timeout,
        chunk_size=chunk_size,
    )


def make_net_channel[IE = Never](
    port: int,
    host: str = "localhost",
    *,
    open_timeout: DurationInput | None = None,
    chunk_size: float = DEFAULT_CHUNK_SIZE,
) -> SocketChannel[bytes, IE]:
    service = make_net(port, host, open_timeout=open_timeout, chunk_size=chunk_size)
    return unwrap_channel(succeed(to_channel(service)))


def make_tls_channel[IE = Never](
    port: int,
    host: str = "localhost",
    *,
    tls: TlsUpgradeOptions | None = None,
    open_timeout: DurationInput | None = None,
    chunk_size: float = DEFAULT_CHUNK_SIZE,
) -> SocketChannel[bytes, IE]:
    service = make_tls(port, host, tls=tls, open_timeout=open_timeout, chunk_size=chunk_size)
    return unwrap_channel(succeed(to_channel(service)))


def layer_net(
    port: int,
    host: str = "localhost",
    *,
    open_timeout: DurationInput | None = None,
    chunk_size: float = DEFAULT_CHUNK_SIZE,
) -> Layer[Socket]:
    return layer_effect(
        Socket,
        sync(lambda: make_net(port, host, open_timeout=open_timeout, chunk_size=chunk_size)),
    )


def layer_tls(
    port: int,
    host: str = "localhost",
    *,
    tls: TlsUpgradeOptions | None = None,
    open_timeout: DurationInput | None = None,
    chunk_size: float = DEFAULT_CHUNK_SIZE,
) -> Layer[Socket]:
    return layer_effect(
        Socket,
        sync(
            lambda: make_tls(port, host, tls=tls, open_timeout=open_timeout, chunk_size=chunk_size)
        ),
    )
