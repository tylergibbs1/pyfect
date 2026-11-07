"""Ports of Effect's ``sql-pg/test/KeyValueStore.integration.test.ts``: the
``persistence/KeyValueStoreTest.ts`` suite (``_kv_suite``) on ``layer_sql()`` and on
``layer_sql(table="effect_key_value_store_custom")``, on the throwaway
PostgreSQL server (``_postgres.pg_server``; skipped without one).

Each test's docstring is the Effect test title; the two suites
(``KeyValueStore (sql-pg)`` and ``(sql-pg-custom-table)``) are the
parameters.
"""

from typing import Any

import pytest

pytest.importorskip("psycopg")

import pyfect as fx
from pyfect.persistence import key_value_store as kvs
from pyfect.sql import pg

from . import _kv_suite as suite
from ._postgres import PgServer

_TABLES = pytest.mark.parametrize(
    "table",
    [
        pytest.param("effect_key_value_store", id="sql-pg"),
        pytest.param("effect_key_value_store_custom", id="sql-pg-custom-table"),
    ],
)


def _layer(server: PgServer, table: str) -> fx.Layer[kvs.KeyValueStore, Any, Any]:
    client = pg.layer(pg.PgPoolConfig(url=server.url))
    return kvs.layer_sql(table=table).pipe(fx.provide(client))


@_TABLES
def test_set_get_size(pg_server: PgServer, table: str) -> None:
    """set + get + size"""
    suite.run(_layer(pg_server, table), suite.set_get_size)


@_TABLES
def test_binary_values(pg_server: PgServer, table: str) -> None:
    """binary values"""
    suite.run(_layer(pg_server, table), suite.binary_values)


@_TABLES
def test_string_values_are_not_decoded_as_base64(pg_server: PgServer, table: str) -> None:
    """string values are not decoded as base64"""
    suite.run(_layer(pg_server, table), suite.string_values_are_not_decoded_as_base64)


@_TABLES
def test_utf8_string_values(pg_server: PgServer, table: str) -> None:
    """utf8 string values"""
    suite.run(_layer(pg_server, table), suite.utf8_string_values)


@_TABLES
def test_remove(pg_server: PgServer, table: str) -> None:
    """remove"""
    suite.run(_layer(pg_server, table), suite.remove)


@_TABLES
def test_clear(pg_server: PgServer, table: str) -> None:
    """clear"""
    suite.run(_layer(pg_server, table), suite.clear)
