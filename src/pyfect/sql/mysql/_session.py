"""One asyncmy connection, used from the SQL loop thread (``pyfect.sql._loop``).

Statements take turns on it (a lock, as mysql2 queues commands), and a
stream holds the turn until it closes. A prepared statement goes through
``COM_STMT_PREPARE`` / ``COM_STMT_EXECUTE`` (binary protocol), kept
prepared per connection; any other statement is sent as text with its
parameters escaped in (``_bind``), several statements at once allowed.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, cast

from pyfect import _json_text as json_text
from pyfect.sql.mysql import _asyncmy
from pyfect.sql.mysql._asyncmy import Cursor, PreparedStatement, RawConnection
from pyfect.sql.mysql._bind import bind

_STATEMENT_CACHE_SIZE = 256
_STREAM_CHUNK = 128
_KILL_TIMEOUT = 5.0


@dataclass(frozen=True, slots=True)
class ResultSetHeader:
    """What a statement without rows returns (mysql2's ``ResultSetHeader``)."""

    affected_rows: int
    insert_id: int


type Row = dict[str, Any]
type ResultSet = list[Row] | list[tuple[Any, ...]] | ResultSetHeader


def _header(affected_rows: object, insert_id: int) -> ResultSetHeader:
    affected = affected_rows if isinstance(affected_rows, int) else 0
    return ResultSetHeader(affected_rows=affected, insert_id=insert_id)


def _parameter(value: object) -> object:
    """A dict or list as its JSON text (mysql2's ``execute``); asyncmy would
    send its ``repr``."""
    if isinstance(value, dict | list):
        return json_text.stringify(cast("object", value))
    return value


def _parameters(params: Sequence[object]) -> tuple[object, ...]:
    return tuple(_parameter(value) for value in params)


class Session:
    """A connection and its prepared statements."""

    __slots__ = ("_lock", "_options", "_statements", "broken", "raw")

    def __init__(self, raw: RawConnection, options: Mapping[str, Any]) -> None:
        self.raw = raw
        self._options = options
        self._lock = asyncio.Lock()
        self._statements: OrderedDict[str, PreparedStatement] = OrderedDict()
        self.broken = False

    @staticmethod
    async def open(options: Mapping[str, Any]) -> Session:
        return Session(await _asyncmy.connect(options), options)

    @property
    def usable(self) -> bool:
        return not self.broken and self.raw.connected

    def _cut_short(self) -> None:
        # A read cut short leaves the protocol out of step.
        self.broken = True
        self.raw.close()

    # --- statements -----------------------------------------------------------

    async def _prepared(self, sql: str) -> PreparedStatement:
        statements = self._statements
        found = statements.get(sql)
        if found is not None:
            statements.move_to_end(sql)
            return found
        prepared = await self.raw.prepare(sql)
        statements[sql] = prepared
        if len(statements) > _STATEMENT_CACHE_SIZE:
            _, oldest = statements.popitem(last=False)
            await oldest.close()
        return prepared

    async def _execute(
        self, sql: str, params: Sequence[object], as_tuples: bool
    ) -> list[ResultSet]:
        prepared = await self._prepared(sql)
        result = await prepared.execute(_parameters(params))
        description = result.description
        if description is None:
            return [_header(result.affected_rows, result.insert_id)]
        rows = result.rows or ()
        if as_tuples:
            return [list(rows)]
        names = [column[0] for column in description]
        return [[dict(zip(names, row, strict=True)) for row in rows]]

    async def _query(self, sql: str, params: Sequence[object], as_tuples: bool) -> list[ResultSet]:
        text = bind(sql, _parameters(params), self.raw.escape)
        cursor = _asyncmy.text_cursor(self.raw, as_tuples=as_tuples)
        results: list[ResultSet] = []
        try:
            await cursor.execute(text)
            while True:
                if cursor.description is None:
                    results.append(_header(cursor.rowcount, cursor.lastrowid))
                else:
                    results.append(list(await cursor.fetchall()))
                if not await cursor.nextset():
                    break
        except Exception:
            # A failed statement leaves the connection in step, so what
            # follows it can be read past.
            with contextlib.suppress(Exception):
                await cursor.close()
            raise
        await cursor.close()
        return results

    async def run(
        self, sql: str, params: Sequence[object], *, prepared: bool, as_tuples: bool
    ) -> list[ResultSet]:
        """Each statement's result: its rows, or a header."""
        async with self._lock:
            try:
                if prepared:
                    return await self._execute(sql, params, as_tuples)
                return await self._query(sql, params, as_tuples)
            except asyncio.CancelledError:
                self._cut_short()
                raise

    # --- streams --------------------------------------------------------------

    async def open_stream(self, sql: str, params: Sequence[object]) -> Cursor:
        """An unbuffered cursor on ``sql``; the session is this stream's
        until ``close_stream``."""
        await self._lock.acquire()
        try:
            cursor = _asyncmy.stream_cursor(self.raw)
            await cursor.execute(bind(sql, _parameters(params), self.raw.escape))
        except asyncio.CancelledError:
            self._cut_short()
            self._lock.release()
            raise
        except BaseException:
            self._lock.release()
            raise
        return cursor

    async def next_rows(self, cursor: Cursor) -> list[Row]:
        """Up to a chunk of rows; ``[]`` at the end."""
        try:
            return list(await cursor.fetchmany(_STREAM_CHUNK))
        except asyncio.CancelledError:
            self._cut_short()
            raise
        except Exception as error:
            if _asyncmy.is_server_error(error):
                _asyncmy.end_unbuffered_result(self.raw)
            else:
                self._cut_short()
            raise

    async def close_stream(self, cursor: Cursor) -> None:
        """Read what the stream left unread, then give the turn back."""
        try:
            if self.usable:
                try:
                    await cursor.close()
                except Exception:
                    self._cut_short()
        finally:
            self._lock.release()

    # --- ending ---------------------------------------------------------------

    async def kill(self) -> None:
        """End the server side of this connection from another one, so a
        statement cut short stops holding its locks."""
        thread_id = self.raw.thread_id()
        with contextlib.suppress(Exception):
            async with asyncio.timeout(_KILL_TIMEOUT):
                side = await _asyncmy.connect(self._options)
                try:
                    await side.kill(thread_id)
                finally:
                    side.close()

    async def stop(self, task: asyncio.Task[Any]) -> None:
        """Interrupt ``task``'s statement: a statement on the wire is cut
        short, which closes this connection, and the server is told to
        end it."""
        if task.done():
            return
        task.cancel()
        await asyncio.wait([task])
        if self.broken:
            await self.kill()

    async def close(self) -> None:
        with contextlib.suppress(Exception):
            if self.raw.connected:
                await self.raw.ensure_closed()
        self.raw.close()


__all__ = ["ResultSet", "ResultSetHeader", "Row", "Session"]
