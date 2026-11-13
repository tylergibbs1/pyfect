"""(pyfect) Hostile names and values round-trip unchanged on every dialect's real server.

Identifier and value escaping is written per dialect, so each one is checked against its own
server's lexer: a name from ``sql.identifier``, a record key of ``sql.insert`` / ``sql.update``
and the column of ``sql.in_``, and values bound on every path the dialect has (prepared,
unprepared, stream; MySQL also with prepared statements disabled, under each of its quoting
modes). A name or value holding quotes, backslashes, comment markers, NUL (where the server
stores it) or any other text must come back as it went in, as the only column of the only row.

D1 runs on ``_d1_fake`` (a real SQLite database behind D1's HTTP API); the others on the
session's servers (``_postgres``, ``_mysql``, ``_mssql``, ``_libsql``, ``_clickhouse``).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable, Generator, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime
from decimal import Decimal
from typing import Any, LiteralString

import pytest
from hypothesis import example, given, settings
from hypothesis import strategies as st

import pyfect as fx
from pyfect import _json_text as json_text
from pyfect import redacted
from pyfect.sql import SqlClient

from ._clickhouse import PASSWORD as CLICKHOUSE_PASSWORD
from ._clickhouse import USER as CLICKHOUSE_USER
from ._clickhouse import ClickhouseServer
from ._d1_fake import FakeD1
from ._libsql import LibsqlServer
from ._mssql import MssqlServer
from ._mysql import MysqlServer
from ._postgres import PgServer

type Path = Callable[[Any], fx.Effect[Any, Any]]

_SETTINGS = settings(max_examples=25, deadline=None, derandomize=True, database=None)

_FRAGMENTS = (
    "'",
    '"',
    "`",
    "\\",
    "\\'",
    '\\"',
    "\\`",
    "''",
    '""',
    "]",
    "[",
    "]]",
    "--",
    "-- ",
    "#",
    "/*",
    "*/",
    "/*!",
    ";",
    "?",
    "$1",
    ":a",
    "@p1",
    "{p1: String}",
    "{}",
    "%s",
    "\n",
    "\r",
    "\t",
    "\x1a",
    " ",
    "é",
    "ß",
    "\N{LINE SEPARATOR}",
    "\N{ZERO WIDTH NO-BREAK SPACE}",
    "' OR 1=1 -- ",
    '" , 1 AS injected -- ',
)


def _hostile(*, nul: bool, max_codepoint: int = 0x10FFFF, max_size: int = 8) -> Any:
    piece = st.one_of(
        st.sampled_from(_FRAGMENTS),
        st.characters(codec="utf-8", max_codepoint=max_codepoint, exclude_characters="\x00"),
        *([st.just("\x00")] if nul else []),
    )
    return st.lists(piece, max_size=max_size).map("".join)


def _column(tail: str) -> str:
    return "c" + tail.replace(".", "")


_NAMES = _hostile(nul=False, max_codepoint=0xFFFF).map(_column)
"""A column name: never empty, never ``id``, no dot (a dot qualifies a name), no NUL, and in
the Basic Multilingual Plane (MySQL names hold no other characters)."""

_VALUES = _hostile(nul=True, max_size=12)
_BINARY = st.binary(max_size=24) | st.sampled_from(
    [b"' AS b, 2 AS one -- ", b"\\", b"\\'", b"\x00'\x1a\\\"", bytes(range(256))]
)

_KNOWN_NAMES = (
    'c\\" , 1 AS x --',
    "c\\",
    'c\\"',
    "c`",
    "c]",
    'c"',
    "c'",
    "c\\`",
)
_KNOWN_VALUES = ("' AS b, 2 AS one -- ", "\\", "\\'", "') OR 1=1 -- ", "a\x00b", "\\\x00'")


def _known_examples[F: Callable[..., Any]](test: F) -> F:
    for name, value in zip(_KNOWN_NAMES, _KNOWN_VALUES * 2, strict=False):
        test = example(name=name, value=value)(test)
    return test


def _prepared(statement: Any) -> fx.Effect[Any, Any]:
    return statement


def _unprepared(statement: Any) -> fx.Effect[Any, Any]:
    return statement.unprepared


def _stream(statement: Any) -> fx.Effect[Any, Any]:
    return statement.stream.run_collect()


@dataclass(frozen=True)
class Dialect:
    """How one dialect makes, updates and drops the table the check uses."""

    create: LiteralString
    update: LiteralString
    paths: Sequence[Path]
    session: Sequence[LiteralString] = ()
    """Statements run first, on the client's one connection (a SQL mode)."""
    name: Callable[[str], str] = lambda name: name
    """The name made legal for the server (MySQL: no trailing space)."""
    value: Callable[[str], str] = lambda value: value
    """The value made storable (PostgreSQL text holds no NUL)."""
    binary: LiteralString | None = None
    """The type of a binary column, when its bytes round-trip as ``bytes``."""
    extra: Callable[[Any, str], Generator[Any, Any]] | None = field(default=None)
    write: Callable[[Any, Any], Any] = lambda _sql, statement: statement
    """How an ``INSERT`` or ``UPDATE`` runs (ClickHouse: as a command)."""


def _rows(rows: Any) -> list[dict[str, Any]]:
    return [dict(row) for row in rows]


def _table(
    sql: Any, dialect: Dialect, create: LiteralString, *names: Any
) -> Generator[Any, Any, Any]:
    """A fresh table for one check, dropped when its scope closes, after the session's
    statements (a SQL mode)."""
    table = sql.identifier(f"hostile_{uuid.uuid4().hex[:12]}")
    for statement in dialect.session:
        yield from sql.unsafe(statement)
    yield from fx.acquire_release(
        sql(create, table, *names), lambda _, __: sql("DROP TABLE {}", table).ignore()
    )
    return table


def _run(layer: fx.Layer[Any, Any], body: Callable[[], Generator[Any, Any]]) -> None:
    fx.run_blocking(fx.scoped(fx.gen(body)).pipe(fx.provide(layer)).timeout("1 minute").or_die())


def _check(dialect: Dialect, layer: fx.Layer[Any, Any], name: str, value: str) -> None:
    name, value = dialect.name(name), dialect.value(value)
    changed = value + "'\\"
    expected = [{name: value}]

    def body() -> Generator[Any, Any]:
        sql = yield from SqlClient()
        c = sql.identifier(name)
        t = yield from _table(sql, dialect, dialect.create, c)
        yield from dialect.write(
            sql, sql("INSERT INTO {} {}", t, sql.insert({"id": 1, name: value}))
        )
        for path in dialect.paths:
            assert _rows((yield from path(sql("SELECT {} FROM {}", c, t)))) == expected
            where_equal = sql("SELECT {} FROM {} WHERE {} = {}", c, t, c, value)
            assert _rows((yield from path(where_equal))) == expected
            where_in = sql("SELECT {} FROM {} WHERE {}", c, t, sql.in_(name, [value, "x"]))
            assert _rows((yield from path(where_in))) == expected
            selected = sql("SELECT {} AS v, 1 AS one", value)
            assert _rows((yield from path(selected))) == [{"v": value, "one": 1}]
        yield from dialect.write(sql, sql(dialect.update, t, sql.update({name: changed})))
        for path in dialect.paths:
            rows = _rows((yield from path(sql("SELECT * FROM {}", t))))
            assert rows == [{"id": 1, name: changed}]
        if dialect.extra is not None:
            yield from dialect.extra(sql, value)

    _run(layer, body)


def _check_binary(dialect: Dialect, layer: fx.Layer[Any, Any], data: bytes) -> None:
    assert dialect.binary is not None
    create = dialect.binary

    def body() -> Generator[Any, Any]:
        sql = yield from SqlClient()
        t = yield from _table(sql, dialect, create)
        yield from sql("INSERT INTO {} {}", t, sql.insert({"id": 1, "b": data}))
        for path in dialect.paths:
            matched = sql("SELECT id, b FROM {} WHERE b = {}", t, data)
            assert _rows((yield from path(matched))) == [{"id": 1, "b": data}]
            in_list = sql("SELECT id FROM {} WHERE {}", t, sql.in_("b", [data, b"x"]))
            assert _rows((yield from path(in_list))) == [{"id": 1}]

    _run(layer, body)


# --- PostgreSQL ------------------------------------------------------------------


def _pg(server: PgServer) -> fx.Layer[Any, Any]:
    from pyfect.sql import pg

    return pg.layer(pg.PgPoolConfig(url=server.url, max_connections=1))


_PG = Dialect(
    create="CREATE TABLE {} (id INT, {} TEXT)",
    update="UPDATE {} SET {} WHERE id = 1",
    paths=(_prepared, _unprepared, _stream),
    value=lambda value: value.replace("\x00", ""),
    binary="CREATE TABLE {} (id INT, b BYTEA)",
)


@_SETTINGS
@_known_examples
@given(name=_NAMES, value=_VALUES)
def test_pg_round_trips_hostile_names_and_values(pg_server: PgServer, name: str, value: str):
    """(pyfect) pg: hostile names and values round-trip"""
    _check(_PG, _pg(pg_server), name, value)


@_SETTINGS
@given(data=_BINARY)
def test_pg_round_trips_hostile_bytes(pg_server: PgServer, data: bytes):
    """(pyfect) pg: hostile bytes round-trip"""
    _check_binary(_PG, _pg(pg_server), data)


# --- MySQL -----------------------------------------------------------------------

_MYSQL_MODES: tuple[LiteralString, ...] = (
    "SET SESSION sql_mode = DEFAULT",
    "SET SESSION sql_mode = 'NO_BACKSLASH_ESCAPES'",
    "SET SESSION sql_mode = CONCAT(@@sql_mode, ',ANSI_QUOTES')",
    "SET SESSION sql_mode = 'NO_BACKSLASH_ESCAPES,ANSI_QUOTES'",
)


def _mysql(server: MysqlServer, *, prepared: bool) -> fx.Layer[Any, Any]:
    from pyfect.sql import mysql

    # One connection, so the session's SQL mode holds for every statement after it.
    return mysql.layer(
        mysql.MysqlClientConfig(
            url=server.url, max_connections=1, disable_prepared_statements=not prepared
        )
    )


def _mysql_other_values(sql: Any, value: str) -> Generator[Any, Any]:
    """The other values the text protocol writes: a tuple (``IN``), a list, a dict (JSON
    text), and the types whose literal the driver formats."""
    document = {value: [value, {"k": value}]}
    for path in (_unprepared, _stream):
        found = sql("SELECT 1 AS hit FROM DUAL WHERE {} IN {}", value, ("x", value))
        assert _rows((yield from path(found))) == [{"hit": 1}]
        missed = sql("SELECT 1 AS hit FROM DUAL WHERE 'z' IN {}", ("x", value))
        assert _rows((yield from path(missed))) == []
        nested = sql("SELECT 1 AS hit FROM DUAL WHERE ({}) IN {}", value, ((value,), ("x",)))
        assert _rows((yield from path(nested))) == [{"hit": 1}]
        listed = sql("SELECT 1 AS hit FROM DUAL WHERE {} IN ({})", value, ["x", value])
        assert _rows((yield from path(listed))) == [{"hit": 1}]
        as_json = sql("SELECT {} AS j", document)
        assert _rows((yield from path(as_json))) == [{"j": json_text.stringify(document)}]
        fixed = sql(
            "SELECT {} IS NULL AS a, {} AS b, CAST({} AS DECIMAL(10, 2)) AS c,"
            " CAST({} AS DATETIME(6)) AS d, CAST({} AS DATE) AS e, {} AS f",
            None,
            True,
            Decimal("-12.50"),
            datetime(2024, 1, 2, 3, 4, 5, 6),
            date(2024, 1, 2),
            uuid.UUID(int=7),
        )
        assert _rows((yield from path(fixed))) == [
            {
                "a": 1,
                "b": 1,
                "c": Decimal("-12.50"),
                "d": datetime(2024, 1, 2, 3, 4, 5, 6),
                "e": date(2024, 1, 2),
                "f": str(uuid.UUID(int=7)),
            }
        ]


def _mysql_dialect(mode: LiteralString) -> Dialect:
    return Dialect(
        create="CREATE TABLE {} (id INT, {} LONGTEXT)",
        update="UPDATE {} SET {} WHERE id = 1",
        paths=(_prepared, _unprepared, _stream),
        session=(mode,),
        name=lambda name: name.rstrip(),
        binary="CREATE TABLE {} (id INT, b LONGBLOB)",
        extra=_mysql_other_values,
    )


_MYSQL_SESSIONS = pytest.mark.parametrize(
    ("prepared", "mode"),
    [(prepared, mode) for prepared in (True, False) for mode in _MYSQL_MODES],
)


@_MYSQL_SESSIONS
@_SETTINGS
@_known_examples
@given(name=_NAMES, value=_VALUES)
def test_mysql_round_trips_hostile_names_and_values(
    mysql_server: MysqlServer, prepared: bool, mode: LiteralString, name: str, value: str
):
    """(pyfect) mysql: hostile names and values round-trip, in every quoting mode, with
    prepared statements on and off"""
    _check(_mysql_dialect(mode), _mysql(mysql_server, prepared=prepared), name, value)


@_MYSQL_SESSIONS
@_SETTINGS
@given(data=_BINARY)
def test_mysql_round_trips_hostile_bytes(
    mysql_server: MysqlServer, prepared: bool, mode: LiteralString, data: bytes
):
    """(pyfect) mysql: hostile bytes round-trip, in every quoting mode, with prepared
    statements on and off"""
    _check_binary(_mysql_dialect(mode), _mysql(mysql_server, prepared=prepared), data)


# --- SQL Server ------------------------------------------------------------------


def _mssql(server: MssqlServer) -> fx.Layer[Any, Any]:
    from pyfect.sql import mssql

    return mssql.layer(
        mssql.MssqlClientConfig(
            server=server.host,
            port=server.port,
            database=server.database,
            username=server.username,
            password=server.password,
            trust_server=True,
        )
    )


_MSSQL = Dialect(
    create="CREATE TABLE {} (id INT, {} NVARCHAR(MAX))",
    update="UPDATE {} SET {} WHERE id = 1",
    paths=(_prepared, _unprepared),
    binary="CREATE TABLE {} (id INT, b VARBINARY(MAX))",
)


@_SETTINGS
@_known_examples
@given(name=_NAMES, value=_VALUES)
def test_mssql_round_trips_hostile_names_and_values(
    mssql_server: MssqlServer, name: str, value: str
):
    """(pyfect) mssql: hostile names and values round-trip"""
    _check(_MSSQL, _mssql(mssql_server), name, value)


@_SETTINGS
@given(data=_BINARY)
def test_mssql_round_trips_hostile_bytes(mssql_server: MssqlServer, data: bytes):
    """(pyfect) mssql: hostile bytes round-trip"""
    _check_binary(_MSSQL, _mssql(mssql_server), data)


# --- SQLite, libSQL, D1 ----------------------------------------------------------

_SQLITE = Dialect(
    create="CREATE TABLE {} (id INTEGER, {} TEXT)",
    update="UPDATE {} SET {} WHERE id = 1",
    paths=(_prepared, _unprepared),
    binary="CREATE TABLE {} (id INTEGER, b BLOB)",
)


def _sqlite() -> fx.Layer[Any, Any]:
    from pyfect.sql import sqlite

    return sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))


@_SETTINGS
@_known_examples
@given(name=_NAMES, value=_VALUES)
def test_sqlite_round_trips_hostile_names_and_values(name: str, value: str):
    """(pyfect) sqlite: hostile names and values round-trip"""
    _check(_SQLITE, _sqlite(), name, value)


@_SETTINGS
@given(data=_BINARY)
def test_sqlite_round_trips_hostile_bytes(data: bytes):
    """(pyfect) sqlite: hostile bytes round-trip"""
    _check_binary(_SQLITE, _sqlite(), data)


def _libsql(server: LibsqlServer) -> fx.Layer[Any, Any]:
    from pyfect.sql import libsql
    from pyfect.sql.libsql import LibsqlClientConfig

    return libsql.layer(LibsqlClientConfig(url=server.url))


@_SETTINGS
@_known_examples
@given(name=_NAMES, value=_VALUES)
def test_libsql_round_trips_hostile_names_and_values(
    libsql_server: LibsqlServer, name: str, value: str
):
    """(pyfect) libsql: hostile names and values round-trip"""
    _check(_SQLITE, _libsql(libsql_server), name, value)


@_SETTINGS
@given(data=_BINARY)
def test_libsql_round_trips_hostile_bytes(libsql_server: LibsqlServer, data: bytes):
    """(pyfect) libsql: hostile bytes round-trip"""
    _check_binary(_SQLITE, _libsql(libsql_server), data)


@_SETTINGS
@_known_examples
@given(name=_NAMES, value=_VALUES)
def test_d1_round_trips_hostile_names_and_values(name: str, value: str):
    """(pyfect) d1: hostile names and values round-trip"""
    _check(_SQLITE, FakeD1().client_layer(), name, value)


# --- ClickHouse ------------------------------------------------------------------


def _clickhouse(server: ClickhouseServer) -> fx.Layer[Any, Any]:
    from pyfect.sql import clickhouse

    return clickhouse.layer(
        clickhouse.ClickhouseClientConfig(
            url=server.url,
            username=CLICKHOUSE_USER,
            password=redacted.make(CLICKHOUSE_PASSWORD),
        )
    )


_CLICKHOUSE = Dialect(
    create="CREATE TABLE {} (id Int32, {} String) ENGINE = MergeTree ORDER BY id",
    update="ALTER TABLE {} UPDATE {} WHERE id = 1 SETTINGS mutations_sync = 2",
    paths=(_prepared, _unprepared, _stream),
    write=lambda sql, statement: sql.as_command(statement),
)


@_SETTINGS
@_known_examples
@given(name=_NAMES, value=_VALUES)
def test_clickhouse_round_trips_hostile_names_and_values(
    clickhouse_server: ClickhouseServer, name: str, value: str
):
    """(pyfect) clickhouse: hostile names and values round-trip"""
    _check(_CLICKHOUSE, _clickhouse(clickhouse_server), name, value)


def test_every_dialect_is_checked():
    """(pyfect) every SQL dialect pyfect ships has a hostile round trip here"""
    import pkgutil

    import pyfect.sql

    dialects = {
        module.name
        for module in pkgutil.iter_modules(pyfect.sql.__path__)
        if module.ispkg and module.name not in ("client", "statement")
    }
    checked = {
        name.removeprefix("test_").split("_round_trips")[0]
        for name in globals()
        if name.startswith("test_") and "_round_trips_hostile_names" in name
    }
    assert dialects == checked
    pytest.importorskip("hypothesis")
