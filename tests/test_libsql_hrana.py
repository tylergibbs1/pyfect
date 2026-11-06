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
