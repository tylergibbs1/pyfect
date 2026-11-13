"""Ports of the ``PersistedQueue`` suites of Effect's
``sql-pg/test/Persistence.integration.test.ts`` on the throwaway
PostgreSQL server (``_postgres.pg_server``; skipped without one): the
``PersistedQueueTest`` suite (``_persisted_queue_suite``) on
``layer_store_sql`` (``PersistedQueue (sql-pg)``), the
``PersistedQueueSqlTest`` suite (``_persisted_queue_sql_suite``) and the
file's ``PersistedQueue SQL locks`` titles; then
``sql-pglite/test/PersistedQueue.test.ts`` (``PersistedQueue SQL
migrations``), run on the same server since pyfect has no PGlite driver.

Each test's docstring is the Effect test title. The file's other suites
are in ``test_pg_persistence.py``. Adapted: each title's tables are
dropped first, since the server is shared by every test of the session.
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Generator
from typing import Any

import pytest

pytest.importorskip("psycopg")

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.latch import Latch
from pyfect.persistence import persisted_queue as pq
from pyfect.sql import SqlClient, pg

from . import _persisted_queue_sql_suite as sql_suite
from . import _persisted_queue_suite as suite
from ._postgres import PgServer, query_now

pytestmark = pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")


def _client(server: PgServer) -> fx.Layer[Any, Any]:
    return pg.layer(pg.PgPoolConfig(url=server.url))


def _drop(*tables: str) -> None:
    for table in tables:
        query_now(f"DROP TABLE IF EXISTS {table}, {table}_migrations")


class _Server:
    server: PgServer

    @pytest.fixture(autouse=True)
    def _server(self, pg_server: PgServer) -> None:
        self.server = pg_server

    def client(self) -> fx.Layer[Any, Any]:
        return _client(self.server)


class TestPersistedQueuePg(_Server, suite.PersistedQueueSuite):
    """PersistedQueue (sql-pg)"""

    @pytest.fixture(autouse=True)
    def _fresh_table(self, _server: None) -> None:
        _drop("effect_queue")

    def make_layer(self) -> fx.Layer[pq.PersistedQueueStore, Any, Any]:
        return pq.layer_store_sql().pipe(fx.provide(self.client()))


class TestPersistedQueuePgSql(_Server, sql_suite.PersistedQueueSqlSuite):
    """PersistedQueue SQL delays / PersistedQueue SQL claims (sql-pg)"""

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


# --- PersistedQueue SQL locks ---------------------------------------------------------


def _run(server: PgServer, body: Callable[[], Generator[Any, Any]], *tables: str) -> None:
    _drop(*tables)
    program = testing.with_live(fx.scoped(fx.gen(body)))
    testing.run_test(program.pipe(fx.provide(_client(server))))


def _wait_for(condition: Callable[[], fx.Effect[bool, Any, Any]]) -> Generator[Any, Any]:
    """Poll ``condition`` every 100 ms until it holds or 100 rounds pass."""
    for _ in range(100):
        if (yield from condition()):
            return
        yield from fx.sleep("100 millis")


def _factory_queue[A](
    store: pq.PersistedQueueStoreService, name: str, schema: S.Codec[A, Any, Any, Any], **opts: Any
) -> Generator[Any, Any, pq.PersistedQueue[A, Any]]:
    factory = yield from pq.make_factory.pipe(fx.provide_service(pq.PersistedQueueStore, store))
    return (yield from factory.make(name=name, schema=schema, **opts))


def test_refreshes_locks_for_acquired_elements(pg_server: PgServer) -> None:
    """PersistedQueue SQL locks / refreshes locks for acquired elements"""

    def body():
        options: dict[str, Any] = {
            "table_name": "effect_queue_lock_refresh",
            "poll_interval": "10 millis",
            "lock_refresh_interval": "100 millis",
            "lock_expiration": "1 second",
        }
        store1 = yield from pq.make_store_sql(**options)
        store2 = yield from pq.make_store_sql(**options)
        element = {"message": "hello"}
        yield from store1.offer(
            name="lock-refresh", id=str(uuid.uuid4()), element=element, is_custom_id=False
        )
        take_options = pq.TakeOptions(
            name="lock-refresh",
            max_attempts=10,
            retry_delay=lambda _: fx.succeed(fx.duration.zero),
        )
        acquired = Latch()

        def hold() -> Generator[Any, Any]:
            yield from store1.take(take_options)
            yield from acquired.open()
            yield from fx.never

        first = yield from fx.scoped(fx.gen(hold)).fork_scoped()
        yield from acquired.wait()
        second = yield from fx.scoped(store2.take(take_options)).fork_scoped()

        yield from fx.sleep("1500 millis")
        assert second.poll_unsafe() is None

        yield from first.interrupt()
        received = yield from second.join()
        assert received.element == element

    _run(pg_server, body, "effect_queue_lock_refresh")


def test_dead_letters_malformed_json_and_continues(pg_server: PgServer) -> None:
    """PersistedQueue SQL locks / dead-letters malformed JSON and continues"""

    def body():
        table_name = "effect_queue_invalid_json"
        store = yield from pq.make_store_sql(table_name=table_name, poll_interval="10 millis")
        queue = yield from _factory_queue(store, "invalid-json", S.String)
        sql = (yield from SqlClient()).without_transforms()
        table = sql.identifier(table_name)
        poison_id = str(uuid.uuid4())

        yield from store.offer(
            name="invalid-json", id=poison_id, element="poison", is_custom_id=False
        )
        yield from sql("UPDATE {} SET element = {} WHERE id = {}", table, "{", poison_id)
        yield from queue.offer("valid")

        # the malformed element is skipped and the next one is delivered
        assert (yield from queue.take(lambda value, _meta: fx.succeed(value))) == "valid"

        rows = yield from sql(
            "SELECT state, attempts, last_failure FROM {} WHERE id = {}", table, poison_id
        )
        assert rows[0]["state"] == "failed"
        assert int(str(rows[0]["attempts"])) == 1
        assert rows[0]["last_failure"] is not None

    _run(pg_server, body, "effect_queue_invalid_json")


def test_processes_elements_exactly_once_across_two_workers(pg_server: PgServer) -> None:
    """PersistedQueue SQL locks / processes elements exactly once across two workers"""

    def body():
        options: dict[str, Any] = {
            "table_name": "effect_queue_two_workers",
            "poll_interval": "10 millis",
        }
        queue1 = yield from _factory_queue(
            (yield from pq.make_store_sql(**options)), "two-workers", S.Number
        )
        queue2 = yield from _factory_queue(
            (yield from pq.make_store_sql(**options)), "two-workers", S.Number
        )
        total = 20
        yield from fx.for_each(range(total), queue1.offer, concurrency=8)

        seen: dict[float, int] = {}

        def count(n: float, _meta: pq.Metadata) -> fx.Effect[None]:
            return fx.sync(lambda: seen.__setitem__(n, seen.get(n, 0) + 1))

        for queue in (queue1, queue1, queue2, queue2):
            yield from queue.take(count).forever().fork_scoped()

        yield from _wait_for(lambda: fx.sync(lambda: len(seen) == total))
        assert len(seen) == total
        for n, deliveries in seen.items():
            assert deliveries == 1, f"deliveries for element {n}"

    _run(pg_server, body, "effect_queue_two_workers")


def test_recovers_elements_from_crashed_workers_after_lock_expiration(
    pg_server: PgServer,
) -> None:
    """PersistedQueue SQL locks / recovers elements from crashed workers after lock
    expiration"""

    def body():
        table_name = "effect_queue_crash_recovery"
        store = yield from pq.make_store_sql(
            table_name=table_name, poll_interval="10 millis", lock_expiration="1 second"
        )
        queue = yield from _factory_queue(store, "crash-recovery", S.Number)
        sql = (yield from SqlClient()).without_transforms()
        table = sql.identifier(table_name)

        id = yield from queue.offer(1)
        # simulate a worker that claimed the element and then crashed: the
        # lock is held by a dead worker and the claim consumed an attempt
        yield from sql(
            "UPDATE {} SET acquired_by = {}, acquired_at = NOW(), attempts = 1 WHERE id = {}",
            table,
            str(uuid.uuid4()),
            id,
        )
        attempts = yield from queue.take(lambda _n, meta: fx.succeed(meta.attempts))
        assert attempts == 2

    _run(pg_server, body, "effect_queue_crash_recovery")


def test_dead_letters_elements_from_workers_that_crashed_on_the_final_attempt(
    pg_server: PgServer,
) -> None:
    """PersistedQueue SQL locks / dead-letters elements from workers that crashed on the final
    attempt"""

    def body():
        table_name = "effect_queue_crash_exhausted"
        store = yield from pq.make_store_sql(
            table_name=table_name,
            poll_interval="10 millis",
            lock_expiration="500 millis",
            lock_refresh_interval="200 millis",
        )
        queue = yield from _factory_queue(store, "crash-exhausted", S.Number, max_attempts=1)
        sql = (yield from SqlClient()).without_transforms()
        table = sql.identifier(table_name)

        id = yield from queue.offer(1)
        # the final attempt was claimed by a worker that crashed, so no
        # finalizer will ever settle this element
        yield from sql(
            "UPDATE {} SET acquired_by = {}, acquired_at = NOW(), attempts = 1 WHERE id = {}",
            table,
            str(uuid.uuid4()),
            id,
        )

        # an active taker runs the periodic pass that flips such rows to failed
        fiber = yield from queue.take(lambda n, _meta: fx.succeed(n)).fork_scoped()

        def state() -> fx.Effect[Any, Any]:
            return sql("SELECT state, last_failure FROM {} WHERE id = {}", table, id).map(
                lambda rows: rows[0]
            )

        yield from _wait_for(lambda: state().map(lambda row: row["state"] == "failed"))
        row = yield from state()
        assert row["state"] == "failed"
        assert "Lock expired after final attempt" in str(row["last_failure"] or "")
        assert fiber.poll_unsafe() is None

    _run(pg_server, body, "effect_queue_crash_exhausted")


# --- PersistedQueue SQL migrations (sql-pglite) ---------------------------------------


def test_runs_fresh_install_migrations_once(pg_server: PgServer) -> None:
    """PersistedQueue SQL migrations / runs fresh-install migrations once"""
    table_name = "persisted_queue_migration_test"

    def body():
        sql = (yield from SqlClient()).without_transforms()
        yield from pq.make_store_sql(table_name=table_name)
        yield from pq.make_store_sql(table_name=table_name)

        migrations = yield from sql(
            "SELECT migration_id, name FROM {} ORDER BY migration_id",
            sql.identifier(f"{table_name}_migrations"),
        )
        assert [(row["migration_id"], row["name"]) for row in migrations] == [
            (1, "create_table"),
            (2, "upgrade_schema"),
            # pyfect's own, a no-op on PostgreSQL (PARITY section 4)
            (3, "exact_ids"),
        ]

        indexes = yield from sql(
            "SELECT indexname FROM pg_indexes WHERE tablename = {} ORDER BY indexname",
            table_name,
        )
        assert [row["indexname"] for row in indexes] == [
            f"idx_{table_name}_id",
            f"idx_{table_name}_take",
            f"idx_{table_name}_update",
            f"{table_name}_pkey",
        ]

    _run(pg_server, body, table_name)
