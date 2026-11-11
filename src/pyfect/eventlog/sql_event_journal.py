"""A journal in a SQL database (Effect's ``eventlog/SqlEventJournal``),
on SQLite or PostgreSQL.

Entries live in ``entry_table``; ``<entry_table>_sequence`` numbers them in
insertion order (uploads checkpoint that number, since ids order creation,
not insertion), ``<entry_table>_sources`` records the remote each imported
entry came from, and the cursors and checkpoints tables keep each remote's
download and upload progress. Several processes may share the database:
local ids sort after the latest stored id, and on PostgreSQL writers
serialize on a table lock so checkpoints cannot skip a commit.

A database written by a release that kept a ``remotes_table`` row per
entry per remote is migrated in one transaction when opened.
"""

from __future__ import annotations

from collections.abc import Callable, Sequence
from typing import Any, Literal, LiteralString, Never, cast

from pyfect._concurrency import for_each
from pyfect._core import Effect, Restore, uninterruptible_mask
from pyfect.clock import Clock, ClockService
from pyfect.effect import die, gen, succeed
from pyfect.eventlog._conflicts import ConflictGroup, ConflictIndex
from pyfect.eventlog.event_journal import (
    Compact,
    Entry,
    EntryId,
    EntryInput,
    EventJournal,
    EventJournalError,
    EventJournalService,
    RemoteAck,
    RemoteEntry,
    RemoteId,
    ReplayBatch,
    StoreId,
    WithLock,
    advance_sequence,
    entry_id_millis,
    entry_order,
    make_entries,
    next_sequence_after,
    warn_if_ahead,
)
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect
from pyfect.option import Option, Some
from pyfect.persistence._columns import column_bytes, column_int
from pyfect.pubsub import PubSub, Subscription
from pyfect.schema import new
from pyfect.scope import Scope
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.connection import Row
from pyfect.sql.error import SqlError
from pyfect.sql.statement import Fragment, Identifier

__all__ = ["SqlError", "layer", "make"]

type _Dialect = Literal["sqlite", "pg"]


def _dialect(sql: SqlClientService) -> _Dialect:
    match sql.dialect:
        case "sqlite" | "pg":
            return sql.dialect
        case _:
            pass
    raise ValueError(f"SqlEventJournal supports SQLite and PostgreSQL, not {sql.dialect}")


def _to_entry(row: Row) -> Entry:
    return new(Entry, disable_checks=True)(
        id=EntryId(column_bytes(row["id"])),
        event=str(row["event"]),
        primary_key=str(row["primary_key"]),
        payload=column_bytes(row["payload"]),
    )


def _to_ordered_entries(rows: Sequence[Row]) -> list[Entry]:
    # Timestamp ties sort by id bytes the same way on every dialect.
    return sorted(map(_to_entry, rows), key=entry_order)


def _to_entry_row(entry: Entry) -> dict[str, object]:
    return {
        "id": entry.id,
        "event": entry.event,
        "primary_key": entry.primary_key,
        "payload": entry.payload,
        "timestamp": entry_id_millis(entry.id),
    }


class _CallbackFailure:
    """A write callback's own error, kept apart from the journal's SQL
    errors."""

    __slots__ = ("error",)

    def __init__(self, error: object) -> None:
        self.error = error


def _journal_error(method: str) -> Callable[[object], EventJournalError]:
    return lambda cause: EventJournalError(method, cause)


def make(
    *,
    entry_table: str = "effect_event_journal",
    remotes_table: str = "effect_event_remotes",
    remote_cursors_table: str | None = None,
) -> Effect[EventJournalService, SqlError, SqlClient]:
    """A journal in the ``SqlClient``'s database, creating or migrating its
    tables (Effect's ``SqlEventJournal.make``). Fails with ``ValueError``
    as a defect on a dialect other than SQLite or PostgreSQL."""

    def build():
        sql = (yield from SqlClient()).without_transforms()
        dialect = _dialect(sql)
        tables = _Tables(
            sql,
            entry_table,
            remotes_table,
            remote_cursors_table or f"{remotes_table}_cursors",
        )
        yield from _open_schema(sql, dialect, tables).with_tracer_enabled(False)
        pubsub = yield from PubSub[Entry].unbounded()
        clock = yield from Clock()
        return _SqlJournal(sql, dialect, tables, pubsub, clock)

    return gen(build)


def layer(
    *,
    entry_table: str = "effect_event_journal",
    remotes_table: str = "effect_event_remotes",
    remote_cursors_table: str | None = None,
) -> Layer[EventJournal, SqlError, SqlClient]:
    """The ``EventJournal`` of ``make``."""
    return layer_effect(
        EventJournal,
        make(
            entry_table=entry_table,
            remotes_table=remotes_table,
            remote_cursors_table=remote_cursors_table,
        ),
    )


class _Tables:
    __slots__ = (
        "checkpoints",
        "cursors",
        "entries",
        "entry_name",
        "remotes",
        "remotes_name",
        "sequence",
        "sources",
        "sources_name",
    )

    def __init__(
        self, sql: SqlClientService, entry_table: str, remotes_table: str, cursors_table: str
    ) -> None:
        self.entry_name = entry_table
        self.remotes_name = remotes_table
        self.sources_name = f"{entry_table}_sources"
        self.entries: Identifier = sql.identifier(entry_table)
        self.remotes: Identifier = sql.identifier(remotes_table)
        self.sequence: Identifier = sql.identifier(f"{entry_table}_sequence")
        self.sources: Identifier = sql.identifier(self.sources_name)
        self.checkpoints: Identifier = sql.identifier(f"{remotes_table}_checkpoints")
        self.cursors: Identifier = sql.identifier(cursors_table)


def _quoted(sql: SqlClientService, table: str) -> str:
    # to_regclass folds unquoted names to lowercase, so pass the quoted name.
    return sql("{}", sql.identifier(table)).compile(True)[0]


def _table_exists(sql: SqlClientService, dialect: _Dialect, table: str) -> Effect[bool, SqlError]:
    if dialect == "pg":
        # Reading the catalog refreshes cached names after concurrent DDL.
        query = sql(
            "SELECT 1 AS found FROM pg_class WHERE oid = to_regclass({})", _quoted(sql, table)
        )
    else:
        query = sql(
            "SELECT 1 AS found FROM sqlite_master WHERE type = 'table' AND name = {}", table
        )
    return query.map(lambda rows: len(rows) > 0)


def _create_schema(sql: SqlClientService, dialect: _Dialect, t: _Tables) -> Effect[None, SqlError]:
    event_index = sql.identifier(f"{t.entry_name}_event_idx")
    timestamp_index = sql.identifier(f"{t.entry_name}_timestamp_idx")
    pg = dialect == "pg"

    def body():
        if pg:
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (id BYTEA PRIMARY KEY, event TEXT NOT NULL, "
                "primary_key TEXT NOT NULL, payload BYTEA NOT NULL, timestamp BIGINT NOT NULL)",
                t.entries,
            )
            # Insertion sequences let uploads include older entries imported later.
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (sequence BIGSERIAL PRIMARY KEY, "
                "entry_id BYTEA NOT NULL UNIQUE)",
                t.sequence,
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (remote_id BYTEA PRIMARY KEY, "
                "sequence BIGINT NOT NULL)",
                t.checkpoints,
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (remote_id BYTEA PRIMARY KEY, "
                "next_sequence INT NOT NULL)",
                t.cursors,
            )
            # The remote each imported entry came from, so uploads skip it.
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (entry_id BYTEA PRIMARY KEY, "
                "remote_id BYTEA NOT NULL)",
                t.sources,
            )
            # B-tree entries are limited to about 2.7 KB, so index hashes of
            # the unbounded columns.
            yield from sql(
                "CREATE INDEX IF NOT EXISTS {} ON {} (md5(event), md5(primary_key), timestamp)",
                event_index,
                t.entries,
            )
        else:
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (id BLOB PRIMARY KEY, event TEXT NOT NULL, "
                "primary_key TEXT NOT NULL, payload BLOB NOT NULL, timestamp INTEGER NOT NULL)",
                t.entries,
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (sequence INTEGER PRIMARY KEY, "
                "entry_id BLOB NOT NULL UNIQUE)",
                t.sequence,
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (remote_id BLOB PRIMARY KEY, "
                "sequence INTEGER NOT NULL)",
                t.checkpoints,
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (remote_id BLOB PRIMARY KEY, "
                "next_sequence INT NOT NULL)",
                t.cursors,
            )
            yield from sql(
                "CREATE TABLE IF NOT EXISTS {} (entry_id BLOB PRIMARY KEY, "
                "remote_id BLOB NOT NULL)",
                t.sources,
            )
            yield from sql(
                "CREATE INDEX IF NOT EXISTS {} ON {} (event, primary_key, timestamp)",
                event_index,
                t.entries,
            )
        yield from sql(
            "CREATE INDEX IF NOT EXISTS {} ON {} (timestamp)", timestamp_index, t.entries
        )
        # Number existing entries in creation order. ``WHERE true`` keeps
        # SQLite from parsing ON CONFLICT as a join constraint.
        yield from sql(
            "INSERT INTO {} (entry_id) SELECT id FROM {} WHERE true "
            "ORDER BY timestamp ASC, id ASC ON CONFLICT DO NOTHING",
            t.sequence,
            t.entries,
        )

    return gen(body)


def _import_remotes(sql: SqlClientService, t: _Tables) -> Effect[None, SqlError]:
    # Earlier releases kept a remotes row per entry per remote. An entry
    # known to several remotes keeps one of them as its source, and a remote
    # without a cursor resumes after its highest downloaded sequence.
    def body():
        yield from sql(
            "INSERT INTO {} (entry_id, remote_id) SELECT entry_id, remote_id FROM {} "
            "WHERE true ON CONFLICT DO NOTHING",
            t.sources,
            t.remotes,
        )
        yield from sql(
            "INSERT INTO {} (remote_id, next_sequence) SELECT remote_id, MAX(sequence) + 1 "
            "FROM {} GROUP BY remote_id ON CONFLICT DO NOTHING",
            t.cursors,
            t.remotes,
        )
        yield from sql("DROP TABLE {}", t.remotes)

    return gen(body)


def _open_schema(sql: SqlClientService, dialect: _Dialect, t: _Tables) -> Effect[None, SqlError]:
    # Both steps run in one transaction, so a complete schema has the sources
    # table and no remotes table. Checking that first lets complete databases
    # open read-only; PostgreSQL also locks and rechecks so concurrent opens
    # migrate once.
    def state():
        sources = yield from _table_exists(sql, dialect, t.sources_name)
        remotes = yield from _table_exists(sql, dialect, t.remotes_name)
        return sources, remotes

    def migrate():
        if dialect == "pg":
            yield from sql("SELECT pg_advisory_xact_lock(hashtext({}))", _quoted(sql, t.entry_name))
        sources, remotes = yield from gen(state)
        if not sources:
            yield from _create_schema(sql, dialect, t)
        if remotes:
            yield from _import_remotes(sql, t)

    def body():
        sources, remotes = yield from gen(state)
        if sources and not remotes:
            return
        yield from sql.with_transaction(gen(migrate))

    return gen(body)


# Statements bind at most this many parameters: Cloudflare Durable Object
# SQLite's per-statement limit, the lowest of the supported databases.
_MAX_PARAMETERS = 100


def _for_each_chunk[A, B, E](
    values: Sequence[A],
    parameters_per_value: int,
    f: Callable[[list[A]], Effect[list[B], E]],
) -> Effect[list[B], E]:
    """``f`` in order over chunks of ``values`` binding at most
    ``_MAX_PARAMETERS`` parameters each, the rows concatenated."""
    size = _MAX_PARAMETERS // parameters_per_value
    chunks = [list(values[i : i + size]) for i in range(0, len(values), size)]
    return for_each(chunks, f).map(lambda rows: [row for chunk in rows for row in chunk])


class _SqlJournal(EventJournalService):
    def __init__(
        self,
        sql: SqlClientService,
        dialect: _Dialect,
        tables: _Tables,
        pubsub: PubSub[Entry],
        clock: ClockService,
    ) -> None:
        self._sql = sql
        self._dialect = dialect
        self._t = tables
        self._pubsub = pubsub
        self._clock = clock

    # --- statements -----------------------------------------------------------------

    @property
    def _lock_writers(self) -> Effect[None, SqlError]:
        # Serialize writers so checkpoints cannot skip out-of-order commits.
        # Lock before callbacks in both paths to avoid projection-row deadlocks.
        if self._dialect == "pg":
            return self._sql(
                "LOCK TABLE {} IN SHARE ROW EXCLUSIVE MODE", self._t.sequence
            ).as_void()
        return succeed(None)

    def _insert(self, table: object, rows: list[dict[str, object]]) -> Effect[object, SqlError]:
        """Insert ``rows`` in statements within the parameter limit (none is
        nothing to do: ``sql.insert`` needs one)."""
        sql = self._sql
        columns = len(rows[0]) if rows else 1
        return _for_each_chunk(
            rows,
            columns,
            lambda chunk: sql("INSERT INTO {} {} ON CONFLICT DO NOTHING", table, sql.insert(chunk)),
        )

    def _insert_entries(self, entries: Sequence[Entry]) -> Effect[object, SqlError]:
        return self._insert(self._t.entries, [_to_entry_row(entry) for entry in entries])

    def _insert_sequence(self, entries: Sequence[Entry]) -> Effect[object, SqlError]:
        return self._insert(self._t.sequence, [{"entry_id": entry.id} for entry in entries])

    def _insert_sources(
        self, entries: Sequence[Entry], remote_id: RemoteId
    ) -> Effect[object, SqlError]:
        rows: list[dict[str, object]] = [
            {"entry_id": entry.id, "remote_id": remote_id} for entry in entries
        ]
        return self._insert(self._t.sources, rows)

    def _select_by_id(
        self, columns: LiteralString, ids: Sequence[bytes]
    ) -> Effect[list[Row], SqlError]:
        sql = self._sql
        return _for_each_chunk(
            ids,
            1,
            lambda chunk: sql(
                f"SELECT {columns} FROM {{}} WHERE {{}}", self._t.entries, sql.in_("id", chunk)
            ),
        )

    def _read_cursor(self, remote_id: RemoteId) -> Effect[int, SqlError]:
        return self._sql(
            "SELECT next_sequence FROM {} WHERE remote_id = {}", self._t.cursors, remote_id
        ).map(lambda rows: column_int(rows[0]["next_sequence"]) if rows else 0)

    def _write_cursor(self, remote_id: RemoteId, next: int) -> Effect[object, SqlError]:
        # Cursors only move forward.
        sql = self._sql
        return sql(
            "INSERT INTO {} {} ON CONFLICT (remote_id) DO UPDATE "
            "SET next_sequence = excluded.next_sequence "
            "WHERE {}.next_sequence < excluded.next_sequence",
            self._t.cursors,
            sql.insert({"remote_id": remote_id, "next_sequence": next}),
            self._t.cursors,
        )

    @property
    def _latest_entry_ids(self) -> Effect[list[EntryId], SqlError]:
        # Other processes share the database but not the entry id sequence.
        # Ids in the latest millisecond are few, and comparing them here
        # avoids ordering id bytes in SQL.
        return self._sql(
            "SELECT id FROM {} WHERE timestamp = (SELECT MAX(timestamp) FROM {})",
            self._t.entries,
            self._t.entries,
        ).map(lambda rows: [EntryId(column_bytes(row["id"])) for row in rows])

    def _conflicts(self, index: ConflictIndex) -> Effect[list[Entry], SqlError]:
        """The stored entries of the batch's groups, each once, in statements
        within the parameter limit."""
        # Each group binds its event and key, twice on PostgreSQL, and one
        # parameter is left for the timestamp.
        per_chunk = (_MAX_PARAMETERS - 1) // (4 if self._dialect == "pg" else 2)
        groups = list(index.groups())
        chunks = [groups[i : i + per_chunk] for i in range(0, len(groups), per_chunk)]

        def unique(rows: list[list[Row]]) -> list[Entry]:
            # Chunks can share an event and a key, so a row can come twice.
            seen: set[bytes] = set()
            entries: list[Entry] = []
            for row in (row for chunk in rows for row in chunk):
                found = _to_entry(row)
                if found.id not in seen:
                    seen.add(found.id)
                    entries.append(found)
            return entries

        return for_each(chunks, lambda chunk: self._conflicts_of(index, chunk)).map(unique)

    def _conflicts_of(
        self, index: ConflictIndex, groups: list[ConflictGroup]
    ) -> Effect[list[Row], SqlError]:
        sql = self._sql
        events = list(dict.fromkeys(group.event for group in groups))
        primary_keys = list(dict.fromkeys(group.primary_key for group in groups))
        clauses: list[Fragment] = []
        if self._dialect == "pg":
            # Match the hash index; the exact predicates rule out collisions.
            clauses.append(
                sql(
                    "md5(event) IN ({})",
                    sql.csv([sql("md5({})", event) for event in events]),
                )
            )
            clauses.append(
                sql(
                    "md5(primary_key) IN ({})",
                    sql.csv([sql("md5({})", key) for key in primary_keys]),
                )
            )
        clauses.append(sql.in_("event", events))
        clauses.append(sql.in_("primary_key", primary_keys))
        # A coarse filter: the index compares ids exactly.
        clauses.append(sql("timestamp >= {}", index.oldest_millis))
        return sql("SELECT * FROM {} WHERE {}", self._t.entries, sql.and_(clauses))

    # --- the service ----------------------------------------------------------------

    @property
    def entries(self) -> Effect[list[Entry], EventJournalError]:
        return (
            self._sql("SELECT * FROM {} ORDER BY timestamp ASC", self._t.entries)
            .with_tracer_enabled(False)
            .map(_to_ordered_entries)
            .map_error(_journal_error("entries"))
        )

    def entries_by_id(
        self, ids: Sequence[EntryId], /
    ) -> Effect[list[Entry | None], EventJournalError]:
        def pick(rows: list[Row]) -> list[Entry | None]:
            by_id = {entry.id: entry for entry in map(_to_entry, rows)}
            return [by_id.get(entry_id) for entry_id in ids]

        return (
            self._select_by_id("*", ids)
            .with_tracer_enabled(False)
            .map(pick)
            .map_error(_journal_error("entriesById"))
        )

    def write_many[A, E, R](
        self,
        entries: Sequence[EntryInput],
        effect: Callable[[list[Entry]], Effect[A, E, R]],
        /,
    ) -> Effect[A, EventJournalError | E, R]:
        sql = self._sql

        def unwrap(error: object) -> Any:
            if isinstance(error, _CallbackFailure):
                return error.error
            if isinstance(error, EventJournalError):
                return error
            return EventJournalError("writeMany", error)

        def masked(restore: Restore) -> Effect[A, Any, R]:
            def body():
                yield from self._lock_writers
                # Rows visible here include an enclosing transaction's
                # uncommitted ones, which local ids must also sort after.
                after = yield from self._latest_entry_ids
                committed = yield from make_entries(entries, after)
                result = yield from restore(effect(committed)).map_error(_CallbackFailure)
                yield from self._insert_entries(committed)
                yield from self._insert_sequence(committed)
                return result, committed

            def publish(written: tuple[A, list[Entry]]) -> Effect[A]:
                result, committed = written
                return self._pubsub.publish_all(committed).as_(result)

            return sql.with_transaction(gen(body)).map_error(unwrap).flat_map(publish)

        return uninterruptible_mask(masked).with_tracer_enabled(False)

    def _write_from_remote(
        self,
        remote_id: RemoteId,
        remote_entries: Sequence[RemoteEntry],
        effect: ReplayBatch,
        compact: Compact | None,
    ) -> Effect[list[Entry], Any]:
        def body():
            yield from self._lock_writers
            rows = yield from self._select_by_id(
                "id", [remote_entry.entry.id for remote_entry in remote_entries]
            )
            existing = {column_bytes(row["id"]) for row in rows}
            # Overlapping batches can repeat an entry; the first copy wins.
            incoming: set[bytes] = set()
            uncommitted: list[RemoteEntry] = []
            for remote_entry in remote_entries:
                entry_id = remote_entry.entry.id
                if entry_id in existing or entry_id in incoming:
                    continue
                incoming.add(entry_id)
                uncommitted.append(remote_entry)
            duplicates = [
                remote_entry.entry
                for remote_entry in remote_entries
                if remote_entry.entry.id in existing
            ]
            compacted = (
                (yield from compact(uncommitted))
                if compact is not None
                else [remote_entry.entry for remote_entry in uncommitted]
            )
            if compacted:
                index = ConflictIndex(compacted)
                for stored in (yield from self._conflicts(index)):
                    index.add(stored)
                yield from effect(index.to_batch())
            # Keep the incoming batch out of conflict queries and persist only
            # after compaction and every callback have succeeded.
            if uncommitted:
                imported = [remote_entry.entry for remote_entry in uncommitted]
                yield from self._insert_entries(imported)
                yield from self._insert_sequence(imported)
                yield from self._insert_sources(imported, remote_id)
            # The change stream is ordered, so every earlier sequence is known.
            if remote_entries:
                yield from self._write_cursor(remote_id, next_sequence_after(remote_entries))
            yield from warn_if_ahead(
                self._clock, (remote_entry.entry.id for remote_entry in uncommitted)
            )
            return duplicates

        return gen(body)

    def write_from_remote(
        self,
        *,
        remote_id: RemoteId,
        entries: Sequence[RemoteEntry],
        effect: ReplayBatch,
        compact: Compact | None = None,
    ) -> Effect[list[Entry], EventJournalError]:
        def wrap(error: object) -> EventJournalError:
            if isinstance(error, EventJournalError):
                return error
            return EventJournalError("writeFromRemote", error)

        return (
            self._sql.with_transaction(self._write_from_remote(remote_id, entries, effect, compact))
            .with_tracer_enabled(False)
            .map_error(wrap)
        )

    def with_remote_uncommitted[A, E, R](
        self, remote_id: RemoteId, f: Callable[[list[Entry]], Effect[A, E, R]], /
    ) -> Effect[Option[A], EventJournalError | E, R]:
        sql = self._sql
        t = self._t
        journal_error = _journal_error("withRemoteUncommited")

        def body():
            # An upper bound, so entries committed during the upload stay pending.
            bounds = yield from sql(
                "SELECT COALESCE((SELECT sequence FROM {} WHERE remote_id = {}), 0) AS checkpoint, "
                "COALESCE((SELECT MAX(sequence) FROM {}), 0) AS latest",
                t.checkpoints,
                remote_id,
                t.sequence,
            ).map_error(journal_error)
            checkpoint = column_int(bounds[0]["checkpoint"])
            latest = column_int(bounds[0]["latest"])
            if latest <= checkpoint:
                return None
            rows = yield from sql(
                "SELECT e.* FROM {} s JOIN {} e ON e.id = s.entry_id "
                "WHERE s.sequence > {} AND s.sequence <= {} AND NOT EXISTS ("
                "SELECT 1 FROM {} src WHERE src.entry_id = s.entry_id AND src.remote_id = {})",
                t.sequence,
                t.entries,
                checkpoint,
                latest,
                t.sources,
                remote_id,
            ).map_error(journal_error)
            entries = _to_ordered_entries(rows)
            # Uploads can complete out of order; the checkpoint only moves forward.
            save_checkpoint = sql(
                "INSERT INTO {} {} ON CONFLICT (remote_id) DO UPDATE "
                "SET sequence = excluded.sequence WHERE {}.sequence < excluded.sequence",
                t.checkpoints,
                sql.insert({"remote_id": remote_id, "sequence": latest}),
                t.checkpoints,
            ).map_error(journal_error)

            def upload(restore: Restore) -> Effect[Option[A], Any, R]:
                run: Effect[Option[A], E, R] = f(entries).map(Some) if entries else succeed(None)
                return restore(run).tap(lambda _: save_checkpoint)

            return (yield from uninterruptible_mask(upload))

        return gen(body).with_tracer_enabled(False)

    def write_remote_acks(
        self, *, remote_id: RemoteId, acks: Sequence[RemoteAck], first_sequence: int | None = None
    ) -> Effect[None, EventJournalError]:
        if not acks:
            return succeed(None)

        def body():
            next = yield from self._read_cursor(remote_id)
            yield from self._write_cursor(
                remote_id, advance_sequence(next, acks, first_sequence or 0)
            )

        return (
            self._sql.with_transaction(gen(body))
            .with_tracer_enabled(False)
            .map_error(_journal_error("writeRemoteAcks"))
        )

    def next_remote_sequence(self, remote_id: RemoteId, /) -> Effect[int, EventJournalError]:
        return (
            self._read_cursor(remote_id)
            .with_tracer_enabled(False)
            .map_error(_journal_error("nextRemoteSequence"))
        )

    @property
    def changes(self) -> Effect[Subscription[Entry], Never, Scope]:
        return self._pubsub.subscribe()

    @property
    def destroy(self) -> Effect[None, EventJournalError]:
        sql = self._sql
        t = self._t

        def body():
            for table in (t.entries, t.sequence, t.sources, t.checkpoints, t.cursors):
                yield from sql("DROP TABLE {}", table)

        return gen(body).with_tracer_enabled(False).map_error(_journal_error("destroy"))

    def with_lock(self, store_id: StoreId, /) -> WithLock:
        return _TransactionLock(self._sql)


class _TransactionLock:
    """A store's lock is a transaction of the journal's client."""

    __slots__ = ("_sql",)

    def __init__(self, sql: SqlClientService) -> None:
        self._sql = sql

    def __call__[A, E, R](self, effect: Effect[A, E, R], /) -> Effect[A, E, R]:
        def defect(error: object) -> Effect[Never]:
            return die(cast("BaseException", error))

        return cast(
            "Effect[A, E, R]",
            self._sql.with_transaction(effect).catch_if(
                lambda error: isinstance(error, SqlError), defect
            ),
        )
