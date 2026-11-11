"""Ports of Effect's ``sql-pg/test/SqlEventJournal.integration.test.ts``
and the shared ``SqlEventJournalSharedTest.ts`` suite (``pg``) for
``pyfect.eventlog.sql_event_journal`` on the throwaway PostgreSQL server
(``_postgres.pg_server``; skipped without one).

Each test's docstring is the Effect test title. The server is shared by
the session, so each test uses its own tables, as Effect's do.
"""

import itertools
import os
import time
from collections.abc import Callable, Generator
from typing import Any

import pytest

pytest.importorskip("psycopg")

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.deferred import Deferred
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import sql_event_journal as SqlJ
from pyfect.eventlog.event_journal import Entry, RemoteEntry, StoreId
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql import pg
from pyfect.sql.client import SqlClient, SqlClientService

from ._postgres import PgServer

_namespaces = itertools.count()


def _client(server: PgServer, **options: Any):
    return pg.make(pg.PgPoolConfig(url=server.url, **options))


def _open(client: SqlClientService, **options: Any) -> fx.Effect[J.EventJournalService, Any]:
    return SqlJ.make(**options).pipe(fx.provide_service(SqlClient, client))


def _tables(prefix: str) -> dict[str, str]:
    # Unique per run of the session's server.
    n = f"{prefix}_{os.getpid()}_{next(_namespaces)}"
    return {"entry_table": f"{n}_entries", "remotes_table": f"{n}_remotes"}


def _run(body: Callable[[], Generator[Any, Any, Any]]) -> fx.Effect[Any, Any, Any]:
    return fx.gen(body).pipe(fx.provide(reactivity_layer))


def _local(journal: J.EventJournalService, primary_key: str, **options: Any):
    return journal.write(
        event="Repro", primary_key=primary_key, payload=b"", effect=fx.succeed, **options
    )


def _remote_entry(primary_key: str, msecs: int | None = None) -> RemoteEntry:
    return RemoteEntry(
        remote_sequence=0,
        entry=S.new(Entry, disable_checks=True)(
            id=J.make_entry_id_unsafe(msecs=msecs),
            event="Repro",
            primary_key=primary_key,
            payload=b"",
        ),
    )


def _backend_pid(client: SqlClientService) -> fx.Effect[int, Any]:
    return client("SELECT pg_backend_pid() AS pid").map(lambda rows: int(rows[0]["pid"]))  # type: ignore[arg-type]


def _wait_until_blocked_by(
    client: SqlClientService, holder: int, count: int, fiber: fx.Fiber[Any, Any] | None = None
) -> Generator[fx.Effect[Any, Any, Any], Any]:
    """Fails unless, within ten seconds, ``count`` backends are blocked by
    ``holder`` directly or behind one that is, or ``fiber`` succeeds."""
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        exit_ = fiber.poll_unsafe() if fiber is not None else None
        if exit_ is not None:
            yield from fx.from_exit(exit_)
            return
        rows = yield from client(
            "SELECT count(*)::int4 AS blocked FROM pg_stat_activity waiter "
            "WHERE {} = ANY(pg_blocking_pids(waiter.pid)) OR EXISTS ("
            "SELECT 1 FROM pg_stat_activity other "
            "WHERE other.pid = ANY(pg_blocking_pids(waiter.pid)) "
            "AND {} = ANY(pg_blocking_pids(other.pid)))",
            holder,
            holder,
        )
        if int(rows[0]["blocked"]) >= count:  # type: ignore[arg-type]
            return None
        yield from fx.sleep("20 millis")
    yield from fx.die(
        RuntimeError(f"Expected {count} backends blocked by {holder} within 10 seconds")
    )


@testing.live
def test_round_trips_a_local_entry(pg_server: PgServer):
    """SqlEventJournal / round-trips a local entry"""

    def body():
        journal = yield from _open((yield from _client(pg_server)), **_tables("local"))
        written = yield from journal.write(
            event="UserCreated", primary_key="user-1", payload=b"\1", effect=fx.succeed
        )
        entries = yield from journal.entries
        assert len(entries) == 1
        assert entries[0].id_string == written.id_string
        assert entries[0].event == "UserCreated"
        assert entries[0].primary_key == "user-1"
        assert entries[0].payload == b"\1"
        assert entries[0].created_at_millis == written.created_at_millis

    yield from _run(body)


@testing.live
def test_round_trips_a_remote_entry_and_advances_its_sequence(pg_server: PgServer):
    """SqlEventJournal / round-trips a remote entry and advances its sequence"""

    def body():
        journal = yield from _open((yield from _client(pg_server)), **_tables("remote"))
        remote_id = J.make_remote_id_unsafe()
        remote = S.new(Entry, disable_checks=True)(
            id=J.make_entry_id_unsafe(msecs=1_700_000_000_000),
            event="UserCreated",
            primary_key="user-2",
            payload=b"\2",
        )
        assert (yield from journal.next_remote_sequence(remote_id)) == 0
        yield from journal.write_from_remote(
            remote_id=remote_id,
            entries=[RemoteEntry(remote_sequence=0, entry=remote)],
            effect=lambda _: fx.void,
        )
        entries = yield from journal.entries
        assert len(entries) == 1
        assert entries[0].id_string == remote.id_string
        assert entries[0].event == "UserCreated"
        assert entries[0].primary_key == "user-2"
        assert entries[0].payload == b"\2"
        assert entries[0].created_at_millis == 1_700_000_000_000
        assert (yield from journal.next_remote_sequence(remote_id)) == 1

    yield from _run(body)


@testing.live
def test_reopens_a_migrated_journal_read_only(pg_server: PgServer):
    """SqlEventJournal / reopens a migrated journal read-only"""

    def body():
        client = yield from _client(pg_server)
        readonly = yield from _client(
            pg_server, startup_parameters={"default_transaction_read_only": "on"}
        )
        options = _tables("readonly")
        journal = yield from _open(client, **options)
        written = yield from _local(journal, "a")
        reopened = yield from _open(readonly, **options)
        assert [e.id_string for e in (yield from reopened.entries)] == [written.id_string]

    yield from _run(body)


@testing.live
def test_writes_and_finds_conflicts_for_primary_keys_beyond_the_index_tuple_limit(
    pg_server: PgServer,
):
    """SqlEventJournal / writes and finds conflicts for primary keys beyond the index tuple limit"""

    def body():
        import base64

        journal = yield from _open((yield from _client(pg_server)), **_tables("long_key"))
        # Random text barely compresses, so the key stays above the ~2.7 KB
        # B-tree tuple limit.
        primary_key = base64.b64encode(os.urandom(6000)).decode()
        written = yield from _local(journal, primary_key)
        conflicts: list[str] = []
        yield from journal.write_from_remote(
            remote_id=J.make_remote_id_unsafe(),
            entries=[_remote_entry(primary_key, written.created_at_millis - 1)],
            effect=lambda batch: fx.sync(
                lambda: conflicts.extend(c.id_string for c in batch[0].conflicts)
            ),
        )
        assert conflicts == [written.id_string]

    yield from _run(body)


@testing.live
def test_concurrent_opens_migrate_a_legacy_database_once(pg_server: PgServer):
    """SqlEventJournal / concurrent opens migrate a legacy database once"""

    def body():
        sql = yield from _client(pg_server)
        options = _tables("concurrent_open")
        entries_table = sql.identifier(options["entry_table"])
        remotes_table = sql.identifier(options["remotes_table"])
        # The entry table as created by the first release of SqlEventJournal.
        yield from sql(
            "CREATE TABLE {} (id BYTEA PRIMARY KEY, event TEXT NOT NULL, "
            "primary_key TEXT NOT NULL, payload BYTEA NOT NULL, timestamp BIGINT NOT NULL)",
            entries_table,
        )
        remote_a = J.make_remote_id_unsafe()
        remote_b = J.make_remote_id_unsafe()
        entries = [_remote_entry(key).entry for key in ("pending", "fromA", "fromB")]
        yield from sql(
            "INSERT INTO {} {}",
            entries_table,
            sql.insert(
                [
                    {
                        "id": e.id,
                        "event": e.event,
                        "primary_key": e.primary_key,
                        "payload": e.payload,
                        "timestamp": e.created_at_millis,
                    }
                    for e in entries
                ]
            ),
        )
        yield from sql(
            "CREATE TABLE {} (remote_id BYTEA NOT NULL, entry_id BYTEA NOT NULL, "
            "sequence INT NOT NULL, PRIMARY KEY (remote_id, entry_id))",
            remotes_table,
        )
        yield from sql(
            "INSERT INTO {} {}",
            remotes_table,
            sql.insert(
                [
                    {"remote_id": remote_a, "entry_id": entries[1].id, "sequence": 1},
                    {"remote_id": remote_b, "entry_id": entries[2].id, "sequence": 7},
                ]
            ),
        )
        cursors = sql.identifier(f"{options['remotes_table']}_cursors")
        yield from sql(
            "CREATE TABLE {} (remote_id BYTEA PRIMARY KEY, next_sequence INT NOT NULL)", cursors
        )
        yield from sql(
            "INSERT INTO {} {}", cursors, sql.insert({"remote_id": remote_a, "next_sequence": 9})
        )
        warmed = Deferred[None]()
        start_waiting = Deferred[None]()
        migrated = Deferred[int]()
        release = Deferred[None]()

        def waiting_body():
            # Pin this backend and cache both old names before the other
            # opener changes them.
            [before] = yield from sql(
                "SELECT to_regclass({})::text AS legacy, to_regclass({})::text AS sources",
                options["remotes_table"],
                f"{options['entry_table']}_sources",
            )
            assert before["legacy"] == options["remotes_table"]
            assert before["sources"] is None
            yield from warmed.succeed(None)
            yield from start_waiting.wait()
            return (yield from _open(sql, **options))

        waiting = yield from sql.with_transaction(fx.gen(waiting_body)).fork()
        yield from warmed.wait()
        first = yield from sql.with_transaction(
            _open(sql, **options)
            .tap(lambda _: _backend_pid(sql).flat_map(migrated.succeed))
            .tap(lambda _: release.wait())
        ).fork()
        holder = yield from migrated.wait()
        yield from start_waiting.succeed(None)
        yield from _wait_until_blocked_by(sql, holder, 1, waiting)
        yield from release.succeed(None)
        journals: list[J.EventJournalService] = [
            (yield from first.join()),
            (yield from waiting.join()),
        ]
        for journal in journals:
            assert (yield from journal.next_remote_sequence(remote_a)) == 9
            assert (yield from journal.next_remote_sequence(remote_b)) == 8
            assert sorted(e.id_string for e in (yield from journal.entries)) == sorted(
                e.id_string for e in entries
            )

        def upload(remote_id: J.RemoteId):
            return journals[0].with_remote_uncommitted(
                remote_id, lambda es: fx.succeed(sorted(e.primary_key for e in es))
            )

        assert (yield from upload(remote_a)) == fx.Some(["fromB", "pending"])
        assert (yield from upload(remote_b)) == fx.Some(["fromA", "pending"])
        [row] = yield from sql("SELECT to_regclass({})::text AS legacy", options["remotes_table"])
        assert row["legacy"] is None

    yield from _run(body)


@testing.live
def test_with_remote_uncommitted_uploads_entries_whose_commits_finish_out_of_order(
    pg_server: PgServer,
):
    """SqlEventJournal / withRemoteUncommited uploads entries whose commits finish out of order"""

    def body():
        sql = yield from _client(pg_server)
        journal = yield from _open(sql, **_tables("ordering"))
        remote_id = J.make_remote_id_unsafe()
        upload = journal.with_remote_uncommitted(
            remote_id, lambda es: fx.succeed([e.id_string for e in es])
        )
        written = Deferred[int]()
        release = Deferred[None]()
        # The first write stays uncommitted until released.
        first = yield from sql.with_transaction(
            _local(journal, "first")
            .tap(lambda _: _backend_pid(sql).flat_map(written.succeed))
            .tap(lambda _: release.wait())
        ).fork()
        holder = yield from written.wait()
        second = yield from _local(journal, "second").fork()
        yield from _wait_until_blocked_by(sql, holder, 1, second)
        before_commit = yield from upload
        yield from release.succeed(None)
        ids = [(yield from first.join()).id_string, (yield from second.join()).id_string]
        after_commit = yield from upload
        uploaded = [
            *(before_commit.value if before_commit is not None else []),
            *(after_commit.value if after_commit is not None else []),
        ]
        assert sorted(uploaded) == sorted(ids)

    yield from _run(body)


@testing.live
def test_an_outer_transaction_can_import_an_entry_that_another_remote_is_importing(
    pg_server: PgServer,
):
    """SqlEventJournal / an outer transaction can import an entry that another remote is importing"""  # noqa: E501

    def body():
        sql = yield from _client(pg_server)
        journal = yield from _open(sql, **_tables("overlapping"))
        b = _remote_entry("b")

        def import_entry(remote_id: J.RemoteId, item: RemoteEntry):
            return journal.write_from_remote(
                remote_id=remote_id, entries=[item], effect=lambda _: fx.void
            )

        imported = Deferred[int]()
        proceed = Deferred[None]()
        remote_id = J.make_remote_id_unsafe()
        outer = yield from sql.with_transaction(
            import_entry(remote_id, _remote_entry("a"))
            .and_then(_backend_pid(sql))
            .flat_map(imported.succeed)
            .and_then(proceed.wait())
            .and_then(import_entry(remote_id, b))
        ).fork()
        holder = yield from imported.wait()
        other = yield from import_entry(J.make_remote_id_unsafe(), b).fork()
        yield from _wait_until_blocked_by(sql, holder, 1, other)
        yield from proceed.succeed(None)
        yield from outer.join()
        yield from other.join()

    yield from _run(body)


@testing.live
def test_a_local_write_and_a_remote_import_updating_the_same_projection_row_both_commit(
    pg_server: PgServer,
):
    """SqlEventJournal / a local write and a remote import updating the same projection row both commit"""  # noqa: E501

    def body():
        sql = yield from _client(pg_server)
        options = _tables("projection")
        journal = yield from _open(sql, **options)
        # EventLog runs handlers inside the journal lock's transaction.
        with_lock = journal.with_lock(StoreId("store"))
        table = sql.identifier(f"{options['entry_table']}_callback_projection")
        yield from sql("CREATE TABLE {} (id TEXT PRIMARY KEY, count INT NOT NULL)", table)
        yield from sql("INSERT INTO {} (id, count) VALUES ('p', 0)", table)
        project = sql("UPDATE {} SET count = count + 1 WHERE id = 'p'", table).or_die()
        updated = Deferred[int]()
        proceed = Deferred[None]()
        # The local handler keeps the projection row locked until released.
        local = yield from with_lock(
            journal.write(
                event="Repro",
                primary_key="local",
                payload=b"",
                effect=lambda _: (
                    project.and_then(_backend_pid(sql))
                    .flat_map(updated.succeed)
                    .and_then(proceed.wait())
                ),
            )
        ).fork()
        holder = yield from updated.wait()
        remote = yield from with_lock(
            journal.write_from_remote(
                remote_id=J.make_remote_id_unsafe(),
                entries=[_remote_entry("imported")],
                effect=lambda _: project.as_void(),
            )
        ).fork()
        yield from _wait_until_blocked_by(sql, holder, 1, remote)
        yield from proceed.succeed(None)
        yield from local.join()
        yield from remote.join()
        [row] = yield from sql("SELECT count FROM {} WHERE id = 'p'", table)
        assert row["count"] == 2

    yield from _run(body)


@testing.live
def test_a_write_without_an_outer_transaction_rolls_back_its_callbacks_sql(pg_server: PgServer):
    """SqlEventJournal / a write without an outer transaction rolls back its callback's SQL when the callback fails"""  # noqa: E501

    def body():
        sql = yield from _client(pg_server)
        options = _tables("rollback")
        journal = yield from _open(sql, **options)
        table = sql.identifier(f"{options['entry_table']}_rollback_projection")
        yield from sql("CREATE TABLE {} (id TEXT PRIMARY KEY)", table)
        yield from journal.write(
            event="Repro",
            primary_key="failed",
            payload=b"",
            effect=lambda _: sql("INSERT INTO {} (id) VALUES ('failed')", table).and_then(
                fx.fail("failed")
            ),
        ).flip()
        assert (yield from sql("SELECT id FROM {}", table)) == []

    yield from _run(body)


# --- SqlEventJournalSharedTest.ts (pg) ------------------------------------------------


def _lock_waits(sql: SqlClientService) -> fx.Effect[int, Any]:
    # Connections waiting on a lock of any kind.
    return sql(
        "SELECT COUNT(*)::int AS n FROM pg_stat_activity "
        "WHERE wait_event_type = 'Lock' AND datname = current_database()"
    ).map(lambda rows: int(rows[0]["n"]))  # type: ignore[arg-type]


@testing.live(timeout="1 minute")
def test_an_import_waits_for_a_local_write_in_flight_on_another_connection(pg_server: PgServer):
    """SqlEventJournal shared by processes (pg) / an import waits for a local write in flight on another connection"""  # noqa: E501

    # Process B's local write stays open in its callback while process A
    # imports a newer entry. If A commits first, B then commits an entry that
    # sorts before one committed ahead of it, and B's callback never saw it.
    def body():
        sql = yield from _client(pg_server)
        options = _tables("shared")
        journal_a = yield from _open(sql, **options)
        journal_b = yield from _open(sql, **options)
        started = Deferred[Entry]()
        release = Deferred[None]()
        write_b = yield from journal_b.write_many(
            [J.EntryInput("Repro", "key", b"")],
            lambda written: started.succeed(written[0]).and_then(release.wait()),
        ).fork()
        local = yield from started.wait()
        newer = S.new(Entry, disable_checks=True)(
            id=J.make_entry_id_unsafe(msecs=J.entry_id_millis(local.id) + 60_000),
            event="Repro",
            primary_key="key",
            payload=b"",
        )
        import_a = yield from journal_a.write_from_remote(
            remote_id=J.make_remote_id_unsafe(),
            entries=[RemoteEntry(remote_sequence=0, entry=newer)],
            effect=lambda _: fx.void,
        ).fork()
        waited = False
        for _ in range(500):
            if import_a.poll_unsafe() is not None:
                break
            waited = (yield from _lock_waits(sql)) > 0
            if waited:
                break
            yield from fx.sleep("10 millis")
        yield from release.succeed(None)
        yield from write_b.join()
        yield from import_a.join()
        assert waited, "the import committed while an older local write was in flight"
        assert [e.id_string for e in (yield from journal_a.entries)] == [
            local.id_string,
            newer.id_string,
        ]

    yield from _run(body)
