"""The migrations of the SQL queue table, as Effect's: ``0001`` makes the
first schema (a ``completed`` flag), ``0002`` upgrades it to ``state``
and ``visible_at`` with a partial index for pollers."""

from __future__ import annotations

from collections.abc import Generator
from typing import Any

from pyfect._core import Effect
from pyfect.effect import gen
from pyfect.sql import migrator
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.error import SqlError


def _create_table(sql: SqlClientService, table_name: str) -> Effect[object, SqlError]:
    table = sql.identifier(table_name)
    return sql.on_dialect_or_else(
        mysql=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} ("
            "sequence BIGINT UNSIGNED AUTO_INCREMENT PRIMARY KEY, "
            "id VARCHAR(36) NOT NULL, "
            "queue_name VARCHAR(100) NOT NULL, "
            "element TEXT NOT NULL, "
            "completed BOOLEAN NOT NULL, "
            "attempts INT NOT NULL DEFAULT 0, "
            "last_failure TEXT NULL, "
            "acquired_at DATETIME NULL, "
            "acquired_by VARCHAR(36) NULL, "
            "created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL)",
            table,
        ),
        pg=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} ("
            "sequence SERIAL PRIMARY KEY, "
            "id VARCHAR(36) NOT NULL, "
            "queue_name VARCHAR(100) NOT NULL, "
            "element TEXT NOT NULL, "
            "completed BOOLEAN NOT NULL, "
            "attempts INTEGER NOT NULL DEFAULT 0, "
            "last_failure TEXT NULL, "
            "acquired_at TIMESTAMP NULL, "
            "acquired_by UUID NULL, "
            "created_at TIMESTAMP NOT NULL, "
            "updated_at TIMESTAMP NOT NULL)",
            table,
        ),
        mssql=lambda: sql(
            "IF NOT EXISTS (SELECT * FROM sysobjects WHERE name={} AND xtype='U') "
            "CREATE TABLE {} ("
            "sequence INT IDENTITY(1,1) PRIMARY KEY, "
            "id NVARCHAR(36) NOT NULL, "
            "queue_name NVARCHAR(100) NOT NULL, "
            "element NVARCHAR(MAX) NOT NULL, "
            "completed BIT NOT NULL, "
            "attempts INT NOT NULL DEFAULT 0, "
            "last_failure NVARCHAR(MAX) NULL, "
            "acquired_at DATETIME2 NULL, "
            "acquired_by UNIQUEIDENTIFIER NULL, "
            "created_at DATETIME2 NOT NULL, "
            "updated_at DATETIME2 NOT NULL)",
            table_name,
            table,
        ),
        or_else=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "id TEXT NOT NULL, "
            "queue_name TEXT NOT NULL, "
            "element TEXT NOT NULL, "
            "completed BOOLEAN NOT NULL, "
            "attempts INTEGER NOT NULL DEFAULT 0, "
            "last_failure TEXT NULL, "
            "acquired_at DATETIME NULL, "
            "acquired_by TEXT NULL, "
            "created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL)",
            table,
        ),
    )


def _index(
    sql: SqlClientService, table_name: str, suffix: str, columns: str, *, unique: bool = False
) -> Effect[object, SqlError]:
    """``CREATE [UNIQUE] INDEX idx_<table>_<suffix> ON <table> (<columns>)``
    unless it exists (MySQL has no ``IF NOT EXISTS``: the error is
    ignored)."""
    table = sql.identifier(table_name)
    index_name = f"idx_{table_name}_{suffix}"
    index = sql.identifier(index_name)
    kind = sql.literal("UNIQUE INDEX" if unique else "INDEX")
    cols = sql.unsafe(columns)
    return sql.on_dialect_or_else(
        mssql=lambda: sql(
            "IF NOT EXISTS (SELECT * FROM sys.indexes WHERE name = {}) CREATE {} {} ON {} ({})",
            index_name,
            kind,
            index,
            table,
            cols,
        ),
        mysql=lambda: sql("CREATE {} {} ON {} ({})", kind, index, table, cols).ignore(),
        or_else=lambda: sql("CREATE {} IF NOT EXISTS {} ON {} ({})", kind, index, table, cols),
    )


def _create(table_name: str) -> Effect[object, object, SqlClient]:
    def body() -> Generator[Any, Any]:
        sql = (yield from SqlClient()).without_transforms()
        yield from _create_table(sql, table_name)
        yield from _index(sql, table_name, "id", "id, queue_name", unique=True)
        yield from _index(sql, table_name, "take", "queue_name, completed, attempts, acquired_at")
        yield from _index(sql, table_name, "update", "sequence, acquired_by")

    return gen(body)


_UPGRADED_COLUMNS = (
    "sequence, id, queue_name, element, state, attempts, last_failure, visible_at, "
    "acquired_at, acquired_by, created_at, updated_at"
)


def _upgrade_pg(sql: SqlClientService, table_name: str) -> Effect[object, SqlError]:
    table = sql.identifier(table_name)
    take_index = sql.identifier(f"idx_{table_name}_take")

    def body() -> Generator[Any, Any]:
        yield from sql("DROP INDEX IF EXISTS {}", take_index)
        yield from sql(
            "ALTER TABLE {} ADD COLUMN state VARCHAR(10), ADD COLUMN visible_at TIMESTAMP", table
        )
        yield from sql(
            "UPDATE {} SET state = CASE WHEN completed THEN 'completed' ELSE 'pending' END, "
            "visible_at = updated_at",
            table,
        )
        yield from sql(
            "ALTER TABLE {} "
            "ALTER COLUMN sequence TYPE BIGINT, "
            "ALTER COLUMN id TYPE VARCHAR(255), "
            "ALTER COLUMN queue_name TYPE VARCHAR(255), "
            "ALTER COLUMN state SET NOT NULL, "
            "ALTER COLUMN visible_at SET NOT NULL, "
            "DROP COLUMN completed",
            table,
        )

    return gen(body)


def _upgrade_mysql(sql: SqlClientService, table_name: str) -> Effect[object, SqlError]:
    table = sql.identifier(table_name)
    take_index = sql.identifier(f"idx_{table_name}_take")

    def body() -> Generator[Any, Any]:
        yield from sql("DROP INDEX {} ON {}", take_index, table)
        yield from sql(
            "ALTER TABLE {} "
            "MODIFY COLUMN id VARCHAR(255) NOT NULL, "
            "MODIFY COLUMN queue_name VARCHAR(255) NOT NULL, "
            "MODIFY COLUMN element MEDIUMTEXT NOT NULL, "
            "MODIFY COLUMN last_failure MEDIUMTEXT NULL, "
            "ADD COLUMN state VARCHAR(10) NULL, "
            "ADD COLUMN visible_at DATETIME NULL",
            table,
        )
        yield from sql(
            "UPDATE {} SET state = CASE WHEN completed THEN 'completed' ELSE 'pending' END, "
            "visible_at = updated_at",
            table,
        )
        yield from sql(
            "ALTER TABLE {} "
            "MODIFY COLUMN state VARCHAR(10) NOT NULL, "
            "MODIFY COLUMN visible_at DATETIME NOT NULL, "
            "DROP COLUMN completed",
            table,
        )

    return gen(body)


def _upgrade_mssql(sql: SqlClientService, table_name: str) -> Effect[object, SqlError]:
    table = sql.identifier(table_name)
    upgraded_name = f"{table_name}_upgrade"
    upgraded = sql.identifier(upgraded_name)

    def body() -> Generator[Any, Any]:
        yield from sql(
            "CREATE TABLE {} ("
            "sequence BIGINT IDENTITY(1,1) PRIMARY KEY, "
            "id NVARCHAR(255) NOT NULL, "
            "queue_name NVARCHAR(255) NOT NULL, "
            "element NVARCHAR(MAX) NOT NULL, "
            "state NVARCHAR(10) NOT NULL, "
            "attempts INT NOT NULL DEFAULT 0, "
            "last_failure NVARCHAR(MAX) NULL, "
            "visible_at DATETIME2 NOT NULL, "
            "acquired_at DATETIME2 NULL, "
            "acquired_by UNIQUEIDENTIFIER NULL, "
            "created_at DATETIME2 NOT NULL, "
            "updated_at DATETIME2 NOT NULL)",
            upgraded,
        )
        yield from sql(
            "SET IDENTITY_INSERT {} ON; "
            "INSERT INTO {} (" + _UPGRADED_COLUMNS + ") "
            "SELECT sequence, id, queue_name, element, "
            "CASE WHEN completed = 1 THEN 'completed' ELSE 'pending' END, "
            "attempts, last_failure, updated_at, acquired_at, acquired_by, created_at, updated_at "
            "FROM {}; "
            "SET IDENTITY_INSERT {} OFF",
            upgraded,
            upgraded,
            table,
            upgraded,
        )
        yield from sql("DROP TABLE {}", table)
        yield from sql("EXEC sp_rename {}, {}", upgraded_name, table_name)
        yield from sql(
            "CREATE UNIQUE INDEX {} ON {} (id, queue_name)",
            sql.identifier(f"idx_{table_name}_id"),
            table,
        )
        yield from sql(
            "CREATE INDEX {} ON {} (sequence, acquired_by)",
            sql.identifier(f"idx_{table_name}_update"),
            table,
        )

    return gen(body)


def _upgrade_sqlite(sql: SqlClientService, table_name: str) -> Effect[object, SqlError]:
    """Rebuilds the table: altering or dropping constrained columns is not
    portable across SQLite versions."""
    table = sql.identifier(table_name)
    upgraded = sql.identifier(f"{table_name}_upgrade")

    def body() -> Generator[Any, Any]:
        yield from sql("DROP INDEX IF EXISTS {}", sql.identifier(f"idx_{table_name}_take"))
        yield from sql(
            "CREATE TABLE {} ("
            "sequence INTEGER PRIMARY KEY AUTOINCREMENT, "
            "id TEXT NOT NULL, "
            "queue_name TEXT NOT NULL, "
            "element TEXT NOT NULL, "
            "state TEXT NOT NULL, "
            "attempts INTEGER NOT NULL DEFAULT 0, "
            "last_failure TEXT NULL, "
            "visible_at DATETIME NOT NULL, "
            "acquired_at DATETIME NULL, "
            "acquired_by TEXT NULL, "
            "created_at DATETIME NOT NULL, "
            "updated_at DATETIME NOT NULL)",
            upgraded,
        )
        yield from sql(
            "INSERT INTO {} (" + _UPGRADED_COLUMNS + ") "
            "SELECT sequence, id, queue_name, element, "
            "CASE WHEN completed THEN 'completed' ELSE 'pending' END, "
            "attempts, last_failure, updated_at, acquired_at, acquired_by, created_at, updated_at "
            "FROM {}",
            upgraded,
            table,
        )
        yield from sql("DROP TABLE {}", table)
        yield from sql("ALTER TABLE {} RENAME TO {}", upgraded, table)
        yield from sql(
            "CREATE UNIQUE INDEX {} ON {} (id, queue_name)",
            sql.identifier(f"idx_{table_name}_id"),
            table,
        )
        yield from sql(
            "CREATE INDEX {} ON {} (sequence, acquired_by)",
            sql.identifier(f"idx_{table_name}_update"),
            table,
        )

    return gen(body)


def _upgrade(table_name: str) -> Effect[object, object, SqlClient]:
    def body() -> Generator[Any, Any]:
        sql = (yield from SqlClient()).without_transforms()
        table = sql.identifier(table_name)
        take_index = sql.identifier(f"idx_{table_name}_take")
        yield from sql.on_dialect_or_else(
            pg=lambda: _upgrade_pg(sql, table_name),
            mysql=lambda: _upgrade_mysql(sql, table_name),
            mssql=lambda: _upgrade_mssql(sql, table_name),
            or_else=lambda: _upgrade_sqlite(sql, table_name),
        )
        # a partial index where supported, so pollers never scan completed rows
        yield from sql.on_dialect_or_else(
            mysql=lambda: sql(
                "CREATE INDEX {} ON {} (queue_name, state, visible_at)", take_index, table
            ),
            or_else=lambda: sql(
                "CREATE INDEX {} ON {} (queue_name, visible_at) WHERE state = 'pending'",
                take_index,
                table,
            ),
        )

    return gen(body)


def migrations(table_name: str) -> migrator.Loader:
    return migrator.from_record(
        {
            "0001_create_table": _create(table_name),
            "0002_upgrade_schema": _upgrade(table_name),
        }
    )
