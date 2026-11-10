"""Ports of Effect's ``effect/test/eventlog/EventLogServerEncryptedCompactionTest.ts``
suite, run on the memory storage (``EventLogServerEncrypted.test.ts``), the
SQLite storage (``sql-sqlite-node``), and the PostgreSQL, MySQL and SQL
Server storages (``sql-pg``, ``sql-mysql2``, ``sql-mssql``, each skipped
without its server). Each test's docstring is the Effect test title.

Effect's suite shares one storage and ``TestClock`` between tests run one
at a time; here each test builds its own storage under its own
``TestClock`` (SQL storages on their own tables).
"""

import itertools
import os
import uuid
from collections.abc import Callable, Generator, Sequence
from datetime import timedelta
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.crypto import digest
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog import sql_event_log_server_encrypted as SqlServer
from pyfect.eventlog.event_journal import EntryId, StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch
from pyfect.sql import sqlite
from pyfect.sql.client import SqlClient

store_id = StoreId("store-a")
MINUTE = 60_000
"""Milliseconds, for clock arithmetic; ``millis`` makes them a duration."""
HOUR = 60 * MINUTE
DAY = 24 * HOUR


def millis(n: int) -> timedelta:
    return timedelta(milliseconds=n)


_namespaces = itertools.count()

type MakeStorage = Callable[[Server.CompactionOptions | None], fx.Layer[Server.Storage, Any]]


def _sql(client: Callable[[], fx.Layer[SqlClient, Any]]) -> MakeStorage:
    def make(options: Server.CompactionOptions | None) -> fx.Layer[Server.Storage, Any]:
        namespace = f"compaction_{os.getpid()}_{next(_namespaces)}"
        return (
            SqlServer.layer_storage(
                entry_table_prefix=f"{namespace}_events",
                remote_id_table=f"{namespace}_remote_id",
                compaction=options,
            )
            .pipe(fx.layer.provide(client()))
            .pipe(fx.layer.provide(digest.layer_web_crypto))
        )

    return make


@pytest.fixture(params=["memory", "SQLite", "pg", "mysql2", "mssql"])
def make_storage(request: pytest.FixtureRequest) -> MakeStorage:
    """A storage with the given compaction options: in memory, on an
    in-memory SQLite database, or on the session's PostgreSQL server or its
    MySQL or SQL Server container (skipped without one)."""
    match request.param:
        case "memory":
            return Server.layer_storage_memory_with
        case "SQLite":
            return _sql(lambda: sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:")))
        case "pg":
            pytest.importorskip("psycopg")
            from pyfect.sql import pg

            from ._postgres import PgServer

            server: PgServer = request.getfixturevalue("pg_server")
            return _sql(lambda: pg.layer(pg.PgPoolConfig(url=server.url)))
        case "mssql":
            pytest.importorskip("pytds")
            from pyfect.sql import mssql

            from ._mssql import MssqlServer

            mssql_server: MssqlServer = request.getfixturevalue("mssql_server")
            return _sql(lambda: mssql.layer(mssql_server.config()))
        case _:
            pytest.importorskip("asyncmy")
            from pyfect.sql import mysql

            from ._mysql import MysqlServer

            mysql_server: MysqlServer = request.getfixturevalue("mysql_server")
            return _sql(lambda: mysql.layer(mysql.MysqlClientConfig(url=mysql_server.url)))


def make_batch(marker: int, *entry_ids: EntryId) -> EncryptedBatch:
    """``marker`` identifies the stored bytes, so a test can tell a snapshot
    batch from the original holding the same ids."""
    return EncryptedBatch(entry_ids=entry_ids, iv=bytes(12), encrypted_batch=bytes([marker]))


def make_ids(count: int) -> list[EntryId]:
    return [J.make_entry_id_unsafe() for _ in range(count)]


def header(sequence: int, entry_ids: Sequence[EntryId], marker: int | None = None):
    return {"sequence": sequence, "entry_ids": list(entry_ids), "marker": marker}


def summarize(batches: Sequence[Any]) -> list[dict[str, Any]]:
    return [
        header(
            batch.sequence,
            batch.entry_ids,
            batch.encrypted_batch[0] if hasattr(batch, "encrypted_batch") else None,
        )
        for batch in batches
    ]


def started(result: Server.CompactionBeginResult) -> Server.BeginStarted:
    assert isinstance(result, Server.BeginStarted), f"expected Started, got {result}"
    return result


def outcome(stream: fx.Stream[Any, Any]) -> fx.Effect[str]:
    """The error tag a stream fails with, or how many items it held."""
    return stream.run_collect().match(
        on_failure=lambda error: type(error).__name__,
        on_success=lambda items: f"{len(items)} items",
    )


def eventually[A](
    read: fx.Effect[A, Any, Any], done: Callable[[A], bool]
) -> Generator[Any, Any, A]:
    """A sweep that waits on I/O can finish after ``adjust`` returns, so a
    read that depends on it retries for a while on the live clock."""
    for _ in range(200):
        value = yield from read
        if done(value):
            return value
        yield from testing.with_live(fx.sleep("10 millis"))
    return (yield from read)


class Store:
    """A store holding [e0, e1] at 0, [e2, e3] at 2, [e4] at 4 and [e5] at
    5, counted from the storage's first sequence by ``seq``."""

    def __init__(self, storage: Server.StorageService) -> None:
        assert storage.compaction is not None, "Storage does not provide compaction"
        self.storage = storage
        self.compaction = storage.compaction
        self.first = storage.first_sequence or 0
        self.public_key = str(uuid.uuid4())
        self.ids = make_ids(6)

    def seq(self, offset: int) -> int:
        return self.first + offset

    def changes(self, start_sequence: int, count: int) -> fx.Effect[list[Any]]:
        return (
            self.storage.changes(self.public_key, store_id, self.seq(start_sequence))
            .take(count)
            .run_collect()
            .map(list)
        )

    def begin(self, through: int) -> fx.Effect[Server.CompactionBeginResult]:
        return self.compaction.begin(self.public_key, store_id, through=self.seq(through))

    def active_id(self) -> fx.Effect[str]:
        return self.compaction.history(self.public_key, store_id).map(
            lambda history: next(a for a in history if a.active).activation_id
        )

    def commit_snapshot(self) -> Generator[Any, Any, str]:
        """Keeps e1, e3 and e4 of the input through 4, as [e1] ending at its
        input sequence 1 and [e3, e4] ending at the base."""
        ids = self.ids
        stage = started((yield from self.begin(4)))
        yield from self.compaction.stage_part(
            self.public_key,
            store_id,
            stage.stage_id,
            0,
            [make_batch(11, ids[1]), make_batch(13, ids[3], ids[4])],
        )
        return (
            yield from self.compaction.commit(
                self.public_key, store_id, stage.stage_id, [self.seq(1), self.seq(3)]
            )
        )


def make_store() -> Generator[Any, Any, Store]:
    store = Store((yield from Server.Storage()))
    ids = store.ids
    yield from store.storage.write(
        store.public_key,
        store_id,
        [
            make_batch(0, ids[0], ids[1]),
            make_batch(2, ids[2], ids[3]),
            make_batch(4, ids[4]),
            make_batch(5, ids[5]),
        ],
    )
    return store


def _run(
    make_storage: MakeStorage,
    body: Callable[[], Generator[Any, Any, Any]],
    options: Server.CompactionOptions | None = None,
) -> fx.Effect[Any, Any, Any]:
    return fx.gen(body).pipe(fx.provide(make_storage(options)))


@testing.effect(timeout="60 seconds")
def test_slides_a_claim_on_each_part(make_storage: MakeStorage):
    """slides a stage's claim on each Part and rejects a stale Part after a steal"""

    def body():
        store = yield from make_store()
        compaction, ids, pk = store.compaction, store.ids, store.public_key
        begun_at = yield from fx.clock.current_time_millis()
        first = started((yield from store.begin(1)))
        yield from testing.adjust(millis(5 * MINUTE))
        yield from compaction.stage_part(pk, store_id, first.stage_id, 0, [make_batch(11, ids[1])])
        yield from testing.adjust(millis(6 * MINUTE))
        busy = yield from store.begin(1)
        yield from testing.adjust(millis(5 * MINUTE))
        second = started((yield from store.begin(1)))
        stale = yield from compaction.stage_part(
            pk, store_id, first.stage_id, 1, [make_batch(10, ids[0])]
        ).flip()
        assert busy == Server.BeginBusy(int(begun_at) + 15 * MINUTE)
        assert second.stage_id != first.stage_id
        assert isinstance(stale, Server.CompactionNotFound)

    yield from _run(make_storage, body)


@testing.effect(timeout="60 seconds")
def test_acknowledges_a_retried_segment(make_storage: MakeStorage):
    """acknowledges a retried segment without staging it twice"""

    def body():
        store = yield from make_store()
        compaction, ids, pk = store.compaction, store.ids, store.public_key
        stage = started((yield from store.begin(4)))
        part = [make_batch(11, ids[1])]
        results = [
            (yield from compaction.stage_part(pk, store_id, stage.stage_id, 0, part)),
            (yield from compaction.stage_part(pk, store_id, stage.stage_id, 0, part)),
        ]
        staged = yield from compaction.staged_headers(pk, store_id, stage.stage_id).run_collect()
        assert results == ["Stored", "AlreadyStored"]
        assert [list(h.entry_ids) for h in staged] == [[ids[1]]]

    yield from _run(make_storage, body)


@testing.effect(timeout="60 seconds")
def test_releases_the_claim_on_abort_and_no_op(make_storage: MakeStorage):
    """releases the claim on abort and no-op, and clears the no-op state on commit"""

    def body():
        store = yield from make_store()
        compaction, ids, pk = store.compaction, store.ids, store.public_key
        aborted = started((yield from store.begin(4)))
        yield from compaction.abort(pk, store_id, aborted.stage_id)
        no_op = started((yield from store.begin(4)))
        yield from compaction.record_no_op(pk, store_id, no_op.stage_id)
        after_no_op = (yield from compaction.status(pk, store_id)).no_op
        stage = started((yield from store.begin(4)))
        yield from compaction.stage_part(pk, store_id, stage.stage_id, 0, [make_batch(11, ids[1])])
        commit = yield from compaction.commit(pk, store_id, stage.stage_id, [store.seq(1)])
        after_commit = (yield from compaction.status(pk, store_id)).no_op
        assert after_no_op == Server.NoOpState(at=store.seq(4), count=1)
        assert commit == "Committed"
        assert after_commit is None

    yield from _run(make_storage, body)


@testing.effect(timeout="60 seconds")
def test_reports_the_lag_head(make_storage: MakeStorage):
    """reports as the lag head the last sequence of each storage hour once it ended a lag ago"""

    def body():
        now = yield from fx.clock.current_time_millis()
        # 30 minutes into an hour, so the store's first writes share it.
        yield from testing.adjust(millis(HOUR - (int(now) % HOUR) + 30 * MINUTE))
        store = yield from make_store()
        yield from testing.adjust(millis(HOUR))
        yield from store.storage.write(store.public_key, store_id, [make_batch(6, *make_ids(1))])
        lag_head = store.compaction.status(store.public_key, store_id).map(lambda s: s.lag_head)
        # 30 minutes into the second hour: the first hour passes the lag in
        # 23 hours and 30 minutes.
        yield from testing.adjust(millis(23 * HOUR + 29 * MINUTE))
        before_first = yield from lag_head
        yield from testing.adjust(millis(2 * MINUTE))
        after_first = yield from lag_head
        yield from testing.adjust(millis(HOUR - 2 * MINUTE))
        before_second = yield from lag_head
        yield from testing.adjust(millis(2 * MINUTE))
        after_second = yield from lag_head
        assert (before_first, after_first, before_second, after_second) == (
            store.seq(-1),
            store.seq(5),
            store.seq(5),
            store.seq(6),
        )

    yield from _run(make_storage, body)


@testing.effect(timeout="60 seconds")
def test_fails_reads_of_an_expired_stage(make_storage: MakeStorage):
    """fails reads of an expired stage before the sweep closes it"""

    def body():
        store = yield from make_store()
        compaction, pk = store.compaction, store.public_key
        stage = started((yield from store.begin(4)))
        # Past the 10 minute stage TTL, well before the hourly sweep.
        yield from testing.adjust(millis(11 * MINUTE))
        reads = [
            (yield from outcome(compaction.input_headers(pk, store_id, stage.stage_id))),
            (yield from outcome(compaction.fetch(pk, store_id, stage.stage_id, [store.seq(0)]))),
            (yield from outcome(compaction.staged_headers(pk, store_id, stage.stage_id))),
        ]
        assert reads == ["CompactionNotFound"] * 3

    yield from _run(make_storage, body)


@testing.effect(timeout="60 seconds")
def test_fails_input_or_fetch_after_the_pin_was_pruned(make_storage: MakeStorage):
    """fails an Input or Fetch read again after its stage's pin was pruned"""

    def body():
        store = yield from make_store()
        compaction, ids, pk, seq = store.compaction, store.ids, store.public_key, store.seq
        yield from store.commit_snapshot()
        stage = started((yield from store.begin(5)))
        yield from compaction.rollback(pk, store_id, (yield from store.active_id()))
        input_ = compaction.input_headers(pk, store_id, stage.stage_id)
        fetch = compaction.fetch(pk, store_id, stage.stage_id, [seq(1), seq(3), seq(5)])
        before_prune = [(yield from outcome(input_)), (yield from outcome(fetch))]
        # A Part keeps the stage alive past the withdrawn snapshot's grace.
        yield from testing.adjust(millis(23 * HOUR))
        yield from compaction.stage_part(pk, store_id, stage.stage_id, 0, [make_batch(11, ids[1])])
        yield from testing.adjust(millis(3 * HOUR))
        after_prune = [
            (yield from eventually(outcome(input_), lambda r: r == "CompactionNotFound")),
            (yield from outcome(fetch)),
        ]
        assert before_prune == ["3 items", "3 items"]
        assert after_prune == ["CompactionNotFound", "CompactionNotFound"]

    yield from _run(
        make_storage, body, {"grace": "25 hours", "lag": "24 hours", "stage_ttl": "24 hours"}
    )


@testing.effect(timeout="60 seconds")
def test_serves_the_snapshot_and_the_originals_above_it(make_storage: MakeStorage):
    """serves the snapshot at or below the base and the originals above it"""

    def body():
        store = yield from make_store()
        compaction, ids, pk, seq = store.compaction, store.ids, store.public_key, store.seq
        assert (yield from store.commit_snapshot()) == "Committed"
        from_below = yield from store.changes(0, 3)
        from_inside = yield from store.changes(2, 2)
        from_above = yield from store.changes(5, 1)
        stage = started((yield from store.begin(5)))
        input_ = yield from compaction.input_headers(pk, store_id, stage.stage_id).run_collect()
        fetched = yield from compaction.fetch(
            pk, store_id, stage.stage_id, [seq(3), seq(5)]
        ).run_collect()
        snapshot_first = header(seq(1), [ids[1]], 11)
        snapshot_second = header(seq(3), [ids[3], ids[4]], 13)
        tail = header(seq(5), [ids[5]], 5)
        assert summarize(from_below) == [snapshot_first, snapshot_second, tail]
        assert summarize(from_inside) == [snapshot_second, tail]
        assert summarize(from_above) == [tail]
        assert summarize(input_) == [
            header(seq(1), [ids[1]]),
            header(seq(3), [ids[3], ids[4]]),
            header(seq(5), [ids[5]]),
        ]
        assert summarize(fetched) == [snapshot_second, tail]

    yield from _run(make_storage, body)


@testing.effect(timeout="60 seconds")
def test_fails_changes_when_the_snapshot_has_no_rows(make_storage: MakeStorage):
    """fails changes when the active snapshot has no rows"""

    def body():
        store = yield from make_store()
        stage = started((yield from store.begin(4)))
        yield from store.compaction.commit(store.public_key, store_id, stage.stage_id, [])
        exit = yield from store.changes(0, 1).exit()
        assert isinstance(exit, fx.Failure)

    yield from _run(make_storage, body)


@testing.effect(timeout="60 seconds")
def test_rolls_back_to_the_originals_within_grace(make_storage: MakeStorage):
    """rolls back to the originals within grace, and the sweep leaves them"""

    def body():
        store = yield from make_store()
        compaction, ids, pk, seq = store.compaction, store.ids, store.public_key, store.seq
        yield from store.commit_snapshot()
        yield from testing.adjust(millis(29 * DAY))
        pinned = started((yield from store.begin(5)))
        yield from compaction.rollback(pk, store_id, (yield from store.active_id()))
        commit = yield from compaction.commit(pk, store_id, pinned.stage_id, [])
        status = yield from compaction.status(pk, store_id)
        yield from testing.adjust(millis(2 * DAY))
        served = yield from store.changes(0, 4)
        assert commit == "Superseded"
        assert status.base == seq(-1)
        assert summarize(served) == [
            header(seq(0), [ids[0], ids[1]], 0),
            header(seq(2), [ids[2], ids[3]], 2),
            header(seq(4), [ids[4]], 4),
            header(seq(5), [ids[5]], 5),
        ]

    yield from _run(make_storage, body)


@testing.effect(timeout="60 seconds")
def test_re_appends_the_withdrawn_snapshots_input(make_storage: MakeStorage):
    """re-appends the withdrawn snapshot's input on rollback, so its readers end with every entry"""

    def body():
        store = yield from make_store()
        compaction, ids, pk, seq = store.compaction, store.ids, store.public_key, store.seq
        yield from store.commit_snapshot()
        [sentinel] = make_ids(1)
        every = {*ids, sentinel}

        def follow(start_sequence: int, received: list[EntryId]) -> fx.Effect[None]:
            """Follows changes until the sentinel, written after the
            rollback, arrives."""
            return (
                store.storage.changes(pk, store_id, start_sequence)
                .tap(lambda batch: fx.sync(lambda: received.extend(batch.entry_ids)))
                .take_until(lambda batch: sentinel in batch.entry_ids)
                .run_drain()
            )

        # One reader has read the whole snapshot, [e1] [e3, e4] [e5], and
        # stays subscribed.
        whole: list[EntryId] = []
        whole_fiber = yield from follow(seq(0), whole).fork()
        before_rollback = yield from eventually(fx.sync(lambda: list(whole)), lambda r: len(r) == 4)
        # The other stopped after the snapshot's first batch.
        [first] = yield from store.changes(0, 1)
        partway = list(first.entry_ids)
        yield from compaction.rollback(pk, store_id, (yield from store.active_id()))
        yield from store.storage.write(pk, store_id, [make_batch(6, sentinel)])
        yield from follow(first.sequence + len(first.entry_ids), partway)
        yield from whole_fiber.join()
        assert sorted(before_rollback) == sorted([ids[1], ids[3], ids[4], ids[5]])
        assert set(whole) == every
        assert set(partway) == every

    yield from _run(make_storage, body)


@testing.effect(timeout="60 seconds")
def test_prunes_the_superseded_originals_after_grace(make_storage: MakeStorage):
    """prunes the superseded originals after grace and then refuses to roll back to them"""

    def body():
        store = yield from make_store()
        compaction, pk, seq = store.compaction, store.public_key, store.seq
        yield from store.commit_snapshot()
        originals, snapshot = yield from compaction.history(pk, store_id)
        yield from testing.adjust(millis(30 * DAY - MINUTE))
        before_grace = (yield from compaction.history(pk, store_id))[0].restorable
        yield from testing.adjust(millis(2 * HOUR))
        after_grace = yield from eventually(
            compaction.history(pk, store_id).map(lambda history: history[0].restorable),
            lambda restorable: not restorable,
        )
        rollback = yield from compaction.rollback(pk, store_id, snapshot.activation_id).flip()
        served = yield from store.changes(0, 3)
        assert (originals.base, originals.active) == (seq(-1), False)
        assert (before_grace, after_grace) == (True, False)
        assert rollback.reason == "PruneStarted"
        assert [batch["marker"] for batch in summarize(served)] == [11, 13, 5]

    yield from _run(make_storage, body)
