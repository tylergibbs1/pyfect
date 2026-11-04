"""Ports of Effect's ``sql-mysql2/test/Persistence.integration.test.ts`` on
the session's MySQL container (``_mysql.mysql_server``; skipped without
Docker): the ``PersistedCacheTest`` suite (``_persisted_cache_suite``) on
``layer_sql_multi_table`` (``PersistedCache (sql-mysql2-multi)``) and
``layer_sql`` (``(sql-mysql2-single)``), the ``PersistedQueueTest`` suite
(``_persisted_queue_suite``) on ``layer_store_sql`` (``PersistedQueue
(sql-mysql2)``), the ``PersistedQueueSqlTest`` suite
(``_persisted_queue_sql_suite``), and the file's own two titles.

Each test's docstring is the Effect test title. Adapted: each title's
tables are dropped first, since the server is shared by every test of the
session (Effect's container is the file's own).
"""

from __future__ import annotations

from typing import Any, Literal

import pytest

pytest.importorskip("asyncmy")

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.persistence import persisted_queue as pq
from pyfect.persistence import persistence
from pyfect.sql import SqlClient, mysql

from . import _backing_suite as backing_suite
from . import _persisted_cache_suite as cache_suite
from . import _persisted_queue_sql_suite as sql_suite
from . import _persisted_queue_suite as queue_suite
from ._mysql import MysqlServer, query_now

pytestmark = pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")


def _client(server: MysqlServer) -> fx.Layer[Any, Any]:
    return mysql.layer(mysql.MysqlClientConfig(url=server.url))


def _drop(*tables: str) -> None:
    names = ", ".join(f"{t}, {t}_migrations" for t in tables)
    query_now(f"DROP TABLE IF EXISTS {names}")


# --- PersistedCache -------------------------------------------------------------------

_LAYERS = pytest.mark.parametrize(
    ("layer", "store_id"),
    [
        pytest.param(persistence.layer_sql_multi_table, "sql-mysql2-multi", id="sql-mysql2-multi"),
        pytest.param(persistence.layer_sql, "sql-mysql2-single", id="sql-mysql2-single"),
    ],
)


def _with(server: MysqlServer, layer: fx.Layer[Any, Any, Any]) -> fx.Layer[Any, Any]:
    return layer.pipe(fx.provide(_client(server)))


@_LAYERS
def test_smoke_test(mysql_server: MysqlServer, layer: fx.Layer[Any, Any, Any], store_id: str):
    """smoke test"""
    cache_suite.run(_with(mysql_server, layer), cache_suite.smoke_test)


@_LAYERS
@pytest.mark.parametrize("outcome", ["success", "error"])
def test_recomputes_and_replaces_entries_with_stale_schemas(
    mysql_server: MysqlServer,
    layer: fx.Layer[Any, Any, Any],
    store_id: str,
    outcome: Literal["success", "error"],
):
    """recomputes and replaces entries with stale ${outcome} schemas"""
    cache_suite.run(_with(mysql_server, layer), cache_suite.recomputes_stale(store_id, outcome))


@_LAYERS
def test_require_services_at_lookup_requires_lookup_services_at_get_time(
    mysql_server: MysqlServer, layer: fx.Layer[Any, Any, Any], store_id: str
):
    """requireServicesAt: 'lookup' requires lookup services at get-time"""
    cache_suite.run(_with(mysql_server, layer), cache_suite.require_services_at_lookup(store_id))


def test_deletes_expired_entries_in_batches(mysql_server: MysqlServer):
    """deletes expired entries in batches"""
    body = backing_suite.deletes_expired_entries_in_batches(
        "SELECT COUNT(*) AS count FROM information_schema.statistics "
        "WHERE table_schema = DATABASE() AND table_name = 'effect_persistence' "
        "AND index_name = 'effect_persistence_expires_idx'",
        key_type="VARCHAR(191)",
    )

    def fresh_table():
        sql = yield from SqlClient()
        yield from sql("DROP TABLE IF EXISTS effect_persistence")
        yield from fx.gen(body)

    testing.run_test(
        fx.scoped(fx.gen(fresh_table)).pipe(fx.provide(_client(mysql_server))).or_die()
    )


# --- PersistedQueue -------------------------------------------------------------------


class _Server:
    server: MysqlServer

    @pytest.fixture(autouse=True)
    def _server(self, mysql_server: MysqlServer) -> None:
        self.server = mysql_server

    def client(self) -> fx.Layer[Any, Any]:
        return _client(self.server)


class TestPersistedQueueMysql(_Server, queue_suite.PersistedQueueSuite):
    """PersistedQueue (sql-mysql2)"""

    @pytest.fixture(autouse=True)
    def _fresh_table(self, _server: None) -> None:
        _drop("effect_queue")

    def make_layer(self) -> fx.Layer[pq.PersistedQueueStore, Any, Any]:
        return pq.layer_store_sql().pipe(fx.provide(self.client()))


class TestPersistedQueueMysqlSql(_Server, sql_suite.PersistedQueueSqlSuite):
    """PersistedQueue SQL delays / PersistedQueue SQL claims (sql-mysql2)"""

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


def test_round_trips_queue_payloads_larger_than_64kb(mysql_server: MysqlServer):
    """round-trips queue payloads larger than 64KB"""
    _drop("effect_queue_large_payload")

    def body():
        store = yield from pq.make_store_sql(
            table_name="effect_queue_large_payload", poll_interval=0.01
        )
        factory = yield from pq.make_factory.pipe(fx.provide_service(pq.PersistedQueueStore, store))
        queue = yield from factory.make(name="large-payload", schema=S.String)
        payload = "x" * 200_000
        yield from queue.offer(payload)
        value = yield from queue.take(lambda value, _meta: fx.succeed(value))
        assert value == payload

    program = testing.with_live(fx.scoped(fx.gen(body)))
    testing.run_test(program.pipe(fx.provide(_client(mysql_server))).or_die())
