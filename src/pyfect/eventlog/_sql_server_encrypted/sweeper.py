"""The sweep of the SQL encrypted storage: closes stages past their claim,
deletes closed stages, prunes what no kept generation needs, and trims the
hour buckets. Every delete is idempotent and runs in short chunks, each
under the store row lock, so a later sweep finishes one that died.
"""

from __future__ import annotations

import itertools
from dataclasses import dataclass
from typing import Any

from pyfect._core import Effect
from pyfect.cause import Cause
from pyfect.clock import Clock, now_millis_unsafe
from pyfect.effect import gen
from pyfect.eventlog._server_encrypted.audit import lag_hour
from pyfect.eventlog._sql_server_encrypted.db import (
    CHUNK,
    PRUNE_CHUNK_SEQUENCES,
    Db,
    Steps,
    new_id,
)
from pyfect.eventlog._sql_server_encrypted.rows import ActivationRow
from pyfect.logger import log_warning
from pyfect.option import Some
from pyfect.persistence._columns import column_int, column_text
from pyfect.sql.error import SqlError
from pyfect.sql.statement import Fragment, Identifier


@dataclass(frozen=True, slots=True)
class _Lease:
    owner: str
    active_activation: str


@dataclass(frozen=True, slots=True)
class _Plan:
    lease: _Lease
    sets: list[str]
    kept_base: float
    pruned_through: int


def _log_sweep_failure(cause: Cause[Any]) -> Effect[None]:
    return log_warning("Compaction sweep failed", cause).annotate_logs(
        {"service": "SqlEventLogServerEncrypted"}
    )


class Sweeper:
    def __init__(self, db: Db) -> None:
        self._db = db

    def _prune_chunk[A](
        self, scope: str, now: int, lease: _Lease, f: Effect[A, SqlError]
    ) -> Effect[Some[A] | None, SqlError]:
        """Runs one chunk of a prune under the store row lock, if this
        sweeper still holds the lease and the active activation hasn't
        changed."""
        db = self._db

        def body():
            store = yield from db.lock_store(scope)
            if (
                store.sweep_lease_owner != lease.owner
                or store.active_activation != lease.active_activation
            ):
                return None
            value = yield from f
            yield from db.sql(
                "UPDATE {} SET sweep_lease_until = {} WHERE scope = {}",
                db.stores,
                int(now + db.config.sweep_interval_millis),
                scope,
            )
            return Some(value)

        return db.sql.with_transaction(gen(body))

    def _plan(self, scope: str, now: int, owner: str) -> Effect[_Plan | None, SqlError]:
        """Claims the store and marks what this prune removes before
        deleting anything."""
        db = self._db
        sql = db.sql

        def body():
            store = yield from db.lock_store(scope)
            if store.next_sweep_at is None or store.next_sweep_at > now:
                return None
            if store.sweep_lease_until is not None and store.sweep_lease_until > now:
                return None
            activations = yield from db.select_activations(scope)

            def is_kept(activation: ActivationRow) -> bool:
                return activation.id == store.active_activation or (
                    activation.prune_started_at is None
                    and (activation.prunable_at is None or activation.prunable_at > now)
                )

            kept = [a for a in activations if is_kept(a)]
            pruned = [a for a in activations if not is_kept(a)]
            starting = [a.id for a in pruned if a.prune_started_at is None]
            for chunk in itertools.batched(starting, CHUNK, strict=False):
                yield from sql(
                    "UPDATE {} SET prune_started_at = {} WHERE {}",
                    db.activations,
                    now,
                    sql.in_("id", list(chunk)),
                )
            kept_sets = {a.batch_set for a in kept}
            yield from sql(
                "UPDATE {} SET sweep_lease_until = {}, sweep_lease_owner = {} WHERE scope = {}",
                db.stores,
                int(now + db.config.sweep_interval_millis),
                owner,
                scope,
            )
            sets = list(
                dict.fromkeys(
                    a.batch_set
                    for a in pruned
                    if a.batch_set is not None and a.batch_set not in kept_sets
                )
            )
            return _Plan(
                lease=_Lease(owner, store.active_activation),
                sets=sets,
                kept_base=min((a.base for a in kept), default=float("inf")),
                pruned_through=store.pruned_through,
            )

        return sql.with_transaction(gen(body))

    def prune_store(self, scope: str, now: int) -> Effect[None, SqlError]:
        """Prunes the batch sets of generations past their grace, and the
        originals at or below the lowest base still kept."""
        db = self._db
        sql = db.sql
        tables = db.scope_tables(scope)
        owner = new_id()

        def body():
            plan = yield from self._plan(scope, now, owner)
            if plan is None:
                return
            for batch_set in plan.sets:
                while True:
                    deleted = yield from self._prune_chunk(
                        scope,
                        now,
                        plan.lease,
                        db.delete_chunk(
                            tables.snapshot_table,
                            "batch_position",
                            sql("batch_set = {}", batch_set),
                        ),
                    )
                    if deleted is None:
                        return
                    if not deleted.value:
                        break
            start = plan.pruned_through
            while start < plan.kept_base:
                end = int(min(start + PRUNE_CHUNK_SEQUENCES, plan.kept_base))
                held = yield from self._prune_chunk(
                    scope,
                    now,
                    plan.lease,
                    sql("DELETE FROM {} WHERE last_sequence <= {}", tables.table, end).and_then(
                        sql(
                            "UPDATE {} SET pruned_through = CASE WHEN pruned_through < {} "
                            "THEN {} ELSE pruned_through END WHERE scope = {}",
                            db.stores,
                            end,
                            end,
                            scope,
                        )
                    ),
                )
                if held is None:
                    return
                start += PRUNE_CHUNK_SEQUENCES
            yield from sql.with_transaction(gen(lambda: self._finish(scope, owner)))

        return gen(body)

    def _finish(self, scope: str, owner: str) -> Steps[None]:
        db = self._db
        store = yield from db.lock_store(scope)
        if store.sweep_lease_owner != owner:
            return
        [following] = yield from db.sql(
            "SELECT MIN(prunable_at) AS next_sweep_at FROM {} "
            "WHERE scope = {} AND id <> {} AND prune_started_at IS NULL",
            db.activations,
            scope,
            store.active_activation,
        )
        next_sweep_at = following["next_sweep_at"]
        yield from db.sql(
            "UPDATE {} SET next_sweep_at = {}, sweep_lease_until = NULL, "
            "sweep_lease_owner = NULL WHERE scope = {}",
            db.stores,
            None if next_sweep_at is None else column_int(next_sweep_at),
            scope,
        )

    def _delete_staged(
        self, scope: str, table: Identifier, key: str, where: Fragment
    ) -> Effect[None, SqlError]:
        """Deletes a closed stage's rows, one chunk per transaction, each
        under the store row lock to keep the lock order."""
        db = self._db

        def body():
            while (
                yield from db.sql.with_transaction(
                    db.lock_store(scope).and_then(db.delete_chunk(table, key, where))
                )
            ):
                pass

        return gen(body)

    def sweep_stages(self, now: int) -> Effect[None, SqlError]:
        """Closes stages past their claim, then deletes closed stages: their
        staged rows first in short chunks, and the stage row last."""
        db = self._db
        sql = db.sql

        def close(scope: str, stage_id: str) -> Steps[None]:
            yield from db.lock_store(scope)
            stage = yield from db.select_stage(scope, stage_id, lock=True)
            if stage is not None and stage.state == "open" and stage.expires_at <= now:
                yield from db.close_stage(scope, stage_id)

        def body():
            expired = yield from sql(
                "SELECT id, scope FROM {} WHERE state = {} AND expires_at <= {}",
                db.stages,
                "open",
                now,
            )
            for row in expired:
                scope, stage_id = column_text(row["scope"]), column_text(row["id"])
                yield from sql.with_transaction(gen(lambda s=scope, i=stage_id: close(s, i)))
            closed = yield from sql(
                "SELECT id, scope FROM {} WHERE state = {}", db.stages, "closed"
            )
            for row in closed:
                scope, stage_id = column_text(row["scope"]), column_text(row["id"])
                yield from self._delete_staged(
                    scope,
                    db.scope_tables(scope).snapshot_table,
                    "batch_position",
                    sql("batch_set = {}", stage_id),
                )
                yield from sql.with_transaction(
                    db.lock_store(scope).and_then(
                        sql("DELETE FROM {} WHERE id = {}", db.stages, stage_id)
                    )
                )

        return gen(body)

    def sweep_buckets(self, now: int) -> Effect[None, SqlError]:
        """Only the newest bucket past the lag matters for the lag head."""
        db = self._db

        def body():
            rows = yield from db.sql(
                "SELECT scope, MAX(bucket_hour) AS newest FROM {} WHERE bucket_hour <= {} "
                "GROUP BY scope HAVING COUNT(*) > 1",
                db.buckets,
                lag_hour(now, int(db.config.lag_millis)),
            )
            for row in rows:
                yield from db.sql(
                    "DELETE FROM {} WHERE scope = {} AND bucket_hour < {}",
                    db.buckets,
                    column_text(row["scope"]),
                    column_int(row["newest"]),
                )

        return gen(body)

    @property
    def sweep(self) -> Effect[None]:
        """One sweep; a failing part is logged and the rest still run."""
        db = self._db

        def guarded(effect: Effect[None, SqlError]) -> Effect[None]:
            return effect.catch_cause(_log_sweep_failure)

        def body():
            now = yield from Clock().map(now_millis_unsafe)
            yield from guarded(self.sweep_stages(now))
            due = yield from db.sql(
                "SELECT scope FROM {} WHERE next_sweep_at <= {}", db.stores, now
            )
            for row in due:
                yield from guarded(self.prune_store(column_text(row["scope"]), now))
            yield from guarded(self.sweep_buckets(now))

        return gen(body).catch_cause(_log_sweep_failure).with_tracer_enabled(False)
