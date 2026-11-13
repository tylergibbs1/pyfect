"""A request cancelled just after its connection is made closes that connection.

The soak test (tests/soak) found the httpx client's pool filling with HTTP/1.1
connections in the ``NEW`` state, each holding a socket the server had long closed.
httpcore (1.0.9) makes the connection, then takes its state lock to start the request;
a cancel landing in between leaves the connection ``NEW`` for good, since only a
request that started closes it on failure, a ``NEW`` one is never handed to another
request, and only idle ones expire. Once the pool's 100 connections were all ``NEW``,
every request waited for a free one until its timeout.
"""

from __future__ import annotations

import asyncio
import contextlib
from typing import Any

import httpx

from pyfect.http._httpcore_backend import close_cancelled_connections


class _CancelOnConnect:
    """A network backend whose connections cancel the request as httpcore reads their
    TLS state, the moment between httpcore's connect and its request starting."""

    def __init__(self, backend: Any) -> None:
        self._backend = backend

    async def connect_tcp(self, *args: Any, **kwargs: Any) -> Any:
        return _CancellingStream(await self._backend.connect_tcp(*args, **kwargs))

    async def sleep(self, seconds: float) -> None:
        await self._backend.sleep(seconds)


class _CancellingStream:
    def __init__(self, stream: Any) -> None:
        self._stream = stream

    def get_extra_info(self, info: str) -> Any:
        if info == "ssl_object":
            task = asyncio.current_task()
            assert task is not None
            task.cancel()
        return self._stream.get_extra_info(info)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._stream, name)


async def _cancelled_requests(count: int) -> tuple[list[str], int]:
    """The infos of the pool's open connections after ``count`` cancelled requests,
    and how many of the server's connections the client closed."""
    closed_by_client = 0

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        nonlocal closed_by_client
        if await reader.read() == b"":
            closed_by_client += 1
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with httpx.AsyncClient() as client:
        pool = client._transport._pool  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
        pool._network_backend = _CancelOnConnect(pool._network_backend)  # pyright: ignore[reportUnknownMemberType]
        close_cancelled_connections(client)
        for _ in range(count):
            request = asyncio.create_task(client.get(f"http://127.0.0.1:{port}/"))
            with contextlib.suppress(asyncio.CancelledError):
                await request
        await asyncio.sleep(0.1)
        left = [c.info() for c in pool.connections if not c.is_closed()]  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
    server.close()
    await server.wait_closed()
    return left, closed_by_client  # pyright: ignore[reportUnknownVariableType]


def test_a_request_cancelled_after_connecting_closes_its_connection() -> None:
    left, closed_by_client = asyncio.run(_cancelled_requests(3))
    assert left == []
    assert closed_by_client == 3


async def _concurrent_errors(requests: int) -> list[str]:
    """The errors of ``requests`` concurrent requests through a one-connection pool."""

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            while await reader.readuntil(b"\r\n\r\n"):
                await asyncio.sleep(0.001)
                writer.write(b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok")
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            writer.close()
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    errors: list[str] = []
    async with httpx.AsyncClient(limits=httpx.Limits(max_connections=1)) as client:
        close_cancelled_connections(client)

        async def one() -> None:
            try:
                await client.get(f"http://127.0.0.1:{port}/")
            except httpx.HTTPError as error:
                errors.append(repr(error))

        await asyncio.gather(*(one() for _ in range(100)))
    server.close()
    await server.wait_closed()
    return errors


def test_a_connection_another_request_holds_stays_open() -> None:
    """A request the pool hands a connection that is still busy fails with httpcore's
    ``ConnectionNotAvailable`` and is retried: the connection is the other request's,
    so it is left alone (closing it failed half the soak's requests)."""
    assert asyncio.run(_concurrent_errors(100)) == []
