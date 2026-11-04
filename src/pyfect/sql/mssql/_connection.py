"""The ``Connection`` of a SQL Server connection (the connection of Effect's
``MssqlClient``): its blocking calls run on its worker thread, so no fiber
blocks, and interrupting one cancels its request.

Rows are those of every result set of the request in turn (tedious's
``rowCollectionOnRequestCompletion``); ``execute_raw`` gives them as
``execute`` does. Streams are not implemented, as in Effect.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import TYPE_CHECKING, Any, cast

from pyfect._core import Effect
from pyfect.process._os import Latch
from pyfect.sql.connection import Row, TransformRows, ValueRow
from pyfect.sql.error import SqlError
from pyfect.sql.mssql._driver import RawConnection, Rows, TypedValue
from pyfect.sql.mssql._names import escape
from pyfect.sql.mssql._worker import Worker
from pyfect.sql.mssql.error import catch
from pyfect.sql.mssql.procedure import Outputs, ProcedureWithValues, Result
from pyfect.sql.mssql.types import DataType, ParameterOptions, ParameterTypes
from pyfect.sql.statement import Custom, custom, is_custom, primitive_kind

if TYPE_CHECKING:
    from pyfect.stream import Stream

type MssqlParam = Custom[str, DataType, object, ParameterOptions]

mssql_param: Callable[[DataType, object, ParameterOptions], MssqlParam] = custom("MssqlParam")
is_mssql_param = is_custom("MssqlParam")

_EXECUTE = catch("Failed to execute statement", "execute")
_BEGIN = catch("Failed to begin transaction", "beginTransaction")
_COMMIT = catch("Failed to commit transaction", "commitTransaction")
_SAVEPOINT = catch("Failed to create savepoint", "createSavepoint")
_ROLLBACK = catch("Failed to rollback transaction", "rollbackTransaction")


def _objects(rows: Rows) -> list[Row]:
    return [dict(row) for row in rows]


def _values(rows: Rows) -> list[ValueRow]:
    return [tuple(value for _, value in row) for row in rows]


class MssqlConnection:
    """A ``Connection`` on one SQL Server connection."""

    __slots__ = ("_ended", "_parameter_types", "_raw", "_worker")

    def __init__(
        self,
        raw: RawConnection,
        worker: Worker,
        ended: Latch[None],
        parameter_types: ParameterTypes,
    ) -> None:
        self._raw = raw
        self._worker = worker
        self._ended = ended
        self._parameter_types = parameter_types

    @property
    def ended(self) -> bool:
        """Whether the driver ended the connection."""
        return self._ended.get() is not None

    def _call[A](
        self, run: Callable[[], A], on_error: Callable[[Exception], SqlError]
    ) -> Effect[A, SqlError]:
        return self._worker.call(run, on_error, self._raw)

    def _typed(self, params: Sequence[object]) -> list[TypedValue]:
        typed: list[TypedValue] = []
        for i, value in enumerate(params):
            name = str(i + 1)
            if is_mssql_param(value):
                param = cast("MssqlParam", value)
                typed.append(TypedValue(name, param.param_a, param.param_b, param.param_c))
            else:
                kind = primitive_kind(value)
                typed.append(
                    TypedValue(name, self._parameter_types[kind], value, ParameterOptions())
                )
        return typed

    def _run(self, sql: str, params: Sequence[object]) -> Effect[Rows, SqlError]:
        raw = self._raw
        typed = self._typed(params)
        return self._call(lambda: raw.execute(sql, typed), _EXECUTE)

    def execute(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]:
        rows = self._run(sql, params).map(_objects)
        if transform_rows is None:
            return rows
        transform = transform_rows
        return rows.map(lambda found: list(transform(found)))

    def execute_raw(self, sql: str, params: Sequence[object], /) -> Effect[object, SqlError]:
        return self._run(sql, params).map(_objects)

    def execute_values(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]:
        return self._run(sql, params).map(_values)

    def execute_values_unprepared(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]:
        return self._run(sql, params).map(_values)

    def execute_unprepared(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]:
        return self.execute(sql, params, transform_rows)

    def execute_stream(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Stream[Row, SqlError]:
        from pyfect import stream

        return stream.die(NotImplementedError("executeStream not implemented"))

    def call[A](
        self, procedure: ProcedureWithValues[A], transform_rows: TransformRows | None
    ) -> Effect[Result[A], SqlError]:
        """Run a stored procedure: its output parameters and rows."""
        raw = self._raw
        definition = procedure.procedure
        params = [
            TypedValue(p.name, p.type, procedure.values[p.name], p.options)
            for p in definition.params
        ]
        outputs = [TypedValue(p.name, p.type, None, p.options) for p in definition.output_params]
        name = escape(definition.name)

        def result(found: tuple[Rows, dict[str, object]]) -> Result[A]:
            rows: Sequence[Any] = _objects(found[0])
            if transform_rows is not None:
                rows = transform_rows(rows)
            return Result(Outputs(found[1]), rows)

        return self._call(lambda: raw.call_procedure(name, params, outputs), _EXECUTE).map(result)

    @property
    def begin(self) -> Effect[None, SqlError]:
        return self._call(self._raw.begin, _BEGIN)

    @property
    def commit(self) -> Effect[None, SqlError]:
        return self._call(self._raw.commit, _COMMIT)

    def savepoint(self, name: str) -> Effect[None, SqlError]:
        raw = self._raw
        return self._call(lambda: raw.save(name), _SAVEPOINT)

    def rollback(self, name: str | None = None) -> Effect[None, SqlError]:
        raw = self._raw
        return self._call(lambda: raw.rollback(name), _ROLLBACK)


__all__ = ["MssqlConnection", "MssqlParam", "is_mssql_param", "mssql_param"]
