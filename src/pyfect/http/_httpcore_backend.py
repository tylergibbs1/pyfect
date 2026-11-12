"""httpcore's connections, closed when a TLS handshake is cancelled.

httpcore (1.0.9) closes a new connection's TCP stream when its TLS handshake fails, but
not when the handshake is cancelled (``except Exception``), and nothing above holds the
stream yet: every request interrupted mid-handshake left its socket open for good
(``tests/test_httpx_client_handshake_cancel.py``). ``close_cancelled_handshakes`` gives
each connection pool of an ``httpx.AsyncClient`` a network backend that closes the
stream whatever ends the handshake.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from pyfect.http._httpx_options import import_httpx

if TYPE_CHECKING:
    import ssl
    from collections.abc import Iterable

    import httpcore
    import httpx


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
        stream = await self._backend.connect_tcp(host, port, timeout, local_address, socket_options)
        return _Stream(stream)

    async def connect_unix_socket(
        self,
        path: str,
        timeout: float | None = None,
        socket_options: Iterable[httpcore.SOCKET_OPTION] | None = None,
    ) -> _Stream:
        return _Stream(await self._backend.connect_unix_socket(path, timeout, socket_options))

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


def close_cancelled_handshakes(client: httpx.AsyncClient) -> None:
    """Install the closing backend on every connection pool ``client`` sends through
    (its own transport's and each mount's; other transports have no pool)."""
    httpx_module = import_httpx()
    transports: list[object] = [client._transport, *client._mounts.values()]  # pyright: ignore[reportPrivateUsage]
    for transport in transports:
        if isinstance(transport, httpx_module.AsyncHTTPTransport):
            pool = transport._pool  # pyright: ignore[reportPrivateUsage]
            if not isinstance(pool._network_backend, _Backend):  # pyright: ignore[reportPrivateUsage]
                # Duck-typed: httpcore calls a backend by its methods only.
                pool._network_backend = _Backend(pool._network_backend)  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue]
