"""A SQLite connection on its worker thread (the connection of Effect's
``@effect/sql-sqlite-node``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import sqlite3
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any
from urllib.parse import quote, urlsplit, urlunsplit

from pyfect._core import Effect, _Succeed, _Suspend, _Sync
from pyfect.sql.connection import Row, TransformRows, ValueRow
from pyfect.sql.error import SqlError, classify_sqlite_error
from pyfect.sql.sqlite._worker import Worker

if TYPE_CHECKING:
    from pyfect.stream import Stream


@dataclass(frozen=True, slots=True)
class RunResult:
    """What ``raw`` gives for a statement without result columns."""

    changes: int
    last_insert_rowid: int


@dataclass(frozen=True, slots=True)
class BackupMetadata:
    total_pages: int
    remaining_pages: int


def _catch(message: str, operation: str) -> Callable[[Exception], SqlError]:
    return lambda cause: SqlError(
        reason=classify_sqlite_error(cause, message=message, operation=operation)
    )


_catch_execute = _catch("Failed to execute statement", "execute")


def _rows(cursor: sqlite3.Cursor) -> list[Row]:
    if cursor.description is None:
        return []
    names = [column[0] for column in cursor.description]
    return [dict(zip(names, row, strict=True)) for row in cursor.fetchall()]


def _changes(db: sqlite3.Connection) -> RunResult:
    changes, rowid = db.execute("SELECT changes(), last_insert_rowid()").fetchone()
    return RunResult(changes, rowid)


class SqliteConnection:
    """Runs statements on one ``sqlite3`` connection, on its worker thread.

    ``sqlite3`` keeps a cache of prepared statements (``cached_statements``)
    and has no other way to run one, so the prepared and unprepared calls
    run alike."""

    def __init__(self, db: sqlite3.Connection, worker: Worker) -> None:
        self._db = db
        self._worker = worker

    def is_transaction(self) -> bool:
        return self._db.in_transaction

    def _call[A](
        self,
        f: Callable[[sqlite3.Connection], A],
        catch: Callable[[Exception], SqlError] = _catch_execute,
    ) -> Effect[A, SqlError]:
        db = self._db
        return self._worker.call(lambda: f(db), catch)

    def _execute(self, sql: str, params: Sequence[object]) -> Effect[list[Row], SqlError]:
        values = tuple(params)
        return self._call(lambda db: _rows(db.execute(sql, values)))

    def execute(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]:
        rows = self._execute(sql, params)
        return rows if transform_rows is None else rows.map(transform_rows)

    def execute_unprepared(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]:
        return self.execute(sql, params, transform_rows)

    def execute_raw(self, sql: str, params: Sequence[object], /) -> Effect[object, SqlError]:
        """Rows, or a ``RunResult`` for a statement without result
        columns."""
        values = tuple(params)

        def run(db: sqlite3.Connection) -> object:
            cursor = db.execute(sql, values)
            if cursor.description is None:
                return _changes(db)
            return _rows(cursor)

        return self._call(run)

    def execute_values(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]:
        values = tuple(params)

        def run(db: sqlite3.Connection) -> list[ValueRow]:
            cursor = db.execute(sql, values)
            if cursor.description is None:
                return []
            return [tuple(row) for row in cursor.fetchall()]

        return self._call(run)

    def execute_values_unprepared(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]:
        return self.execute_values(sql, params)

    def execute_stream(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Stream[Row, SqlError]:
        from pyfect import stream

        return stream.die(NotImplementedError("executeStream not implemented"))

    def backup(self, destination: str) -> Effect[BackupMetadata, SqlError]:
        """Copy the database to the file ``destination``."""

        def run(db: sqlite3.Connection) -> BackupMetadata:
            pages = [0]

            def progress(_status: int, _remaining: int, total: int) -> None:
                pages[0] = total

            target = sqlite3.connect(destination)
            try:
                db.backup(target, progress=progress)
            finally:
                target.close()
            return BackupMetadata(pages[0], 0)

        return self._call(run, _catch("Failed to backup database", "backup"))

    def load_extension(self, path: str) -> Effect[None, SqlError]:
        """Load the SQLite extension at ``path`` (fails where Python's
        ``sqlite3`` was built without extension loading)."""

        def run(db: sqlite3.Connection) -> None:
            enable: Any = getattr(db, "enable_load_extension", None)
            if enable is None:
                raise sqlite3.NotSupportedError("extension loading is not supported")
            enable(True)
            try:
                db.load_extension(path)
            finally:
                enable(False)

        return self._call(run, _catch("Failed to load extension", "loadExtension"))

    def exec_config(self, sql: str) -> Effect[None, SqlError]:
        """Run a configuration statement, failing as a connect error."""

        def run(db: sqlite3.Connection) -> None:
            db.execute(sql).fetchall()

        return self._call(run, _catch("Failed to configure database", "connect"))

    def close(self) -> Effect[None]:
        worker = self._worker

        def run(db: sqlite3.Connection) -> None:
            db.close()

        def stop(_: object) -> Effect[None]:
            worker.shutdown()
            return _Succeed(None)

        return self._call(run).or_die().flat_map(stop)


def _target(filename: str, readonly: bool) -> tuple[str, bool]:
    """What ``sqlite3.connect`` opens for ``filename``, and whether it is a
    URI. A ``file:`` URI is opened as one (as ``node:sqlite`` does); a
    readonly client opens any file through a URI with ``mode=ro`` (the
    ``SQLITE_OPEN_READONLY`` flag ``sqlite3`` cannot pass)."""
    is_uri = filename.startswith("file:")
    if not readonly:
        return filename, is_uri
    if not is_uri:
        return f"file:{quote(filename)}?mode=ro", True
    parts = urlsplit(filename)
    params = [p for p in parts.query.split("&") if p and not p.startswith("mode=")]
    return urlunsplit(parts._replace(query="&".join([*params, "mode=ro"]))), True


def open_connection(
    filename: str, *, readonly: bool, prepare_cache_size: int
) -> Effect[SqliteConnection, SqlError]:
    """Open ``filename`` (a path, ``:memory:`` or a ``file:`` URI) on a new
    worker thread."""
    target, uri = _target(filename, readonly)

    def connect() -> sqlite3.Connection:
        return sqlite3.connect(
            target,
            timeout=0,
            isolation_level=None,
            check_same_thread=False,
            cached_statements=max(prepare_cache_size, 0),
            uri=uri,
        )

    def body() -> Effect[SqliteConnection, SqlError]:
        worker = Worker()
        return (
            worker.call(connect, _catch("Failed to open database", "connect"))
            .map(lambda db: SqliteConnection(db, worker))
            .tap_error(lambda _: _Sync(worker.shutdown))
        )

    return _Suspend(body)


__all__ = ["BackupMetadata", "RunResult", "SqliteConnection", "open_connection"]
