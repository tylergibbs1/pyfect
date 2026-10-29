"""Ports of Effect's ``sql-sqlite-node/test/Persistence.test.ts``, but
for its ``PersistedQueue`` suites (another module's): the
``BackingPersistence`` suite (``_backing_suite``) on
``layer_backing_sql_multi_table`` (``Persistence (table-per-store)``) and
``layer_backing_sql`` (``Persistence (single-table)``), and
``Persistence SQL cleanup``, over a SQLite database in a temporary
directory.

Each test's docstring is the Effect test title; the two suites are the
``layer`` parameters.
"""

from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.persistence import persistence
from pyfect.sql import sqlite

from . import _backing_suite as suite

_PROBES = {
    # ``... WHERE id IN ('secret', '') UNION SELECT id, value FROM
    # effect_persistence_sqli_victim WHERE ('1'='1') AND ...`` if keys were
    # written into the SQL.
    "table-per-store": (
        "') UNION SELECT id, value FROM effect_persistence_sqli_victim WHERE ('1'='1"
    ),
    # ``... AND id IN ('secret', '') OR store_id='sqli_victim' AND ('1'='1') ...``
    "single-table": "') OR store_id='sqli_victim' AND ('1'='1",
}

_LAYERS = pytest.mark.parametrize(
    "layer",
    [
        pytest.param(persistence.layer_backing_sql_multi_table, id="table-per-store"),
        pytest.param(persistence.layer_backing_sql, id="single-table"),
    ],
)


def _client(tmp_path: Path) -> fx.Layer[Any, Any]:
    return sqlite.layer(sqlite.SqliteClientConfig(filename=str(tmp_path / "test.db")))


def _run(tmp_path: Path, layer: fx.Layer[Any, Any, Any], body: suite.Body) -> None:
    program = fx.scoped(fx.gen(body).pipe(fx.provide(layer)))
    testing.run_test(program.pipe(fx.provide(_client(tmp_path))))


@_LAYERS
def test_set_get(tmp_path: Path, layer: fx.Layer[Any, Any, Any]) -> None:
    """set + get"""
    _run(tmp_path, layer, suite.set_get)


@_LAYERS
def test_set_many_get_many(tmp_path: Path, layer: fx.Layer[Any, Any, Any]) -> None:
    """setMany + getMany"""
    _run(tmp_path, layer, suite.set_many_get_many)


@_LAYERS
def test_get_many_with_duplicate_keys(tmp_path: Path, layer: fx.Layer[Any, Any, Any]) -> None:
    """getMany with duplicate keys"""
    _run(tmp_path, layer, suite.get_many_with_duplicate_keys)


@_LAYERS
def test_remove(tmp_path: Path, layer: fx.Layer[Any, Any, Any]) -> None:
    """remove"""
    _run(tmp_path, layer, suite.remove)


@_LAYERS
def test_expires(tmp_path: Path, layer: fx.Layer[Any, Any, Any]) -> None:
    """expires"""
    _run(tmp_path, layer, suite.expires)


@_LAYERS
def test_reused_get_expires(tmp_path: Path, layer: fx.Layer[Any, Any, Any]) -> None:
    """reused get expires"""
    _run(tmp_path, layer, suite.reused_get_expires)


@_LAYERS
def test_reused_get_many_expires(tmp_path: Path, layer: fx.Layer[Any, Any, Any]) -> None:
    """reused getMany expires"""
    _run(tmp_path, layer, suite.reused_get_many_expires)


@_LAYERS
def test_isolation_between_stores(tmp_path: Path, layer: fx.Layer[Any, Any, Any]) -> None:
    """isolation between stores"""
    _run(tmp_path, layer, suite.isolation_between_stores)


@_LAYERS
def test_get_many_treats_keys_containing_single_quotes_as_data(
    tmp_path: Path, layer: fx.Layer[Any, Any, Any]
) -> None:
    """getMany treats keys containing single quotes as data"""
    _run(tmp_path, layer, suite.get_many_treats_quotes_as_data)


@pytest.mark.parametrize(
    ("layer", "probe"),
    [
        pytest.param(
            persistence.layer_backing_sql_multi_table,
            _PROBES["table-per-store"],
            id="table-per-store",
        ),
        pytest.param(persistence.layer_backing_sql, _PROBES["single-table"], id="single-table"),
    ],
)
def test_get_many_preserves_store_isolation_for_crafted_keys(
    tmp_path: Path, layer: fx.Layer[Any, Any, Any], probe: str
) -> None:
    """getMany preserves store isolation for crafted keys"""
    _run(tmp_path, layer, suite.get_many_preserves_store_isolation(probe))


def test_deletes_expired_entries_in_batches(tmp_path: Path) -> None:
    """Persistence SQL cleanup / deletes expired entries in batches"""
    body = suite.deletes_expired_entries_in_batches(
        "SELECT COUNT(*) AS count FROM sqlite_master "
        "WHERE type = 'index' AND name = 'effect_persistence_expires_idx'"
    )
    testing.run_test(fx.scoped(fx.gen(body)).pipe(fx.provide(_client(tmp_path))))
