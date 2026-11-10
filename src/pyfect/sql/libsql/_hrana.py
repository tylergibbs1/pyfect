"""A remote libSQL server (sqld, Turso) over Hrana over HTTP, version 2
(``@libsql/client``'s ``http`` client on ``@libsql/hrana-client``), on
httpx.

A statement outside a transaction is one pipeline request that executes
it and closes its stream. A transaction is a stream: ``BEGIN`` opens it,
each statement is a request carrying the stream's baton, and ``COMMIT`` /
``ROLLBACK`` close it.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
from collections.abc import Mapping, Sequence
from typing import Any, cast

from pyfect._extras import missing_extra

try:
    import httpx
except ImportError as error:  # pragma: no cover - depends on the environment
    raise missing_extra("pyfect.sql.libsql's remote client", "httpx", error) from error

from pyfect.sql.libsql._targets import RemoteTarget
from pyfect.sql.libsql._values import to_values
from pyfect.sql.libsql.sdk import (
    LibsqlError,
    ResultSet,
    SdkProtocol,
    TransactionMode,
    Value,
    begin_statement,
)

type _Json = dict[str, Any]


def _encode(value: Value) -> _Json:
    match value:
        case None:
            return {"type": "null"}
        case int():
            return {"type": "integer", "value": str(value)}
        case float():
            return {"type": "float", "value": value}
        case str():
            return {"type": "text", "value": value}
        case bytes():
            return {"type": "blob", "base64": base64.b64encode(value).decode("ascii")}


def _decode(value: _Json) -> Value:
    match value.get("type"):
        case "null":
            return None
        case "integer":
            return int(value["value"])
        case "float":
            return float(value["value"])
        case "text":
            return cast("str", value["value"])
        case "blob":
            data = cast("str", value["base64"])
            return base64.b64decode(data + "=" * (-len(data) % 4), validate=True)
        case other:
            raise LibsqlError(
                f"Received unrecognized type of Value: {other!r}", "HRANA_PROTO_ERROR"
            )


def _result_set(result: _Json) -> ResultSet:
    cols: list[_Json] = result["cols"]
    last = result.get("last_insert_rowid")
    return ResultSet(
        columns=tuple(col.get("name") or "" for col in cols),
        column_types=tuple(col.get("decltype") or "" for col in cols),
        rows=tuple(tuple(_decode(value) for value in row) for row in result["rows"]),
        rows_affected=int(result["affected_row_count"]),
        last_insert_rowid=None if last is None else int(last),
    )


def _response_error(error: Mapping[str, Any]) -> LibsqlError:
    code = error.get("code")
    return LibsqlError(str(error.get("message", "")), code if isinstance(code, str) else "UNKNOWN")


def _http_error(response: httpx.Response) -> LibsqlError:
    message = f"Server returned HTTP status {response.status_code}"
    kind = response.headers.get("content-type", "text/plain")
    if kind == "application/json":
        body = response.json()
        if isinstance(body, dict) and "message" in body:
            return _response_error(cast("_Json", body))
    elif kind.startswith("text/plain"):
        text = response.text.strip()
        if text:
            message += f": {text}"
    return LibsqlError(message, "SERVER_ERROR")


def _retrieve(task: asyncio.Task[Any]) -> None:
    """Marks the outcome of a request nobody waits for as seen."""
    if not task.cancelled():
        task.exception()


class _Stream:
    """One Hrana stream: the baton of its last response, and the URL the
    server asked to be sent the next one.

    A request is never abandoned half way: if the caller stops waiting
    (an interrupt), it goes on, and the stream's next request waits for
    it first, so a transaction still gets its baton back and can roll
    back, as an unawaited ``fetch`` does in Effect's client."""

    __slots__ = ("_base_url", "_baton", "_client", "_pending", "closed")

    def __init__(self, client: RemoteClient) -> None:
        self._client = client
        self._baton: str | None = None
        self._base_url: str = client.target.base_url
        self._pending: asyncio.Task[list[_Json]] | None = None
        self.closed = False

    async def settle(self) -> None:
        """Wait for a request the caller stopped waiting for."""
        pending, self._pending = self._pending, None
        if pending is not None:
            await asyncio.wait([pending])

    async def _pipeline(self, requests: list[_Json]) -> list[_Json]:
        await self.settle()
        if self.closed:
            raise LibsqlError("The stream is closed", "HRANA_CLOSED_ERROR")
        task = asyncio.ensure_future(self._send(requests))
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            if not task.done():
                task.add_done_callback(_retrieve)
                self._pending = task
            raise

    async def _send(self, requests: list[_Json]) -> list[_Json]:
        http = self._client.http()
        try:
            response = await http.post(
                f"{self._base_url}/v2/pipeline",
                json={"baton": self._baton, "requests": requests},
                headers=self._client.headers,
            )
        except BaseException:
            self.closed = True
            raise
        if response.status_code != 200:
            self.closed = True
            raise _http_error(response)
        body: _Json = response.json()
        self._baton = body.get("baton")
        base_url: str | None = body.get("base_url")
        self._base_url = base_url or self._base_url
        results: list[_Json] = body["results"]
        if len(results) != len(requests):
            self.closed = True
            raise LibsqlError(
                "Server returned unexpected number of pipeline results", "HRANA_PROTO_ERROR"
            )
        if self._baton is None:
            self.closed = True
        return results

    async def close(self) -> None:
        """Give the server its stream back, if it kept one. The caller has a
        better error to report, so a failure here is ignored."""
        if self.closed:
            return
        with contextlib.suppress(LibsqlError, httpx.HTTPError):
            await self._pipeline([{"type": "close"}])
        self.closed = True

    async def execute(self, sql: str, args: Sequence[object], *, close: bool) -> ResultSet:
        stmt = {"sql": sql, "args": [_encode(v) for v in to_values(args)], "want_rows": True}
        requests: list[_Json] = [{"type": "execute", "stmt": stmt}]
        if close:
            requests.append({"type": "close"})
        try:
            results = await self._pipeline(requests)
        finally:
            if close:
                self.closed = True
        result = results[0]
        if result.get("type") == "error":
            raise _response_error(result["error"])
        return _result_set(result["response"]["result"])


class RemoteClient:
    """A remote server (``ManagedSdk``)."""

    __slots__ = ("_http", "headers", "target")

    # ``ws:`` and ``wss:`` URLs are served over HTTP too.
    protocol: SdkProtocol = "http"

    def __init__(self, target: RemoteTarget) -> None:
        self.target = target
        self.headers = {"content-type": "application/json"}
        if target.auth_token is not None:
            self.headers["authorization"] = f"Bearer {target.auth_token}"
        self._http: httpx.AsyncClient | None = None

    def http(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=None)
        return self._http

    async def execute(self, sql: str, args: Sequence[object], /) -> ResultSet:
        return await _Stream(self).execute(sql, args, close=True)

    async def transaction(self, mode: TransactionMode, /) -> RemoteTransaction:
        stream = _Stream(self)
        try:
            await stream.execute(begin_statement(mode), (), close=False)
        except LibsqlError:
            await stream.close()
            raise
        return RemoteTransaction(stream)

    async def close(self) -> None:
        if self._http is not None:
            await self._http.aclose()


class RemoteTransaction:
    """A transaction on its own stream."""

    __slots__ = ("_stream",)

    def __init__(self, stream: _Stream) -> None:
        self._stream = stream

    async def execute(self, sql: str, args: Sequence[object], /) -> ResultSet:
        if self._stream.closed:
            raise LibsqlError(
                "Cannot execute statements because the transaction is closed",
                "TRANSACTION_CLOSED",
            )
        return await self._stream.execute(sql, args, close=False)

    async def commit(self) -> None:
        if self._stream.closed:
            raise LibsqlError(
                "Cannot commit the transaction because it is already closed",
                "TRANSACTION_CLOSED",
            )
        await self._stream.execute("COMMIT", (), close=True)

    async def rollback(self) -> None:
        await self._stream.settle()
        if self._stream.closed:
            return
        await self._stream.execute("ROLLBACK", (), close=True)


__all__ = ["RemoteClient", "RemoteTransaction"]
