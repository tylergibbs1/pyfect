"""Anonymous records (``ROW(...)``, ``(a, b)``) read with typed fields, as Effect's
``@effect/sql-pg`` reads them since Effect-TS/effect#10716, against a throwaway local
PostgreSQL (``_postgres.pg_server``; skipped without one).

The record cases of Effect's ``PgTypes.test.ts`` for #10716 that a server can produce: a
NULL field, nested records and arrays, an empty record, a record array, an unregistered text
field (``xml``), an unregistered binary field (``point``, which fails naming OID 600) and a
codec the client's registry (here ``config.types``) has for a field. Not ported: malformed
record bytes (a server never sends them; psycopg parses the record) and encoding a record
(PostgreSQL rejects anonymous record input itself).

A record's array of fields is a tuple. The rest pins what the binary results must not
change: every other column reads as it does without a record beside it.
"""

from datetime import date
from decimal import Decimal
from typing import Any

import pytest

pytest.importorskip("psycopg")

import psycopg
from psycopg import pq
from psycopg.adapt import AdaptersMap, Loader

import pyfect as fx
from pyfect import testing
from pyfect.scope import Scope
from pyfect.sql import pg
from pyfect.sql.error import SqlError
from pyfect.sql.pg.connection import PgConnection

from ._postgres import PgServer


def _connect(server: PgServer, **fields: Any) -> fx.Effect[PgConnection, SqlError, Scope]:
    return pg.connection.make(pg.PgConnectionConfig(url=server.url, **fields))


def _record(
    connection: PgConnection, sql: str, params: list[object] | None = None
) -> fx.Effect[Any, SqlError]:
    return connection.query(sql, params or []).map(lambda result: result.rows[0]["record"])


@testing.effect
def test_reads_null_nested_and_empty_records_with_typed_fields(pg_server: PgServer):
    connection = yield from _connect(pg_server)
    record = yield from _record(
        connection,
        "SELECT ROW(1, 'a', NULL::int4, ROW(true, ARRAY[1, 2]), ROW(), "
        "'2024-05-06'::date, '\\x00ff'::bytea, 0.5::float4) AS record",
    )
    assert record == (1, "a", None, (True, [1, 2]), (), date(2024, 5, 6), b"\x00\xff", 0.5)


@testing.effect
def test_reads_a_record_built_from_bound_parameters(pg_server: PgServer):
    connection = yield from _connect(pg_server)
    record = yield from _record(connection, "SELECT ROW($1::int8, $2::text) AS record", [7, "b"])
    assert record == (7, "b")


@testing.effect
def test_reads_records_through_query_values_and_streams(pg_server: PgServer):
    connection = yield from _connect(pg_server)
    sql = "SELECT ROW(n, n::text) AS record FROM generate_series(1, 2) AS n"
    values = yield from connection.query_values(sql)
    streamed = yield from connection.stream(sql).run_collect()
    assert values == [((1, "1"),), ((2, "2"),)]
    assert streamed == [{"record": (1, "1")}, {"record": (2, "2")}]


@testing.effect
def test_reads_records_once_the_statement_is_prepared(pg_server: PgServer):
    connection = yield from _connect(pg_server)
    records = yield from fx.for_each(
        range(7), lambda n: _record(connection, "SELECT ROW($1::int4) AS record", [n])
    )
    assert records == [(n,) for n in range(7)]


@testing.effect
def test_reads_text_like_fields_of_unregistered_types_as_strings(pg_server: PgServer):
    connection = yield from _connect(pg_server)
    yield from connection.query("CREATE TYPE record_mood AS ENUM ('ok')")
    record = yield from _record(connection, "SELECT ROW('<a/>'::xml, 'ok'::record_mood) AS record")
    yield from connection.query("DROP TYPE record_mood")
    assert record == ("<a/>", "ok")


@testing.effect
def test_fails_on_an_unregistered_binary_field_naming_its_type(pg_server: PgServer):
    connection = yield from _connect(pg_server)
    error = yield from _record(connection, "SELECT ROW(point(1, 2)) AS record").flip()
    assert isinstance(error, SqlError)
    assert isinstance(error.reason.cause, psycopg.DataError)
    assert "type OID 600" in str(error.reason.cause)


class _UpperXml(Loader):
    format = pq.Format.BINARY

    def load(self, data: Any) -> str:
        return bytes(data).decode().upper()


@testing.effect
def test_uses_a_binary_loader_from_config_types_for_a_field(pg_server: PgServer):
    types = AdaptersMap(psycopg.adapters)
    types.register_loader("xml", _UpperXml)
    connection = yield from _connect(pg_server, types=types)
    record = yield from _record(connection, "SELECT ROW('<a/>'::xml) AS record")
    assert record == ("<A/>",)


@testing.effect
def test_leaves_the_other_columns_as_they_read_without_a_record(pg_server: PgServer):
    connection = yield from _connect(pg_server)
    sql = (
        "SELECT ROW(1) AS record, 1.1::float8 AS real, '{1.1}'::float8[] AS reals, "
        "'1.10'::numeric AS amount, '{\"a\": 1}'::jsonb AS doc, 'x'::name AS label"
    )
    alone = yield from connection.query(sql.replace("ROW(1) AS record, ", ""))
    beside = yield from connection.query(sql)
    assert beside.rows == [{"record": (1,), **alone.rows[0]}]
    assert alone.rows == [
        {"real": 1.1, "reals": [1.1], "amount": Decimal("1.10"), "doc": {"a": 1}, "label": "x"}
    ]


@pytest.mark.parametrize(
    ("column", "value"),
    [("'pg_class'::regclass", "pg_class"), ("1.1::float4", 1.1), ("'{1.1}'::float4[]", [1.1])],
)
@testing.effect
def test_keeps_a_column_that_reads_differently_in_binary_as_text(
    pg_server: PgServer, column: str, value: object
):
    """``regclass`` has no binary loader, and ``float4`` reads in binary as its exact value
    (``1.100000023841858``), so such a column keeps its statement in text, and its record's
    fields read as strings, as before."""
    connection = yield from _connect(pg_server)
    result = yield from connection.query(f"SELECT ROW(1) AS record, {column} AS other")
    assert result.rows == [{"record": ("1",), "other": value}]


@testing.effect
def test_reads_a_named_composite_type_as_text(pg_server: PgServer):
    """Named composite types have their own OID and take the text fallback."""
    connection = yield from _connect(pg_server)
    yield from connection.query("CREATE TYPE record_pair AS (a int4, b text)")
    result = yield from connection.query("SELECT ROW(1, 'a')::record_pair AS pair")
    yield from connection.query("DROP TYPE record_pair")
    assert result.rows == [{"pair": "(1,a)"}]


class _TaggedInt(Loader):
    def load(self, data: Any) -> str:
        return f"int:{bytes(data).decode()}"


@testing.effect
def test_keeps_a_text_loader_from_config_types_for_a_column(pg_server: PgServer):
    """A text loader in ``config.types`` with no binary one keeps its column's statement in
    text, so the loader still reads the column."""
    types = AdaptersMap(psycopg.adapters)
    types.register_loader("int4", _TaggedInt)
    connection = yield from _connect(pg_server, types=types)
    result = yield from connection.query("SELECT ROW(1) AS record, 2::int4 AS tagged")
    assert result.rows == [{"record": ("1",), "tagged": "int:2"}]
