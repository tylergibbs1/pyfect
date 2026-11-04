"""Effect's ``makeXactAbortClient`` (``sql-mssql`` Persistence test): a
third-party mssql-dialect client whose sessions run with ``XACT_ABORT ON``
(tedious's ``abortTransactionOnError``), on the driver's own connections.

Statements with parameters run through ``sp_executesql``, the rest, and
transaction control, as plain batches, so a transaction outlives its
statement. With ``raw_batch`` every statement is a plain batch, its
parameters declared as variables. Interrupting a statement cancels it and
waits for it to settle.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Never

import pyfect as fx
from pyfect.pool import Pool
from pyfect.reactivity import layer as reactivity_layer
from pyfect.scope import Scope
from pyfect.sql import SqlClientService, mssql
from pyfect.sql import client as sql_client
from pyfect.sql.connection import Row, TransformRows, ValueRow
from pyfect.sql.error import SqlError, UnknownError
from pyfect.sql.mssql import ParameterOptions, _tds
from pyfect.sql.mssql._driver import Rows, TypedValue
from pyfect.sql.mssql._worker import Worker
from pyfect.sql.statement import primitive_kind
from pyfect.stream import Stream
from pyfect.stream import die as stream_die

from ._mssql import MssqlServer


def _fail(cause: Exception) -> SqlError:
    return SqlError(reason=UnknownError(cause=cause, operation="execute"))


def _declare(value: object, i: int) -> str:
    """``value`` declared as the variable ``@<i + 1>``."""
    name = f"@{i + 1}"
    match value:
        case None:
            return f"DECLARE {name} NVARCHAR(MAX) = NULL;"
        case bool():
            return f"DECLARE {name} BIT = {int(value)};"
        case int():
            return f"DECLARE {name} BIGINT = {value};"
        case float():
            return f"DECLARE {name} FLOAT = {value!r};"
        case str():
            escaped = value.replace("'", "''")
            return f"DECLARE {name} NVARCHAR(MAX) = N'{escaped}';"
        case datetime():
            return f"DECLARE {name} DATETIME2 = CONVERT(DATETIME2, '{value.isoformat()}', 126);"
        case _:
            raise TypeError(f"unsupported parameter {value!r}")


class _Connection:
    def __init__(self, raw: _tds.TdsConnection, worker: Worker, raw_batch: bool) -> None:
        self._raw = raw
        self._worker = worker
        self._raw_batch = raw_batch

    def _run(self, sql: str, params: Sequence[object]) -> fx.Effect[Rows, SqlError]:
        raw = self._raw
        if self._raw_batch or not params:
            text = "\n".join([*(_declare(v, i) for i, v in enumerate(params)), sql])
            thunk = lambda: raw._run(lambda session: session.submit_plain_query(text))  # noqa: E731
        else:
            typed = [
                TypedValue(
                    str(i + 1),
                    mssql.default_parameter_types[primitive_kind(v)],
                    v,
                    ParameterOptions(),
                )
                for i, v in enumerate(params)
            ]
            thunk = lambda: raw.execute(sql, typed)  # noqa: E731
        return self._worker.call(thunk, _fail, cancel=raw)

    def execute(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Effect[Sequence[Row], SqlError]:
        def rows(result: Rows) -> Sequence[Row]:
            found: list[Row] = [dict(row) for row in result]
            return found if transform_rows is None else transform_rows(found)

        return self._run(sql, params).map(rows)

    def execute_raw(self, sql: str, params: Sequence[object], /) -> fx.Effect[object, SqlError]:
        return self.execute(sql, params, None).map(lambda rows: rows)

    def execute_stream(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Stream[Row, SqlError]:
        return stream_die(NotImplementedError("executeStream not implemented"))

    def execute_values(
        self, sql: str, params: Sequence[object], /
    ) -> fx.Effect[Sequence[ValueRow], SqlError]:
        return self._run(sql, params).map(
            lambda result: [tuple(value for _, value in row) for row in result]
        )

    def execute_values_unprepared(
        self, sql: str, params: Sequence[object], /
    ) -> fx.Effect[Sequence[ValueRow], SqlError]:
        return self.execute_values(sql, params)

    def execute_unprepared(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Effect[Sequence[Row], SqlError]:
        return self.execute(sql, params, transform_rows)


def make(
    server: MssqlServer, database: str, *, raw_batch: bool = False, size: int = 4
) -> fx.Effect[SqlClientService, Never, Scope]:
    """A client of ``size`` connections to ``database``."""
    options = mssql.client.connect_options(server.config(database=database))

    def connect() -> fx.Effect[_Connection, SqlError, Scope]:
        worker = Worker()

        def open_() -> _tds.TdsConnection:
            raw = _tds.connect(options, lambda: None)
            raw._run(lambda session: session.submit_plain_query("SET XACT_ABORT ON"))
            return raw

        def close(conn: _Connection) -> fx.Effect[None]:
            def run() -> None:
                conn._raw.close()
                worker.shutdown()

            return fx.sync(run)

        opened = worker.call(open_, _fail).map(lambda raw: _Connection(raw, worker, raw_batch))
        return fx.acquire_release(opened, lambda conn, _: close(conn))

    def build():
        pool: Pool[_Connection, SqlError] = yield from Pool.make(fx.suspend(connect), size=size)
        acquirer: Any = pool.get()
        return (
            yield from sql_client.make(
                driver="test-xact-abort",
                compiler=mssql.make_compiler(),
                acquirer=acquirer,
                begin_transaction="BEGIN TRANSACTION",
                commit="COMMIT TRANSACTION",
                rollback="ROLLBACK TRANSACTION",
                savepoint=lambda name: f"SAVE TRANSACTION {name}",
                rollback_savepoint=lambda name: f"ROLLBACK TRANSACTION {name}",
            ).pipe(fx.provide(reactivity_layer))
        )

    return fx.gen(build)


__all__ = ["make"]
