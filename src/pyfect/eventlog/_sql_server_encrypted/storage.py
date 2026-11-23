"""The SQL encrypted storage (Effect's ``SqlEventLogServerEncrypted.makeStorage``):
opening stores, writes, acks and changes. Compaction is in
``compaction.py`` and the sweep in ``sweeper.py``.
"""

from __future__ import annotations

import itertools
import threading
from collections.abc import Sequence
from typing import Any

from pyfect._core import Effect
from pyfect.clock import Clock, now_millis_unsafe
from pyfect.crypto.digest import Digest, DigestService
from pyfect.effect import gen, succeed
from pyfect.eventlog._server_encrypted.audit import hour_of
from pyfect.eventlog._server_encrypted.models import CompactionOptions, make_compaction_config
from pyfect.eventlog._server_encrypted.storage import StorageService
from pyfect.eventlog._sql_server_encrypted import upgrade
from pyfect.eventlog._sql_server_encrypted.compaction import SqlCompaction
from pyfect.eventlog._sql_server_encrypted.db import (
    CHUNK,
    BatchRow,
    Db,
    Steps,
    StoreResources,
    batch_chunks,
)
from pyfect.eventlog._sql_server_encrypted.legacy import (
    UPGRADE_NOTES,
    LegacyMigration,
    LegacyStoreNeedsMigration,
    Resolved,
    legacy_key,
    resolve_scope,
    still_resolves,
)
from pyfect.eventlog._sql_server_encrypted.rows import to_batch
from pyfect.eventlog._sql_server_encrypted.sweeper import Sweeper
from pyfect.eventlog._sql_server_encrypted.tables import create_scope_tables
from pyfect.eventlog.event_journal import EntryId, RemoteId, StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, EncryptedRemoteBatch
from pyfect.eventlog.event_log_message import WriteAck
from pyfect.logger import log_info, log_warning
from pyfect.persistence._columns import column_bytes, column_int
from pyfect.persistence._sql_keys import key_equals
from pyfect.pubsub import PubSub
from pyfect.rc_map import RcMap
from pyfect.schedule import fixed
from pyfect.scope import Scope, acquire_release, fork_scoped, scoped
from pyfect.semaphore import Semaphore
from pyfect.sql.client import SqlClient
from pyfect.sql.error import SqlError
from pyfect.stream import Stream, from_iterable, from_subscription
from pyfect.stream import die as stream_die
from pyfect.stream import unwrap as stream_unwrap

type _Pair = tuple[str, str]
"""A store's public key and id."""


class _Once:
    """Logs each (tables, pair, event) once per process, however many
    storages open it, remembering the latest 4096."""

    def __init__(self) -> None:
        self._seen: dict[tuple[str, _Pair, str], None] = {}
        self._lock = threading.Lock()

    def _first(self, key: tuple[str, _Pair, str]) -> bool:
        with self._lock:
            if key in self._seen:
                return False
            if len(self._seen) >= 4096:
                del self._seen[next(iter(self._seen))]
            self._seen[key] = None
            return True

    def log(self, db: Db, pair: _Pair, event: str, log: Effect[None]) -> Effect[None]:
        def body():
            if self._first((db.prefix, pair, event)):
                yield from log.annotate_logs({"service": "SqlEventLogServerEncrypted"})

        return gen(body)


_once = _Once()


def _resolve(
    db: Db, digest: DigestService, migration: LegacyMigration, pair: _Pair
) -> Effect[str, SqlError | LegacyStoreNeedsMigration]:
    """The pair's scope, logging a migration, a split, new tables beside
    legacy ones, or a refusal once per process."""
    public_key, store_id = pair
    legacy = legacy_key(public_key, store_id)

    def logged(resolved: Resolved) -> Effect[str]:
        match resolved.event:
            case "migrated":
                message = (
                    f"Store {store_id!r} of {public_key!r} now holds its tables from pyfect "
                    f"0.6.5 ({legacy!r}): it is the only identity sharing that name that had "
                    "authenticated before the upgrade, and migrate_legacy_stores is "
                    "'when_server_written'"
                )
                return _once.log(db, pair, "migrated", log_info(message)).as_(resolved.scope)
            case "split":
                message = (
                    f"Store {store_id!r} of {public_key!r} holds batches under its own tables "
                    f"and under those pyfect 0.6.5 named {legacy!r}: a 0.6.5 node wrote to it "
                    "after it opened on a newer version. Only its own tables are served; stop "
                    f"every 0.6.5 node (see {UPGRADE_NOTES})"
                )
                return _once.log(db, pair, "split", log_warning(message)).as_(resolved.scope)
            case "beside":
                message = (
                    f"Store {store_id!r} of {public_key!r} opens tables of its own while the "
                    f"tables pyfect 0.6.5 named {legacy!r} hold batches that another store has "
                    "or may get. If this store wrote them, they were given to the wrong store: "
                    f"check {legacy!r} with legacy_stores (see {UPGRADE_NOTES})"
                )
                return _once.log(db, pair, "beside", log_warning(message)).as_(resolved.scope)
            case None:
                return succeed(resolved.scope)

    def refused(error: SqlError | LegacyStoreNeedsMigration) -> Effect[None]:
        if isinstance(error, LegacyStoreNeedsMigration):
            return _once.log(db, pair, "refused", log_warning(error.message))
        return succeed(None)

    return (
        resolve_scope(db, digest, public_key, store_id, migration)
        .tap_error(refused)
        .flat_map(logged)
    )


def _make_lookup(db: Db, digest: DigestService, migration: LegacyMigration):
    # Stores whose tables and row this instance has ensured, so a store
    # reopened after idling skips the DDL.
    ensured: set[str] = set()

    def lookup(pair: _Pair) -> Effect[StoreResources, SqlError | LegacyStoreNeedsMigration, Scope]:
        def body():
            scope = yield from _resolve(db, digest, migration, pair)
            tables = db.scope_tables(scope)
            if scope not in ensured:
                yield from create_scope_tables(db.sql, f"{db.prefix}_{scope}")
                yield from db.ensure_store(scope, tables.table)
                ensured.add(scope)
            pubsub = yield from acquire_release(
                PubSub[EncryptedRemoteBatch].unbounded(), lambda p, _: p.shutdown()
            )
            return StoreResources(tables, pubsub, Semaphore(1))

        return gen(body).with_tracer_enabled(False)

    return lookup


class _Stores:
    """The open stores. A store that failed to open is forgotten at once, so
    the next request tries again (an ``RcMap`` keeps a failed lookup until
    it idles out, as Effect's does). An open store whose legacy tables the
    operator has given to it or taken from it since is opened again."""

    def __init__(
        self,
        stores: RcMap[_Pair, StoreResources, SqlError | LegacyStoreNeedsMigration],
        db: Db,
        digest: DigestService,
    ):
        self._stores = stores
        self._db = db
        self._digest = digest

    def current(self, pair: _Pair, scope: str) -> Effect[bool, SqlError]:
        """Whether the pair's store is still in ``scope``."""
        return still_resolves(self._db, self._digest, *pair, scope)

    def open(
        self, public_key: str, store_id: StoreId
    ) -> Effect[StoreResources, SqlError | LegacyStoreNeedsMigration, Scope]:
        pair = (public_key, store_id)

        def body():
            store = yield from self._stores.get(pair)
            if (yield from self.current(pair, store.scope)):
                return store
            yield from self._stores.invalidate(pair)
            return (yield from self._stores.get(pair))

        return gen(body).on_error(lambda _: self._stores.invalidate(pair))


def make_storage(
    *,
    entry_table_prefix: str = "effect_events",
    remote_id_table: str = "effect_remote_id",
    compaction: CompactionOptions | None = None,
    migrate_legacy_stores: LegacyMigration = "never",
) -> Effect[StorageService, SqlError, SqlClient | Digest | Scope]:
    """Storage in the ``SqlClient``'s database, creating its tables, with
    compaction and its sweep (Effect's ``makeStorage``).
    ``migrate_legacy_stores``: see ``LegacyMigration``."""

    def build():
        digest = yield from Digest()
        sql = (yield from SqlClient()).without_transforms()
        config = yield from make_compaction_config(compaction)
        db = Db(sql, entry_table_prefix, config)
        remote_id = yield from upgrade.prepare(db, remote_id_table)
        stores = yield from RcMap.make(
            _make_lookup(db, digest, migrate_legacy_stores), idle_time_to_live="5 minutes"
        )
        sweeper = Sweeper(db)
        # A fixed schedule starts an overdue sweep straight away, so slow
        # queries don't push sweeps back.
        yield from fork_scoped(
            sweeper.sweep.repeat(fixed(config.sweep_interval)).delay(config.sweep_interval)
        )
        return _SqlStorage(db, remote_id, _Stores(stores, db, digest))

    return gen(build).with_tracer_enabled(False)


class _SqlStorage(StorageService):
    # Auto-increment sequences start at 1.
    first_sequence = 1

    def __init__(
        self,
        db: Db,
        remote_id: RemoteId,
        stores: _Stores,
    ) -> None:
        self._db = db
        self._remote_id = remote_id
        self._stores = stores
        self.compaction = SqlCompaction(db, self._get_store)

    def _get_store(self, public_key: str, store_id: StoreId) -> Effect[StoreResources, Any, Scope]:
        return self._stores.open(public_key, store_id).or_die()

    @property
    def get_id(self) -> Effect[RemoteId]:
        return succeed(self._remote_id)

    def get_or_create_session_auth_binding(
        self, public_key: str, signing_public_key: bytes, /
    ) -> Effect[bytes]:
        sql = self._db.sql

        def body():
            rows = yield from sql(
                "SELECT signing_public_key FROM {} WHERE {}",
                self._db.bindings,
                key_equals(sql, "public_key", public_key),
            )
            if rows:
                return column_bytes(rows[0]["signing_public_key"])
            yield from sql(
                "INSERT INTO {} (public_key, signing_public_key) VALUES ({}, {})",
                self._db.bindings,
                public_key,
                signing_public_key,
            )
            return signing_public_key

        return sql.with_transaction(gen(body)).with_tracer_enabled(False).or_die()

    def write(
        self, public_key: str, store_id: StoreId, batches: Sequence[EncryptedBatch], /
    ) -> Effect[list[EncryptedRemoteBatch]]:
        if not batches:
            return succeed([])
        db = self._db
        sql = db.sql

        pair = (public_key, store_id)

        def write_batches(
            store: StoreResources, now: int
        ) -> Steps[list[EncryptedRemoteBatch] | None]:
            """The stored batches, or ``None`` when the operator moved the
            store's tables since it opened (``migrate.py`` takes this lock)."""
            tables = store.tables
            stored: list[EncryptedRemoteBatch] = []
            # The store row lock makes sequence order commit order. The row's
            # ``next_sequence`` survives pruning, and ``MAX(last_sequence)``
            # covers instances that predate the row. Read before inserting
            # ids, which record the sequence they are stored at.
            row = yield from db.lock_store(store.scope)
            if not (yield from self._stores.current(pair, store.scope)):
                return None
            next_sequence = max(
                row.next_sequence, (yield from db.max_last_sequence(tables.table)) + 1
            )
            # A batch is new when one of its ids is: stored ids keep their
            # first sequence. The store row lock keeps other writers out, so
            # the ids read here stay the stored ones until the commit.
            unique = list(
                dict.fromkeys(entry_id for batch in batches for entry_id in batch.entry_ids)
            )
            known: set[bytes] = set()
            for chunk in itertools.batched(unique, CHUNK, strict=False):
                rows = yield from sql(
                    "SELECT entry_id FROM {} WHERE {}",
                    tables.ids_table,
                    sql.in_("entry_id", list(chunk)),
                )
                known.update(column_bytes(row["entry_id"]) for row in rows)
            new_ids: list[dict[str, object]] = []
            new_rows: list[BatchRow] = []
            for batch in batches:
                ids: dict[bytes, dict[str, object]] = {}
                for i, entry_id in enumerate(batch.entry_ids):
                    if entry_id not in known:
                        ids.setdefault(
                            entry_id, {"entry_id": entry_id, "sequence": next_sequence + i}
                        )
                if not ids:
                    continue
                known.update(ids)
                new_ids.extend(ids.values())
                new_rows.append(
                    {
                        "sequence": next_sequence,
                        "last_sequence": next_sequence + len(batch.entry_ids) - 1,
                        "iv": batch.iv,
                        "entry_ids": b"".join(batch.entry_ids),
                        "encrypted_batch": batch.encrypted_batch,
                    }
                )
                stored.append(
                    EncryptedRemoteBatch(
                        sequence=next_sequence,
                        entry_ids=batch.entry_ids,
                        iv=batch.iv,
                        encrypted_batch=batch.encrypted_batch,
                    )
                )
                next_sequence += len(batch.entry_ids)
            for chunk in itertools.batched(new_ids, CHUNK, strict=False):
                yield from db.insert_new(tables.ids_table, chunk, ["entry_id"])
            for chunk in batch_chunks(new_rows):
                yield from sql("INSERT INTO {} {}", tables.table, sql.insert(chunk))
            if stored:
                yield from sql(
                    "UPDATE {} SET next_sequence = {} WHERE scope = {}",
                    db.stores,
                    next_sequence,
                    store.scope,
                )
                yield from db.upsert_bucket(store.scope, hour_of(now), next_sequence - 1)
                # Published after the outermost commit, as ``rollback`` publishes.
                yield from sql.after_commit(store.pubsub.publish_all(stored).as_(None))
            return stored

        def attempt():
            store = yield from self._stores.open(public_key, store_id)
            now = yield from Clock().map(now_millis_unsafe)
            return (
                yield from store.semaphore.with_permits(
                    sql.with_transaction(gen(lambda: write_batches(store, now)))
                )
            )

        def body():
            # Opening again resolves the store's tables afresh.
            while (stored := (yield from scoped(gen(attempt)))) is None:
                pass
            return stored

        return gen(body).with_tracer_enabled(False).or_die()

    def entry_sequences(
        self, public_key: str, store_id: StoreId, entry_ids: Sequence[EntryId], /
    ) -> Effect[list[WriteAck]]:
        sql = self._db.sql

        def body():
            store = yield from self._stores.open(public_key, store_id)
            acks: list[WriteAck] = []
            for chunk in itertools.batched(entry_ids, CHUNK, strict=False):
                rows = yield from sql(
                    "SELECT entry_id, sequence FROM {} WHERE {}",
                    store.tables.ids_table,
                    sql.in_("entry_id", list(chunk)),
                )
                acks.extend(
                    WriteAck(
                        entry_id=EntryId(column_bytes(row["entry_id"])),
                        sequence=column_int(row["sequence"]),
                    )
                    for row in rows
                )
            return acks

        return scoped(gen(body)).with_tracer_enabled(False).or_die()

    def changes(
        self, public_key: str, store_id: StoreId, start_sequence: int, /
    ) -> Stream[EncryptedRemoteBatch]:
        """Reads the store row, the active set and the tail as separate
        statements: a transaction would take the SQLite write lock on every
        stream open, and set rows never change before they are pruned."""
        db = self._db
        sql = db.sql

        def body():
            store = yield from self._stores.open(public_key, store_id)
            tables = store.tables
            subscription = yield from store.pubsub.subscribe()
            live = from_subscription(subscription)
            row = yield from db.select_store(store.scope)
            # Below the base an active snapshot replaces the originals.
            if row.active_batch_set is not None and start_sequence <= row.base:
                snapshot = yield from sql(
                    "SELECT sequence, iv, entry_ids, encrypted_batch FROM {} "
                    "WHERE batch_set = {} AND last_sequence >= {} ORDER BY batch_position ASC",
                    tables.snapshot_table,
                    row.active_batch_set,
                    start_sequence,
                )
                # The final batch ends at the base, so only an empty set reads
                # nothing.
                if not snapshot:
                    return stream_die(
                        RuntimeError(
                            f"The active compaction snapshot of store {store_id} has no batches"
                        )
                    )
                tail = yield from sql(
                    "SELECT sequence, iv, entry_ids, encrypted_batch FROM {} "
                    "WHERE sequence > {} ORDER BY sequence ASC",
                    tables.table,
                    row.base,
                )
                return from_iterable([to_batch(r) for r in [*snapshot, *tail]]).concat(live)
            initial = yield from sql(
                "SELECT sequence, iv, entry_ids, encrypted_batch FROM {} "
                "WHERE last_sequence >= {} ORDER BY sequence ASC",
                tables.table,
                start_sequence,
            )
            return from_iterable([to_batch(r) for r in initial]).concat(live)

        return stream_unwrap(gen(body).with_tracer_enabled(False).or_die())

    def latest_sequence(self, public_key: str, store_id: StoreId, /) -> Effect[int | None]:
        """The store's head, which survives pruning."""
        db = self._db

        def body():
            store = yield from self._stores.open(public_key, store_id)
            row = yield from db.select_store(store.scope)
            last_sequence = yield from db.max_last_sequence(store.tables.table)
            head = max(row.next_sequence - 1, last_sequence)
            return head if head > 0 else None

        return scoped(gen(body)).with_tracer_enabled(False).or_die()
