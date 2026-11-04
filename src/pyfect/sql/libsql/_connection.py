"""The libSQL client's connections (Effect's ``LibsqlConnectionImpl``): one
on the SDK client, and one on each transaction it begins. Every call is
awaited on the SQL loop thread."""

from __future__ import annotations

from collections.abc import Callable, Coroutine, Sequence
from typing import TYPE_CHECKING, Any

from pyfect._core import Effect
from pyfect.sql import _loop
from pyfect.sql.connection import Row, TransformRows, ValueRow
from pyfect.sql.error import SqlError, classify_sqlite_error
from pyfect.sql.libsql.sdk import LibsqlSdk, LibsqlSdkTransaction, ResultSet

if TYPE_CHECKING:
    from pyfect.stream import Stream


def _call[A](
    make: Callable[[], Coroutine[Any, Any, A]], message: str, operation: str
) -> Effect[A, SqlError]:
    def catch(cause: BaseException) -> SqlError:
        return SqlError(reason=classify_sqlite_error(cause, message=message, operation=operation))

    return _loop.call(make, catch, waits_for="work")


class _Statements:
    """Runs statements on a client or a transaction."""

    __slots__ = ("_statements",)

    def __init__(self, statements: LibsqlSdk | LibsqlSdkTransaction) -> None:
        self._statements = statements

    def _run(self, sql: str, params: Sequence[object]) -> Effect[ResultSet, SqlError]:
        sdk, args = self._statements, tuple(params)
        return _call(lambda: sdk.execute(sql, args), "Failed to execute statement", "execute")

    def execute(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]:
        rows: Effect[Sequence[Row], SqlError] = self._run(sql, params).map(
            lambda result: result.records()
        )
        return rows if transform_rows is None else rows.map(transform_rows)

    def execute_unprepared(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]:
        return self.execute(sql, params, transform_rows)

    def execute_raw(self, sql: str, params: Sequence[object], /) -> Effect[object, SqlError]:
        """The ``ResultSet``."""
        return self._run(sql, params)

    def execute_values(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]:
        return self._run(sql, params).map(lambda result: result.rows)

    def execute_values_unprepared(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]:
        return self.execute_values(sql, params)

    def execute_stream(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Stream[Row, SqlError]:
        from pyfect import stream

        return stream.die(NotImplementedError("executeStream not implemented"))


class ClientConnection(_Statements):
    """Statements on the SDK client, and the transactions it begins."""

    __slots__ = ("sdk",)

    def __init__(self, sdk: LibsqlSdk) -> None:
        super().__init__(sdk)
        self.sdk = sdk

    def begin_transaction(self) -> Effect[OpenTransaction, SqlError]:
        sdk = self.sdk
        return _call(
            lambda: sdk.transaction("write"), "Failed to begin transaction", "beginTransaction"
        ).map(OpenTransaction)


class OpenTransaction(_Statements):
    """Statements in an SDK transaction, and its end."""

    __slots__ = ("sdk",)

    def __init__(self, sdk: LibsqlSdkTransaction) -> None:
        super().__init__(sdk)
        self.sdk = sdk

    def commit(self) -> Effect[None, SqlError]:
        sdk = self.sdk
        return _call(sdk.commit, "Failed to commit transaction", "commitTransaction")

    def rollback(self) -> Effect[None, SqlError]:
        sdk = self.sdk
        return _call(sdk.rollback, "Failed to rollback transaction", "rollbackTransaction")


__all__ = ["ClientConnection", "OpenTransaction"]
