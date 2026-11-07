"""Ports of the PostgreSQL-only titles of Effect's ``sql-pg`` tests for the SQL
event log server storages, on the session's throwaway server
(``_postgres.pg_server``; skipped without one): the ``SqlEventLogServerUnencrypted
commit visibility`` titles. The shared suites run on PostgreSQL through the
``storage`` and ``connect`` fixtures of their own modules, and
``SqlEventLogServerEncryptedStorageTest`` in
``test_sql_event_log_server_encrypted_storage.py``.

Each test's docstring is the Effect test title.
"""

import itertools
from collections.abc import Callable, Generator
from typing import Any

import pytest

pytest.importorskip("psycopg")

import pyfect as fx
from pyfect import testing
from pyfect.eventlog.event_journal import StoreId
from pyfect.eventlog.event_log_encryption import layer_subtle
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import pg
from pyfect.sql.client import SqlClientService

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


@testing.live(timeout="30 seconds")
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


@testing.live(timeout="30 seconds")
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
