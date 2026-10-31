"""``layer_backing_sql`` (one table) and ``layer_backing_sql_multi_table``
(a table per store): stores in SQL."""

from __future__ import annotations

from collections.abc import Callable, Generator, Mapping, Sequence
from typing import Any, Final, Never

from pyfect import _json_text
from pyfect._concurrency import for_each
from pyfect._core import Effect
from pyfect.clock import Clock, ClockService, now_nanos
from pyfect.duration import Seconds
from pyfect.effect import fail, gen, succeed, suspend
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.logger import log_warning
from pyfect.persistence._columns import column_int, column_text
from pyfect.persistence._error import PersistenceError
from pyfect.persistence._sql_keys import (
    MSSQL_KEY,
    MSSQL_PAIR_KEY,
    MYSQL_KEY,
    key_equals,
    mssql_match,
)
from pyfect.persistence.persistence._service import (
    BackingEntry,
    BackingPersistence,
    BackingPersistenceService,
    BackingPersistenceStore,
    now_millis,
    to_json,
    unsafe_ttl_to_expires,
)
from pyfect.schedule import spaced
from pyfect.scope import Scope, scoped
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.connection import Row
from pyfect.sql.error import SqlError
from pyfect.sql.statement import Fragment, Identifier

_BATCH_LIMIT: Final = "1000"
SQL_CLEANUP_BATCH_SIZE: Final = int(_BATCH_LIMIT)
"""How many expired entries the single-table backend deletes at a time."""

_CLEANUP_BATCH_DELAY: Final = 0.01
_CLEANUP_INTERVAL: Final = 300.0

type _Upsert = Callable[[list[dict[str, object]]], Effect[object, SqlError]]
type _Key = Mapping[str, str]
"""The columns naming a store's rows: none for a table of its own,
``store_id`` in the shared table."""


def _parse_failed(key: str, cause: BaseException) -> PersistenceError:
    return PersistenceError(
        message=f"Failed to parse value for key {key} from backing store", cause=cause
    )


def _make_store(
    sql: SqlClientService,
    clock: ClockService,
    table: Identifier,
    scope: _Key,
    upsert: _Upsert,
) -> BackingPersistenceStore:
    """A store over the rows of ``table`` matching ``scope``."""

    def where(*clauses: Fragment) -> Fragment:
        owned = [key_equals(sql, column, value) for column, value in scope.items()]
        return sql.and_([*owned, *clauses])

    def live() -> Fragment:
        return sql("(expires IS NULL OR expires > {})", now_millis(clock))

    def get(key: str) -> Effect[object | None, PersistenceError]:
        def parse(rows: list[Row]) -> Effect[object | None, PersistenceError]:
            if not rows:
                return succeed(None)
            try:
                return succeed(_json_text.parse(str(rows[0]["value"])))
            except ValueError as cause:
                return fail(_parse_failed(key, cause))

        return (
            suspend(
                lambda: sql(
                    "SELECT value FROM {} WHERE {}",
                    table,
                    where(key_equals(sql, "id", key), live()),
                )
            )
            .map_error(
                lambda cause: PersistenceError(
                    message=f"Failed to get key {key} from backing store", cause=cause
                )
            )
            .flat_map(parse)
        )

    def get_many(keys: Sequence[str]) -> Effect[list[object | None], PersistenceError]:
        def parse(rows: list[Row]) -> list[object | None]:
            values: dict[str, object] = {}
            for row in rows:
                try:
                    values[column_text(row["id"])] = _json_text.parse(str(row["value"]))
                except ValueError:
                    continue
            return [values.get(key) for key in keys]

        return (
            suspend(
                lambda: (
                    sql(
                        "SELECT id, value FROM {} WHERE {}",
                        table,
                        where(sql.in_("id", list(keys)), live()),
                    ).unprepared
                )
            )
            .map_error(
                lambda cause: PersistenceError(
                    message="Failed to getMany from backing store", cause=cause
                )
            )
            .map(parse)
        )

    def rows_of(entries: Sequence[BackingEntry]) -> list[dict[str, object]]:
        return [
            {
                **scope,
                "id": key,
                "value": to_json(value),
                "expires": unsafe_ttl_to_expires(clock, ttl),
            }
            for key, value, ttl in entries
        ]

    def write(
        entries: Sequence[BackingEntry], failed: str, unserializable: str
    ) -> Effect[None, PersistenceError]:
        def attempt() -> Effect[None, PersistenceError]:
            try:
                rows = rows_of(entries)
            except (TypeError, ValueError) as cause:
                return fail(PersistenceError(message=unserializable, cause=cause))
            return (
                upsert(rows)
                .map_error(lambda cause: PersistenceError(message=failed, cause=cause))
                .as_void()
            )

        return suspend(attempt)

    def set_value(key: str, value: object, ttl: Seconds | None) -> Effect[None, PersistenceError]:
        return write(
            ((key, value, ttl),),
            f"Failed to set key {key} in backing store",
            f"Failed to serialize value for key {key} to backing store",
        )

    def set_many(entries: Sequence[BackingEntry]) -> Effect[None, PersistenceError]:
        return write(
            entries,
            "Failed to setMany in backing store",
            "Failed to serialize values into backing store",
        )

    def remove(key: str) -> Effect[None, PersistenceError]:
        return (
            sql("DELETE FROM {} WHERE {}", table, where(key_equals(sql, "id", key)))
            .map_error(
                lambda cause: PersistenceError(
                    message=f"Failed to remove key {key} from backing store", cause=cause
                )
            )
            .as_void()
        )

    clear = (
        sql("DELETE FROM {} WHERE {}", table, where())
        .map_error(
            lambda cause: PersistenceError(message="Failed to clear backing store", cause=cause)
        )
        .as_void()
    )
    return BackingPersistenceStore(
        get=get, get_many=get_many, set=set_value, set_many=set_many, remove=remove, clear=clear
    )


def _upsert(sql: SqlClientService, table: Identifier, *, single_table: bool) -> _Upsert:
    """Insert rows, replacing ``value`` and ``expires`` of rows with the
    same key (``store_id`` and ``id`` in the single table)."""
    conflict = sql.literal("store_id, id" if single_table else "id")

    def pg() -> _Upsert:
        return lambda rows: (
            sql(
                "INSERT INTO {} {} ON CONFLICT ({}) DO UPDATE SET value=EXCLUDED.value, "
                "expires=EXCLUDED.expires",
                table,
                sql.insert(rows),
                conflict,
            ).unprepared
        )

    def mysql() -> _Upsert:
        return lambda rows: (
            sql(
                "INSERT INTO {} {} ON DUPLICATE KEY UPDATE value=VALUES(value), "
                "expires=VALUES(expires)",
                table,
                sql.insert(rows),
            ).unprepared
        )

    def merge(row: Mapping[str, object]) -> Effect[object, SqlError]:
        if single_table:
            return sql(
                "MERGE {} AS target USING (SELECT {} AS store_id, {} AS id, {} AS value, "
                "{} AS expires) AS source "
                f"ON {mssql_match('store_id')} AND {mssql_match('id')} "
                "WHEN MATCHED THEN UPDATE SET value = source.value, expires = source.expires "
                "WHEN NOT MATCHED THEN INSERT (store_id, id, value, expires) "
                "VALUES (source.store_id, source.id, source.value, source.expires);",
                table,
                row["store_id"],
                row["id"],
                row["value"],
                row["expires"],
            )
        return sql(
            "MERGE {} AS target USING (SELECT {} AS id, {} AS value, {} AS expires) AS source "
            f"ON {mssql_match('id')} "
            "WHEN MATCHED THEN UPDATE SET value = source.value, expires = source.expires "
            "WHEN NOT MATCHED THEN INSERT (id, value, expires) "
            "VALUES (source.id, source.value, source.expires);",
            table,
            row["id"],
            row["value"],
            row["expires"],
        )

    def mssql() -> _Upsert:
        return lambda rows: for_each(rows, merge).as_void()

    def sqlite() -> _Upsert:
        return lambda rows: (
            sql(
                "INSERT INTO {} {} ON CONFLICT({}) DO UPDATE SET value=excluded.value, "
                "expires=excluded.expires",
                table,
                sql.insert(rows),
                conflict,
            ).unprepared
        )

    return sql.on_dialect_or_else(pg=pg, mysql=mysql, mssql=mssql, or_else=sqlite)


# --- a table per store ---------------------------------------------------------------


def _build_multi_table() -> Generator[
    Effect[Any, Never, SqlClient], Any, BackingPersistenceService
]:
    sql = (yield from SqlClient()).without_transforms()

    def make(store_id: str) -> Generator[Effect[Any, Never, Any], Any, BackingPersistenceStore]:
        clock = yield from Clock()
        table_name = f"effect_persistence_{store_id}"
        table = sql.identifier(table_name)
        yield from sql.on_dialect_or_else(
            mysql=lambda: sql(
                f"CREATE TABLE IF NOT EXISTS {{}} (id {MYSQL_KEY} PRIMARY KEY, "
                "value TEXT NOT NULL, expires BIGINT)",
                table,
            ),
            pg=lambda: sql(
                "CREATE TABLE IF NOT EXISTS {} (id TEXT PRIMARY KEY, value TEXT NOT NULL, "
                "expires BIGINT)",
                table,
            ),
            mssql=lambda: sql(
                "IF NOT EXISTS (SELECT * FROM sysobjects WHERE name={} AND xtype='U') "
                f"CREATE TABLE {{}} (id {MSSQL_KEY} PRIMARY KEY, "
                "value NVARCHAR(MAX) NOT NULL, expires BIGINT)",
                table_name,
                table,
            ),
            or_else=lambda: sql(
                "CREATE TABLE IF NOT EXISTS {} (id TEXT PRIMARY KEY, value TEXT NOT NULL, "
                "expires INTEGER)",
                table,
            ),
        ).or_die()
        yield from sql(
            "DELETE FROM {} WHERE expires IS NOT NULL AND expires <= {}",
            table,
            now_millis(clock),
        ).ignore()
        return _make_store(sql, clock, table, {}, _upsert(sql, table, single_table=False))

    return BackingPersistenceService(lambda store_id: gen(lambda: make(store_id)))


layer_backing_sql_multi_table: Layer[BackingPersistence, Never, SqlClient] = layer_effect(
    BackingPersistence, gen(_build_multi_table)
)
"""Each store in a table of its own, ``effect_persistence_<store id>``
(made if missing; expired rows are deleted when a store is opened)."""


# --- one table ------------------------------------------------------------------------


def _build_single_table() -> Generator[
    Effect[Any, Never, SqlClient | Scope], Any, BackingPersistenceService
]:
    sql = (yield from SqlClient()).without_transforms()
    table = sql.identifier("effect_persistence")
    yield from sql.on_dialect_or_else(
        mysql=lambda: sql(
            f"CREATE TABLE IF NOT EXISTS {{}} (store_id {MYSQL_KEY} NOT NULL, "
            f"id {MYSQL_KEY} NOT NULL, value TEXT NOT NULL, expires BIGINT, "
            "PRIMARY KEY (store_id, id))",
            table,
        ),
        pg=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} (store_id TEXT NOT NULL, id TEXT NOT NULL, "
            "value TEXT NOT NULL, expires BIGINT, PRIMARY KEY (store_id, id))",
            table,
        ),
        mssql=lambda: sql(
            "IF NOT EXISTS (SELECT * FROM sysobjects WHERE name={} AND xtype='U') "
            f"CREATE TABLE {{}} (store_id {MSSQL_PAIR_KEY} NOT NULL, "
            f"id {MSSQL_PAIR_KEY} NOT NULL, "
            "value NVARCHAR(MAX) NOT NULL, expires BIGINT, PRIMARY KEY (store_id, id))",
            "effect_persistence",
            table,
        ),
        or_else=lambda: sql(
            "CREATE TABLE IF NOT EXISTS {} (store_id TEXT NOT NULL, id TEXT NOT NULL, "
            "value TEXT NOT NULL, expires INTEGER, PRIMARY KEY (store_id, id))",
            table,
        ),
    ).or_die()
    yield from _create_expires_index(sql, table)
    delete_batch = _delete_expired_batch(sql, table)

    def delete_expired() -> Generator[Effect[Any, SqlError, Any], Any, int]:
        expires_at_or_before = (yield from now_nanos()) // 1_000_000
        return (
            yield from delete_batch(expires_at_or_before).repeat(
                while_=lambda deleted: deleted == SQL_CLEANUP_BATCH_SIZE,
                schedule=spaced(_CLEANUP_BATCH_DELAY),
            )
        )

    yield from (
        gen(delete_expired)
        .catch_all(
            lambda cause: log_warning("Failed to clean up expired persistence entries", cause)
        )
        .repeat(spaced(_CLEANUP_INTERVAL))
        .fork_scoped()
    )
    upsert = _upsert(sql, table, single_table=True)

    def make(store_id: str) -> Effect[BackingPersistenceStore]:
        return Clock().map(
            lambda clock: _make_store(sql, clock, table, {"store_id": store_id}, upsert)
        )

    return BackingPersistenceService(make)


def _create_expires_index(sql: SqlClientService, table: Identifier) -> Effect[None]:
    partial = sql(
        "CREATE INDEX IF NOT EXISTS effect_persistence_expires_idx ON {} (expires) "
        "WHERE expires IS NOT NULL",
        table,
    )

    def unless_exists(
        create: Effect[object, SqlError], exists: Effect[list[Row], SqlError]
    ) -> Effect[None]:
        def recover(error: SqlError) -> Effect[None, SqlError]:
            return exists.flat_map(
                lambda rows: succeed(None) if column_int(rows[0]["count"]) > 0 else fail(error)
            )

        return create.as_void().catch_all(recover).or_die()

    def mysql() -> Effect[None]:
        return unless_exists(
            sql("CREATE INDEX effect_persistence_expires_idx ON {} (expires)", table),
            sql(
                "SELECT COUNT(*) AS count FROM information_schema.statistics "
                "WHERE table_schema = DATABASE() AND table_name = 'effect_persistence' "
                "AND index_name = 'effect_persistence_expires_idx'"
            ),
        )

    def mssql() -> Effect[None]:
        return unless_exists(
            sql(
                "CREATE INDEX effect_persistence_expires_idx ON {} (expires) "
                "WHERE expires IS NOT NULL",
                table,
            ),
            sql(
                "SELECT COUNT(*) AS count FROM sys.indexes "
                "WHERE name = N'effect_persistence_expires_idx' "
                "AND object_id = OBJECT_ID(N'effect_persistence')"
            ),
        )

    return sql.on_dialect_or_else(
        mysql=mysql, mssql=mssql, or_else=lambda: partial.as_void().or_die()
    )


def _delete_expired_batch(
    sql: SqlClientService, table: Identifier
) -> Callable[[int], Effect[int, SqlError]]:
    """Delete up to ``SQL_CLEANUP_BATCH_SIZE`` rows expired by the given
    time; the number deleted."""
    limit = sql.literal(_BATCH_LIMIT)

    def pg() -> Callable[[int], Effect[int, SqlError]]:
        return lambda before: sql(
            "WITH deleted_entries AS (DELETE FROM {} WHERE ctid IN (SELECT ctid FROM {} "
            "WHERE expires IS NOT NULL AND expires <= {} LIMIT {}) RETURNING 1) "
            "SELECT COUNT(*)::INT AS count FROM deleted_entries",
            table,
            table,
            before,
            limit,
        ).map(lambda rows: column_int(rows[0]["count"]))

    def mysql() -> Callable[[int], Effect[int, SqlError]]:
        def run(before: int) -> Effect[int, SqlError]:
            statement, params = sql(
                "DELETE FROM {} WHERE expires IS NOT NULL AND expires <= {} LIMIT {}",
                table,
                before,
                limit,
            ).compile()

            def body() -> Generator[Effect[Any, SqlError, Scope], Any, int]:
                connection = yield from sql.reserve
                yield from connection.execute(statement, params, None)
                rows = yield from connection.execute_values("SELECT ROW_COUNT()", ())
                return column_int(rows[0][0])

            return scoped(gen(body))

        return run

    def mssql() -> Callable[[int], Effect[int, SqlError]]:
        return lambda before: sql(
            "WITH expired_entries AS (SELECT TOP {} store_id, id FROM {} "
            "WITH (UPDLOCK, READPAST, READCOMMITTEDLOCK) "
            "WHERE expires IS NOT NULL AND expires <= {}) "
            "DELETE persistence OUTPUT DELETED.store_id FROM {} AS persistence "
            "INNER JOIN expired_entries ON persistence.store_id = expired_entries.store_id "
            "AND persistence.id = expired_entries.id",
            limit,
            table,
            before,
            table,
        ).map(len)

    def sqlite() -> Callable[[int], Effect[int, SqlError]]:
        # One bounded statement: some SQLite clients have no interactive
        # transactions.
        return lambda before: sql(
            "DELETE FROM {} WHERE rowid IN (SELECT rowid FROM {} "
            "WHERE expires IS NOT NULL AND expires <= {} LIMIT {}) RETURNING 1 AS deleted",
            table,
            table,
            before,
            limit,
        ).map(len)

    return sql.on_dialect_or_else(pg=pg, mysql=mysql, mssql=mssql, or_else=sqlite)


layer_backing_sql: Layer[BackingPersistence, Never, SqlClient] = layer_effect(
    BackingPersistence, gen(_build_single_table)
)
"""Every store in one table, ``effect_persistence``, keyed by store id and
key (made if missing, with an index on ``expires``). Expired rows are
deleted in batches when the layer is built and every five minutes."""
