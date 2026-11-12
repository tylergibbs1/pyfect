"""A guard: a request cancelled at any point leaves no connection behind.

httpcore leaked a connection when a cancel landed in its TLS handshake, and again
between connecting and starting the request (``tests/test_httpx_client_handshake_cancel.py``,
``tests/test_httpx_client_cancelled_connect.py``): both are moments where a connection
exists but nothing that would close it holds it yet. This cancels a request after each
number of event-loop turns over its whole life, on a client set up as pyfect's is, and
checks every time that the pool holds only idle or closed connections and the server
has no more open connections than the pool has idle ones.
"""

from __future__ import annotations

import asyncio
import contextlib

import httpx

from pyfect.http._httpcore_backend import close_cancelled_connections

_RESPONSE = b"HTTP/1.1 200 OK\r\nContent-Length: 2\r\n\r\nok"


async def _leaks(turns: int) -> list[str]:
    """What a request cancelled after ``turns`` event-loop turns left behind."""
    open_on_server: set[asyncio.StreamWriter] = set()

    async def serve(reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        open_on_server.add(writer)
        try:
            while await reader.readuntil(b"\r\n\r\n"):
                writer.write(_RESPONSE)
                await writer.drain()
        except (asyncio.IncompleteReadError, ConnectionError):
            pass
        finally:
            open_on_server.discard(writer)
            writer.close()
            # A reset leaves its error on the stream; collected unread, asyncio logs it.
            with contextlib.suppress(ConnectionError):
                await writer.wait_closed()

    server = await asyncio.start_server(serve, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    async with httpx.AsyncClient() as client:
        close_cancelled_connections(client)
        pool = client._transport._pool  # pyright: ignore[reportPrivateUsage, reportAttributeAccessIssue, reportUnknownMemberType, reportUnknownVariableType]
        request = asyncio.create_task(client.get(f"http://127.0.0.1:{port}/"))
        for _ in range(turns):
            await asyncio.sleep(0)
        request.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await request
        for _ in range(20):
            await asyncio.sleep(0.005)
        connections = list(pool.connections)  # pyright: ignore[reportUnknownMemberType, reportUnknownArgumentType, reportUnknownVariableType]
        busy = [c.info() for c in connections if not (c.is_idle() or c.is_closed())]  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        idle = sum(1 for c in connections if c.is_idle())  # pyright: ignore[reportUnknownMemberType, reportUnknownVariableType]
        server_side = len(open_on_server)
    server.close()
    for writer in open_on_server:
        writer.close()
    await server.wait_closed()
    unowned = [f"{server_side} open on the server, {idle} idle"] if server_side > idle else []
    return busy + unowned  # pyright: ignore[reportUnknownVariableType]


def test_a_request_cancelled_at_any_turn_leaves_no_connection_behind() -> None:
    leaks = {turns: found for turns in range(40) if (found := asyncio.run(_leaks(turns)))}
    assert leaks == {}
