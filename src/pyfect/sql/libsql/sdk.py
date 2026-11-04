"""What the libSQL client runs statements on (``@libsql/client``'s
``Client`` and ``Transaction``, the part Effect's driver uses).

``LibsqlSdk`` and ``LibsqlSdkTransaction`` are async: the client awaits
them on pyfect's SQL loop thread (``pyfect.sql._loop``), so a caller-owned
client (``LibsqlLiveConfig``) must be usable from that loop. The client
makes its own for a ``file:`` / ``:memory:`` database (``sqlite3``) or a
remote server (Hrana over HTTP).
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Protocol

type Value = int | float | str | bytes | None
"""A value as libSQL stores it."""

type TransactionMode = Literal["write", "read", "deferred"]
"""``write`` starts with ``BEGIN IMMEDIATE``, ``read`` with ``BEGIN
TRANSACTION READONLY`` (a libSQL server's), ``deferred`` with ``BEGIN
DEFERRED``."""

_BEGIN: dict[TransactionMode, str] = {
    "write": "BEGIN IMMEDIATE",
    "read": "BEGIN TRANSACTION READONLY",
    "deferred": "BEGIN DEFERRED",
}


def begin_statement(mode: TransactionMode) -> str:
    return _BEGIN[mode]


@dataclass(frozen=True, slots=True)
class ResultSet:
    """A statement's result (``@libsql/client``'s ``ResultSet``): the rows
    as values in column order, and for a statement without rows the rows
    it changed and the last inserted rowid. ``column_types`` are the
    declared types a remote server reports (empty for a local database:
    ``sqlite3`` does not expose them)."""

    columns: tuple[str, ...]
    column_types: tuple[str, ...]
    rows: tuple[tuple[Value, ...], ...]
    rows_affected: int
    last_insert_rowid: int | None

    def records(self) -> list[dict[str, Value]]:
        """The rows as column name to value; of columns with the same
        name, the first one's value."""
        names = self.columns
        records: list[dict[str, Value]] = []
        for row in self.rows:
            record: dict[str, Value] = {}
            for name, value in zip(names, row, strict=True):
                record.setdefault(name, value)
            records.append(record)
        return records


class LibsqlError(Exception):
    """A failure the libSQL client reports (``@libsql/core``'s
    ``LibsqlError``): ``code`` is SQLite's primary code name
    (``"SQLITE_CONSTRAINT"``) or the client's own (``"CLIENT_CLOSED"``,
    ``"TRANSACTION_CLOSED"``, ``"SERVER_ERROR"``, ...); ``extended_code``
    and ``raw_code`` are SQLite's extended code name and number, when a
    local database reports them."""

    message: str
    code: str
    extended_code: str | None
    raw_code: int | None

    def __init__(
        self,
        message: str,
        code: str,
        extended_code: str | None = None,
        raw_code: int | None = None,
    ) -> None:
        super().__init__(f"{code}: {message}")
        self.message = message
        self.code = code
        self.extended_code = extended_code
        self.raw_code = raw_code


class LibsqlSdkTransaction(Protocol):
    """An open transaction (``@libsql/client``'s ``Transaction``)."""

    async def execute(self, sql: str, args: Sequence[object], /) -> ResultSet: ...

    async def commit(self) -> None: ...

    async def rollback(self) -> None: ...


class LibsqlSdk(Protocol):
    """A libSQL database client (``@libsql/client``'s ``Client``)."""

    async def execute(self, sql: str, args: Sequence[object], /) -> ResultSet: ...

    async def transaction(self, mode: TransactionMode, /) -> LibsqlSdkTransaction: ...


class ManagedSdk(LibsqlSdk, Protocol):
    """A client the libSQL client made, and closes with its scope."""

    async def close(self) -> None: ...


__all__ = [
    "LibsqlError",
    "LibsqlSdk",
    "LibsqlSdkTransaction",
    "ManagedSdk",
    "ResultSet",
    "TransactionMode",
    "Value",
    "begin_statement",
]
