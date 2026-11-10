"""Ports of the compaction suite of Effect's
``effect/test/eventlog/SqlEventLogServerEncryptedStorageTest.ts``
(``compactionSuite``) for ``pyfect.eventlog.sql_event_log_server_encrypted``,
on SQLite and the session's PostgreSQL server and MySQL and SQL Server
containers (each skipped without one), under the TestClock.

Each test's docstring is the Effect test title. Every test gets its own
tables, the global ones included, so stores and sweeps from other tests
stay out of its way.
"""

import itertools
import os
import uuid
from collections.abc import Callable, Generator, Sequence
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.crypto import digest
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog import sql_event_log_server_encrypted as SqlE
from pyfect.eventlog.event_journal import EntryId, StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, EncryptedRemoteBatch
from pyfect.persistence._columns import column_int
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.statement import CurrentTransformer

store_id = StoreId("store-a")
_namespaces = itertools.count()
SNAPSHOT_MARKER = 99

type Connect = Callable[[], fx.Effect[SqlClientService, Any, Any]]


@pytest.fixture(params=["SQLite", "pg", "mysql2", "mssql"])
def connect(request: pytest.FixtureRequest) -> Connect:
    """A new client on an in-memory SQLite database, the session's
    PostgreSQL server, or the MySQL or SQL Server container."""
    match request.param:
        case "SQLite":
            return lambda: sqlite.make(sqlite.SqliteClientConfig(filename=":memory:"))
        case "pg":
            pytest.importorskip("psycopg")
            from pyfect.sql import pg

            from ._postgres import PgServer

            server: PgServer = request.getfixturevalue("pg_server")
            return lambda: pg.make(pg.PgPoolConfig(url=server.url))
        case "mssql":
            pytest.importorskip("pytds")
            from pyfect.sql import mssql

            from ._mssql import MssqlServer

            mssql_server: MssqlServer = request.getfixturevalue("mssql_server")
            return lambda: mssql.make(mssql_server.config())
        case _:
            pytest.importorskip("asyncmy")
            from pyfect.sql import mysql

            from ._mysql import MysqlServer

            mysql_server: MysqlServer = request.getfixturevalue("mysql_server")
            return lambda: mysql.make(mysql.MysqlClientConfig(url=mysql_server.url))


def _run(body: Callable[[], Generator[Any, Any, Any]]) -> fx.Effect[Any, Any, Any]:
    return fx.gen(body).pipe(fx.provide(fx.layer.merge(reactivity_layer, digest.layer_web_crypto)))


def make_ids(count: int) -> list[EntryId]:
    return [J.make_entry_id_unsafe() for _ in range(count)]


def make_batch(*entry_ids: EntryId, marker: int | None = None) -> EncryptedBatch:
    return EncryptedBatch(
        entry_ids=entry_ids,
        iv=bytes(12),
        encrypted_batch=bytes([len(entry_ids) if marker is None else marker]),
    )


def ids(batches: Sequence[Any]) -> list[list[bytes]]:
    return [list(batch.entry_ids) for batch in batches]


def served(batches: Sequence[EncryptedRemoteBatch]) -> list[tuple[int, int]]:
    return [(batch.sequence, batch.encrypted_batch[0]) for batch in batches]


class Namespace:
    """A test's own tables and identity, with the scope's batch table ``T``
    named as every version of the storage names it."""

    def __init__(
        self, sql: SqlClientService, scope_hash: str, compaction: Server.CompactionOptions | None
    ) -> None:
        namespace = f"compaction_{os.getpid()}_{next(_namespaces)}"
        self.sql = sql
        self.public_key = str(uuid.uuid4())
        self.prefix = f"{namespace}_events"
        self.remote_id_table = f"{namespace}_remote_id"
        self.compaction = compaction
        self.table = f"{self.prefix}_{scope_hash}"

    def storage(self) -> fx.Effect[Server.StorageService, Any, Any]:
        return SqlE.make_storage(
            entry_table_prefix=self.prefix,
            remote_id_table=self.remote_id_table,
            compaction=self.compaction,
        ).pipe(fx.provide_service(SqlClient, self.sql))


def make_namespace(
    sql: SqlClientService, compaction: Server.CompactionOptions | None = None
) -> Generator[Any, Any, Namespace]:
    namespace = Namespace(sql, "", compaction)
    service = yield from digest.Digest()
    scope_hash = yield from service.digest_hex(
        digest.sha256, f"{namespace.public_key}/{store_id}".encode()
    )
    namespace.table = f"{namespace.prefix}_{scope_hash[:16]}"
    return namespace


def compaction_of(storage: Server.StorageService) -> Server.StorageCompaction:
    assert storage.compaction is not None, "Storage does not provide compaction"
    return storage.compaction


def create_legacy_tables(sql: SqlClientService, table: str) -> fx.Effect[None, Any]:
    """``T`` and ``T_ids`` as the storage created them before compaction."""
    table_sql = sql.identifier(table)
    ids_sql = sql.identifier(f"{table}_ids")
    index_sql = sql.identifier(f"{table}_last_sequence")

    def body():
        if sql.dialect == "mysql":
            yield from sql(
                "CREATE TABLE {} (sequence INT PRIMARY KEY, last_sequence INT NOT NULL, "
                "iv BINARY(12) NOT NULL, entry_ids LONGBLOB NOT NULL, "
                "encrypted_batch LONGBLOB NOT NULL, INDEX (last_sequence))",
                table_sql,
            )
            yield from sql(
                "CREATE TABLE {} (entry_id BINARY(16) PRIMARY KEY, sequence INT NOT NULL)", ids_sql
            )
        elif sql.dialect == "mssql":
            yield from sql(
                "CREATE TABLE {} (sequence INT PRIMARY KEY, last_sequence INT NOT NULL, "
                "iv VARBINARY(12) NOT NULL, entry_ids VARBINARY(MAX) NOT NULL, "
                "encrypted_batch VARBINARY(MAX) NOT NULL, "
                "INDEX {} NONCLUSTERED (last_sequence))",
                table_sql,
                index_sql,
            )
            yield from sql(
                "CREATE TABLE {} (entry_id VARBINARY(16) PRIMARY KEY, sequence INT NOT NULL)",
                ids_sql,
            )
        else:
            binary = sql.literal("BYTEA") if sql.dialect == "pg" else sql.literal("BLOB")
            yield from sql(
                "CREATE TABLE {} (sequence INTEGER PRIMARY KEY, last_sequence INTEGER NOT NULL, "
                "iv {b} NOT NULL, entry_ids {b} NOT NULL, encrypted_batch {b} NOT NULL)",
                table_sql,
                b=binary,
            )
            yield from sql("CREATE INDEX {} ON {} (last_sequence)", index_sql, table_sql)
            yield from sql(
                "CREATE TABLE {} (entry_id {} PRIMARY KEY, sequence INTEGER NOT NULL)",
                ids_sql,
                binary,
            )

    return fx.gen(body)


def legacy_write(sql: SqlClientService, table: str, batch: EncryptedBatch) -> fx.Effect[int, Any]:
    """Writes a batch of new ids as an instance from before compaction does,
    at ``MAX(last_sequence) + 1`` and without touching the store row or the
    buckets."""

    def body():
        [last] = yield from sql(
            "SELECT MAX(last_sequence) AS last_sequence FROM {}", sql.identifier(table)
        )
        found = last["last_sequence"]
        sequence = (0 if found is None else column_int(found)) + 1
        yield from sql(
            "INSERT INTO {} {}",
            sql.identifier(f"{table}_ids"),
            sql.insert(
                [{"entry_id": e, "sequence": sequence + i} for i, e in enumerate(batch.entry_ids)]
            ),
        )
        yield from sql(
            "INSERT INTO {} {}",
            sql.identifier(table),
            sql.insert(
                {
                    "sequence": sequence,
                    "last_sequence": sequence + len(batch.entry_ids) - 1,
                    "iv": batch.iv,
                    "entry_ids": b"".join(batch.entry_ids),
                    "encrypted_batch": batch.encrypted_batch,
                }
            ),
        )
        return sequence

    return sql.with_transaction(fx.gen(body))


def count_rows(sql: SqlClientService, table: str, where: Any = None) -> fx.Effect[int, Any]:
    statement = (
        sql("SELECT COUNT(*) AS n FROM {}", sql.identifier(table))
        if where is None
        else sql("SELECT COUNT(*) AS n FROM {} WHERE {}", sql.identifier(table), where)
    )
    return statement.map(lambda rows: column_int(rows[0]["n"]))


def sweep_until[A](
    read: fx.Effect[A, Any, Any], done: Callable[[A], bool]
) -> Generator[Any, Any, A]:
    """Advances the clock an hour at a time until ``done`` holds. A sweep the
    clock wakes finishes its queries in real time, so each hour polls on the
    live clock."""
    for _ in range(24):
        yield from testing.adjust("1 hour")
        for _ in range(50):
            value = yield from read
            if done(value):
                return value
            yield from testing.with_live(fx.sleep("10 millis"))
    return (yield from read)


def commit_snapshot(
    storage: Server.StorageService, public_key: str, kept: EntryId
) -> Generator[Any, Any, str]:
    """Commits a snapshot of the whole store that keeps only ``kept``, as one
    batch ending at the base."""
    compaction = compaction_of(storage)
    status = yield from compaction.status(public_key, store_id)
    begun = yield from compaction.begin(public_key, store_id, through=status.head)
    assert isinstance(begun, Server.BeginStarted), f"expected Started, got {begun}"
    yield from compaction.stage_part(
        public_key, store_id, begun.stage_id, 0, [make_batch(kept, marker=SNAPSHOT_MARKER)]
    )
    return (yield from compaction.commit(public_key, store_id, begun.stage_id, [status.head]))


def hang_on_delete(table: str, reached: fx.Deferred[None], delete_number: int = 1) -> Any:
    """Hangs the selected statement that deletes from ``table``, as a sweeper
    whose process dies mid-prune, and signals that it got there."""
    deletes = 0

    def transform(statement: Any, constructor: Any, *_: object) -> fx.Effect[Any]:
        nonlocal deletes
        text = statement.compile()[0]
        target = constructor("{}", constructor.identifier(table)).compile()[0]
        if "DELETE" not in text.upper() or target not in text:
            return fx.succeed(statement)
        deletes += 1
        if deletes != delete_number:
            return fx.succeed(statement)
        return reached.succeed(None).and_then(fx.never)

    return transform


def follow_changes(
    storage: Server.StorageService, public_key: str, start_sequence: int, last: EntryId
) -> Generator[Any, Any, fx.Fiber[Any, Any]]:
    """Follows ``changes`` from ``start_sequence`` up to the batch carrying
    ``last``, returning once the live subscription is open."""
    subscribed = yield from fx.Deferred[None].make()
    fiber = yield from (
        storage.changes(public_key, store_id, start_sequence)
        .tap(lambda _: subscribed.succeed(None))
        .take_until(lambda batch: last in batch.entry_ids)
        .run_collect()
        .fork()
    )
    # The first batch comes from the initial query, which runs after
    # subscribing.
    yield from subscribed.wait()
    return fiber


def active_id(compaction: Server.StorageCompaction, public_key: str) -> fx.Effect[str]:
    return compaction.history(public_key, store_id).map(
        lambda history: next(a for a in history if a.active).activation_id
    )


@testing.effect
def test_seeds_a_store_written_before_the_upgrade_once(connect: Connect):
    """seeds a store written before the upgrade once when two instances open it together"""

    def body():
        sql = yield from connect()
        ns = yield from make_namespace(sql)
        entries = make_ids(4)
        yield from create_legacy_tables(sql, ns.table)
        yield from legacy_write(sql, ns.table, make_batch(entries[0], entries[1]))
        legacy_last = yield from legacy_write(sql, ns.table, make_batch(entries[2]))
        # Startup creates the global tables, so only opening the store races.
        storage_a = yield from ns.storage()
        storage_b = yield from ns.storage()
        nothing = (storage_a.first_sequence or 0) - 1
        instances = [compaction_of(storage_a), compaction_of(storage_b)]
        opened = yield from fx.all(
            instances[0].status(ns.public_key, store_id),
            instances[1].status(ns.public_key, store_id),
            concurrency="unbounded",
        )
        histories = [
            (yield from instances[0].history(ns.public_key, store_id)),
            (yield from instances[1].history(ns.public_key, store_id)),
        ]
        # The seed bucket is in the hour the store was first opened.
        yield from testing.adjust("25 hours")
        lag_heads = [
            (yield from instances[0].status(ns.public_key, store_id)).lag_head,
            (yield from instances[1].status(ns.public_key, store_id)).lag_head,
        ]
        following = yield from storage_b.write(ns.public_key, store_id, [make_batch(entries[3])])

        expected = (legacy_last, nothing, nothing)
        assert [(s.head, s.base, s.lag_head) for s in opened] == [expected, expected]
        assert len(histories[0]) == 1
        assert histories[0][0].active
        assert histories[1] == histories[0]
        assert lag_heads == [legacy_last, legacy_last]
        assert [batch.sequence for batch in following] == [legacy_last + 1]

    return _run(body)


@testing.effect
def test_allocates_sequences_after_an_old_instances_writes(connect: Connect):
    """allocates sequences after an old instance's writes during a rolling deploy"""

    def body():
        sql = yield from connect()
        ns = yield from make_namespace(sql)
        storage = yield from ns.storage()
        entries = make_ids(6)

        def write(batch: EncryptedBatch) -> fx.Effect[int]:
            return storage.write(ns.public_key, store_id, [batch]).map(
                lambda stored: stored[0].sequence
            )

        batches = [
            make_batch(entries[0]),
            make_batch(entries[1], entries[2]),
            make_batch(entries[3]),
            make_batch(entries[4]),
            make_batch(entries[5]),
        ]
        sequences = [
            (yield from write(batches[0])),
            (yield from legacy_write(sql, ns.table, batches[1])),
            (yield from write(batches[2])),
            (yield from legacy_write(sql, ns.table, batches[3])),
            (yield from write(batches[4])),
        ]
        persisted = yield from storage.changes(ns.public_key, store_id, 0).take(5).run_collect()

        first = sequences[0]
        assert sequences == [first, first + 1, first + 3, first + 4, first + 5]
        assert [batch.sequence for batch in persisted] == sequences
        assert ids(persisted) == ids(batches)

    return _run(body)


@testing.effect
def test_keeps_sequences_increasing_after_every_original_is_pruned(connect: Connect):
    """keeps sequences increasing after every original is pruned"""

    def body():
        sql = yield from connect()
        ns = yield from make_namespace(sql, {"grace": "2 hours", "lag": "1 hour"})
        storage = yield from ns.storage()
        entries = make_ids(5)
        written = yield from storage.write(
            ns.public_key, store_id, [make_batch(entries[0], entries[1]), make_batch(entries[2])]
        )
        yield from commit_snapshot(storage, ns.public_key, entries[2])

        remaining = yield from sweep_until(count_rows(sql, ns.table), lambda count: count == 0)
        after_prune = yield from storage.write(ns.public_key, store_id, [make_batch(entries[3])])
        # A second instance learns the next sequence from the store row.
        other = yield from ns.storage()
        from_other = yield from other.write(ns.public_key, store_id, [make_batch(entries[4])])
        acks = yield from storage.entry_sequences(ns.public_key, store_id, entries)
        persisted = yield from storage.changes(ns.public_key, store_id, 0).take(3).run_collect()

        first = written[0].sequence
        assert remaining == 0
        assert [batch.sequence for batch in after_prune] == [first + 3]
        assert [batch.sequence for batch in from_other] == [first + 4]
        # ``T_ids`` keeps the pruned ids as tombstones.
        assert sorted(ack.sequence for ack in acks) == [first + i for i in range(5)]
        assert served(persisted) == [(first + 2, SNAPSHOT_MARKER), (first + 3, 1), (first + 4, 1)]

    return _run(body)


@testing.effect
def test_reappends_the_withdrawn_input_in_order_at_the_head(connect: Connect):
    """re-appends the withdrawn input in order at the head, before later writes"""

    def body():
        sql = yield from connect()
        ns = yield from make_namespace(sql)
        storage = yield from ns.storage()
        compaction = compaction_of(storage)

        def commit(
            batches: Sequence[EncryptedBatch], virtual_sequences: Sequence[int]
        ) -> Generator[Any, Any, str]:
            status = yield from compaction.status(ns.public_key, store_id)
            begun = yield from compaction.begin(ns.public_key, store_id, through=status.head)
            assert isinstance(begun, Server.BeginStarted), f"expected Started, got {begun}"
            yield from compaction.stage_part(ns.public_key, store_id, begun.stage_id, 0, batches)
            return (
                yield from compaction.commit(
                    ns.public_key, store_id, begun.stage_id, virtual_sequences
                )
            )

        # More than one 500-row page, each kept by g+1 as its own snapshot batch.
        entries = make_ids(501)
        originals = [make_batch(e) for e in entries]
        written = yield from storage.write(ns.public_key, store_id, originals)
        yield from commit(
            [make_batch(e, marker=SNAPSHOT_MARKER) for e in entries],
            [batch.sequence for batch in written],
        )
        t1, t2, after = make_ids(3)
        [tail] = yield from storage.write(ns.public_key, store_id, [make_batch(t1, t2)])
        head = tail.sequence + 1
        yield from commit([make_batch(t2, marker=SNAPSHOT_MARKER + 1)], [head])
        active = yield from active_id(compaction, ns.public_key)

        # Withdraws g+2, whose input is g+1's batches, then the original [t1, t2].
        yield from compaction.rollback(ns.public_key, store_id, active)
        [later] = yield from storage.write(ns.public_key, store_id, [make_batch(after)])
        reappended = yield from (
            storage.changes(ns.public_key, store_id, head + 1)
            .take_until(lambda batch: batch.sequence == later.sequence)
            .run_collect()
        )

        assert served(reappended) == [
            *[(head + 1 + i, SNAPSHOT_MARKER) for i in range(len(entries))],
            (head + len(entries) + 1, 2),
            (head + len(entries) + 3, 1),
        ]
        assert ids(reappended) == ids([*originals, tail, make_batch(after)])

    return _run(body)


@testing.effect
def test_publishes_nothing_from_a_write_whose_outer_transaction_aborts(connect: Connect):
    """publishes nothing from a write whose outer transaction aborts"""

    def body():
        sql = yield from connect()
        ns = yield from make_namespace(sql)
        storage = yield from ns.storage()
        first, reverted, after = make_ids(3)
        [written] = yield from storage.write(ns.public_key, store_id, [make_batch(first)])
        live = yield from follow_changes(storage, ns.public_key, written.sequence, after)

        aborted = yield from sql.with_transaction(
            storage.write(ns.public_key, store_id, [make_batch(reverted)]).and_then(
                fx.fail("abort")
            )
        ).exit()
        following = yield from storage.write(ns.public_key, store_id, [make_batch(after)])
        published = yield from live.join()

        assert isinstance(aborted, fx.Failure)
        assert [batch.sequence for batch in following] == [written.sequence + 1]
        assert ids(published) == ids([make_batch(first), make_batch(after)])
        assert [batch.sequence for batch in published] == [written.sequence, written.sequence + 1]

    return _run(body)


@testing.effect
def test_publishes_nothing_from_a_rollback_whose_outer_transaction_aborts(connect: Connect):
    """publishes nothing from a rollback whose outer transaction aborts"""

    def body():
        sql = yield from connect()
        ns = yield from make_namespace(sql)
        storage = yield from ns.storage()
        compaction = compaction_of(storage)
        first, kept, after = make_ids(3)
        yield from storage.write(ns.public_key, store_id, [make_batch(first), make_batch(kept)])
        yield from commit_snapshot(storage, ns.public_key, kept)
        head = (yield from compaction.status(ns.public_key, store_id)).head
        snapshot = yield from active_id(compaction, ns.public_key)
        live = yield from follow_changes(storage, ns.public_key, head, after)

        aborted = yield from sql.with_transaction(
            compaction.rollback(ns.public_key, store_id, snapshot).and_then(fx.fail("abort"))
        ).exit()
        following = yield from storage.write(ns.public_key, store_id, [make_batch(after)])
        published = yield from live.join()
        history = yield from compaction.history(ns.public_key, store_id)

        assert isinstance(aborted, fx.Failure)
        assert [batch.sequence for batch in following] == [head + 1]
        assert served(published) == [(head, SNAPSHOT_MARKER), (head + 1, 1)]
        assert next(a for a in history if a.activation_id == snapshot).active

    return _run(body)


@testing.effect
def test_resumes_a_partially_pruned_snapshot_after_its_sweeper_dies(connect: Connect):
    """resumes a partially pruned snapshot after its sweeper dies without deleting originals"""

    def body():
        sql = yield from connect()
        ns = yield from make_namespace(sql, {"grace": "2 hours", "lag": "1 hour"})
        snapshot_table = f"{ns.table}_snapshot"
        reached = yield from fx.Deferred[None].make()
        # Registered first, so a failing test still stops the sweeper and
        # releases the transaction its hung DELETE holds.
        scope_a = yield from fx.scope.acquire_release(
            fx.scope.make(), lambda scope, _: scope.close(fx.exit.succeed(None))
        )
        storage_a = (
            yield from ns.storage()
            .pipe(
                fx.provide_service(CurrentTransformer, hang_on_delete(snapshot_table, reached, 2))
            )
            .pipe(fx.scope.provide(scope_a))
        )
        compaction_a = compaction_of(storage_a)
        # More than two 200-row chunks, with one entry per snapshot row.
        batches = [make_batch(e) for e in make_ids(401)]
        written = yield from storage_a.write(ns.public_key, store_id, batches)
        begun = yield from compaction_a.begin(
            ns.public_key, store_id, through=written[400].sequence
        )
        assert isinstance(begun, Server.BeginStarted), f"expected Started, got {begun}"
        yield from compaction_a.stage_part(ns.public_key, store_id, begun.stage_id, 0, batches)
        committed = yield from compaction_a.commit(
            ns.public_key, store_id, begun.stage_id, [batch.sequence for batch in written]
        )
        assert committed == "Committed"
        snapshot = yield from active_id(compaction_a, ns.public_key)
        yield from compaction_a.rollback(ns.public_key, store_id, snapshot)

        # Poll only the signal while A holds a transaction (SQLite cannot
        # query through that lock). sweep_until bounds the missing second
        # delete.
        interrupted = yield from sweep_until(reached.is_done(), lambda done: done)
        yield from scope_a.close(fx.exit.succeed(None))
        assert interrupted, "snapshot pruning never reached a second DELETE"

        storage_b = yield from ns.storage()
        compaction_b = compaction_of(storage_b)
        history = yield from compaction_b.history(ns.public_key, store_id)
        withdrawn = next(a for a in history if a.activation_id == snapshot)
        remaining_rows = count_rows(sql, snapshot_table, sql("batch_set = {}", begun.stage_id))
        before_b = yield from remaining_rows
        assert not withdrawn.restorable
        assert 0 < before_b < len(batches)
        # The originals, and their copies the rollback re-appended.
        assert (yield from count_rows(sql, ns.table)) == 2 * len(batches)

        assert (yield from sweep_until(remaining_rows, lambda count: count == 0)) == 0
        assert (yield from count_rows(sql, ns.table)) == 2 * len(batches)
        persisted = yield from (
            storage_b.changes(ns.public_key, store_id, storage_b.first_sequence or 0)
            .take(len(batches))
            .run_collect()
        )
        assert ids(persisted) == ids(batches)
        assert served(persisted) == served(written)

    return _run(body)


@testing.effect
def test_finishes_the_prune_of_a_sweeper_that_died_in_the_middle_of_it(connect: Connect):
    """finishes the prune of a sweeper that died in the middle of it"""

    def body():
        sql = yield from connect()
        ns = yield from make_namespace(sql, {"grace": "2 hours", "lag": "1 hour"})
        reached = yield from fx.Deferred[None].make()
        scope_a = yield from fx.scope.acquire_release(
            fx.scope.make(), lambda scope, _: scope.close(fx.exit.succeed(None))
        )
        storage_a = (
            yield from ns.storage()
            .pipe(fx.provide_service(CurrentTransformer, hang_on_delete(ns.table, reached)))
            .pipe(fx.scope.provide(scope_a))
        )
        entries = make_ids(3)
        written = yield from storage_a.write(
            ns.public_key, store_id, [make_batch(entries[0], entries[1]), make_batch(entries[2])]
        )
        yield from commit_snapshot(storage_a, ns.public_key, entries[2])

        died = yield from sweep_until(reached.is_done(), lambda done: done)
        yield from scope_a.close(fx.exit.succeed(None))
        storage_b = yield from ns.storage()
        [originals, *_] = yield from compaction_of(storage_b).history(ns.public_key, store_id)
        before_b = yield from count_rows(sql, ns.table)
        after_b = yield from sweep_until(count_rows(sql, ns.table), lambda count: count == 0)
        persisted = yield from storage_b.changes(ns.public_key, store_id, 0).take(1).run_collect()

        assert died
        assert not originals.restorable
        assert before_b == 2
        assert after_b == 0
        assert served(persisted) == [(written[1].sequence, SNAPSHOT_MARKER)]

    return _run(body)
