"""Exact key columns for the event log server storages on MySQL and SQL
Server (``persistence._sql_keys``).

Their tables are made at start when missing (no migrator), so a
table made by an earlier version keeps its text columns, which compare
under the database's collation (``Alice``, ``alice`` and ``alice `` one
key). Each start converts such a table in place, keeping its rows, and
does nothing once it is converted.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Final, LiteralString

from pyfect._core import Effect
from pyfect.effect import gen, succeed
from pyfect.persistence._columns import column_int, column_text
from pyfect.sql.client import SqlClientService
from pyfect.sql.error import SqlError

MYSQL_EXACT_COLLATION: Final = "utf8mb4_0900_bin"
"""Binary and ``NO PAD``: every character, trailing spaces included,
counts. Values stay text, so Effect's storages can still read the
tables."""
MYSQL_KEY: Final = f"VARCHAR(191) CHARACTER SET utf8mb4 COLLATE {MYSQL_EXACT_COLLATION}"
MYSQL_TEXT: Final = f"TEXT CHARACTER SET utf8mb4 COLLATE {MYSQL_EXACT_COLLATION}"


def mysql_exact_columns(
    sql: SqlClientService, table: str, columns: Mapping[LiteralString, LiteralString]
) -> Effect[None, SqlError]:
    """``MODIFY`` the ``NOT NULL`` text ``columns`` of ``table`` to their
    types (``MYSQL_KEY``, ``MYSQL_TEXT``) when one is in another collation.
    The values and prefix indexes stay as they are. Concurrent starts may
    both run the ``ALTER``; the second changes nothing."""
    inexact = sql(
        "SELECT COUNT(*) AS count FROM information_schema.columns "
        "WHERE table_schema = DATABASE() AND table_name = {} AND {} AND collation_name <> {}",
        table,
        sql.in_("column_name", list(columns)),
        MYSQL_EXACT_COLLATION,
    ).map(lambda rows: column_int(rows[0]["count"]))
    modify = sql.csv(
        [
            sql("MODIFY {} {} NOT NULL", sql.identifier(name), sql.literal(type_))
            for name, type_ in columns.items()
        ]
    )

    def body():
        if (yield from inexact) > 0:
            yield from sql("ALTER TABLE {} {}", sql.identifier(table), modify)

    return gen(body)


def mssql_exact_primary_key(
    sql: SqlClientService, table: str, column: LiteralString, definition: LiteralString
) -> Effect[None, SqlError]:
    """Give the text primary key ``column`` of ``table`` the ``BIN2``
    ``definition`` (``NVARCHAR(n) COLLATE ...``) and its length as
    ``<column>_length``, the primary key becoming both: SQL Server ignores
    trailing spaces in keys under every collation. A start converting takes
    the table's exclusive lock and checks again, so a concurrent start
    waits and then finds it converted."""
    table_sql = sql.identifier(table)
    length = f"{column}_length"
    # A row while the length column is missing.
    unconverted = sql("IF COL_LENGTH({}, {}) IS NULL SELECT 1 AS pending", table, length).map(
        lambda rows: len(rows) > 0
    )

    def convert():
        yield from sql("SELECT COUNT(*) AS count FROM {} WITH (TABLOCKX, HOLDLOCK)", table_sql)
        if not (yield from unconverted):
            return
        constraints = yield from sql(
            "SELECT name FROM sys.key_constraints WHERE parent_object_id = OBJECT_ID({}) "
            "AND type = 'PK'",
            table,
        )
        for row in constraints:
            yield from sql(
                "ALTER TABLE {} DROP CONSTRAINT {}",
                table_sql,
                sql.identifier(column_text(row["name"])),
            )
        yield from sql(
            "ALTER TABLE {} ALTER COLUMN {} {} NOT NULL",
            table_sql,
            sql.identifier(column),
            sql.literal(definition),
        )
        yield from sql(
            "ALTER TABLE {} ADD {} AS DATALENGTH({}) PERSISTED NOT NULL",
            table_sql,
            sql.identifier(length),
            sql.identifier(column),
        )
        yield from sql(
            "ALTER TABLE {} ADD PRIMARY KEY ({}, {})",
            table_sql,
            sql.identifier(column),
            sql.identifier(length),
        )

    return unconverted.flat_map(
        lambda pending: sql.with_transaction(gen(convert)) if pending else succeed(None)
    )


__all__ = ["MYSQL_KEY", "MYSQL_TEXT", "mssql_exact_primary_key", "mysql_exact_columns"]
