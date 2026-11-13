"""The SQL encrypted storage (Effect's ``SqlEventLogServerEncrypted.makeStorage``):
opening stores, writes, acks and changes. Compaction is in
``compaction.py`` and the sweep in ``sweeper.py``.
"""

from __future__ import annotations

import itertools
from collections.abc import Sequence
from typing import Any

from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.clock import Clock, now_millis_unsafe
from pyfect.crypto.digest import Digest, DigestService, sha256
from pyfect.effect import gen, succeed
from pyfect.eventlog._server_encrypted.audit import hour_of
from pyfect.eventlog._server_encrypted.models import CompactionOptions, make_compaction_config
from pyfect.eventlog._server_encrypted.storage import StorageService
from pyfect.eventlog._sql_server_encrypted.compaction import SqlCompaction
from pyfect.eventlog._sql_server_encrypted.db import CHUNK, Db, Steps, StoreResources, new_id
from pyfect.eventlog._sql_server_encrypted.rows import to_batch
from pyfect.eventlog._sql_server_encrypted.sweeper import Sweeper
from pyfect.eventlog._sql_server_encrypted.tables import (
    create_global_tables,
    create_scope_tables,
)
from pyfect.eventlog.event_journal import EntryId, RemoteId, StoreId, make_remote_id_unsafe
from pyfect.eventlog.event_log_encryption import EncryptedBatch, EncryptedRemoteBatch
from pyfect.eventlog.event_log_message import WriteAck
from pyfect.persistence._columns import column_bytes, column_int
from pyfect.persistence._sql_keys import key_equals
from pyfect.pubsub import PubSub
from pyfect.rc_map import RcMap
from pyfect.schedule import fixed
from pyfect.scope import Scope, acquire_release, fork_scoped, scoped
from pyfect.semaphore import Semaphore
from pyfect.sql.client import SqlClient
from pyfect.sql.error import SqlError
from pyfect.sql.statement import Identifier
from pyfect.stream import Stream, from_iterable, from_subscription
from pyfect.stream import die as stream_die
from pyfect.stream import unwrap as stream_unwrap


def _scope_key(public_key: str, store_id: str) -> str:
    return f"{public_key}/{store_id}"


def _ensure_store(db: Db, scope: str, table: Identifier) -> Effect[None, SqlError]:
    """Creates the store row on first open. The first instance to insert it
    also records the originals activation and seeds a bucket at the
    current last sequence, so data written before the upgrade becomes
    compactable."""
    sql = db.sql

    def seed(now: int) -> Steps[None]:
        last_sequence = yield from db.max_last_sequence(table)
        originals = new_id()
        inserted = yield from db.insert_new(
            db.stores,
            [
                {
                    "scope": scope,
                    "next_sequence": last_sequence + 1,
                    "active_activation": originals,
                    "active_batch_set": None,
                    "base_sequence": 0,
                    "active_kept_count": 0,
                    "no_op_at": None,
                    "no_op_count": 0,
                    "open_stage": None,
                    "next_sweep_at": None,
                    "sweep_lease_until": None,
                    "sweep_lease_owner": None,
                    "pruned_through": 0,
                }
            ],
            ["scope"],
        )
        if inserted == 0:
            return
        yield from sql(
            "INSERT INTO {} {}",
            db.activations,
            sql.insert(
                {
                    "id": originals,
                    "scope": scope,
                    "ordinal": 0,
                    "batch_set": None,
                    "base_sequence": 0,
                    "kept_count": None,
                    "previous": None,
                    "superseded_at": None,
                    "prunable_at": None,
                    "prune_started_at": None,
                }
            ),
        )
        if last_sequence > 0:
            yield from db.upsert_bucket(scope, hour_of(now), last_sequence)

    def body():
        existing = yield from sql("SELECT scope FROM {} WHERE scope = {}", db.stores, scope)
        if existing:
            return
        now = yield from Clock().map(now_millis_unsafe)
        yield from sql.with_transaction(gen(lambda: seed(now)))

    return gen(body)


def _make_lookup(db: Db, digest: DigestService):
    # Stores whose tables and row this instance has ensured, so a store
    # reopened after idling skips the DDL.
    ensured: set[str] = set()

    def lookup(scope_key: str) -> Effect[StoreResources, SqlError, Scope]:
        def body():
            scope = (yield from digest.digest_hex(sha256, text_encode(scope_key)))[:16]
            tables = db.scope_tables(scope)
            if scope not in ensured:
                yield from create_scope_tables(db.sql, f"{db.prefix}_{scope}")
                yield from _ensure_store(db, scope, tables.table)
                ensured.add(scope)
            pubsub = yield from acquire_release(
                PubSub[EncryptedRemoteBatch].unbounded(), lambda p, _: p.shutdown()
            )
            return StoreResources(tables, pubsub, Semaphore(1))

        return gen(body).with_tracer_enabled(False)

    return lookup


def make_storage(
    *,
    entry_table_prefix: str = "effect_events",
    remote_id_table: str = "effect_remote_id",
    compaction: CompactionOptions | None = None,
) -> Effect[StorageService, SqlError, SqlClient | Digest | Scope]:
    """Storage in the ``SqlClient``'s database, creating its tables, with
    compaction and its sweep (Effect's ``makeStorage``)."""

    def build():
        digest = yield from Digest()
        sql = (yield from SqlClient()).without_transforms()
        config = yield from make_compaction_config(compaction)
        db = Db(sql, entry_table_prefix, config)
        yield from create_global_tables(sql, entry_table_prefix, remote_id_table)
        remote_ids = sql.identifier(remote_id_table)
        rows = yield from sql("SELECT remote_id FROM {}", remote_ids)
        if rows:
            remote_id = RemoteId(column_bytes(rows[0]["remote_id"]))
        else:
            remote_id = make_remote_id_unsafe()
            yield from sql("INSERT INTO {} (remote_id) VALUES ({})", remote_ids, remote_id)
        resources = yield from RcMap.make(_make_lookup(db, digest), idle_time_to_live="5 minutes")
        sweeper = Sweeper(db)
        # A fixed schedule starts an overdue sweep straight away, so slow
        # queries don't push sweeps back.
        yield from fork_scoped(
            sweeper.sweep.repeat(fixed(config.sweep_interval)).delay(config.sweep_interval)
        )
        return _SqlStorage(db, remote_id, resources)

    return gen(build).with_tracer_enabled(False)


class _SqlStorage(StorageService):
    # Auto-increment sequences start at 1.
    first_sequence = 1

    def __init__(
        self, db: Db, remote_id: RemoteId, resources: RcMap[str, StoreResources, SqlError]
    ) -> None:
        self._db = db
        self._remote_id = remote_id
        self._resources = resources
        self._bindings = db.sql.identifier(f"{db.prefix}_session_auth_bindings")
        self.compaction = SqlCompaction(db, self._get_store)

    def _get_store(self, public_key: str, store_id: StoreId) -> Effect[StoreResources, Any, Scope]:
        return self._resources.get(_scope_key(public_key, store_id)).or_die()

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
                self._bindings,
                key_equals(sql, "public_key", public_key),
            )
            if rows:
                return column_bytes(rows[0]["signing_public_key"])
            yield from sql(
                "INSERT INTO {} (public_key, signing_public_key) VALUES ({}, {})",
                self._bindings,
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

        def write_batches(store: StoreResources, now: int) -> Steps[list[EncryptedRemoteBatch]]:
            tables = store.tables
            stored: list[EncryptedRemoteBatch] = []
            # The store row lock makes sequence order commit order. The row's
            # ``next_sequence`` survives pruning, and ``MAX(last_sequence)``
            # covers instances that predate the row. Read before inserting
            # ids, which record the sequence they are stored at.
            row = yield from db.lock_store(store.scope)
            next_sequence = max(
                row.next_sequence, (yield from db.max_last_sequence(tables.table)) + 1
            )
            for batch in batches:
                # Inserting the ids decides whether the batch is new. SQL
                # Server's MERGE also requires unique source ids.
                ids: dict[bytes, dict[str, object]] = {}
                for i, entry_id in enumerate(batch.entry_ids):
                    ids.setdefault(entry_id, {"entry_id": entry_id, "sequence": next_sequence + i})
                inserted = 0
                for chunk in itertools.batched(ids.values(), CHUNK, strict=False):
                    # Stored ids keep their first sequence.
                    inserted += yield from db.insert_new(tables.ids_table, chunk, ["entry_id"])
                if inserted == 0:
                    continue
                yield from sql(
                    "INSERT INTO {} {}",
                    tables.table,
                    sql.insert(
                        {
                            "sequence": next_sequence,
                            "last_sequence": next_sequence + len(batch.entry_ids) - 1,
                            "iv": batch.iv,
                            "entry_ids": b"".join(batch.entry_ids),
                            "encrypted_batch": batch.encrypted_batch,
                        }
                    ),
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

        def body():
            store = yield from self._resources.get(_scope_key(public_key, store_id))
            now = yield from Clock().map(now_millis_unsafe)
            return (
                yield from store.semaphore.with_permits(
                    sql.with_transaction(gen(lambda: write_batches(store, now)))
                )
            )

        return scoped(gen(body)).with_tracer_enabled(False).or_die()

    def entry_sequences(
        self, public_key: str, store_id: StoreId, entry_ids: Sequence[EntryId], /
    ) -> Effect[list[WriteAck]]:
        sql = self._db.sql

        def body():
            store = yield from self._resources.get(_scope_key(public_key, store_id))
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
            store = yield from self._resources.get(_scope_key(public_key, store_id))
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
            store = yield from self._resources.get(_scope_key(public_key, store_id))
            row = yield from db.select_store(store.scope)
            last_sequence = yield from db.max_last_sequence(store.tables.table)
            head = max(row.next_sequence - 1, last_sequence)
            return head if head > 0 else None

        return scoped(gen(body)).with_tracer_enabled(False).or_die()
