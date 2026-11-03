"""Storage of an encrypted event log server in a SQL database (Effect's
``eventlog/SqlEventLogServerEncrypted``), on SQLite or PostgreSQL.

Each identity and store has a table of batches, named by a hash of the
pair under ``entry_table_prefix``, and a table of the entry ids it holds
with the sequence each was first stored at. A batch is stored when one of
its ids is new; sequences start at 1. ``remote_id_table`` keeps the
server's remote id, and ``<entry_table_prefix>_session_auth_bindings`` the
signing key bound to each public key.
"""

from __future__ import annotations

import itertools
from collections.abc import Generator, Sequence
from dataclasses import dataclass
from typing import Any

from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.effect import gen, succeed
from pyfect.eventlog.event_journal import EntryId, RemoteId, StoreId, make_remote_id_unsafe
from pyfect.eventlog.event_log_encryption import (
    EncryptedBatch,
    EncryptedRemoteBatch,
    EventLogEncryption,
    EventLogEncryptionService,
    layer_subtle,
)
from pyfect.eventlog.event_log_message import WriteAck
from pyfect.eventlog.event_log_server_encrypted import Storage, StorageService
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.layer import provide as layer_provide
from pyfect.persistence._columns import column_bytes, column_int
from pyfect.pubsub import PubSub
from pyfect.rc_map import RcMap
from pyfect.scope import Scope, acquire_release, scoped
from pyfect.semaphore import Semaphore
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.connection import Row
from pyfect.sql.error import SqlError
from pyfect.sql.statement import Identifier
from pyfect.stream import Stream, from_iterable, from_subscription
from pyfect.stream import unwrap as stream_unwrap

__all__ = ["layer_storage", "layer_storage_subtle", "make_storage"]

# Keeps each statement within the dialects' bind parameter limits.
_CHUNK = 200


@dataclass(frozen=True, slots=True)
class _Scope:
    pubsub: PubSub[EncryptedRemoteBatch]
    # Serializes writes within this storage instance.
    semaphore: Semaphore
    table: Identifier
    ids_table: Identifier


def _dialect(sql: SqlClientService) -> str:
    if sql.dialect not in ("sqlite", "pg"):
        raise ValueError(
            f"SqlEventLogServerEncrypted supports SQLite and PostgreSQL, not {sql.dialect}"
        )
    return sql.dialect


def _to_batch(row: Row) -> EncryptedRemoteBatch:
    data = column_bytes(row["entry_ids"])
    return EncryptedRemoteBatch(
        sequence=column_int(row["sequence"]),
        entry_ids=tuple(EntryId(data[i : i + 16]) for i in range(0, len(data), 16)),
        iv=column_bytes(row["iv"]),
        encrypted_batch=column_bytes(row["encrypted_batch"]),
    )


def _scope_key(public_key: str, store_id: str) -> str:
    return f"{public_key}/{store_id}"


def make_storage(
    *, entry_table_prefix: str = "effect_events", remote_id_table: str = "effect_remote_id"
) -> Effect[StorageService, SqlError, SqlClient | EventLogEncryption | Scope]:
    """Storage in the ``SqlClient``'s database, creating its tables
    (Effect's ``makeStorage``). Fails with ``ValueError`` as a defect on a
    dialect other than SQLite or PostgreSQL."""

    def build():
        encryption = yield from EventLogEncryption()
        sql = (yield from SqlClient()).without_transforms()
        pg = _dialect(sql) == "pg"
        binary = "BYTEA" if pg else "BLOB"
        remote_ids = sql.identifier(remote_id_table)
        bindings = sql.identifier(f"{entry_table_prefix}_session_auth_bindings")
        if pg:
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (remote_id BYTEA PRIMARY KEY)", remote_ids
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (public_key TEXT PRIMARY KEY, "
                "signing_public_key BYTEA NOT NULL)",
                bindings,
            )
        else:
            yield from sql("CREATE TABLE IF NOT EXISTS {} (remote_id BLOB PRIMARY KEY)", remote_ids)
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (public_key TEXT PRIMARY KEY, "
                "signing_public_key BLOB NOT NULL)",
                bindings,
            )
        rows = yield from sql("SELECT remote_id FROM {}", remote_ids)
        if rows:
            remote_id = RemoteId(column_bytes(rows[0]["remote_id"]))
        else:
            remote_id = make_remote_id_unsafe()
            yield from sql("INSERT INTO {} (remote_id) VALUES ({})", remote_ids, remote_id)

        def lookup(scope_key: str) -> Effect[_Scope, SqlError, Scope]:
            return _open_scope(sql, encryption, entry_table_prefix, binary, scope_key)

        resources = yield from RcMap.make(lookup, idle_time_to_live=300)
        return _SqlStorage(sql, remote_id, bindings, resources)

    return gen(build).with_tracer_enabled(False)


def _open_scope(
    sql: SqlClientService,
    encryption: EventLogEncryptionService,
    prefix: str,
    binary: str,
    scope_key: str,
) -> Effect[_Scope, SqlError, Scope]:
    def body():
        digest = yield from encryption.sha256_string(text_encode(scope_key))
        name = f"{prefix}_{digest[:16]}"
        table = sql.identifier(name)
        ids_table = sql.identifier(f"{name}_ids")
        index = sql.identifier(f"{name}_last_sequence")
        if binary == "BYTEA":
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (sequence INTEGER PRIMARY KEY, "
                "last_sequence INTEGER NOT NULL, iv BYTEA NOT NULL, entry_ids BYTEA NOT NULL, "
                "encrypted_batch BYTEA NOT NULL)",
                table,
            )
            yield from sql("CREATE INDEX IF NOT EXISTS {} ON {} (last_sequence)", index, table)
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (entry_id BYTEA PRIMARY KEY, "
                "sequence INTEGER NOT NULL)",
                ids_table,
            )
        else:
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (sequence INTEGER PRIMARY KEY, "
                "last_sequence INTEGER NOT NULL, iv BLOB NOT NULL, entry_ids BLOB NOT NULL, "
                "encrypted_batch BLOB NOT NULL)",
                table,
            )
            yield from sql("CREATE INDEX IF NOT EXISTS {} ON {} (last_sequence)", index, table)
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (entry_id BLOB PRIMARY KEY, "
                "sequence INTEGER NOT NULL)",
                ids_table,
            )
        pubsub = yield from acquire_release(
            PubSub[EncryptedRemoteBatch].unbounded(), lambda p, _: p.shutdown()
        )
        semaphore = Semaphore(1)
        return _Scope(pubsub, semaphore, table, ids_table)

    return gen(body).with_tracer_enabled(False)


class _SqlStorage(StorageService):
    # Auto-increment sequences start at 1.
    first_sequence = 1

    def __init__(
        self,
        sql: SqlClientService,
        remote_id: RemoteId,
        bindings: Identifier,
        resources: RcMap[str, _Scope, SqlError],
    ) -> None:
        self._sql = sql
        self._remote_id = remote_id
        self._bindings = bindings
        self._resources = resources

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
                self._bindings,
                public_key,
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

    def _insert_new_ids(self, ids_table: Identifier, rows: Sequence[dict[str, object]]):
        # How many of the ids were not stored yet; stored ids keep their
        # first sequence.
        sql = self._sql
        return sql(
            "INSERT INTO {} {} ON CONFLICT DO NOTHING RETURNING entry_id",
            ids_table,
            sql.insert(rows),
        ).map(len)

    def write(
        self, public_key: str, store_id: StoreId, batches: Sequence[EncryptedBatch], /
    ) -> Effect[list[EncryptedRemoteBatch]]:
        if not batches:
            return succeed([])
        sql = self._sql

        def write_batches(scope: _Scope) -> Generator[Any, Any, list[EncryptedRemoteBatch]]:
            stored: list[EncryptedRemoteBatch] = []
            # Read before inserting ids, which record the sequence they are
            # stored at.
            [last] = yield from sql(
                "SELECT MAX(last_sequence) AS last_sequence FROM {}", scope.table
            )
            next_sequence = (
                0 if last["last_sequence"] is None else column_int(last["last_sequence"])
            ) + 1
            for batch in batches:
                # Inserting the ids decides whether the batch is new.
                ids: dict[bytes, dict[str, object]] = {}
                for i, entry_id in enumerate(batch.entry_ids):
                    ids.setdefault(entry_id, {"entry_id": entry_id, "sequence": next_sequence + i})
                inserted = 0
                for chunk in itertools.batched(ids.values(), _CHUNK, strict=False):
                    inserted += yield from self._insert_new_ids(scope.ids_table, chunk)
                if inserted == 0:
                    continue
                yield from sql(
                    "INSERT INTO {} {}",
                    scope.table,
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
            return stored

        def body():
            scope = yield from self._resources.get(_scope_key(public_key, store_id))

            def locked():
                stored = yield from sql.with_transaction(gen(lambda: write_batches(scope)))
                yield from scope.pubsub.publish_all(stored)
                return stored

            return (yield from scope.semaphore.with_permits(gen(locked)))

        return scoped(gen(body)).with_tracer_enabled(False).or_die()

    def entry_sequences(
        self, public_key: str, store_id: StoreId, entry_ids: Sequence[EntryId], /
    ) -> Effect[list[WriteAck]]:
        sql = self._sql

        def body():
            scope = yield from self._resources.get(_scope_key(public_key, store_id))
            acks: list[WriteAck] = []
            for chunk in itertools.batched(entry_ids, _CHUNK, strict=False):
                rows = yield from sql(
                    "SELECT entry_id, sequence FROM {} WHERE {}",
                    scope.ids_table,
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
        sql = self._sql

        def body():
            scope = yield from self._resources.get(_scope_key(public_key, store_id))
            subscription = yield from scope.pubsub.subscribe()
            rows = yield from sql(
                "SELECT sequence, iv, entry_ids, encrypted_batch FROM {} "
                "WHERE last_sequence >= {} ORDER BY sequence ASC",
                scope.table,
                start_sequence,
            )
            initial = [_to_batch(row) for row in rows]
            return from_iterable(initial).concat(from_subscription(subscription))

        return stream_unwrap(gen(body).with_tracer_enabled(False).or_die())

    def latest_sequence(self, public_key: str, store_id: StoreId, /) -> Effect[int | None]:
        sql = self._sql

        def body():
            scope = yield from self._resources.get(_scope_key(public_key, store_id))
            [last] = yield from sql(
                "SELECT MAX(last_sequence) AS last_sequence FROM {}", scope.table
            )
            found = last["last_sequence"]
            return None if found is None else column_int(found)

        return scoped(gen(body)).with_tracer_enabled(False).or_die()


def layer_storage(
    *, entry_table_prefix: str = "effect_events", remote_id_table: str = "effect_remote_id"
) -> Layer[Storage, SqlError, SqlClient | EventLogEncryption]:
    """The ``Storage`` of ``make_storage``."""
    return layer_effect(
        Storage,
        make_storage(entry_table_prefix=entry_table_prefix, remote_id_table=remote_id_table),
    )


def layer_storage_subtle(
    *, entry_table_prefix: str = "effect_events", remote_id_table: str = "effect_remote_id"
) -> Layer[Storage, SqlError, SqlClient]:
    """``layer_storage`` with the ``EventLogEncryption`` of
    ``layer_subtle``."""
    return layer_storage(
        entry_table_prefix=entry_table_prefix, remote_id_table=remote_id_table
    ).pipe(layer_provide(layer_subtle))
