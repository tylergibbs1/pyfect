"""Ports of Effect's ``sql-sqlite-node/test/KeyValueStore.test.ts``: the
``KeyValueStoreTest`` suite (``_kv_suite``) on ``layer_sql()`` and on
``layer_sql(table="effect_key_value_store_custom")``, over a SQLite
database in a temporary directory.

Each test's docstring is the Effect test title; the two suites
(``KeyValueStore (sql-sqlite)`` and ``(sql-sqlite-custom-table)``) are the
parameters.
"""

from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect.persistence import key_value_store as kvs
from pyfect.sql import sqlite

from . import _kv_suite as suite

_TABLES = pytest.mark.parametrize(
    "table",
    [
        pytest.param("effect_key_value_store", id="sql-sqlite"),
        pytest.param("effect_key_value_store_custom", id="sql-sqlite-custom-table"),
    ],
)


def _layer(tmp_path: Path, table: str) -> fx.Layer[kvs.KeyValueStore, Any, Any]:
    client = sqlite.layer(sqlite.SqliteClientConfig(filename=str(tmp_path / "test.db")))
    return kvs.layer_sql(table=table).pipe(fx.provide(client))


@_TABLES
def test_set_get_size(tmp_path: Path, table: str) -> None:
    """set + get + size"""
    suite.run(_layer(tmp_path, table), suite.set_get_size)


@_TABLES
def test_binary_values(tmp_path: Path, table: str) -> None:
    """binary values"""
    suite.run(_layer(tmp_path, table), suite.binary_values)


@_TABLES
def test_string_values_are_not_decoded_as_base64(tmp_path: Path, table: str) -> None:
    """string values are not decoded as base64"""
    suite.run(_layer(tmp_path, table), suite.string_values_are_not_decoded_as_base64)


@_TABLES
def test_utf8_string_values(tmp_path: Path, table: str) -> None:
    """utf8 string values"""
    suite.run(_layer(tmp_path, table), suite.utf8_string_values)


@_TABLES
def test_remove(tmp_path: Path, table: str) -> None:
    """remove"""
    suite.run(_layer(tmp_path, table), suite.remove)


@_TABLES
def test_clear(tmp_path: Path, table: str) -> None:
    """clear"""
    suite.run(_layer(tmp_path, table), suite.clear)
