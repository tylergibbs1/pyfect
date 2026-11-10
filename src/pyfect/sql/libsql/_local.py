"""A local libSQL database on ``sqlite3`` (``@libsql/client``'s
``sqlite3`` client): a ``file:`` path or ``:memory:``.

Each connection lives on a thread of its own. A transaction takes the
client's connection until it settles; meanwhile the client opens another
for its statements, except for an in-memory database, whose only
connection is the database (a statement then fails with
``TRANSACTION_ACTIVE``, as libSQL's).
"""

from __future__ import annotations

import asyncio
import sqlite3
from collections.abc import Awaitable, Callable, Sequence
from concurrent.futures import ThreadPoolExecutor

from pyfect.sql.libsql._targets import LocalTarget
from pyfect.sql.libsql._values import to_values
from pyfect.sql.libsql.sdk import (
    LibsqlError,
    ResultSet,
    SdkProtocol,
    TransactionMode,
    Value,
    begin_statement,
)

_PRIMARY_CODES = {
    1: "SQLITE_ERROR",
    2: "SQLITE_INTERNAL",
    3: "SQLITE_PERM",
    4: "SQLITE_ABORT",
    5: "SQLITE_BUSY",
    6: "SQLITE_LOCKED",
    7: "SQLITE_NOMEM",
    8: "SQLITE_READONLY",
    9: "SQLITE_INTERRUPT",
    10: "SQLITE_IOERR",
    11: "SQLITE_CORRUPT",
    12: "SQLITE_NOTFOUND",
    13: "SQLITE_FULL",
    14: "SQLITE_CANTOPEN",
    15: "SQLITE_PROTOCOL",
    16: "SQLITE_EMPTY",
    17: "SQLITE_SCHEMA",
    18: "SQLITE_TOOBIG",
    19: "SQLITE_CONSTRAINT",
    20: "SQLITE_MISMATCH",
    21: "SQLITE_MISUSE",
    22: "SQLITE_NOLFS",
    23: "SQLITE_AUTH",
    24: "SQLITE_FORMAT",
    25: "SQLITE_RANGE",
    26: "SQLITE_NOTADB",
    27: "SQLITE_NOTICE",
    28: "SQLITE_WARNING",
}

_BUSY_TIMEOUT = 5.0
"""better-sqlite3's default, which libSQL's local client keeps."""


def _map_error(error: sqlite3.Error) -> Exception:
    raw: object = getattr(error, "sqlite_errorcode", None)
    if not isinstance(raw, int):
        return error
    name: object = getattr(error, "sqlite_errorname", None)
    code = _PRIMARY_CODES.get(raw & 0xFF, f"SQLITE_UNKNOWN_{raw & 0xFF}")
    return LibsqlError(str(error), code, name if isinstance(name, str) else None, raw)


def execute_statement(db: sqlite3.Connection, sql: str, args: Sequence[object]) -> ResultSet:
    values = to_values(args)
    try:
        before = db.total_changes
        cursor = db.execute(sql, values)
        if cursor.description is None:
            changed = db.total_changes != before
            return ResultSet(
                (), (), (), max(cursor.rowcount, 0) if changed else 0, cursor.lastrowid
            )
        columns = tuple(column[0] for column in cursor.description)
        rows: tuple[tuple[Value, ...], ...] = tuple(tuple(row) for row in cursor.fetchall())
        return ResultSet(columns, ("",) * len(columns), rows, 0, None)
    except sqlite3.Error as error:
        raise _map_error(error) from error


class _Connection:
    """One ``sqlite3`` connection on its own thread."""

    __slots__ = ("_db", "_executor")

    def __init__(self, db: sqlite3.Connection, executor: ThreadPoolExecutor) -> None:
        self._db = db
        self._executor = executor

    @staticmethod
    async def open(target: LocalTarget) -> _Connection:
        executor = ThreadPoolExecutor(1, thread_name_prefix="pyfect-libsql")

        def connect() -> sqlite3.Connection:
            db = sqlite3.connect(
                target.database,
                timeout=_BUSY_TIMEOUT,
                isolation_level=None,
                check_same_thread=False,
                uri=target.uri,
            )
            try:
                db.execute("SELECT 1 AS checkThatTheDatabaseCanBeOpened").fetchall()
            except BaseException:
                db.close()
                raise
            return db

        try:
            db = await asyncio.get_running_loop().run_in_executor(executor, connect)
        except sqlite3.Error as error:
            executor.shutdown(wait=False)
            raise _map_error(error) from error
        except BaseException:
            executor.shutdown(wait=False)
            raise
        return _Connection(db, executor)

    async def run[A](self, f: Callable[[sqlite3.Connection], A]) -> A:
        db = self._db
        return await asyncio.get_running_loop().run_in_executor(self._executor, lambda: f(db))

    async def execute(self, sql: str, args: Sequence[object]) -> ResultSet:
        return await self.run(lambda db: execute_statement(db, sql, args))

    async def in_transaction(self) -> bool:
        return await self.run(lambda db: db.in_transaction)

    async def close(self) -> None:
        def close(db: sqlite3.Connection) -> None:
            if db.in_transaction:
                db.execute("ROLLBACK")
            db.close()

        try:
            await self.run(close)
        finally:
            self._executor.shutdown(wait=False)


class LocalClient:
    """A local database (``ManagedSdk``)."""

    __slots__ = ("_closed", "_idle", "_in_transaction", "_target")

    protocol: SdkProtocol = "file"

    def __init__(self, target: LocalTarget, first: _Connection) -> None:
        self._target = target
        self._idle: _Connection | None = first
        self._in_transaction = 0
        self._closed = False

    @staticmethod
    async def open(target: LocalTarget) -> LocalClient:
        """Open the database; fails when it cannot be opened."""
        return LocalClient(target, await _Connection.open(target))

    async def _take(self) -> _Connection:
        if self._closed:
            raise LibsqlError("The client is closed", "CLIENT_CLOSED")
        idle = self._idle
        if idle is not None:
            self._idle = None
            return idle
        if self._target.in_memory:
            raise LibsqlError(
                "This client has a single connection, which an open transaction is holding. "
                "In-memory databases cannot have more than one. "
                "Commit or roll back the transaction before using the client again.",
                "TRANSACTION_ACTIVE",
            )
        return await _Connection.open(self._target)

    async def _give_back(self, conn: _Connection) -> None:
        if self._closed or self._idle is not None:
            await conn.close()
            return
        if await conn.in_transaction():
            try:
                await conn.execute("ROLLBACK", ())
            except LibsqlError:
                await conn.close()
                return
        self._idle = conn

    async def execute(self, sql: str, args: Sequence[object], /) -> ResultSet:
        conn = await self._take()
        try:
            return await conn.execute(sql, args)
        finally:
            await self._give_back(conn)

    async def transaction(self, mode: TransactionMode, /) -> LocalTransaction:
        conn = await self._take()
        try:
            await conn.execute(begin_statement(mode), ())
        except BaseException:
            await self._give_back(conn)
            raise
        return LocalTransaction(conn, self._give_back)

    async def close(self) -> None:
        self._closed = True
        idle, self._idle = self._idle, None
        if idle is not None:
            await idle.close()


class LocalTransaction:
    """A transaction holding one connection until it commits or rolls
    back."""

    __slots__ = ("_conn", "_release")

    def __init__(
        self, conn: _Connection, release: Callable[[_Connection], Awaitable[None]]
    ) -> None:
        self._conn: _Connection | None = conn
        self._release = release

    async def _settle(self) -> None:
        conn, self._conn = self._conn, None
        if conn is not None:
            await self._release(conn)

    async def _open(self) -> _Connection:
        conn = self._conn
        if conn is None or not await conn.in_transaction():
            raise LibsqlError("The transaction is closed", "TRANSACTION_CLOSED")
        return conn

    async def execute(self, sql: str, args: Sequence[object], /) -> ResultSet:
        return await (await self._open()).execute(sql, args)

    async def commit(self) -> None:
        try:
            await (await self._open()).execute("COMMIT", ())
        finally:
            await self._settle()

    async def rollback(self) -> None:
        conn = self._conn
        try:
            if conn is not None and await conn.in_transaction():
                await conn.execute("ROLLBACK", ())
        finally:
            await self._settle()


__all__ = ["LocalClient", "LocalTransaction", "execute_statement"]
