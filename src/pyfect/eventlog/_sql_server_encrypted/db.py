"""The statements the SQL encrypted storage shares between its writes,
compaction primitives and sweep (Effect's helpers inside
``SqlEventLogServerEncrypted.makeStorage``).

Lock order is store row, then stage row, then snapshot rows. SQLite
transactions take the database write lock instead of row locks.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Never

from pyfect._catch import catch_tag
from pyfect._core import Effect
from pyfect.effect import die, gen, succeed
from pyfect.errors import NoSuchElementException
from pyfect.eventlog._server_encrypted.models import CompactionConfig
from pyfect.eventlog._sql_server_encrypted.rows import ActivationRow, StageRow, StoreRow
from pyfect.eventlog.event_log_encryption import EncryptedRemoteBatch
from pyfect.option import Some
from pyfect.persistence._columns import column_int
from pyfect.pubsub import PubSub
from pyfect.semaphore import Semaphore
from pyfect.sql.client import SqlClientService
from pyfect.sql.connection import Row
from pyfect.sql.error import SqlError
from pyfect.sql.result import affected_rows
from pyfect.sql.statement import Fragment, Identifier
from pyfect.stream import Stream, paginate

PAGE_SIZE = 500
"""Rows per statement when streaming compaction input or staged batches."""

PRUNE_CHUNK_SEQUENCES = 10_000
"""Sequences of originals deleted per prune chunk."""

PRUNE_CHUNK_ROWS = 200
"""Snapshot or staged rows deleted per prune chunk."""

CHUNK = 200
"""Keeps each statement within the dialects' bind parameter limits."""

_STORE_COLUMNS = (
    "next_sequence, active_activation, active_batch_set, base_sequence, active_kept_count, "
    "no_op_at, no_op_count, open_stage, next_sweep_at, sweep_lease_until, sweep_lease_owner, "
    "pruned_through"
)
_STAGE_COLUMNS = "id, scope, state, pinned, through_sequence, expires_at"
_ACTIVATION_COLUMNS = (
    "id, ordinal, batch_set, base_sequence, kept_count, previous, superseded_at, prunable_at, "
    "prune_started_at"
)


type Steps[T, E = SqlError] = Generator[Effect[Any, E, Never], Any, T]
"""The generator of a ``gen`` body whose steps fail with ``E``."""


def new_id() -> str:
    return str(uuid.uuid4())


@dataclass(frozen=True, slots=True)
class ScopeTables:
    """A store's tables: its batches, entry ids and snapshot batches."""

    scope: str
    table: Identifier
    ids_table: Identifier
    snapshot_table: Identifier


@dataclass(frozen=True, slots=True)
class RowCap:
    """The clauses that cap a statement at a number of rows, for
    ``SELECT {top} ... {limit}``."""

    top: Fragment
    limit: Fragment


class Db:
    """The client, the global tables and the shared statements."""

    def __init__(self, sql: SqlClientService, prefix: str, config: CompactionConfig) -> None:
        self.sql = sql
        self.prefix = prefix
        self.config = config
        self.stores = sql.identifier(f"{prefix}_compaction_stores")
        self.buckets = sql.identifier(f"{prefix}_compaction_buckets")
        self.activations = sql.identifier(f"{prefix}_compaction_activations")
        self.stages = sql.identifier(f"{prefix}_compaction_stages")
        none = sql.literal("")
        self.none = none
        self.lock_hint = sql.on_dialect_or_else(
            mssql=lambda: sql.literal("WITH (UPDLOCK, ROWLOCK, HOLDLOCK)"), or_else=lambda: none
        )
        self.for_update = sql.on_dialect_or_else(
            pg=lambda: sql.literal("FOR UPDATE"),
            mysql=lambda: sql.literal("FOR UPDATE"),
            or_else=lambda: none,
        )
        self.page = sql.on_dialect_or_else(
            mssql=lambda: RowCap(sql.literal("TOP (500)"), none),
            or_else=lambda: RowCap(none, sql.literal("LIMIT 500")),
        )
        self.chunk = sql.on_dialect_or_else(
            mssql=lambda: RowCap(sql.literal("TOP (200)"), none),
            or_else=lambda: RowCap(none, sql.literal("LIMIT 200")),
        )

    def scope_tables(self, scope: str) -> ScopeTables:
        table = f"{self.prefix}_{scope}"
        sql = self.sql
        return ScopeTables(
            scope,
            sql.identifier(table),
            sql.identifier(f"{table}_ids"),
            sql.identifier(f"{table}_snapshot"),
        )

    # Inserts and upserts.

    def insert_new(
        self, table: Identifier, rows: Sequence[Mapping[str, object]], keys: Sequence[str]
    ) -> Effect[int, SqlError]:
        """Inserts the rows whose ``keys`` are not stored yet, leaving stored
        rows as they are; how many were inserted. Every row has the same
        columns, and SQL Server's MERGE needs them unique by key."""
        sql = self.sql
        if sql.dialect == "mysql":
            return sql("INSERT IGNORE INTO {} {}", table, sql.insert(rows)).raw.map(affected_rows)
        if sql.dialect == "mssql":
            columns = list(rows[0])
            values = sql.join(", ", False)(
                [
                    sql("({})", sql.join(", ", False)([sql("{}", row[c]) for c in columns]))
                    for row in rows
                ]
            )
            column_list = sql.join(", ", False)([sql("{}", sql.identifier(c)) for c in columns])
            source_list = sql.join(", ", False)(
                [sql("source.{}", sql.identifier(c)) for c in columns]
            )
            on = sql.join(" AND ", False)(
                [sql("target.{} = source.{}", sql.identifier(k), sql.identifier(k)) for k in keys]
            )
            return sql(
                "MERGE {} WITH (HOLDLOCK) AS target USING (VALUES {}) AS source ({}) ON {} "
                "WHEN NOT MATCHED THEN INSERT ({}) VALUES ({}) OUTPUT inserted.{};",
                table,
                values,
                column_list,
                on,
                column_list,
                source_list,
                sql.identifier(keys[0]),
            ).map(len)
        return sql(
            "INSERT INTO {} {} ON CONFLICT DO NOTHING RETURNING {}",
            table,
            sql.insert(rows),
            sql.identifier(keys[0]),
        ).map(len)

    def upsert_bucket(self, scope: str, hour: int, last_sequence: int) -> Effect[Any, SqlError]:
        sql, buckets = self.sql, self.buckets
        return sql.on_dialect_or_else(
            pg=lambda: sql(
                "INSERT INTO {} (scope, bucket_hour, last_sequence) VALUES ({}, {}, {}) "
                "ON CONFLICT (scope, bucket_hour) DO UPDATE SET "
                "last_sequence = GREATEST({}.last_sequence, EXCLUDED.last_sequence)",
                buckets,
                scope,
                hour,
                last_sequence,
                buckets,
            ),
            mysql=lambda: sql(
                "INSERT INTO {} (scope, bucket_hour, last_sequence) VALUES ({}, {}, {}) "
                "ON DUPLICATE KEY UPDATE last_sequence = GREATEST(last_sequence, "
                "VALUES(last_sequence))",
                buckets,
                scope,
                hour,
                last_sequence,
            ),
            mssql=lambda: sql(
                "MERGE {} WITH (HOLDLOCK) AS target "
                "USING (VALUES ({}, {}, {})) AS source (scope, bucket_hour, last_sequence) "
                "ON target.scope = source.scope AND target.bucket_hour = source.bucket_hour "
                "WHEN MATCHED AND source.last_sequence > target.last_sequence THEN "
                "UPDATE SET last_sequence = source.last_sequence "
                "WHEN NOT MATCHED THEN INSERT (scope, bucket_hour, last_sequence) "
                "VALUES (source.scope, source.bucket_hour, source.last_sequence);",
                buckets,
                scope,
                hour,
                last_sequence,
            ),
            or_else=lambda: sql(
                "INSERT INTO {} (scope, bucket_hour, last_sequence) VALUES ({}, {}, {}) "
                "ON CONFLICT (scope, bucket_hour) DO UPDATE SET "
                "last_sequence = MAX({}.last_sequence, excluded.last_sequence)",
                buckets,
                scope,
                hour,
                last_sequence,
                buckets,
            ),
        )

    def max_last_sequence(self, table: Identifier) -> Effect[int, SqlError]:
        """The table's highest last sequence, 0 when it has none."""
        return self.sql("SELECT MAX(last_sequence) AS last_sequence FROM {}", table).map(
            lambda rows: (
                0
                if not rows or rows[0]["last_sequence"] is None
                else column_int(rows[0]["last_sequence"])
            )
        )

    # Store, stage and activation rows.

    def select_store(self, scope: str) -> Effect[StoreRow, SqlError]:
        """The store row, which every opened store has."""
        return self.sql(
            "SELECT {} FROM {} WHERE scope = {}",
            self.sql.literal(_STORE_COLUMNS),
            self.stores,
            scope,
        ).flat_map(lambda rows: self._store_row(scope, rows))

    def lock_store(self, scope: str) -> Effect[StoreRow, SqlError]:
        """Locks the store row for the rest of the transaction."""
        return self.sql(
            "SELECT {} FROM {} {} WHERE scope = {} {}",
            self.sql.literal(_STORE_COLUMNS),
            self.stores,
            self.lock_hint,
            scope,
            self.for_update,
        ).flat_map(lambda rows: self._store_row(scope, rows))

    def _store_row(self, scope: str, rows: list[Row]) -> Effect[StoreRow]:
        if not rows:
            return die(NoSuchElementException(f"No compaction store row for scope {scope}"))
        return succeed(StoreRow.parse(rows[0]))

    def select_stage(
        self, scope: str, stage_id: str, *, lock: bool
    ) -> Effect[StageRow | None, SqlError]:
        """The stage, when it belongs to ``scope``."""

        def parse(rows: list[Row]) -> StageRow | None:
            if not rows:
                return None
            stage = StageRow.parse(rows[0])
            return stage if stage.scope == scope else None

        return self.sql(
            "SELECT {} FROM {} {} WHERE id = {} {}",
            self.sql.literal(_STAGE_COLUMNS),
            self.stages,
            self.lock_hint if lock else self.none,
            stage_id,
            self.for_update if lock else self.none,
        ).map(parse)

    def select_activation(self, activation_id: str) -> Effect[ActivationRow | None, SqlError]:
        return self.sql(
            "SELECT {} FROM {} WHERE id = {}",
            self.sql.literal(_ACTIVATION_COLUMNS),
            self.activations,
            activation_id,
        ).map(lambda rows: ActivationRow.parse(rows[0]) if rows else None)

    def select_activations(self, scope: str) -> Effect[list[ActivationRow], SqlError]:
        return self.sql(
            "SELECT {} FROM {} WHERE scope = {} ORDER BY ordinal",
            self.sql.literal(_ACTIVATION_COLUMNS),
            self.activations,
            scope,
        ).map(lambda rows: [ActivationRow.parse(row) for row in rows])

    def release_claim(self, scope: str, stage_id: str) -> Effect[Any, SqlError]:
        return self.sql(
            "UPDATE {} SET open_stage = NULL WHERE scope = {} AND open_stage = {}",
            self.stores,
            scope,
            stage_id,
        )

    def close_stage(self, scope: str, stage_id: str) -> Effect[Any, SqlError]:
        """Closes an open stage, leaving what it staged to the sweep, and
        releases the store's busy claim."""
        return self.sql(
            "UPDATE {} SET state = {} WHERE id = {} AND state = {}",
            self.stages,
            "closed",
            stage_id,
            "open",
        ).and_then(self.release_claim(scope, stage_id))

    def schedule_sweep(self, scope: str, at: float) -> Effect[Any, SqlError]:
        return self.sql(
            "UPDATE {} SET next_sweep_at = CASE WHEN next_sweep_at IS NULL OR next_sweep_at > {} "
            "THEN {} ELSE next_sweep_at END WHERE scope = {}",
            self.stores,
            int(at),
            int(at),
            scope,
        )

    def insert_activation(
        self,
        scope: str,
        *,
        id: str,
        batch_set: str | None,
        base: int,
        kept_count: int | None,
        previous: str | None,
    ) -> Effect[None, SqlError]:
        sql = self.sql

        def body():
            [last] = yield from sql(
                "SELECT MAX(ordinal) AS ordinal FROM {} WHERE scope = {}", self.activations, scope
            )
            ordinal = 0 if last["ordinal"] is None else column_int(last["ordinal"])
            yield from sql(
                "INSERT INTO {} {}",
                self.activations,
                sql.insert(
                    {
                        "id": id,
                        "scope": scope,
                        "ordinal": ordinal + 1,
                        "batch_set": batch_set,
                        "base_sequence": base,
                        "kept_count": kept_count,
                        "previous": previous,
                        "superseded_at": None,
                        "prunable_at": None,
                        "prune_started_at": None,
                    }
                ),
            )

        return gen(body)

    def supersede(self, activation_id: str, now: int) -> Effect[Any, SqlError]:
        """Supersedes or withdraws an activation, prunable ``grace`` later."""
        return self.sql(
            "UPDATE {} SET superseded_at = {}, prunable_at = {} WHERE id = {}",
            self.activations,
            now,
            int(now + self.config.grace_millis),
            activation_id,
        )

    # Paging and chunked deletes.

    def paged(
        self,
        first: int,
        page: Callable[[int], Effect[list[Row], SqlError]],
        key: Callable[[Row], int],
    ) -> Stream[Row, SqlError]:
        """Rows in key order, one page per statement."""

        def next_page(after: int) -> Effect[tuple[list[Row], Some[int] | None], SqlError]:
            return page(after).map(
                lambda rows: (rows, None if len(rows) < PAGE_SIZE else Some(key(rows[-1])))
            )

        return paginate(first, next_page)

    def set_rows(self, snapshot_table: Identifier, batch_set: str) -> Stream[Row, SqlError]:
        """A batch set's rows (position, sequence, ids) in position order."""
        return self.paged(
            -1,
            lambda after: self.sql(
                "SELECT {} batch_position, sequence, entry_ids FROM {} "
                "WHERE batch_set = {} AND batch_position > {} ORDER BY batch_position {}",
                self.page.top,
                snapshot_table,
                batch_set,
                after,
                self.page.limit,
            ),
            lambda row: column_int(row["batch_position"]),
        )

    def delete_chunk(self, table: Identifier, key: str, where: Fragment) -> Effect[bool, SqlError]:
        """Deletes up to ``PRUNE_CHUNK_ROWS`` rows matching ``where`` in key
        order; whether it found any. No new rows match ``where``, so a later
        call resumes an interrupted one."""
        sql = self.sql
        key_sql = sql.identifier(key)

        def body():
            keys = yield from sql(
                "SELECT {} {} AS chunk_key FROM {} WHERE {} ORDER BY {} {}",
                self.chunk.top,
                key_sql,
                table,
                where,
                key_sql,
                self.chunk.limit,
            )
            if not keys:
                return False
            yield from sql(
                "DELETE FROM {} WHERE {} AND {} <= {}",
                table,
                where,
                key_sql,
                keys[-1]["chunk_key"],
            )
            return True

        return gen(body)


def die_on_sql_error[A, E, R](effect: Effect[A, E | SqlError, R]) -> Effect[A, E, R]:
    """SQL failures are defects for the compaction primitives."""
    return effect.pipe(catch_tag(SqlError, die))


@dataclass(frozen=True, slots=True)
class StoreResources:
    """An opened store: its tables, the pubsub of its live readers and the
    semaphore that orders this instance's writes."""

    tables: ScopeTables
    pubsub: PubSub[EncryptedRemoteBatch]
    semaphore: Semaphore

    @property
    def scope(self) -> str:
        return self.tables.scope
