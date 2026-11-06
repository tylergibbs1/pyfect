"""On MySQL and SQL Server the SQL persistence and key-value stores compare
keys exactly, as the memory, Redis, SQLite and PostgreSQL stores do. A
server whose default collation ignores case or accents
(``utf8mb4_0900_ai_ci``, ``*_CI_AS``) cannot make ``K:Alice`` and
``K:alice`` one row, and neither can trailing spaces (``K:alice `` and
``K:alice``), which every SQL Server collation and MySQL's ``PAD SPACE``
collations (``utf8mb4_bin`` among them) ignore in ``=``: MySQL keys are
``VARBINARY``, SQL Server keys a ``BIN2`` collation compared with their
length.

No MySQL or SQL Server runs here, so the tests read the DDL each layer
sends on a client of that dialect."""

from __future__ import annotations

import re
from collections.abc import Sequence
from typing import Any

import pytest

import pyfect as fx
from pyfect import reactivity
from pyfect.persistence import key_value_store
from pyfect.persistence.persistence import (
    BackingPersistence,
    layer_backing_sql,
    layer_backing_sql_multi_table,
)
from pyfect.sql import client as sql_client
from pyfect.sql import statement as st
from pyfect.sql.client import SqlClient
from pyfect.sql.connection import Row, TransformRows, ValueRow
from pyfect.sql.error import SqlError

KEY_TYPES = {"mysql": "VARBINARY", "mssql": "NVARCHAR"}
MSSQL_BINARY = "COLLATE Latin1_General_100_BIN2"


class _Recording:
    def __init__(self, sent: list[str], rows: list[Row]) -> None:
        self._sent = sent
        self._rows = rows

    def _run(self, sql: str) -> fx.Effect[list[Any]]:
        return fx.sync(lambda: self._sent.append(sql)).as_(
            self._rows if sql.startswith("SELECT") else []
        )

    def execute(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Effect[Sequence[Row], SqlError]:
        return self._run(sql)

    def execute_raw(self, sql: str, params: Sequence[object], /) -> fx.Effect[object, SqlError]:
        return self._run(sql)

    def execute_values(
        self, sql: str, params: Sequence[object], /
    ) -> fx.Effect[Sequence[ValueRow], SqlError]:
        return self._run(sql)

    def execute_values_unprepared(
        self, sql: str, params: Sequence[object], /
    ) -> fx.Effect[Sequence[ValueRow], SqlError]:
        return self._run(sql)

    def execute_unprepared(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Effect[Sequence[Row], SqlError]:
        return self._run(sql)

    def execute_stream(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Stream[Row, SqlError]:
        return fx.stream.from_effect(self._run(sql)).flat_map(fx.stream.from_iterable)


def _nothing(*_args: object) -> st.Compiled:
    return ("", ())


def _client(dialect: Any, sent: list[str], rows: list[Row] | None = None) -> fx.Layer[SqlClient]:
    compiler = st.make_compiler(
        dialect=dialect,
        placeholder=lambda _index, _value: "?",
        on_identifier=lambda name, _raw: st.default_escape("`")(name),
        on_record_update=_nothing,
        on_custom=_nothing,
    )
    made = sql_client.make(
        driver="test", acquirer=fx.succeed(_Recording(sent, rows or [])), compiler=compiler
    )
    return fx.layer.effect(SqlClient, made).pipe(fx.layer.provide(reactivity.layer))


def _persistence(layer: fx.Layer[BackingPersistence, Any, Any]) -> Any:
    open_store = BackingPersistence().flat_map(lambda backing: backing.make("users"))
    return fx.scoped(open_store).pipe(fx.provide(layer))


def _key_value_store() -> Any:
    return key_value_store.KeyValueStore().pipe(fx.provide(key_value_store.layer_sql()))


def _use_persistence(layer: fx.Layer[BackingPersistence, Any, Any]) -> Any:
    def program() -> Any:
        backing = yield from BackingPersistence()
        store = yield from backing.make("users")
        yield from store.get("K:alice")
        yield from store.get_many(["K:alice"])
        yield from store.set("K:alice", 1, None)
        yield from store.remove("K:alice")

    return fx.scoped(fx.gen(program)).pipe(fx.provide(layer))


def _use_key_value_store() -> Any:
    def program() -> Any:
        store = yield from key_value_store.KeyValueStore()
        yield from store.get("K:alice")
        yield from store.set("K:alice", "1")
        yield from store.remove("K:alice")

    return fx.gen(program).pipe(fx.provide(key_value_store.layer_sql()))


USES = {
    "persistence single table": lambda: _use_persistence(layer_backing_sql),
    "persistence multi table": lambda: _use_persistence(layer_backing_sql_multi_table),
    "key value store": _use_key_value_store,
}


STORES = {
    "persistence single table": lambda: _persistence(layer_backing_sql),
    "persistence multi table": lambda: _persistence(layer_backing_sql_multi_table),
    "key value store": _key_value_store,
}


def _sent(
    dialect: str, program: fx.Effect[Any, Any, Any], rows: list[Row] | None = None
) -> list[str]:
    sent: list[str] = []
    fx.run_blocking(fx.scoped(program).pipe(fx.provide(_client(dialect, sent, rows))).or_die())
    return sent


@pytest.mark.parametrize("dialect", sorted(KEY_TYPES))
@pytest.mark.parametrize("store", sorted(STORES))
def test_every_key_column_compares_exactly(dialect: str, store: str) -> None:
    tables = [sql for sql in _sent(dialect, STORES[store]()) if "CREATE TABLE" in sql]
    assert tables
    for table in tables:
        columns = re.findall(r"\b(store_id|id) ([A-Z]+)([^,]*)", table)
        assert columns, table
        for name, type_, rest in columns:
            assert type_ == KEY_TYPES[dialect], f"{name} in {table}"
            if dialect == "mssql":
                assert MSSQL_BINARY in rest, f"{name} in {table}"


@pytest.mark.parametrize("store", sorted(USES))
def test_sql_server_key_comparisons_count_trailing_spaces(store: str) -> None:
    queries = [sql for sql in _sent("mssql", USES[store]()) if "CREATE TABLE" not in sql]
    key = r"(?<!DATALENGTH\()(?<![\w`\"\[.])((?:\w+\.)?[`\"\[]?(?:store_)?id[`\"\]]?) = "
    compared = [sql for sql in queries if re.search(key, sql)]
    assert compared
    for sql in compared:
        for column in re.findall(key, sql):
            assert f"DATALENGTH({column})" in sql, sql


def test_mysql_binary_keys_read_back_as_text() -> None:
    def program() -> Any:
        backing = yield from BackingPersistence()
        store = yield from backing.make("users")
        return (yield from store.get_many(["K:alice", "K:alice "]))

    rows: list[Row] = [{"id": b"K:alice", "value": "1"}]
    sent: list[str] = []
    found = fx.run_blocking(
        fx.scoped(fx.gen(program))
        .pipe(fx.provide(layer_backing_sql_multi_table))
        .pipe(fx.provide(_client("mysql", sent, rows)))
        .or_die()
    )
    assert found == [1, None]
