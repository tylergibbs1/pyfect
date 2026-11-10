"""The compaction primitives of the SQL encrypted storage (Effect's
``StorageCompaction`` inside ``SqlEventLogServerEncrypted.makeStorage``).

Every primitive reads the time before its transaction starts, runs under
the store row lock where it changes state, and turns SQL failures into
defects. Input and Fetch read without a transaction, then check that the
stage's pin was not pruned while they read.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Sequence
from typing import Literal, Never

from pyfect._core import Effect
from pyfect.clock import Clock, now_millis_unsafe
from pyfect.effect import die, fail, gen, succeed
from pyfect.errors import IllegalArgumentError
from pyfect.eventlog._server_encrypted.audit import (
    MAX_SEGMENTS,
    POSITIONS_PER_SEGMENT,
    hour_of,
    lag_hour,
    log_commit,
    log_no_op,
    log_rollback,
)
from pyfect.eventlog._server_encrypted.models import (
    BeginBusy,
    BeginStarted,
    CompactionActivation,
    CompactionBatchHeader,
    CompactionBeginResult,
    CompactionInvalidRequest,
    CompactionNotFound,
    CompactionRollbackError,
    CompactionStoreStatus,
    NoOpState,
    RollbackRefusal,
    StagedHeader,
    StorageCompaction,
)
from pyfect.eventlog._sql_server_encrypted.db import (
    CHUNK,
    Db,
    Steps,
    StoreResources,
    die_on_sql_error,
    new_id,
)
from pyfect.eventlog._sql_server_encrypted.rows import (
    ActivationRow,
    StageRow,
    to_batch,
    to_entry_ids,
)
from pyfect.eventlog.event_journal import StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, EncryptedRemoteBatch
from pyfect.persistence._columns import column_bytes, column_int
from pyfect.scope import Scope, scoped
from pyfect.sql.connection import Row
from pyfect.sql.error import SqlError
from pyfect.stream import Stream, from_effect_drain, from_iterable
from pyfect.stream import empty as stream_empty
from pyfect.stream import unwrap as stream_unwrap

type GetStore = Callable[[str, StoreId], Effect[StoreResources, Never, Scope]]

_now: Effect[int] = Clock().map(now_millis_unsafe)


def _not_found(stage_id: str) -> Effect[Never, CompactionNotFound]:
    return fail(CompactionNotFound(stage_id))


class SqlCompaction(StorageCompaction):
    def __init__(self, db: Db, get_store: GetStore) -> None:
        self._db = db
        self._get_store = get_store
        self.config = db.config

    def _with_store[A, E](
        self,
        public_key: str,
        store_id: StoreId,
        f: Callable[[StoreResources, int], Effect[A, E | SqlError]],
    ) -> Effect[A, E]:
        """Runs ``f`` with the store's resources and the time, read before
        any transaction starts. SQL failures are defects."""
        return scoped(
            self._get_store(public_key, store_id)
            .zip(_now)
            .flat_map(lambda pair: die_on_sql_error(f(pair[0], pair[1])))
        ).with_tracer_enabled(False)

    def _with_store_stream[A, E](
        self,
        public_key: str,
        store_id: StoreId,
        f: Callable[[StoreResources, int], Effect[Stream[A, E], E | SqlError]],
    ) -> Stream[A, E]:
        return stream_unwrap(self._with_store(public_key, store_id, f))

    # Reads.

    def _find_input_stage(
        self, scope: str, stage_id: str, now: int
    ) -> Effect[tuple[StageRow, ActivationRow] | None, SqlError]:
        """An open stage whose pin isn't being pruned yet, for Input and Fetch."""
        db = self._db

        def body():
            stage = yield from db.select_stage(scope, stage_id, lock=False)
            if stage is None or not stage.is_open_at(now):
                return None
            pinned = yield from db.select_activation(stage.pinned)
            if pinned is None or pinned.prune_started_at is not None:
                return None
            return stage, pinned

        return gen(body)

    def _recheck_pin(
        self, stage_id: str, pinned: str
    ) -> Effect[None, CompactionNotFound | SqlError]:
        """Fails a read that may have been truncated by a prune of its pin."""
        return self._db.select_activation(pinned).flat_map(
            lambda activation: (
                _not_found(stage_id)
                if activation is None or activation.prune_started_at is not None
                else succeed(None)
            )
        )

    def status(self, public_key: str, store_id: StoreId, /) -> Effect[CompactionStoreStatus]:
        db = self._db

        def run(store: StoreResources, now: int) -> Steps[CompactionStoreStatus]:
            row = yield from db.select_store(store.scope)
            last_sequence = yield from db.max_last_sequence(store.tables.table)
            [lag] = yield from db.sql(
                "SELECT MAX(last_sequence) AS last_sequence FROM {} "
                "WHERE scope = {} AND bucket_hour <= {}",
                db.buckets,
                store.scope,
                lag_hour(now, int(self.config.lag_millis)),
            )
            lag_head = lag["last_sequence"]
            return CompactionStoreStatus(
                head=max(row.next_sequence - 1, last_sequence),
                base=row.base,
                active_kept_count=row.active_kept_count,
                lag_head=0 if lag_head is None else column_int(lag_head),
                no_op=None if row.no_op_at is None else NoOpState(row.no_op_at, row.no_op_count),
            )

        return self._with_store(public_key, store_id, lambda s, now: gen(lambda: run(s, now)))

    def begin(
        self, public_key: str, store_id: StoreId, /, *, through: int
    ) -> Effect[CompactionBeginResult]:
        db = self._db

        def run(store: StoreResources, now: int) -> Steps[CompactionBeginResult]:
            scope = store.scope
            row = yield from db.lock_store(scope)
            if row.open_stage is not None:
                current = yield from db.select_stage(scope, row.open_stage, lock=True)
                if current is not None and current.state == "open":
                    if current.expires_at > now:
                        return BeginBusy(current.expires_at)
                    yield from db.close_stage(scope, current.id)
            stage_id = new_id()
            yield from db.sql(
                "INSERT INTO {} {}",
                db.stages,
                db.sql.insert(
                    {
                        "id": stage_id,
                        "scope": scope,
                        "state": "open",
                        "pinned": row.active_activation,
                        "through_sequence": through,
                        "expires_at": int(now + self.config.stage_ttl_millis),
                    }
                ),
            )
            yield from db.sql(
                "UPDATE {} SET open_stage = {} WHERE scope = {}", db.stores, stage_id, scope
            )
            return BeginStarted(stage_id)

        return self._with_store(
            public_key, store_id, lambda s, now: db.sql.with_transaction(gen(lambda: run(s, now)))
        )

    def input_headers(
        self, public_key: str, store_id: StoreId, stage_id: str, /
    ) -> Stream[CompactionBatchHeader, CompactionNotFound]:
        db = self._db

        def run(
            store: StoreResources, now: int
        ) -> Steps[
            Stream[CompactionBatchHeader, CompactionNotFound], SqlError | CompactionNotFound
        ]:
            found = yield from self._find_input_stage(store.scope, stage_id, now)
            if found is None:
                return (yield from _not_found(stage_id))
            stage, pinned = found
            tables = store.tables
            # Membership comes from the batch rows, never from the id table.
            snapshot: Stream[Row, SqlError] = (
                stream_empty
                if pinned.batch_set is None
                else db.set_rows(tables.snapshot_table, pinned.batch_set)
            )
            tail = db.paged(
                pinned.base,
                lambda after: db.sql(
                    "SELECT {} sequence, entry_ids FROM {} "
                    "WHERE sequence > {} AND last_sequence <= {} ORDER BY sequence {}",
                    db.page.top,
                    tables.table,
                    after,
                    stage.through,
                    db.page.limit,
                ),
                lambda row: column_int(row["sequence"]),
            )
            headers = (
                snapshot.concat(tail)
                .map(
                    lambda row: CompactionBatchHeader(
                        column_int(row["sequence"]), to_entry_ids(column_bytes(row["entry_ids"]))
                    )
                )
                .or_die()
            )
            return headers.concat(
                from_effect_drain(die_on_sql_error(self._recheck_pin(stage_id, pinned.id)))
            )

        return self._with_store_stream(
            public_key, store_id, lambda s, now: gen(lambda: run(s, now))
        )

    def fetch(
        self, public_key: str, store_id: StoreId, stage_id: str, sequences: Sequence[int], /
    ) -> Stream[EncryptedRemoteBatch, CompactionNotFound]:
        db = self._db
        sql = db.sql

        def run(
            store: StoreResources, now: int
        ) -> Steps[Stream[EncryptedRemoteBatch, CompactionNotFound], SqlError | CompactionNotFound]:
            found = yield from self._find_input_stage(store.scope, stage_id, now)
            if found is None:
                return (yield from _not_found(stage_id))
            stage, pinned = found
            tables = store.tables
            by_sequence: dict[int, EncryptedRemoteBatch] = {}
            if pinned.batch_set is not None:
                below = [s for s in sequences if s <= pinned.base]
                for chunk in itertools.batched(below, CHUNK, strict=False):
                    rows = yield from sql(
                        "SELECT sequence, iv, entry_ids, encrypted_batch FROM {} "
                        "WHERE batch_set = {} AND {}",
                        tables.snapshot_table,
                        pinned.batch_set,
                        sql.in_("sequence", list(chunk)),
                    )
                    for row in rows:
                        batch = to_batch(row)
                        by_sequence[batch.sequence] = batch
            originals = [s for s in sequences if pinned.base < s <= stage.through]
            for chunk in itertools.batched(originals, CHUNK, strict=False):
                rows = yield from sql(
                    "SELECT sequence, iv, entry_ids, encrypted_batch FROM {} WHERE {}",
                    tables.table,
                    sql.in_("sequence", list(chunk)),
                )
                for row in rows:
                    batch = to_batch(row)
                    by_sequence[batch.sequence] = batch
            yield from self._recheck_pin(stage_id, pinned.id)
            return from_iterable([by_sequence[s] for s in sequences if s in by_sequence])

        return self._with_store_stream(
            public_key, store_id, lambda s, now: gen(lambda: run(s, now))
        )

    # Stages.

    def stage_part(
        self,
        public_key: str,
        store_id: StoreId,
        stage_id: str,
        segment: int,
        batches: Sequence[EncryptedBatch],
        /,
    ) -> Effect[Literal["Stored", "AlreadyStored"], CompactionInvalidRequest | CompactionNotFound]:
        db = self._db
        sql = db.sql
        invalid = (
            "Invalid segment index"
            if not 0 <= segment < MAX_SEGMENTS
            else "Too many batches in a segment"
            if len(batches) > POSITIONS_PER_SEGMENT
            else None
        )

        def run(
            store: StoreResources, now: int
        ) -> Steps[Literal["Stored", "AlreadyStored"], SqlError | CompactionNotFound]:
            scope = store.scope
            yield from db.lock_store(scope)
            stage = yield from db.select_stage(scope, stage_id, lock=True)
            if stage is None or not stage.is_open_at(now):
                return (yield from _not_found(stage_id))
            # The snapshot table's key makes a retried segment insert nothing.
            rows = [
                {
                    "batch_set": stage_id,
                    "batch_position": segment * POSITIONS_PER_SEGMENT + i,
                    "entry_count": len(batch.entry_ids),
                    "iv": batch.iv,
                    "entry_ids": b"".join(batch.entry_ids),
                    "encrypted_batch": batch.encrypted_batch,
                }
                for i, batch in enumerate(batches)
            ]
            inserted = 0
            for chunk in itertools.batched(rows, CHUNK, strict=False):
                inserted += yield from db.insert_new(
                    store.tables.snapshot_table, chunk, ["batch_set", "batch_position"]
                )
            if inserted == 0:
                return "AlreadyStored"
            yield from sql(
                "UPDATE {} SET expires_at = {} WHERE id = {}",
                db.stages,
                int(now + self.config.stage_ttl_millis),
                stage_id,
            )
            return "Stored"

        def guarded(
            store: StoreResources, now: int
        ) -> Effect[
            Literal["Stored", "AlreadyStored"],
            CompactionInvalidRequest | CompactionNotFound | SqlError,
        ]:
            # A Part that fails validation closes the stage.
            if invalid is not None:
                return self._abort(store, stage_id).and_then(
                    fail(CompactionInvalidRequest(stage_id, invalid))
                )
            return sql.with_transaction(gen(lambda: run(store, now)))

        return self._with_store(public_key, store_id, guarded)

    def staged_headers(
        self, public_key: str, store_id: StoreId, stage_id: str, /
    ) -> Stream[StagedHeader, CompactionNotFound]:
        db = self._db

        def run(
            store: StoreResources, now: int
        ) -> Steps[Stream[StagedHeader, CompactionNotFound], SqlError | CompactionNotFound]:
            stage = yield from db.select_stage(store.scope, stage_id, lock=False)
            if stage is None or not stage.is_open_at(now):
                return (yield from _not_found(stage_id))
            return (
                db.set_rows(store.tables.snapshot_table, stage_id)
                .map(
                    lambda row: StagedHeader(
                        column_int(row["batch_position"]),
                        to_entry_ids(column_bytes(row["entry_ids"])),
                    )
                )
                .or_die()
            )

        return self._with_store_stream(
            public_key, store_id, lambda s, now: gen(lambda: run(s, now))
        )

    def commit(
        self, public_key: str, store_id: StoreId, stage_id: str, virtual_sequences: Sequence[int], /
    ) -> Effect[Literal["Committed", "Superseded"], CompactionNotFound]:
        db = self._db
        sql = db.sql

        def run(
            store: StoreResources, now: int
        ) -> Steps[
            tuple[Literal["Committed", "Superseded"], str | None, int, int],
            SqlError | CompactionNotFound,
        ]:
            scope = store.scope
            snapshot_table = store.tables.snapshot_table
            row = yield from db.lock_store(scope)
            stage = yield from db.select_stage(scope, stage_id, lock=True)
            if stage is None or not stage.is_open_at(now):
                return (yield from _not_found(stage_id))
            staged = yield from sql(
                "SELECT batch_position, entry_count FROM {} WHERE batch_set = {} "
                "ORDER BY batch_position",
                snapshot_table,
                stage_id,
            )
            counts = [column_int(r["entry_count"]) for r in staged]
            kept_count = sum(counts)
            if stage.pinned != row.active_activation:
                yield from db.close_stage(scope, stage_id)
                return ("Superseded", None, stage.through, kept_count)
            if len(staged) != len(virtual_sequences):
                return (
                    yield from die(
                        IllegalArgumentError("Expected one virtual sequence per staged batch")
                    )
                )
            for r, count, sequence in zip(staged, counts, virtual_sequences, strict=True):
                yield from sql(
                    "UPDATE {} SET sequence = {}, last_sequence = {} "
                    "WHERE batch_set = {} AND batch_position = {}",
                    snapshot_table,
                    sequence,
                    sequence + count - 1,
                    stage_id,
                    column_int(r["batch_position"]),
                )
            activation_id = new_id()
            yield from db.insert_activation(
                scope,
                id=activation_id,
                batch_set=stage_id,
                base=stage.through,
                kept_count=kept_count,
                previous=row.active_activation,
            )
            yield from db.supersede(row.active_activation, now)
            yield from sql(
                "UPDATE {} SET active_activation = {}, active_batch_set = {}, "
                "base_sequence = {}, active_kept_count = {}, no_op_at = NULL, no_op_count = 0 "
                "WHERE scope = {}",
                db.stores,
                activation_id,
                stage_id,
                stage.through,
                kept_count,
                scope,
            )
            yield from db.schedule_sweep(scope, now + self.config.grace_millis)
            # The staged rows are now the active batch set.
            yield from sql("DELETE FROM {} WHERE id = {}", db.stages, stage_id)
            yield from db.release_claim(scope, stage_id)
            return ("Committed", activation_id, stage.through, kept_count)

        def logged(
            outcome: tuple[Literal["Committed", "Superseded"], str | None, int, int],
        ) -> Effect[Literal["Committed", "Superseded"]]:
            result, activation_id, through, kept_count = outcome
            return log_commit(
                public_key=public_key,
                store_id=store_id,
                result=result,
                through=through,
                kept_count=kept_count,
                activation_id=activation_id,
            ).as_(result)

        return self._with_store(
            public_key, store_id, lambda s, now: sql.with_transaction(gen(lambda: run(s, now)))
        ).flat_map(logged)

    def record_no_op(
        self, public_key: str, store_id: StoreId, stage_id: str, /
    ) -> Effect[None, CompactionNotFound]:
        db = self._db

        def run(store: StoreResources, now: int) -> Steps[int, SqlError | CompactionNotFound]:
            scope = store.scope
            row = yield from db.lock_store(scope)
            stage = yield from db.select_stage(scope, stage_id, lock=True)
            if stage is None or not stage.is_open_at(now):
                return (yield from _not_found(stage_id))
            # A rollback since begin cleared the no-op state, so a stale run
            # leaves it.
            if stage.pinned == row.active_activation:
                yield from db.sql(
                    "UPDATE {} SET no_op_at = {}, no_op_count = {} WHERE scope = {}",
                    db.stores,
                    stage.through,
                    row.no_op_count + 1,
                    scope,
                )
            yield from db.close_stage(scope, stage_id)
            return stage.through

        return self._with_store(
            public_key, store_id, lambda s, now: db.sql.with_transaction(gen(lambda: run(s, now)))
        ).flat_map(
            lambda through: log_no_op(
                public_key=public_key, store_id=store_id, stage_id=stage_id, through=through
            )
        )

    def _abort(self, store: StoreResources, stage_id: str) -> Effect[None, SqlError]:
        db = self._db

        def run() -> Steps[None]:
            yield from db.lock_store(store.scope)
            stage = yield from db.select_stage(store.scope, stage_id, lock=True)
            if stage is not None and stage.state == "open":
                yield from db.close_stage(store.scope, stage_id)

        return db.sql.with_transaction(gen(run))

    def abort(self, public_key: str, store_id: StoreId, stage_id: str, /) -> Effect[None]:
        return self._with_store(public_key, store_id, lambda s, _: self._abort(s, stage_id))

    # Generations.

    def _rollback_transaction(
        self, store: StoreResources, now: int, expected_activation_id: str
    ) -> Effect[tuple[str, ActivationRow, ActivationRow], CompactionRollbackError | SqlError]:
        db = self._db
        sql = db.sql
        scope = store.scope
        tables = store.tables

        def refuse(reason: RollbackRefusal) -> Effect[Never, CompactionRollbackError]:
            return fail(CompactionRollbackError(reason))

        def run() -> Steps[
            tuple[str, ActivationRow, ActivationRow], SqlError | CompactionRollbackError
        ]:
            row = yield from db.lock_store(scope)
            if row.active_activation != expected_activation_id:
                return (yield from refuse("NotActive"))
            withdrawn = yield from db.select_activation(row.active_activation)
            assert withdrawn is not None
            target = (
                None
                if withdrawn.previous is None
                else (yield from db.select_activation(withdrawn.previous))
            )
            if target is None:
                return (yield from refuse("NoPrevious"))
            if target.prune_started_at is not None:
                return (yield from refuse("PruneStarted"))
            activation_id = new_id()
            yield from db.insert_activation(
                scope,
                id=activation_id,
                batch_set=target.batch_set,
                base=target.base,
                kept_count=target.kept_count,
                previous=target.previous,
            )
            yield from db.supersede(withdrawn.id, now)
            yield from sql(
                "UPDATE {} SET active_activation = {}, active_batch_set = {}, "
                "base_sequence = {}, active_kept_count = {}, no_op_at = NULL, no_op_count = 0 "
                "WHERE scope = {}",
                db.stores,
                activation_id,
                target.batch_set,
                target.base,
                target.kept_count or 0,
                scope,
            )
            yield from db.schedule_sweep(scope, now + self.config.grace_millis)

            # Re-appends the input of the stage that built the withdrawn
            # generation, the target's batch set and then the originals
            # between the two bases, at sequences taken as ``write`` takes them.
            next_sequence = max(
                row.next_sequence, (yield from db.max_last_sequence(tables.table)) + 1
            )
            reappended: list[EncryptedRemoteBatch] = []

            def reappend(rows: Sequence[Row]) -> Effect[None, SqlError]:
                nonlocal next_sequence
                inserted: list[dict[str, object]] = []
                for r in rows:
                    entry_ids = column_bytes(r["entry_ids"])
                    batch = EncryptedRemoteBatch(
                        sequence=next_sequence,
                        entry_ids=to_entry_ids(entry_ids),
                        iv=column_bytes(r["iv"]),
                        encrypted_batch=column_bytes(r["encrypted_batch"]),
                    )
                    next_sequence += len(batch.entry_ids)
                    reappended.append(batch)
                    inserted.append(
                        {
                            "sequence": batch.sequence,
                            "last_sequence": next_sequence - 1,
                            "iv": batch.iv,
                            "entry_ids": entry_ids,
                            "encrypted_batch": batch.encrypted_batch,
                        }
                    )

                def insert() -> Steps[None]:
                    for chunk in itertools.batched(inserted, CHUNK, strict=False):
                        yield from sql("INSERT INTO {} {}", tables.table, sql.insert(chunk))

                return gen(insert)

            if target.batch_set is not None:
                batch_set = target.batch_set
                yield from db.paged(
                    -1,
                    lambda after: sql(
                        "SELECT {} batch_position, iv, entry_ids, encrypted_batch FROM {} "
                        "WHERE batch_set = {} AND batch_position > {} ORDER BY batch_position {}",
                        db.page.top,
                        tables.snapshot_table,
                        batch_set,
                        after,
                        db.page.limit,
                    ),
                    lambda r: column_int(r["batch_position"]),
                ).run_for_each_array(reappend)
            # The copies land above ``withdrawn.base``, so the pages never
            # reach them.
            yield from db.paged(
                target.base,
                lambda after: sql(
                    "SELECT {} sequence, iv, entry_ids, encrypted_batch FROM {} "
                    "WHERE sequence > {} AND last_sequence <= {} ORDER BY sequence {}",
                    db.page.top,
                    tables.table,
                    after,
                    withdrawn.base,
                    db.page.limit,
                ),
                lambda r: column_int(r["sequence"]),
            ).run_for_each_array(reappend)
            if reappended:
                yield from sql(
                    "UPDATE {} SET next_sequence = {} WHERE scope = {}",
                    db.stores,
                    next_sequence,
                    scope,
                )
                yield from db.upsert_bucket(scope, hour_of(now), next_sequence - 1)
                yield from sql.after_commit(store.pubsub.publish_all(reappended).as_(None))
            return activation_id, target, withdrawn

        return sql.with_transaction(gen(run))

    def rollback(
        self, public_key: str, store_id: StoreId, expected_activation_id: str, /
    ) -> Effect[str, CompactionRollbackError]:
        def run(store: StoreResources, now: int):
            # The re-appended batches are published after the outermost
            # commit. When the storage owns the transaction, that happens
            # before the semaphore is released, so live readers get them in
            # sequence order.
            return store.semaphore.with_permits(
                self._rollback_transaction(store, now, expected_activation_id)
            )

        def logged(outcome: tuple[str, ActivationRow, ActivationRow]) -> Effect[str]:
            activation_id, target, withdrawn = outcome
            return log_rollback(
                public_key=public_key,
                store_id=store_id,
                activation_id=activation_id,
                base=target.base,
                kept_count=target.kept_count,
                withdrawn_id=withdrawn.id,
                withdrawn_base=withdrawn.base,
                withdrawn_kept_count=withdrawn.kept_count,
            ).as_(activation_id)

        return self._with_store(public_key, store_id, run).flat_map(logged)

    def history(
        self, public_key: str, store_id: StoreId, /
    ) -> Effect[tuple[CompactionActivation, ...]]:
        db = self._db

        def run(store: StoreResources, _now: int) -> Steps[tuple[CompactionActivation, ...]]:
            row = yield from db.select_store(store.scope)
            activations = yield from db.select_activations(store.scope)
            return tuple(
                CompactionActivation(
                    activation_id=a.id,
                    base=a.base,
                    kept_count=a.kept_count,
                    active=a.id == row.active_activation,
                    superseded_at=None if a.id == row.active_activation else a.superseded_at,
                    restorable=a.prune_started_at is None,
                )
                for a in activations
            )

        return self._with_store(public_key, store_id, lambda s, now: gen(lambda: run(s, now)))
