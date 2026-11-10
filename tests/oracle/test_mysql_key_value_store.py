"""Ports of Effect's ``sql-mysql2/test/KeyValueStore.integration.test.ts``: the
``persistence/KeyValueStoreTest.ts`` suite (``_kv_suite``) on ``layer_sql()`` and on
``layer_sql(table="effect_key_value_store_custom")``, on the session's
MySQL container (``_mysql.mysql_server``; skipped without Docker).

Each test's docstring is the Effect test title; the two suites
(``KeyValueStore (sql-mysql2)`` and ``(sql-mysql2-custom-table)``) are the
parameters.
"""

from typing import Any

import pytest

pytest.importorskip("asyncmy")

import pyfect as fx
from pyfect.persistence import key_value_store as kvs
from pyfect.sql import mysql

from . import _kv_suite as suite
from ._mysql import MysqlServer

_TABLES = pytest.mark.parametrize(
    "table",
    [
        pytest.param("effect_key_value_store", id="sql-mysql2"),
        pytest.param("effect_key_value_store_custom", id="sql-mysql2-custom-table"),
    ],
)


def _layer(server: MysqlServer, table: str) -> fx.Layer[kvs.KeyValueStore, Any, Any]:
    client = mysql.layer(mysql.MysqlClientConfig(url=server.url))
    return kvs.layer_sql(table=table).pipe(fx.provide(client))


@_TABLES
def test_set_get_size(mysql_server: MysqlServer, table: str) -> None:
    """set + get + size"""
    suite.run(_layer(mysql_server, table), suite.set_get_size)


@_TABLES
def test_binary_values(mysql_server: MysqlServer, table: str) -> None:
    """binary values"""
    suite.run(_layer(mysql_server, table), suite.binary_values)


@_TABLES
def test_string_values_are_not_decoded_as_base64(mysql_server: MysqlServer, table: str) -> None:
    """string values are not decoded as base64"""
    suite.run(_layer(mysql_server, table), suite.string_values_are_not_decoded_as_base64)


@_TABLES
def test_utf8_string_values(mysql_server: MysqlServer, table: str) -> None:
    """utf8 string values"""
    suite.run(_layer(mysql_server, table), suite.utf8_string_values)


@_TABLES
def test_remove(mysql_server: MysqlServer, table: str) -> None:
    """remove"""
    suite.run(_layer(mysql_server, table), suite.remove)


@_TABLES
def test_clear(mysql_server: MysqlServer, table: str) -> None:
    """clear"""
    suite.run(_layer(mysql_server, table), suite.clear)


@_TABLES
def test_keys(mysql_server: MysqlServer, table: str) -> None:
    """keys"""
    suite.run(_layer(mysql_server, table), suite.keys)


@_TABLES
@pytest.mark.parametrize("title", list(suite.CLEAR_PREFIX_SUITE))
def test_clear_prefix_suite(mysql_server: MysqlServer, table: str, title: str) -> None:
    """KeyValueStore clearPrefix: each title of clearPrefixSuite"""
    suite.run(_layer(mysql_server, table), suite.CLEAR_PREFIX_SUITE[title])
