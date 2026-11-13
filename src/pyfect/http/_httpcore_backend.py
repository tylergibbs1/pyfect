"""httpcore's connections, closed when a cancel leaves one open with nobody to close it.

httpcore (1.0.9) on anyio (4.15.1) leaks a connection when a cancel lands:

- as anyio finishes connecting: the socket is open but never handed on;
- in the TLS handshake: httpcore closes the stream when the handshake fails, not when
  it is cancelled (``except Exception``);
- between connecting and the HTTP/1.1 request starting: the connection stays ``NEW`` in
  the pool for good (never handed to another request, never expired);
- while a response releases its connection: it stays ``ACTIVE``, since the response
  stream counts as closed before the release finishes.

``close_cancelled_connections`` gives each connection pool of an ``httpx.AsyncClient`` a
network backend and connections that close what such a cancel left behind
(``tests/test_httpx_client_cancel_sweep.py`` cancels a request at every turn of its life).
"""

from __future__ import annotations

import asyncio
import functools
from collections.abc import AsyncIterator, Callable, Coroutine
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from pyfect._extras import missing_extra
from pyfect.http._httpx_options import import_httpx

if TYPE_CHECKING:
    import ssl
    from collections.abc import Iterable

    import httpcore
    import httpx
    from httpcore._synchronization import AsyncShieldCancellation


class _Stream:
    """An ``httpcore.AsyncNetworkStream`` (httpcore calls it by its methods)."""

    __slots__ = ("_stream",)

    def __init__(self, stream: httpcore.AsyncNetworkStream) -> None:
        self._stream = stream

    async def read(self, max_bytes: int, timeout: float | None = None) -> bytes:
        return await self._stream.read(max_bytes, timeout)

    async def write(self, buffer: bytes, timeout: float | None = None) -> None:
        await self._stream.write(buffer, timeout)

    async def aclose(self) -> None:
        await self._stream.aclose()

    async def start_tls(
        self,
        ssl_context: ssl.SSLContext,
        server_hostname: str | None = None,
        timeout: float | None = None,
    ) -> _Stream:
        try:
            secured = await self._stream.start_tls(ssl_context, server_hostname, timeout)
        except BaseException:
            await self._stream.aclose()
            raise
        return _Stream(secured)

    def get_extra_info(self, info: str) -> Any:
        return self._stream.get_extra_info(info)


class _Backend:
    """An ``httpcore.AsyncNetworkBackend``."""

    __slots__ = ("_backend",)

    def __init__(self, backend: httpcore.AsyncNetworkBackend) -> None:
        self._backend = backend

    async def connect_tcp(
        self,
        host: str,
        port: int,
        timeout: float | None = None,
        local_address: str | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> _Stream:
        return await _connect(
            self._backend.connect_tcp(host, port, timeout, local_address, socket_options)
        )

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> _Stream:
        return await _connect(self._backend.connect_unix_socket(path, timeout, socket_options))

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


_CLOSING: set[asyncio.Task[None]] = set()
"""Closes of streams whose connect was cancelled, held until they finish."""


async def _connect(connecting: Coroutine[Any, Any, httpcore.AsyncNetworkStream]) -> _Stream:
    """Run ``connecting`` where a cancel cannot reach it: anyio (4.15.1) leaves the
    socket of a connect cancelled as it succeeds open, and nothing holds it. A
    cancelled caller returns at once; the connect finishes and its stream is closed."""
    task = asyncio.ensure_future(connecting)
    try:
        return _Stream(await asyncio.shield(task))
    except asyncio.CancelledError:
        task.add_done_callback(_close_connected)
        raise


def _close_connected(task: asyncio.Future[httpcore.AsyncNetworkStream]) -> None:
    if task.cancelled() or task.exception() is not None:
        return
    closing = asyncio.ensure_future(task.result().aclose())
    _CLOSING.add(closing)
    closing.add_done_callback(_CLOSING.discard)


class _Connection:
    """An ``httpcore.AsyncConnectionInterface`` that closes its HTTP/1.1 connection when
    a cancel leaves it busy with nobody using it: still ``NEW`` once the request it was
    made for failed (no other request is handed a ``NEW`` one), or still ``ACTIVE`` once
    its response was closed. A failed request's ``ACTIVE`` connection may be another
    request's (httpcore's ``ConnectionNotAvailable``), so it is left alone."""

    __slots__ = ("_connection",)

    def __init__(self, connection: httpcore.AsyncConnectionInterface) -> None:
        self._connection = connection

    async def handle_async_request(self, request: httpcore.Request) -> httpcore.Response:
        try:
            response = await self._connection.handle_async_request(request)
        except BaseException:
            await self._close_if(_internals().unstarted)
            raise
        response.stream = _ResponseStream(response.stream, self)
        return response

    async def close_if_released_busy(self) -> None:
        """Called once this connection's response is closed."""
        await self._close_if(_internals().busy)

    async def _close_if(self, states: frozenset[object]) -> None:
        if _in_state(self._connection, states):
            with _internals().shield():
                await self._connection.aclose()

    async def aclose(self) -> None:
        await self._connection.aclose()

    def can_handle_request(self, origin: httpcore.Origin) -> bool:
        return self._connection.can_handle_request(origin)

    def is_available(self) -> bool:
        return self._connection.is_available()

    def has_expired(self) -> bool:
        return self._connection.has_expired()

    def is_idle(self) -> bool:
        return self._connection.is_idle()

    def is_closed(self) -> bool:
        return self._connection.is_closed()

    def info(self) -> str:
        return self._connection.info()

    def __repr__(self) -> str:
        return repr(self._connection)


class _ResponseStream:
    """A response's byte stream that, closed, leaves its connection idle or closed:
    httpcore marks the stream closed before waiting to release the connection, so a
    cancel in that wait left the connection ``ACTIVE`` for good."""

    __slots__ = ("_connection", "_stream")

    def __init__(self, stream: Any, connection: _Connection) -> None:
        self._stream = stream
        self._connection = connection

    def __aiter__(self) -> AsyncIterator[bytes]:
        return self._stream.__aiter__()

    async def aclose(self) -> None:
        try:
            await self._stream.aclose()
        finally:
            await self._connection.close_if_released_busy()


@dataclass(frozen=True, slots=True)
class _Internals:
    connection: type[httpcore.AsyncHTTPConnection]
    http11: type[httpcore.AsyncHTTP11Connection]
    unstarted: frozenset[object]
    busy: frozenset[object]
    shield: Callable[[], AsyncShieldCancellation]


@functools.cache
def _internals() -> _Internals:
    """The httpcore internals the connections read; resolved when a client is made,
    so a new httpcore that moves them fails there, not in a request's error path."""
    try:
        import httpcore
        from httpcore._async.http11 import HTTPConnectionState
        from httpcore._synchronization import AsyncShieldCancellation
    except ImportError as error:
        raise missing_extra("pyfect.http.httpx_client", "httpx", error) from error
    return _Internals(
        httpcore.AsyncHTTPConnection,
        httpcore.AsyncHTTP11Connection,
        frozenset({HTTPConnectionState.NEW}),
        frozenset({HTTPConnectionState.NEW, HTTPConnectionState.ACTIVE}),
        AsyncShieldCancellation,
    )


def _in_state(connection: httpcore.AsyncConnectionInterface, states: frozenset[object]) -> bool:
    """An HTTP/1.1 connection in one of ``states`` (HTTP/2 ones serve several requests)."""
    internals = _internals()
    if not isinstance(connection, internals.connection):
        return False
    inner = connection._connection  # pyright: ignore[reportPrivateUsage]
    return isinstance(inner, internals.http11) and inner._state in states  # pyright: ignore[reportPrivateUsage]


def _wrap_new_connections(pool: httpcore.AsyncConnectionPool) -> None:
    create = pool.create_connection

    def create_connection(origin: httpcore.Origin) -> _Connection:
        return _Connection(create(origin))

    pool.create_connection = create_connection  # pyright: ignore[reportAttributeAccessIssue]


def close_cancelled_connections(client: httpx.AsyncClient) -> None:
    """Install the closing backend and connections on every connection pool ``client``
    sends through (its own transport's and each mount's; other transports have no pool)."""
    httpx_module = import_httpx()
    _internals()
    transports: list[object] = [client._transport, *client._mounts.values()]  # pyright: ignore[reportPrivateUsage]
    for transport in transports:
        if isinstance(transport, httpx_module.AsyncHTTPTransport):
            pool = transport._pool  # pyright: ignore[reportPrivateUsage]
            if not isinstance(pool._network_backend, _Backend):  # pyright: ignore[reportPrivateUsage]
                # Duck-typed: httpcore calls a backend and a connection by their methods.
                pool._network_backend = _Backend(pool._network_backend)  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue]
                _wrap_new_connections(pool)
