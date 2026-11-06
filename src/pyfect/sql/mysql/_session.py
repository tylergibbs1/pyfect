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
import logging
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
_NO_BACKSLASH_ESCAPES = 0x200  # the protocol's SERVER_STATUS_NO_BACKSLASH_ESCAPES
_DRAIN_GRACE = 0.1

_log = logging.getLogger("pyfect.sql.mysql")


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

    def _bound(self, sql: str, params: Sequence[object]) -> str:
        # The server reports the session's mode with every result, and the
        # connection's ``escape`` follows the same flag.
        no_backslash_escapes = bool(self.raw.server_status & _NO_BACKSLASH_ESCAPES)
        return bind(
            sql, _parameters(params), self.raw.escape, no_backslash_escapes=no_backslash_escapes
        )

    async def _query(self, sql: str, params: Sequence[object], as_tuples: bool) -> list[ResultSet]:
        text = self._bound(sql, params)
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
            await cursor.execute(self._bound(sql, params))
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
        """End the stream, then give the turn back: what it left unread is read past, and a
        statement still sending rows after a moment is killed, as it may send for hours.
        Only the statement: a transaction goes on, if the connection stays in step."""
        try:
            if self.usable:
                await self._read_past(cursor)
        finally:
            self._lock.release()

    async def _read_past(self, cursor: Cursor) -> None:
        reading = asyncio.ensure_future(cursor.close())
        try:
            done, _ = await asyncio.wait([reading], timeout=_DRAIN_GRACE)
            if not done:
                await self.kill(only_statement=True)
                done, _ = await asyncio.wait([reading], timeout=_KILL_TIMEOUT)
            if not done:
                reading.cancel()
                await asyncio.wait([reading])
                self._cut_short()
                await self.kill()
            elif (error := reading.exception()) is not None:
                if _asyncmy.is_server_error(error):
                    _asyncmy.end_unbuffered_result(self.raw)
                else:
                    self._cut_short()
        except asyncio.CancelledError:
            reading.cancel()
            await asyncio.wait([reading])
            self._cut_short()
            raise

    # --- ending ---------------------------------------------------------------

    async def kill(self, *, only_statement: bool = False) -> None:
        """End this connection (or only its statement) on the server, from another
        connection, so a statement cut short stops holding its locks. A kill that cannot be
        sent fails nobody, but the statement stays on the server, so it is logged."""
        thread_id = self.raw.thread_id()
        try:
            async with asyncio.timeout(_KILL_TIMEOUT):
                side = await _asyncmy.connect(self._options)
                try:
                    await _asyncmy.kill(side, thread_id, only_statement=only_statement)
                finally:
                    side.close()
        except Exception as error:
            _log.warning(
                "KILL %d failed, so its statement stays on the server: %r", thread_id, error
            )

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
