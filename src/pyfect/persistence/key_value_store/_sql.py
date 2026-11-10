"""``layer_sql``: a key-value store in a SQL table."""

from __future__ import annotations

import re
from collections.abc import Callable, Generator
from typing import Any, Final, Never

from pyfect._core import Effect
from pyfect._js import text_decoder, text_encode
from pyfect.effect import fail, gen, succeed
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.persistence._columns import column_bytes, column_int, column_text
from pyfect.persistence._sql_keys import MSSQL_KEY, MYSQL_KEY, key_equals, mssql_match
from pyfect.persistence.key_value_store._store import (
    KeyValueStore,
    KeyValueStoreError,
    KeyValueStoreService,
    Value,
    base64_encode,
    make,
)
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.connection import Row
from pyfect.sql.error import SqlError
from pyfect.sql.statement import Identifier, Statement

_STRING: Final = 0
_BYTES: Final = 1


def layer_sql(*, table: str = "effect_key_value_store") -> Layer[KeyValueStore, Never, SqlClient]:
    """A store in ``table`` (made if missing) of the ``SqlClient``: one row
    per key, the value as bytes and whether it was text."""
    return layer_effect(KeyValueStore, gen(lambda: _build(table)))


def _build(table_name: str) -> Generator[Effect[Any, Any, SqlClient], Any, KeyValueStoreService]:
    sql = (yield from SqlClient()).without_transforms()
    table = sql.identifier(table_name)
    yield from sql.on_dialect_or_else(
        mysql=lambda: sql(
            f"CREATE TABLE IF NOT EXISTS {{}} (id {MYSQL_KEY} PRIMARY KEY, value BLOB NOT NULL, "
            "value_type SMALLINT NOT NULL)",
            table,
        ),
        pg=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} (id TEXT PRIMARY KEY, value BYTEA NOT NULL, "
            "value_type SMALLINT NOT NULL)",
            table,
        ),
        mssql=lambda: sql(
            "IF NOT EXISTS (SELECT * FROM sysobjects WHERE name={} AND xtype='U') "
            f"CREATE TABLE {{}} (id {MSSQL_KEY} PRIMARY KEY, value VARBINARY(MAX) NOT NULL, "
            "value_type SMALLINT NOT NULL)",
            table_name,
            table,
        ),
        or_else=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} (id TEXT PRIMARY KEY, value BLOB NOT NULL, "
            "value_type INTEGER NOT NULL)",
            table,
        ),
    ).or_die()
    upsert = _upsert(sql, table)
    delete_by_prefix = _delete_by_prefix(sql, table)

    def failed(
        method: str, key: str | None, message: str
    ) -> Callable[[SqlError], KeyValueStoreError]:
        return lambda cause: KeyValueStoreError(message, method, key, cause)

    def select(method: str, key: str) -> Effect[Row | None, KeyValueStoreError]:
        return (
            sql("SELECT value, value_type FROM {} WHERE {}", table, key_equals(sql, "id", key))
            .map(lambda rows: rows[0] if rows else None)
            .map_error(failed(method, key, f"Unable to get item with key {key}"))
        )

    def invalid(method: str, key: str, row: Row) -> Effect[Any, KeyValueStoreError]:
        return fail(
            KeyValueStoreError(
                f"Invalid stored value type for key {key}: {row['value_type']}", method, key
            )
        )

    def get(key: str) -> Effect[str | None, KeyValueStoreError]:
        def read(row: Row | None) -> Effect[str | None, KeyValueStoreError]:
            if row is None:
                return succeed(None)
            data = column_bytes(row["value"])
            match row["value_type"]:
                case 0:
                    return succeed(text_decoder().decode(data, final=True))
                case 1:
                    return succeed(base64_encode(data))
                case _:
                    return invalid("get", key, row)

        return select("get", key).flat_map(read)

    def get_bytes(key: str) -> Effect[bytes | None, KeyValueStoreError]:
        def read(row: Row | None) -> Effect[bytes | None, KeyValueStoreError]:
            if row is None:
                return succeed(None)
            if row["value_type"] in (_STRING, _BYTES):
                return succeed(column_bytes(row["value"]))
            return invalid("get_bytes", key, row)

        return select("get_bytes", key).flat_map(read)

    def set_value(key: str, value: Value) -> Effect[None, KeyValueStoreError]:
        is_text = isinstance(value, str)
        data = text_encode(value) if isinstance(value, str) else value
        return (
            upsert(key, data, _STRING if is_text else _BYTES)
            .map_error(failed("set", key, f"Unable to set item with key {key}"))
            .as_void()
        )

    def remove(key: str) -> Effect[None, KeyValueStoreError]:
        return (
            sql("DELETE FROM {} WHERE {}", table, key_equals(sql, "id", key))
            .map_error(failed("remove", key, f"Unable to remove item with key {key}"))
            .as_void()
        )

    clear = (
        sql("DELETE FROM {}", table)
        .map_error(failed("clear", None, "Unable to clear storage"))
        .as_void()
    )
    size = (
        sql("SELECT COUNT(*) AS count FROM {}", table)
        .map_error(failed("size", None, "Unable to get size"))
        .map(lambda rows: column_int(rows[0]["count"]) if rows else 0)
    )
    keys = (
        sql("SELECT id FROM {}", table)
        .map_error(failed("keys", None, "Unable to get keys"))
        .map(lambda rows: [column_text(row["id"]) for row in rows])
    )

    def clear_prefix(prefix: str) -> Effect[None, KeyValueStoreError]:
        return (
            delete_by_prefix(prefix)
            .map_error(
                failed("clear_prefix", prefix, f"Unable to clear items with prefix {prefix}")
            )
            .as_void()
        )

    return make(
        get=get,
        get_bytes=get_bytes,
        set=set_value,
        remove=remove,
        clear=clear,
        clear_prefix=clear_prefix,
        size=size,
        keys=keys,
    )


def _escape_like(prefix: str) -> str:
    """``prefix`` as a ``LIKE ... ESCAPE '!'`` pattern matching the keys
    starting with it."""
    return re.sub(r"[!%_\[\]]", lambda match: "!" + match.group(), prefix) + "%"


def _delete_by_prefix(
    sql: SqlClientService, table: Identifier
) -> Callable[[str], Effect[object, SqlError]]:
    # The first LIKE uses the primary key index. On MySQL and SQL Server it
    # follows the column's collation, which may ignore case or accents (a
    # table made before, or by hand), so a second binary LIKE keeps only
    # exact prefix matches. SQLite's LIKE ignores case: compare the leading
    # characters instead.
    def sqlite() -> Callable[[str], Effect[object, SqlError]]:
        return lambda prefix: sql(
            "DELETE FROM {} WHERE substr(id, 1, length({})) = {}", table, prefix, prefix
        )

    def pg() -> Callable[[str], Effect[object, SqlError]]:
        return lambda prefix: sql(
            "DELETE FROM {} WHERE id LIKE {} ESCAPE '!'", table, _escape_like(prefix)
        )

    def mysql() -> Callable[[str], Effect[object, SqlError]]:
        return lambda prefix: sql(
            "DELETE FROM {} WHERE id LIKE {} ESCAPE '!' AND CONVERT(id USING utf8mb4) "
            "COLLATE utf8mb4_bin LIKE {} ESCAPE '!'",
            table,
            _escape_like(prefix),
            _escape_like(prefix),
        )

    def mssql() -> Callable[[str], Effect[object, SqlError]]:
        return lambda prefix: sql(
            "DELETE FROM {} WHERE id LIKE {} ESCAPE '!' AND id COLLATE Latin1_General_100_BIN2 "
            "LIKE {} ESCAPE '!'",
            table,
            _escape_like(prefix),
            _escape_like(prefix),
        )

    return sql.on_dialect_or_else(pg=pg, mysql=mysql, mssql=mssql, or_else=sqlite)


type _Upsert = Callable[[str, bytes, int], Effect[object, SqlError]]


def _upsert(sql: SqlClientService, table: Identifier) -> _Upsert:
    def pg() -> _Upsert:
        return lambda key, value, value_type: _unprepared(
            sql(
                "INSERT INTO {} (id, value, value_type) VALUES ({}, {}, {}) "
                "ON CONFLICT (id) DO UPDATE SET value=EXCLUDED.value, "
                "value_type=EXCLUDED.value_type",
                table,
                key,
                value,
                value_type,
            )
        )

    def mysql() -> _Upsert:
        return lambda key, value, value_type: sql(
            "INSERT INTO {} (id, value, value_type) VALUES ({}, {}, {}) "
            "ON DUPLICATE KEY UPDATE value=VALUES(value), value_type=VALUES(value_type)",
            table,
            key,
            value,
            value_type,
        )

    def mssql() -> _Upsert:
        return lambda key, value, value_type: sql(
            "MERGE {} AS target USING (SELECT {} AS id, {} AS value, {} AS value_type) AS source "
            f"ON {mssql_match('id')} "
            "WHEN MATCHED THEN UPDATE SET value = source.value, value_type = source.value_type "
            "WHEN NOT MATCHED THEN INSERT (id, value, value_type) "
            "VALUES (source.id, source.value, source.value_type);",
            table,
            key,
            value,
            value_type,
        )

    def sqlite() -> _Upsert:
        return lambda key, value, value_type: _unprepared(
            sql(
                "INSERT INTO {} (id, value, value_type) VALUES ({}, {}, {}) "
                "ON CONFLICT(id) DO UPDATE SET value=excluded.value, "
                "value_type=excluded.value_type",
                table,
                key,
                value,
                value_type,
            )
        )

    return sql.on_dialect_or_else(pg=pg, mysql=mysql, mssql=mssql, or_else=sqlite)


def _unprepared(statement: Statement[Row]) -> Effect[list[Row], SqlError]:
    return statement.unprepared
