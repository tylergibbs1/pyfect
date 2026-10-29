"""Ports of Effect's ``sql-pg/test/Persistence.integration.test.ts``, but
for its ``PersistedQueue`` suites (another module's): the
``PersistedCacheTest`` suite (``_persisted_cache_suite``) on
``layer_sql_multi_table`` (``PersistedCache (sql-pg-multi)``) and
``layer_sql`` (``PersistedCache (sql-pg-single)``), and ``Persistence SQL
cleanup``, on the throwaway PostgreSQL server (``_postgres.pg_server``;
skipped without one).

Each test's docstring is the Effect test title; the two suites are the
``layer`` parameters. Adapted: the cleanup test drops
``effect_persistence`` before creating it, since the server is shared by
every test of the session (Effect's container is the file's own).
"""

from typing import Any, Literal

import pytest

pytest.importorskip("psycopg")

import pyfect as fx
from pyfect import testing
from pyfect.persistence import persistence
from pyfect.sql import SqlClient, pg

from . import _backing_suite as backing_suite
from . import _persisted_cache_suite as suite
from ._postgres import PgServer

_LAYERS = pytest.mark.parametrize(
    ("layer", "store_id"),
    [
        pytest.param(persistence.layer_sql_multi_table, "sql-pg-multi", id="sql-pg-multi"),
        pytest.param(persistence.layer_sql, "sql-pg-single", id="sql-pg-single"),
    ],
)


def _client(server: PgServer) -> fx.Layer[Any, Any]:
    return pg.layer(pg.PgPoolConfig(url=server.url))


def _with(server: PgServer, layer: fx.Layer[Any, Any, Any]) -> fx.Layer[Any, Any]:
    return layer.pipe(fx.provide(_client(server)))


@_LAYERS
def test_smoke_test(pg_server: PgServer, layer: fx.Layer[Any, Any, Any], store_id: str) -> None:
    """smoke test"""
    suite.run(_with(pg_server, layer), suite.smoke_test)


@_LAYERS
@pytest.mark.parametrize("outcome", ["success", "error"])
def test_recomputes_and_replaces_entries_with_stale_schemas(
    pg_server: PgServer,
    layer: fx.Layer[Any, Any, Any],
    store_id: str,
    outcome: Literal["success", "error"],
) -> None:
    """recomputes and replaces entries with stale ${outcome} schemas"""
    suite.run(_with(pg_server, layer), suite.recomputes_stale(store_id, outcome))


@_LAYERS
def test_require_services_at_lookup_requires_lookup_services_at_get_time(
    pg_server: PgServer, layer: fx.Layer[Any, Any, Any], store_id: str
) -> None:
    """requireServicesAt: 'lookup' requires lookup services at get-time"""
    suite.run(_with(pg_server, layer), suite.require_services_at_lookup(store_id))


def test_deletes_expired_entries_in_batches(pg_server: PgServer) -> None:
    """Persistence SQL cleanup / deletes expired entries in batches"""
    body = backing_suite.deletes_expired_entries_in_batches(
        "SELECT COUNT(*)::INT AS count FROM pg_indexes "
        "WHERE tablename = 'effect_persistence' "
        "AND indexname = 'effect_persistence_expires_idx'"
    )

    def fresh_table():
        sql = yield from SqlClient()
        yield from sql("DROP TABLE IF EXISTS effect_persistence")
        yield from fx.gen(body)

    testing.run_test(fx.scoped(fx.gen(fresh_table)).pipe(fx.provide(_client(pg_server))).or_die())
