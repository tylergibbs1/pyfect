"""The remote libSQL client's Hrana streams, against a scripted server."""

import asyncio
import json
from collections.abc import Callable
from typing import Any

import httpx
import pytest

from pyfect.sql.libsql._hrana import RemoteClient
from pyfect.sql.libsql._targets import RemoteTarget
from pyfect.sql.libsql.sdk import LibsqlError


def _client(answer: Callable[[dict[str, Any]], dict[str, Any]]) -> RemoteClient:
    def handle(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=answer(json.loads(request.content)))

    client = RemoteClient(RemoteTarget("http://sqld.test", None))
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))  # pyright: ignore[reportPrivateUsage]
    return client


def test_a_failed_begin_closes_its_stream():
    """Effect's client closes the transaction when its ``BEGIN`` fails; left
    open, the stream holds a slot on the server until sqld expires it."""
    received: list[dict[str, Any]] = []

    def answer(body: dict[str, Any]) -> dict[str, Any]:
        received.append(body)
        if body["requests"][0]["type"] == "close":
            return {"baton": None, "results": [{"type": "ok", "response": {"type": "close"}}]}
        error = {"message": "database is locked", "code": "SQLITE_BUSY"}
        return {"baton": "open-stream", "results": [{"type": "error", "error": error}]}

    client = _client(answer)

    async def begin() -> None:
        await client.transaction("write")

    with pytest.raises(LibsqlError, match="database is locked"):
        asyncio.run(begin())
    assert [(b["baton"], b["requests"][0]["type"]) for b in received] == [
        (None, "execute"),
        ("open-stream", "close"),
    ]


def test_an_interrupted_request_that_then_fails_reports_nothing_to_the_loop():
    """A query whose caller stops waiting leaves its request running, and the
    request's later failure is the stream's to settle, not the loop's to
    report. ``asyncio.shield`` (3.14.7 and some other patch releases) handed
    it to the loop's exception handler as an "exception in shielded future";
    Effect's client reports nothing for an abandoned request."""
    release = asyncio.Event()

    async def handle(request: httpx.Request) -> httpx.Response:
        await release.wait()
        raise httpx.ReadError("closed by the server", request=request)

    client = RemoteClient(RemoteTarget("http://sqld.test", None))
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handle))  # pyright: ignore[reportPrivateUsage]
    reported: list[dict[str, Any]] = []

    async def interrupt_then_fail() -> None:
        asyncio.get_running_loop().set_exception_handler(lambda _, ctx: reported.append(ctx))
        query = asyncio.ensure_future(client.execute("SELECT 1", ()))
        await asyncio.sleep(0)
        query.cancel()
        with pytest.raises(asyncio.CancelledError):
            await query
        release.set()
        for _ in range(10):
            await asyncio.sleep(0)

    asyncio.run(interrupt_then_fail())
    assert reported == []
