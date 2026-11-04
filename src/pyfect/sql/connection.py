"""What a driver provides: a ``Connection`` that runs compiled SQL (Effect's
``effect/sql/SqlConnection``).

A driver builds a client from an ``Acquirer`` (an effect leasing a
connection into the current scope) and, optionally, a ``Borrower`` that
lends one for a single statement without a scope.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import TYPE_CHECKING, Protocol

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.scope import Scope
from pyfect.sql.error import SqlError

if TYPE_CHECKING:
    from pyfect.stream import Stream

type Row = Mapping[str, object]
"""A result row: column name to value."""

type TransformRows = Callable[[Sequence[Row]], Sequence[Row]]
"""Renames the columns of result rows."""

type ValueRow = tuple[object, ...]
"""A result row as its values, in column order."""


class Connection(Protocol):
    """Runs SQL on one database connection. ``params`` are bound to the
    placeholders in order; ``transform_rows``, when given, renames the
    result's columns."""

    def execute(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]: ...

    def execute_raw(self, sql: str, params: Sequence[object], /) -> Effect[object, SqlError]:
        """The driver's own result, as it is."""
        ...

    def execute_stream(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Stream[Row, SqlError]: ...

    def execute_values(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]: ...

    def execute_values_unprepared(
        self, sql: str, params: Sequence[object], /
    ) -> Effect[Sequence[ValueRow], SqlError]: ...

    def execute_unprepared(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> Effect[Sequence[Row], SqlError]: ...


type Acquirer = Effect[Connection, SqlError, Scope]
"""Leases a connection until the current scope closes."""


class Borrower(Protocol):
    """Lends a connection to ``f`` for one statement, without a scope."""

    def __call__[A, E, R](
        self, f: Callable[[Connection], Effect[A, E, R]], /
    ) -> Effect[A, E | SqlError, R]: ...


class ConnectionTag(Tag[Connection], key="effect/sql/SqlConnection"):
    """The service of a connection (Effect's ``SqlConnection.Connection``)."""


__all__ = [
    "Acquirer",
    "Borrower",
    "Connection",
    "ConnectionTag",
    "Row",
    "SqlError",
    "TransformRows",
    "ValueRow",
]
