"""Ports of Effect's ``sql-mssql/test/KeyValueStore.integration.test.ts`` on
the session's SQL Server container (``_mssql.mssql_server``; skipped without
Docker): the ``persistence/KeyValueStoreTest.ts`` suite (``_kv_suite``, with
its ``clearPrefixSuite``) on ``layer_sql`` over a table made first with a
case-insensitive key collation (``sql-mssql-ci``), and the file's own title
on ``layer_backing_kvs`` over such a table.

Each test's docstring is the Effect test title. Adapted: each test drops
its table first, since the server is shared by every test of the session.
``clears keys beyond a prefix followed by U+FFFF`` runs on ``layer_sql``'s
own table: the case-insensitive collation calls ``edge`` and ``edge\uffff``
one key, which Effect's ``MERGE`` then writes as one row, while pyfect
compares keys exactly (the kept SQL key row of PARITY section 4), so the
second write fails on the primary key (pinned below).
"""

from __future__ import annotations

from typing import Any

import pytest

pytest.importorskip("pytds")

import pyfect as fx
from pyfect import testing
from pyfect.persistence import key_value_store as kvs
from pyfect.persistence import persistence
from pyfect.sql import SqlClient, mssql
from pyfect.sql.error import SqlError, UniqueViolation

from . import _kv_suite as suite
from ._mssql import MssqlServer, query_now


def _layer(server: MssqlServer, table: str) -> fx.Layer[kvs.KeyValueStore, Any, Any]:
    """``layer_sql(table=table)`` over a table whose key collation ignores
    case, even when the server's default is binary."""
    query_now(f"DROP TABLE IF EXISTS {table}")

    def build():
        sql = yield from SqlClient()
        yield from sql(
            "CREATE TABLE {} (id NVARCHAR(450) COLLATE Latin1_General_100_CI_AS PRIMARY KEY, "
            "value VARBINARY(MAX) NOT NULL, value_type SMALLINT NOT NULL)",
            sql.identifier(table),
        )
        return kvs.layer_sql(table=table)

    return fx.layer.unwrap(fx.gen(build)).pipe(fx.provide(mssql.layer(server.config())))


_SUITE = {
    "set + get + size": suite.set_get_size,
    "binary values": suite.binary_values,
    "string values are not decoded as base64": suite.string_values_are_not_decoded_as_base64,
    "utf8 string values": suite.utf8_string_values,
    "keys": suite.keys,
    "remove": suite.remove,
    "clear": suite.clear,
    **suite.CLEAR_PREFIX_SUITE,
}
_UFFFF = "clears keys beyond a prefix followed by U+FFFF"


@pytest.mark.parametrize("title", [title for title in _SUITE if title != _UFFFF])
def test_key_value_store_suite(mssql_server: MssqlServer, title: str) -> None:
    """KeyValueStore (sql-mssql-ci): each title of ``KeyValueStoreTest.suite``"""
    suite.run(_layer(mssql_server, "effect_key_value_store_ci"), _SUITE[title])


def test_clears_keys_beyond_a_prefix_followed_by_uffff(mssql_server: MssqlServer) -> None:
    """clears keys beyond a prefix followed by U+FFFF: on the store's own (binary) table"""
    query_now("DROP TABLE IF EXISTS effect_key_value_store_bin")
    layer = kvs.layer_sql(table="effect_key_value_store_bin").pipe(
        fx.provide(mssql.layer(mssql_server.config()))
    )
    suite.run(layer, suite.clears_keys_beyond_a_prefix_followed_by_uffff)


def test_a_case_insensitive_table_refuses_keys_its_collation_merges(
    mssql_server: MssqlServer,
) -> None:
    def body():
        kv = yield from kvs.KeyValueStore()
        yield from kv.set("edge", "first")
        error = yield from kv.set("edge\uffff", "second").flip()
        assert isinstance(error, kvs.KeyValueStoreError)
        assert isinstance(error.cause, SqlError)
        assert isinstance(error.cause.reason, UniqueViolation)
        assert (yield from kv.get("edge")) == "first"

    suite.run(_layer(mssql_server, "effect_key_value_store_ci"), body)


def test_clearing_a_store_preserves_a_differently_cased_store_with_a_distinct_entry_key(
    mssql_server: MssqlServer,
) -> None:
    """BackingPersistence (sql-mssql-ci) / clearing a store preserves a differently cased
    store with a distinct entry key"""

    def body():
        backing = yield from persistence.BackingPersistence()
        lower = yield from backing.make("scope")
        upper = yield from backing.make("SCOPE")
        yield from lower.set("one", {"value": "match"}, None)
        yield from upper.set("two", {"value": "unrelated"}, None)
        yield from lower.clear
        assert (yield from lower.get("one")) is None
        assert (yield from upper.get("two")) == {"value": "unrelated"}

    layer = persistence.layer_backing_kvs.pipe(
        fx.provide(_layer(mssql_server, "effect_backing_kvs_ci"))
    )
    testing.run_test(fx.scoped(fx.gen(body).pipe(fx.provide(layer))).or_die())
