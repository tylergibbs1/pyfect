"""Ports of Effect's ``sql-mssql/test/Persistence.integration.test.ts`` on
the session's SQL Server container (``_mssql.mssql_server``; skipped without
Docker): the ``persistence/PersistedCacheTest.ts`` suite (``_persisted_cache_suite``) on
``layer_sql_multi_table`` (``PersistedCache (sql-mssql-multi)``) and
``layer_sql`` (``(sql-mssql-single)``), the ``PersistedQueueTest`` suite
(``_persisted_queue_suite``) on ``layer_store_sql`` (``PersistedQueue
(sql-mssql)``), the ``PersistedQueueSqlTest`` suite
(``_persisted_queue_sql_suite``), and the file's own four titles.

Each test's docstring is the Effect test title. Adapted: each title's
tables are dropped first, since the server is shared by every test of the
session (Effect's container is the file's own).
"""

from __future__ import annotations

import json
import re
import uuid
from collections.abc import Callable, Generator
from typing import Any, Literal

import pytest

pytest.importorskip("pytds")

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.persistence import persisted_queue as pq
from pyfect.persistence import persistence
from pyfect.sql import SqlClient, SqlClientService, mssql

from . import _mssql_xact_abort as _xact_abort
from . import _persisted_cache_suite as cache_suite
from . import _persisted_queue_sql_suite as sql_suite
from . import _persisted_queue_suite as queue_suite
from ._mssql import MssqlServer, query_now

pytestmark = pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")


def _client(server: MssqlServer) -> fx.Layer[Any, Any]:
    return mssql.layer(server.config())


def _drop(*tables: str) -> None:
    names = ", ".join(f"{t}, {t}_migrations" for t in tables)
    query_now(f"DROP TABLE IF EXISTS {names}")


# --- PersistedCache -------------------------------------------------------------------

_LAYERS = pytest.mark.parametrize(
    ("layer", "store_id"),
    [
        pytest.param(persistence.layer_sql_multi_table, "sql-mssql-multi", id="sql-mssql-multi"),
        pytest.param(persistence.layer_sql, "sql-mssql-single", id="sql-mssql-single"),
    ],
)


def _with(server: MssqlServer, layer: fx.Layer[Any, Any, Any]) -> fx.Layer[Any, Any]:
    return layer.pipe(fx.provide(_client(server)))


@_LAYERS
def test_smoke_test(mssql_server: MssqlServer, layer: fx.Layer[Any, Any, Any], store_id: str):
    """smoke test"""
    cache_suite.run(_with(mssql_server, layer), cache_suite.smoke_test)


@_LAYERS
@pytest.mark.parametrize("outcome", ["success", "error"])
def test_recomputes_and_replaces_entries_with_stale_schemas(
    mssql_server: MssqlServer,
    layer: fx.Layer[Any, Any, Any],
    store_id: str,
    outcome: Literal["success", "error"],
):
    """recomputes and replaces entries with stale ${outcome} schemas"""
    cache_suite.run(_with(mssql_server, layer), cache_suite.recomputes_stale(store_id, outcome))


@_LAYERS
def test_require_services_at_lookup_requires_lookup_services_at_get_time(
    mssql_server: MssqlServer, layer: fx.Layer[Any, Any, Any], store_id: str
):
    """requireServicesAt: 'lookup' requires lookup services at get-time"""
    cache_suite.run(_with(mssql_server, layer), cache_suite.require_services_at_lookup(store_id))


# --- PersistedQueue -------------------------------------------------------------------


class _Server:
    server: MssqlServer

    @pytest.fixture(autouse=True)
    def _server(self, mssql_server: MssqlServer) -> None:
        self.server = mssql_server

    def client(self) -> fx.Layer[Any, Any]:
        return _client(self.server)


class TestPersistedQueueMssql(_Server, queue_suite.PersistedQueueSuite):
    """PersistedQueue (sql-mssql)"""

    @pytest.fixture(autouse=True)
    def _fresh_table(self, _server: None) -> None:
        _drop("effect_queue")

    def make_layer(self) -> fx.Layer[pq.PersistedQueueStore, Any, Any]:
        return pq.layer_store_sql().pipe(fx.provide(self.client()))


class TestPersistedQueueMssqlSql(_Server, sql_suite.PersistedQueueSqlSuite):
    """PersistedQueue SQL delays / PersistedQueue SQL claims (sql-mssql)"""

    @pytest.fixture(autouse=True)
    def _fresh_tables(self, _server: None) -> None:
        _drop(
            "effect_queue_delay_boundary",
            "effect_queue_delay_transaction",
            "effect_queue_commit_wake",
            "effect_queue_stale_failure_same",
            "effect_queue_stale_failure_other",
            "effect_queue_stale_success_same",
        )


# --- the file's own titles ------------------------------------------------------------


def _run(server: MssqlServer, body: Callable[[], Generator[Any, Any, Any]]) -> None:
    program = testing.with_live(fx.scoped(fx.gen(body)))
    testing.run_test(program.pipe(fx.provide(_client(server))).or_die())


def _queue(
    table_name: str, *, poll_interval: float | None = None, retry: bool = False
) -> fx.Effect[pq.PersistedQueue[Any, Any], Any, Any]:
    def body():
        store = yield from (
            pq.make_store_sql(table_name=table_name)
            if poll_interval is None
            else pq.make_store_sql(
                table_name=table_name, poll_interval=fx.duration.seconds(poll_interval)
            )
        )
        factory = yield from pq.make_factory.pipe(fx.provide_service(pq.PersistedQueueStore, store))
        if retry:
            return (
                yield from factory.make(
                    name=table_name, schema=S.Int, retry_schedule=fx.schedule.spaced(0)
                )
            )
        return (yield from factory.make(name=table_name, schema=S.String))

    return fx.gen(body)


def _capture_deadlocks() -> Generator[Any, Any, fx.Effect[list[str], Any, Any]]:
    """Records deadlock graphs in a session of their own (``system_health``
    can buffer events for minutes); the effect returned reads them."""
    sql = yield from SqlClient()
    name = f"effect_deadlocks_{uuid.uuid4().hex}"
    session = sql.identifier(name)
    drop = sql(
        "IF EXISTS (SELECT 1 FROM sys.server_event_sessions WHERE name = {}) "
        "DROP EVENT SESSION {} ON SERVER",
        name,
        session,
    )
    # only runs if the test fails before reading
    yield from fx.acquire_release(
        sql(
            "CREATE EVENT SESSION {} ON SERVER ADD EVENT sqlserver.xml_deadlock_report "
            "ADD TARGET package0.ring_buffer WITH (MAX_DISPATCH_LATENCY = 1 SECONDS); "
            "ALTER EVENT SESSION {} ON SERVER STATE = START",
            session,
            session,
        ),
        lambda _session, _exit: drop.ignore(),
    )

    def read():
        # wait out the session's dispatch latency
        yield from fx.sleep("2 seconds")
        rows = yield from sql(
            "SELECT CAST(x.e.query('.') AS NVARCHAR(MAX)) AS graph "
            "FROM sys.dm_xe_sessions s "
            "INNER JOIN sys.dm_xe_session_targets t ON t.event_session_address = s.address "
            "CROSS APPLY (SELECT CAST(t.target_data AS XML) AS data) d "
            "CROSS APPLY d.data.nodes('RingBufferTarget/event[@name=\"xml_deadlock_report\"]') "
            "AS x(e) WHERE s.name = {} AND t.target_name = N'ring_buffer'",
            name,
        )
        yield from drop
        return [str(row["graph"]) for row in rows]

    return fx.gen(read)


def _summarize_deadlock(graph: str) -> str:
    """e.g. ``UPDATE vs UPDATE on PK X, idx_queue_take S``"""
    transactions = re.findall(r'transactionname="([^"]*)"', graph)
    locks = [
        f"{'PK' if index.startswith('PK__') else index} {mode}"
        for index, mode in re.findall(
            r'<keylock [^>]*indexname="([^"]*)"[^>]*mode="([^"]*)"', graph
        )
    ]
    return f"{' vs '.join(transactions)} on {', '.join(dict.fromkeys(locks))}"


def _wait_for[A](check: fx.Effect[A | None, Any, Any], what: str) -> Generator[Any, Any, A]:
    for _ in range(100):
        found = yield from check
        if found is not None:
            return found
        yield from fx.sleep("50 millis")
    return (yield from fx.die(RuntimeError(f"{what} never happened")))


def _rows(sql: SqlClientService, table_name: str) -> fx.Effect[list[dict[str, object]], Any]:
    return sql("SELECT id, element FROM {} ORDER BY id", sql.identifier(table_name)).map(
        lambda rows: [dict(row) for row in rows]
    )


def test_offers_claims_and_settlements_do_not_deadlock(mssql_server: MssqlServer):
    """PersistedQueue offers, claims and settlements do not deadlock"""
    table_name = "effect_queue_mssql_deadlocks"
    _drop(table_name)

    def body():
        read_deadlocks = yield from _capture_deadlocks()
        # two stores poll the same table, so claims race each other as well
        # as offers and settlements
        queues = [
            (yield from _queue(table_name, poll_interval=0.01, retry=True)),
            (yield from _queue(table_name, poll_interval=0.01, retry=True)),
        ]
        total = 120
        deliveries: dict[int, int] = {}
        succeeded: set[int] = set()
        completed = yield from fx.Deferred[None].make()

        def handle(n: int, _meta: Any) -> fx.Effect[None, str]:
            def run() -> fx.Effect[None, str]:
                count = deliveries.get(n, 0) + 1
                deliveries[n] = count
                # every third element fails its first delivery, so claims
                # also race retries
                if n % 3 == 0 and count == 1:
                    return fx.fail("transient")
                succeeded.add(n)
                if len(succeeded) == total:
                    return completed.succeed(None).as_void()
                return fx.void

            return fx.suspend(run)

        for queue in queues:
            worker = queue.take(handle).ignore().forever()
            for _ in range(3):
                yield from worker.fork_scoped()

        offered = yield from fx.for_each(
            range(total), lambda n: queues[n % 2].offer(n), concurrency=10
        ).exit()
        if isinstance(offered, fx.Success):
            yield from completed.wait().timeout_option("15 seconds")

        # a lock resource names the table as objectname="<database>.<schema>.<table>"
        deadlocks = [g for g in (yield from read_deadlocks) if f'.{table_name}"' in g]
        assert [_summarize_deadlock(g) for g in deadlocks] == [], "deadlocks"
        assert isinstance(offered, fx.Success), offered
        assert len(succeeded) == total
        for n, count in deliveries.items():
            assert count == (2 if n % 3 == 0 else 1), f"deliveries for element {n}"

    _run(mssql_server, body)


def test_skips_an_offer_racing_an_uncommitted_duplicate_under_xact_abort(
    mssql_server: MssqlServer,
):
    """PersistedQueue skips an offer racing an uncommitted duplicate under XACT_ABORT"""
    database = "effect_queue_xact_abort"
    table_name = "effect_queue_xact_abort"

    def body():
        master = yield from SqlClient()
        # With read committed snapshot, the Azure SQL Database default, a
        # plain read does not wait for another transaction's uncommitted offer.
        yield from master(
            "IF DB_ID({}) IS NULL CREATE DATABASE {}", database, master.identifier(database)
        )
        yield from master(
            "ALTER DATABASE {} SET READ_COMMITTED_SNAPSHOT ON WITH ROLLBACK IMMEDIATE",
            master.identifier(database),
        )
        sql = yield from _xact_abort.make(mssql_server, database)
        yield from sql("DROP TABLE IF EXISTS {}, {}", *_tables(sql, table_name))
        queue = yield from _queue(table_name).pipe(fx.provide_service(SqlClient, sql))

        offered = yield from fx.Deferred[None].make()

        def first_offer():
            yield from queue.offer("first", id="job")
            yield from offered.succeed(None)
            # commit only once the duplicate offer is waiting on this row
            yield from fx.sleep("1 second")

        first = yield from sql.with_transaction(fx.gen(first_offer)).fork_scoped()
        yield from offered.wait()

        def second_offer():
            [row] = yield from sql("SELECT @@OPTIONS & 16384 AS xactAbort")
            assert row["xactAbort"] == 16384, "XACT_ABORT is on for the duplicate offer"
            yield from queue.offer("duplicate", id="job")
            yield from queue.offer("other", id="other")

        second = yield from sql.with_transaction(fx.gen(second_offer)).exit()
        yield from first.join()

        assert isinstance(second, fx.Success), second
        assert (yield from _rows(sql, table_name)) == [
            {"id": "job", "element": json.dumps("first")},
            {"id": "other", "element": json.dumps("other")},
        ]

    _run(mssql_server, body)


def _tables(sql: SqlClientService, table_name: str) -> tuple[Any, Any]:
    return sql.identifier(table_name), sql.identifier(f"{table_name}_migrations")


def test_skips_a_duplicate_an_older_release_offer_inserts_while_the_offer_waits(
    mssql_server: MssqlServer,
):
    """PersistedQueue skips a duplicate an older release's offer inserts while the offer waits"""
    table_name = "effect_queue_mixed_release"
    _drop(table_name)

    def body():
        sql = yield from SqlClient()
        xa = yield from _xact_abort.make(mssql_server, mssql_server.database)
        queue = yield from _queue(table_name).pipe(fx.provide_service(SqlClient, xa))

        # the SQL Server offer of releases before the MERGE was replaced, which
        # keeps writing during a rolling upgrade
        def legacy_offer(id_: str, element: str) -> fx.Effect[Any, Any]:
            return sql(
                "MERGE {} WITH (HOLDLOCK) AS target "
                "USING (SELECT {} AS id, {} AS queue_name) AS source "
                "ON target.id = source.id AND target.queue_name = source.queue_name "
                "WHEN NOT MATCHED THEN "
                "INSERT (id, queue_name, element, state, attempts, visible_at, created_at, "
                "updated_at) VALUES (source.id, source.queue_name, {}, 'pending', 0, "
                "SYSDATETIME(), SYSDATETIME(), SYSDATETIME());",
                sql.identifier(table_name),
                id_,
                table_name,
                json.dumps(element),
            )

        legacy_locked = yield from fx.Deferred[int].make()
        offer_blocked = yield from fx.Deferred[None].make()

        def legacy_body():
            yield from legacy_offer("earlier", "earlier")
            [row] = yield from sql("SELECT @@SPID AS spid")
            yield from legacy_locked.succeed(int(str(row["spid"])))
            yield from offer_blocked.wait()
            yield from legacy_offer("job", "legacy")

        legacy = yield from sql.with_transaction(fx.gen(legacy_body)).fork_scoped()
        spid = yield from legacy_locked.wait()

        def offer_body():
            [row] = yield from xa("SELECT @@OPTIONS & 16384 AS xactAbort")
            assert row["xactAbort"] == 16384, "XACT_ABORT is on for the offer"
            yield from queue.offer("new", id="job")
            yield from queue.offer("other", id="other")

        offer = yield from xa.with_transaction(fx.gen(offer_body)).exit().fork_scoped()

        # the older release inserts the same id only once the offer is
        # waiting on its range locks
        blocked = sql(
            "SELECT COUNT(*) AS blocked FROM sys.dm_exec_requests WHERE blocking_session_id = {}",
            spid,
        ).map(lambda rows: True if int(str(rows[0]["blocked"])) > 0 else None)
        yield from _wait_for(blocked, "the offer waiting on the older release's locks")
        yield from offer_blocked.succeed(None)
        yield from legacy.join()

        exit_ = yield from offer.join()
        assert isinstance(exit_, fx.Success), exit_
        assert (yield from _rows(sql, table_name)) == [
            {"id": "earlier", "element": json.dumps("earlier")},
            {"id": "job", "element": json.dumps("legacy")},
            {"id": "other", "element": json.dumps("other")},
        ]

    _run(mssql_server, body)


def test_keeps_a_raw_batch_sessions_xact_abort_when_an_offer_is_cancelled(
    mssql_server: MssqlServer,
):
    """PersistedQueue keeps a raw batch session's XACT_ABORT when an offer is cancelled"""
    table_name = "effect_queue_raw_cancel"
    _drop(table_name)

    def body():
        sql = yield from SqlClient()
        # a single connection, so the cancelled offer's session is the one
        # the next statement gets
        raw = yield from _xact_abort.make(
            mssql_server, mssql_server.database, raw_batch=True, size=1
        )
        queue = yield from _queue(table_name)
        raw_queue = yield from _queue(table_name).pipe(fx.provide_service(SqlClient, raw))

        holding = yield from fx.Deferred[int].make()
        release = yield from fx.Deferred[None].make()

        def holder_body():
            yield from queue.offer("first", id="job")
            [row] = yield from sql("SELECT @@SPID AS spid")
            yield from holding.succeed(int(str(row["spid"])))
            yield from release.wait()

        holder = yield from sql.with_transaction(fx.gen(holder_body)).fork_scoped()
        holder_spid = yield from holding.wait()

        offer = yield from raw_queue.offer("duplicate", id="job").fork_scoped()
        # cancel only once the offer waits on the uncommitted duplicate
        waiting = sql(
            "SELECT session_id AS session FROM sys.dm_exec_requests WHERE blocking_session_id = {}",
            holder_spid,
        ).map(lambda rows: rows[0]["session"] if rows else None)
        session = yield from _wait_for(waiting, "the offer waiting on the duplicate")
        yield from offer.interrupt()
        yield from release.succeed(None)
        yield from holder.join()

        [state] = yield from raw(
            "SELECT @@SPID AS spid, @@TRANCOUNT AS tranCount, @@OPTIONS & 16384 AS xactAbort"
        )
        assert dict(state) == {"spid": session, "tranCount": 0, "xactAbort": 16384}

    _run(mssql_server, body)
