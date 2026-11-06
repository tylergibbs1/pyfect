"""Storage of an unencrypted event log server in a SQL database (Effect's
``eventlog/SqlEventLogServerUnencrypted``), on SQLite or PostgreSQL.

Entries of every store share ``entry_table_prefix``, numbered per store
from 1 by ``<entry_table_prefix>_stores``. Writes lock their store's row,
so writers in other processes queue; changes are published once the
outermost transaction commits, and storage-owned transactions hold a
permit through commit and publication so changes stream in commit order.
"""

from __future__ import annotations

import itertools
from collections.abc import Generator, Mapping, Sequence
from typing import Any, Literal, Never, cast

from pyfect._context_effects import service_option
from pyfect._core import Effect
from pyfect.effect import die, fail, gen, succeed
from pyfect.eventlog.event_journal import (
    Entry,
    EntryId,
    RemoteEntry,
    RemoteId,
    StoreId,
    make_remote_id_unsafe,
)
from pyfect.eventlog.event_log import RegisteredCompactor
from pyfect.eventlog.event_log_server_unencrypted import Storage, StorageService, compact_backlog
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.persistence._columns import column_bytes, column_int
from pyfect.pubsub import PubSub
from pyfect.rc_map import RcMap
from pyfect.scope import Scope, acquire_release, scoped
from pyfect.semaphore import Semaphore
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.connection import Row
from pyfect.sql.error import ConstraintError, SqlError, UniqueViolation
from pyfect.sql.statement import Fragment, Identifier, Statement
from pyfect.stream import Stream, from_iterable, from_subscription
from pyfect.stream import unwrap as stream_unwrap

__all__ = ["SqlError", "layer_storage", "make_storage"]

type _Dialect = Literal["sqlite", "pg", "mysql"]

# Keeps each history lookup within the dialects' bind parameter limits.
_LOOKUP_BATCH_SIZE = 200


def _dialect(sql: SqlClientService) -> _Dialect:
    match sql.dialect:
        case "sqlite" | "pg" | "mysql":
            return sql.dialect
        case _:
            pass
    raise ValueError(
        f"SqlEventLogServerUnencrypted supports SQLite, PostgreSQL and MySQL, not {sql.dialect}"
    )


def _to_remote_entry(row: Row) -> RemoteEntry:
    return RemoteEntry(
        remote_sequence=column_int(row["sequence"]),
        entry=Entry(
            id=EntryId(column_bytes(row["entry_id"])),
            event=str(row["event"]),
            primary_key=str(row["primary_key"]),
            payload=column_bytes(row["payload"]),
        ),
    )


def _open_pubsub(_store_id: str) -> Effect[PubSub[RemoteEntry], Never, Scope]:
    return acquire_release(PubSub[RemoteEntry].unbounded(), lambda p, _: p.shutdown())


def _is_constraint_conflict(error: SqlError) -> bool:
    return isinstance(error.reason, ConstraintError | UniqueViolation)


def make_storage(
    *,
    entry_table_prefix: str = "effect_events",
    remote_id_table: str = "effect_remote_id",
    insert_batch_size: int = 200,
) -> Effect[StorageService, SqlError, SqlClient | Scope]:
    """Storage in the ``SqlClient``'s database, creating its tables
    (Effect's ``makeStorage``). ``insert_batch_size`` rows go in one
    ``INSERT`` (one, if that is below 1, as Effect flushes at the size). Fails
    with ``ValueError`` as a defect on a dialect other than SQLite, PostgreSQL
    or MySQL."""

    def build():
        sql = (yield from SqlClient()).without_transforms()
        dialect = _dialect(sql)
        tables = _Tables(sql, entry_table_prefix, remote_id_table)
        yield from _create_tables(sql, dialect, tables)
        remote_id = yield from _remote_id(sql, tables.remote_id)
        pubsubs = yield from RcMap.make(_open_pubsub, idle_time_to_live=300)
        semaphore = yield from Semaphore.make(1)
        return _SqlStorage(
            sql=sql,
            dialect=dialect,
            tables=tables,
            remote_id=remote_id,
            pubsubs=pubsubs,
            semaphore=semaphore,
            insert_batch_size=insert_batch_size,
        )

    return gen(build).with_tracer_enabled(False)


def layer_storage(
    *,
    entry_table_prefix: str = "effect_events",
    remote_id_table: str = "effect_remote_id",
    insert_batch_size: int = 200,
) -> Layer[Storage, SqlError, SqlClient]:
    """The ``Storage`` of ``make_storage``."""
    return layer_effect(
        Storage,
        make_storage(
            entry_table_prefix=entry_table_prefix,
            remote_id_table=remote_id_table,
            insert_batch_size=insert_batch_size,
        ),
    )


class _Tables:
    __slots__ = ("bindings", "entries", "entries_name", "remote_id", "stores")

    def __init__(self, sql: SqlClientService, prefix: str, remote_id_table: str) -> None:
        self.entries_name = prefix
        self.entries: Identifier = sql.identifier(prefix)
        self.remote_id: Identifier = sql.identifier(remote_id_table)
        self.stores: Identifier = sql.identifier(f"{prefix}_stores")
        self.bindings: Identifier = sql.identifier(f"{prefix}_session_auth_bindings")


def _create_mysql_tables(sql: SqlClientService, t: _Tables) -> Effect[None, SqlError]:
    event_key_index = f"{t.entries_name}_event_key_idx"

    def body():
        yield from sql(
            "CREATE TABLE IF NOT EXISTS {} (singleton INT PRIMARY KEY, "
            "remote_id BINARY(16) NOT NULL)",
            t.remote_id,
        )
        yield from sql(
            "CREATE TABLE IF NOT EXISTS {} (store_id VARCHAR(191) NOT NULL, "
            "sequence BIGINT NOT NULL, entry_id BINARY(16) NOT NULL, event TEXT NOT NULL, "
            "primary_key TEXT NOT NULL, payload BLOB NOT NULL, "
            "PRIMARY KEY (store_id, sequence), UNIQUE (store_id, entry_id))",
            t.entries,
        )
        # Serves the batch lookup in ``entries_after`` on prefixes. MySQL has
        # no ``IF NOT EXISTS`` for indexes: an existing one fails the create.
        index_exists = sql(
            "SELECT COUNT(*) AS count FROM information_schema.statistics "
            "WHERE table_schema = DATABASE() AND table_name = {} AND index_name = {}",
            t.entries_name,
            event_key_index,
        ).map(lambda rows: column_int(rows[0]["count"]) > 0)

        def unless_exists(error: SqlError) -> Effect[None, SqlError]:
            return index_exists.flat_map(lambda exists: succeed(None) if exists else fail(error))

        yield from (
            sql(
                "CREATE INDEX {} ON {} (store_id, event(191), primary_key(191), entry_id)",
                sql.identifier(event_key_index),
                t.entries,
            )
            .as_void()
            .catch_all(unless_exists)
        )
        yield from sql(
            "CREATE TABLE IF NOT EXISTS {} (store_id VARCHAR(191) PRIMARY KEY, "
            "next_sequence BIGINT NOT NULL)",
            t.stores,
        )
        yield from sql(
            "CREATE TABLE IF NOT EXISTS {} (public_key VARCHAR(191) PRIMARY KEY, "
            "signing_public_key BINARY(32) NOT NULL)",
            t.bindings,
        )

    return gen(body)


def _create_tables(sql: SqlClientService, dialect: _Dialect, t: _Tables) -> Effect[None, SqlError]:
    if dialect == "mysql":
        return _create_mysql_tables(sql, t)
    pg = dialect == "pg"
    event_key_index = sql.identifier(f"{t.entries_name}_event_key_idx")

    def body():
        if pg:
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (singleton INT PRIMARY KEY, "
                "remote_id BYTEA NOT NULL)",
                t.remote_id,
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (store_id TEXT NOT NULL, sequence BIGINT NOT NULL, "
                "entry_id BYTEA NOT NULL, event TEXT NOT NULL, primary_key TEXT NOT NULL, "
                "payload BYTEA NOT NULL, PRIMARY KEY (store_id, sequence), "
                "UNIQUE (store_id, entry_id))",
                t.entries,
            )
            # Serves the batch lookup in ``entries_after``; hashes stay under
            # PostgreSQL's B-tree row limit.
            yield from sql(
                "CREATE INDEX IF NOT EXISTS {} ON {} (store_id, hashtextextended(event, 0), "
                "hashtextextended(primary_key, 0), entry_id)",
                event_key_index,
                t.entries,
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (store_id TEXT PRIMARY KEY, "
                "next_sequence BIGINT NOT NULL)",
                t.stores,
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (public_key TEXT PRIMARY KEY, "
                "signing_public_key BYTEA NOT NULL)",
                t.bindings,
            )
        else:
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (singleton INTEGER PRIMARY KEY, "
                "remote_id BLOB NOT NULL)",
                t.remote_id,
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (store_id TEXT NOT NULL, sequence INTEGER NOT NULL, "
                "entry_id BLOB NOT NULL, event TEXT NOT NULL, primary_key TEXT NOT NULL, "
                "payload BLOB NOT NULL, PRIMARY KEY (store_id, sequence), "
                "UNIQUE (store_id, entry_id))",
                t.entries,
            )
            yield from sql(
                "CREATE INDEX IF NOT EXISTS {} ON {} (store_id, event, primary_key, entry_id)",
                event_key_index,
                t.entries,
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (store_id TEXT PRIMARY KEY, "
                "next_sequence INTEGER NOT NULL)",
                t.stores,
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (public_key TEXT PRIMARY KEY, "
                "signing_public_key BLOB NOT NULL)",
                t.bindings,
            )

    return gen(body)


def _remote_id(sql: SqlClientService, table: Identifier) -> Effect[RemoteId, SqlError]:
    select = sql("SELECT remote_id FROM {} WHERE singleton = 1", table)

    def first(rows: list[Row]) -> RemoteId | None:
        return RemoteId(column_bytes(rows[0]["remote_id"])) if rows else None

    def body():
        existing = first((yield from select))
        if existing is not None:
            return existing
        created = make_remote_id_unsafe()
        # Another process may insert first; its id wins.
        yield from sql(
            "INSERT INTO {} (singleton, remote_id) VALUES (1, {})", table, created
        ).catch_if(_is_constraint_conflict, lambda _: succeed([]))
        persisted = first((yield from select))
        return created if persisted is None else persisted

    return gen(body)


class _SqlStorage(StorageService):
    first_sequence = 1

    def __init__(
        self,
        *,
        sql: SqlClientService,
        dialect: _Dialect,
        tables: _Tables,
        remote_id: RemoteId,
        pubsubs: RcMap[str, PubSub[RemoteEntry]],
        semaphore: Semaphore,
        insert_batch_size: int,
    ) -> None:
        self._sql = sql
        self._dialect = dialect
        self._t = tables
        self._remote_id = remote_id
        self._pubsubs = pubsubs
        self._semaphore = semaphore
        self._insert_batch_size = insert_batch_size

    # --- statements -----------------------------------------------------------------

    def _publish(self, store_id: str, entries: Sequence[RemoteEntry]) -> Effect[None]:
        return scoped(
            self._pubsubs.get(store_id).flat_map(lambda p: p.publish_all(entries)).as_void()
        )

    def _transaction[A, E, R](self, effect: Effect[A, E, R]) -> Effect[A, E | SqlError, R]:
        # Hold the permit through commit and publication to preserve commit
        # order for storage-owned transactions.
        sql = self._sql

        def run(transaction: object) -> Effect[A, E | SqlError, R]:
            if transaction is not None:
                return sql.with_transaction(effect)
            return self._semaphore.with_permits(sql.with_transaction(effect))

        return service_option(sql.transaction_service).flat_map(run)

    def _ensure_store(self, store_id: str) -> Statement[Row]:
        if self._dialect == "mysql":
            return self._sql(
                "INSERT INTO {} (store_id, next_sequence) VALUES ({}, 1) "
                "ON DUPLICATE KEY UPDATE store_id = store_id",
                self._t.stores,
                store_id,
            )
        return self._sql(
            "INSERT INTO {} (store_id, next_sequence) VALUES ({}, 1) ON CONFLICT DO NOTHING",
            self._t.stores,
            store_id,
        )

    def _lock_store(self, store_id: str) -> Effect[int, SqlError]:
        sql = self._sql
        if self._dialect in ("pg", "mysql"):
            query = sql(
                "SELECT next_sequence FROM {} WHERE store_id = {} FOR UPDATE",
                self._t.stores,
                store_id,
            )
        else:
            query = sql(
                "UPDATE {} SET next_sequence = next_sequence WHERE store_id = {} "
                "RETURNING next_sequence",
                self._t.stores,
                store_id,
            )

        def decode(rows: list[Row]) -> Effect[int]:
            if not rows:
                return die(RuntimeError("SqlEventLogServerUnencrypted missing store sequence row"))
            return succeed(column_int(rows[0]["next_sequence"]))

        return query.flat_map(decode)

    def _select(self, where: Fragment) -> Statement[Row]:
        return self._sql(
            "SELECT sequence, entry_id, event, primary_key, payload FROM {} WHERE {}",
            self._t.entries,
            where,
        )

    def _matches_key(self, event: str, primary_keys: list[str]) -> Fragment:
        # PostgreSQL matches on the indexed hashes, then on the values to
        # rule out collisions.
        sql = self._sql
        if self._dialect == "pg":
            return sql(
                "hashtextextended(event, 0) = hashtextextended({}, 0) AND event = {} "
                "AND hashtextextended(primary_key, 0) IN ({}) AND {}",
                event,
                event,
                sql.csv([sql("hashtextextended({}, 0)", key) for key in primary_keys]),
                sql.in_("primary_key", primary_keys),
            )
        return sql("event = {} AND {}", event, sql.in_("primary_key", primary_keys))

    def _select_chunk_history(
        self, store_id: str, oldest: Entry, entries: Sequence[Entry]
    ) -> Effect[list[RemoteEntry], SqlError]:
        # One SELECT per index lookup, joined with UNION ALL: some databases
        # scan the whole store for the equivalent OR.
        sql = self._sql
        primary_keys_by_event: dict[str, dict[str, None]] = {}
        for entry in entries:
            primary_keys_by_event.setdefault(entry.event, {})[entry.primary_key] = None
        statement: Statement[Row] = self._select(
            sql(
                "store_id = {} AND {}",
                store_id,
                sql.in_("entry_id", [entry.id for entry in entries]),
            )
        )
        for event, primary_keys in primary_keys_by_event.items():
            statement = sql(
                "{} UNION ALL {}",
                statement,
                self._select(
                    sql(
                        "store_id = {} AND {} AND entry_id >= {}",
                        store_id,
                        self._matches_key(event, list(primary_keys)),
                        oldest.id,
                    )
                ),
            )
        return statement.map(lambda rows: [_to_remote_entry(r) for r in rows])

    def _select_batch_history(
        self, store_id: str, oldest: Entry, batch: Sequence[Entry]
    ) -> Effect[list[RemoteEntry], SqlError]:
        # Chunks and the UNION ALL branches can return the same row twice.
        def body():
            by_sequence: dict[int, RemoteEntry] = {}
            for chunk in itertools.batched(batch, _LOOKUP_BATCH_SIZE, strict=False):
                found = yield from self._select_chunk_history(store_id, oldest, chunk)
                for remote_entry in found:
                    by_sequence[remote_entry.remote_sequence] = remote_entry
            return [by_sequence[sequence] for sequence in sorted(by_sequence)]

        return gen(body)

    # --- the service ----------------------------------------------------------------

    @property
    def get_id(self) -> Effect[RemoteId]:
        return succeed(self._remote_id)

    def get_or_create_session_auth_binding(
        self, public_key: str, signing_public_key: bytes, /
    ) -> Effect[bytes]:
        sql = self._sql

        def body():
            rows = yield from sql(
                "SELECT public_key, signing_public_key FROM {} WHERE public_key = {}",
                self._t.bindings,
                public_key,
            )
            if rows:
                return column_bytes(rows[0]["signing_public_key"])
            yield from sql(
                "INSERT INTO {} (public_key, signing_public_key) VALUES ({}, {})",
                self._t.bindings,
                public_key,
                signing_public_key,
            )
            return signing_public_key

        return sql.with_transaction(gen(body)).or_die().with_tracer_enabled(False)

    def entries_after(
        self, store_id: StoreId, oldest: Entry, batch: Sequence[Entry] | None = None, /
    ) -> Effect[list[RemoteEntry]]:
        sql = self._sql
        if batch is None:
            found = sql(
                "SELECT sequence, entry_id, event, primary_key, payload FROM {} "
                "WHERE store_id = {} AND entry_id >= {} ORDER BY sequence ASC",
                self._t.entries,
                store_id,
                oldest.id,
            ).map(lambda rows: [_to_remote_entry(r) for r in rows])
        else:
            found = self._select_batch_history(store_id, oldest, batch)
        return found.or_die().with_tracer_enabled(False)

    def latest_sequence(self, store_id: StoreId, /) -> Effect[int | None]:
        def last(rows: Sequence[Mapping[str, object]]) -> int | None:
            found = rows[0]["sequence"]
            return None if found is None else column_int(found)

        return (
            self._sql(
                "SELECT MAX(sequence) AS sequence FROM {} WHERE store_id = {}",
                self._t.entries,
                store_id,
            )
            .map(last)
            .or_die()
            .with_tracer_enabled(False)
        )

    def write(self, store_id: StoreId, entries: Sequence[Entry], /) -> Effect[list[RemoteEntry]]:
        if not entries:
            return succeed([])
        sql = self._sql
        t = self._t

        def body() -> Generator[Effect[Any, SqlError, Any], Any, list[RemoteEntry]]:
            yield from self._ensure_store(store_id)
            current = yield from self._lock_store(store_id)
            committed = [
                RemoteEntry(remote_sequence=current + i, entry=entry)
                for i, entry in enumerate(entries)
            ]
            rows = [
                {
                    "store_id": store_id,
                    "sequence": remote_entry.remote_sequence,
                    "entry_id": remote_entry.entry.id,
                    "event": remote_entry.entry.event,
                    "primary_key": remote_entry.entry.primary_key,
                    "payload": remote_entry.entry.payload,
                }
                for remote_entry in committed
            ]
            for chunk in itertools.batched(rows, max(self._insert_batch_size, 1), strict=False):
                yield from sql("INSERT INTO {} {}", t.entries, sql.insert(chunk))
            yield from sql(
                "UPDATE {} SET next_sequence = {} WHERE store_id = {}",
                t.stores,
                current + len(entries),
                store_id,
            )
            yield from sql.after_commit(self._publish(store_id, committed))
            return committed

        return self._transaction(gen(body)).with_tracer_enabled(False).or_die()

    def changes(
        self,
        store_id: StoreId,
        start_sequence: int,
        compactors: Mapping[str, RegisteredCompactor],
        /,
    ) -> Stream[RemoteEntry]:
        sql = self._sql

        def body():
            pubsub = yield from self._pubsubs.get(store_id)
            subscription = yield from pubsub.subscribe()
            rows = yield from sql(
                "SELECT sequence, entry_id, event, primary_key, payload FROM {} "
                "WHERE store_id = {} AND sequence >= {} ORDER BY sequence ASC",
                self._t.entries,
                store_id,
                start_sequence,
            )
            remote_entries = [_to_remote_entry(r) for r in rows]
            backlog = yield from compact_backlog(remote_entries, compactors)
            # Compaction can drop trailing entries, so skip live entries up to
            # the last uncompacted one.
            watermark = remote_entries[-1].remote_sequence if remote_entries else start_sequence - 1

            def keep(remote_entry: RemoteEntry) -> bool:
                return remote_entry.remote_sequence > watermark

            return from_iterable(backlog).concat(from_subscription(subscription).filter(keep))

        return stream_unwrap(gen(body).or_die().with_tracer_enabled(False))

    def _with_transaction[A, E, R](self, effect: Effect[A, E, R], /) -> Effect[A, E, R]:
        def defect(error: object) -> Effect[Any]:
            return die(cast("BaseException", error))

        return cast(
            "Effect[A, E, R]",
            self._transaction(effect).catch_if(lambda e: isinstance(e, SqlError), defect),
        )
