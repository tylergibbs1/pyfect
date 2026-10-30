"""Ports of the PostgreSQL-only titles of Effect's ``sql-pg`` tests for the SQL
event log server storages, on the session's throwaway server
(``_postgres.pg_server``; skipped without one): the ``SqlEventLogServerUnencrypted
commit visibility`` titles and the ``SqlEventLogServerEncryptedStorageTest``
suite. The shared suites run on PostgreSQL through the ``storage`` and
``connect`` fixtures of their own modules.

Each test's docstring is the Effect test title.
"""

import itertools
import os
import time
import uuid
from collections.abc import Callable, Generator, Sequence
from typing import Any

import pytest

pytest.importorskip("psycopg")

import pyfect as fx
from pyfect import testing
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog import sql_event_log_server_encrypted as SqlE
from pyfect.eventlog.event_journal import EntryId, StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, layer_subtle
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import pg
from pyfect.sql.client import SqlClient, SqlClientService

from ._postgres import PgServer
from .test_sql_event_log_server_unencrypted import (
    assert_drained,
    make_entry,
    make_options,
    make_storage,
    make_store_id,
    open_changes,
    pausing_client,
)

_namespaces = itertools.count()
store_id = StoreId("store-a")


def _client(server: PgServer) -> fx.Effect[SqlClientService, Any, Any]:
    return pg.make(pg.PgPoolConfig(url=server.url))


def _run(body: Callable[[], Generator[Any, Any, Any]]) -> fx.Effect[Any, Any, Any]:
    return fx.gen(body).pipe(fx.provide(fx.layer.merge(reactivity_layer, layer_subtle)))


# --- SqlEventLogServerUnencrypted commit visibility ----------------------------------


@testing.live(timeout=30)
def test_streams_concurrent_commits_in_sequence_order(pg_server: PgServer):
    """SqlEventLogServerUnencrypted commit visibility / streams concurrent commits in sequence
    order even when the first SQL return is delayed"""

    def body():
        sql = yield from _client(pg_server)
        committed = yield from fx.Deferred[None].make()
        publish = yield from fx.Deferred[None].make()
        # Pause after SQL commits and releases its connection, before storage publishes.
        delayed, pause, entered = pausing_client(sql, committed, publish)
        storage = yield from make_storage(delayed, **make_options("concurrent_publication"))
        store = make_store_id("concurrent_publication")
        backlog, first_entry, second_entry = (
            make_entry("Ada"),
            make_entry("Grace"),
            make_entry("Margaret"),
        )
        yield from storage.write(store, [backlog])
        changes = yield from open_changes(storage, store)
        assert (yield from changes.take()).remote_sequence == 1

        pause[0] = True
        first_writer = yield from storage.write(store, [first_entry]).fork()
        yield from committed.wait()
        # Run writer two until it enters SQL or waits for the storage permit.
        entered.clear()
        second_writer = yield from (
            storage.write(store, [second_entry])
            .pipe(fx.provide_service(fx.PreventSchedulerYield, True))
            .fork(start_immediately=True)
        )
        if entered:
            # Without serialization, force writer two to publish first.
            yield from second_writer.join().ensuring(publish.succeed(None))
        else:
            # Release writer one so writer two can acquire the permit.
            yield from publish.succeed(None)
            yield from second_writer.join()
        yield from first_writer.join()

        rows = yield from changes.take_n(2)
        yield from assert_drained(changes)
        persisted = yield from (yield from open_changes(storage, store)).take_all()
        assert [r.remote_sequence for r in persisted] == [1, 2, 3]
        assert [r.entry.id_string for r in persisted] == [
            backlog.id_string,
            first_entry.id_string,
            second_entry.id_string,
        ]
        assert [r.remote_sequence for r in rows] == [2, 3]
        assert [r.entry.id_string for r in rows] == [first_entry.id_string, second_entry.id_string]

    yield from _run(body)


@testing.live(timeout=30)
def test_streams_a_write_committed_after_the_startup_backlog_read_exactly_once(
    pg_server: PgServer,
):
    """SqlEventLogServerUnencrypted commit visibility / streams a write committed after the
    startup backlog read exactly once"""

    def body():
        sql = yield from _client(pg_server)
        storage = yield from make_storage(sql, **make_options("commit_visibility"))
        store = make_store_id("commit_visibility")
        backlog_entry, raced_entry, live_entry = (
            make_entry("Ada"),
            make_entry("Grace"),
            make_entry("Margaret"),
        )
        yield from storage.write(store, [backlog_entry])
        written = yield from fx.Deferred[None].make()
        commit = yield from fx.Deferred[None].make()

        def transaction():
            yield from storage.write(store, [raced_entry])
            yield from written.succeed(None)
            yield from commit.wait()

        writer = yield from storage.with_transaction(fx.gen(transaction)).fork()
        yield from written.wait()
        # Read the backlog before commit to establish the subscription and snapshot.
        changes = yield from open_changes(storage, store)
        first = yield from changes.take()
        assert first.entry.id_string == backlog_entry.id_string
        yield from commit.succeed(None)
        yield from writer.join()
        # A later write exposes a missed row as [1, 3] instead of a timeout.
        yield from storage.write(store, [live_entry])
        second = yield from changes.take()
        assert [first.remote_sequence, second.remote_sequence] == [1, 2]
        assert second.entry.id_string == raced_entry.id_string
        third = yield from changes.take()
        assert third.remote_sequence == 3
        assert third.entry.id_string == live_entry.id_string
        yield from assert_drained(changes)

    yield from _run(body)


# --- SqlEventLogServerEncrypted storage (pg) -----------------------------------------


def make_batch(*entry_ids: EntryId) -> EncryptedBatch:
    return EncryptedBatch(
        entry_ids=entry_ids, iv=bytes(12), encrypted_batch=bytes([len(entry_ids) % 256])
    )


def ids(batches: Sequence[Any]) -> list[list[bytes]]:
    return [list(batch.entry_ids) for batch in batches]


def _encrypted_options(prefix: str) -> dict[str, str]:
    # Own tables, so other suites sharing the database don't race on creating them.
    namespace = f"{prefix}_{os.getpid()}_{next(_namespaces)}"
    return {
        "entry_table_prefix": f"{namespace}_events",
        "remote_id_table": f"{namespace}_remote_id",
    }


def _encrypted_storage(
    sql: SqlClientService, options: dict[str, str]
) -> fx.Effect[Server.StorageService, Any, Any]:
    return SqlE.make_storage(**options).pipe(fx.provide_service(SqlClient, sql))


def _await_lock_wait(sql: SqlClientService) -> Generator[Any, Any]:
    """Waits until another connection is blocked on a lock held by an open
    transaction."""
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        rows = yield from sql(
            "SELECT COUNT(*)::int AS n FROM pg_stat_activity "
            "WHERE wait_event_type = 'Lock' AND datname = current_database()"
        )
        if int(rows[0]["n"]) > 0:  # type: ignore[arg-type]
            return
        yield from fx.sleep(0.01)
    yield from fx.die(RuntimeError("the competing writer never waited on a lock"))


def competing_writes(
    sql: SqlClientService, first: EncryptedBatch, second: EncryptedBatch
) -> Generator[Any, Any, tuple[list[Any], list[Any]]]:
    """Writer A holds its write open in a transaction until writer B, a
    separate storage standing in for another server process, is blocked on
    it. B retries once if it loses, as a client retries a failed write."""
    public_key = str(uuid.uuid4())
    options = _encrypted_options("competing")
    storage_a = yield from _encrypted_storage(sql, options)
    storage_b = yield from _encrypted_storage(sql, options)
    # Create the scope's tables first, so only the writes compete.
    yield from storage_a.write(public_key, store_id, [make_batch(J.make_entry_id_unsafe())])
    yield from storage_b.changes(public_key, store_id, 0).take(1).run_drain()

    written = yield from fx.Deferred[None].make()
    commit = yield from fx.Deferred[None].make()

    def transaction():
        yield from storage_a.write(public_key, store_id, [first])
        yield from written.succeed(None)
        yield from commit.wait()

    writer_a = yield from sql.with_transaction(fx.gen(transaction)).fork()
    yield from written.wait()
    writer_b = yield from storage_b.write(public_key, store_id, [second]).fork()
    yield from _await_lock_wait(sql)
    yield from commit.succeed(None)
    yield from writer_a.join()
    attempt = yield from writer_b.await_exit()
    if isinstance(attempt, fx.Success):
        stored = attempt.value
    else:
        stored = yield from storage_b.write(public_key, store_id, [second])
    persisted = yield from storage_a.changes(public_key, store_id, 0).take(3).run_collect()
    return stored, persisted[1:]


@testing.live(timeout=60)
def test_stores_a_batch_with_more_ids_than_one_statement_can_bind(pg_server: PgServer):
    """SqlEventLogServerEncrypted storage (pg) / stores a batch with more ids than one
    statement can bind"""

    def body():
        sql = yield from _client(pg_server)
        public_key = str(uuid.uuid4())
        storage = yield from _encrypted_storage(sql, _encrypted_options("oversized"))
        # Above the PostgreSQL client's bind parameter limit of 32767.
        batch = make_batch(*(J.make_entry_id_unsafe() for _ in range(65_536)))
        stored = yield from storage.write(public_key, store_id, [batch])
        retried = yield from storage.write(public_key, store_id, [batch])
        persisted = yield from storage.changes(public_key, store_id, 0).take(1).run_collect()
        assert ids(stored) == ids([batch])
        assert retried == []
        assert ids(persisted) == ids([batch])
        assert persisted[0].sequence == stored[0].sequence

    yield from _run(body)


@testing.live(timeout=30)
def test_stores_a_competing_write_after_its_writer_retries(pg_server: PgServer):
    """SqlEventLogServerEncrypted storage (pg) / stores a competing write after its writer
    retries"""

    def body():
        sql = yield from _client(pg_server)
        a, b = J.make_entry_id_unsafe(), J.make_entry_id_unsafe()
        stored, persisted = yield from competing_writes(sql, make_batch(a), make_batch(b))
        assert ids(stored) == ids([make_batch(b)])
        assert ids(persisted) == ids([make_batch(a), make_batch(b)])
        assert [p.sequence for p in persisted] == [persisted[0].sequence, persisted[0].sequence + 1]

    yield from _run(body)


@testing.live(timeout=30)
def test_stores_a_competing_partly_known_batch_whole_once(pg_server: PgServer):
    """SqlEventLogServerEncrypted storage (pg) / stores a competing partly known batch whole,
    once"""

    def body():
        sql = yield from _client(pg_server)
        a, b = J.make_entry_id_unsafe(), J.make_entry_id_unsafe()
        stored, persisted = yield from competing_writes(sql, make_batch(a), make_batch(b, a))
        assert ids(stored) == ids([make_batch(b, a)])
        assert ids(persisted) == ids([make_batch(a), make_batch(b, a)])
        assert [p.sequence for p in persisted] == [persisted[0].sequence, persisted[0].sequence + 1]

    yield from _run(body)
