"""Every pyfect SQL table compares its keys exactly on MySQL and SQL Server.

Both servers compare text under the column's collation, and the usual
defaults ignore case (and on MySQL accents), so a key column left in the
server's default collation makes ``Alice`` and ``alice`` one key (GitHub
issue #1, audit finding 20). Each schema below is built, by the module's
own migrations or table setup, on a real server in a database whose
default collation ignores case, accents and trailing spaces; the test then
reads the columns the server made. A text column that is indexed, or
whose name says it holds an id, a key, a name, a type or an address, must
be exact: binary (``VARBINARY``, ``BINARY``, ``BLOB``) or in a binary
collation (MySQL's ``NO PAD`` ``utf8mb4_0900_bin``, SQL Server's
``*_BIN2``). SQL Server's ``=`` still ignores trailing spaces under
``BIN2``, so the stores also compare lengths (``persistence._sql_keys``);
each store's integration tests pin that on the server.

``test_every_module_with_ddl_is_checked`` keeps the list complete: a module
of ``src/pyfect`` that creates a table fails it until its schema is added
below (or it is listed as running on neither server).

Skipped without Docker.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect.cluster import sql_message_storage, sql_runner_storage
from pyfect.crypto import digest
from pyfect.eventlog import sql_event_log_server_encrypted, sql_event_log_server_unencrypted
from pyfect.persistence import key_value_store
from pyfect.persistence.persisted_queue._sql_migrations import migrations as queue_migrations
from pyfect.persistence.persistence import (
    BackingPersistence,
    layer_backing_sql,
    layer_backing_sql_multi_table,
)
from pyfect.sql import SqlClient, migrator

SRC = Path(__file__).resolve().parents[2] / "src" / "pyfect"

type Build = Callable[[], fx.Effect[Any, Any, Any]]


def _persistence(layer: fx.Layer[BackingPersistence, Any, Any]) -> Build:
    return lambda: fx.scoped(
        BackingPersistence().flat_map(lambda backing: backing.make("users"))
    ).pipe(fx.provide(layer))


def _key_value_store() -> fx.Effect[Any, Any, Any]:
    return key_value_store.KeyValueStore().pipe(fx.provide(key_value_store.layer_sql(table="kv")))


def _queue() -> fx.Effect[Any, Any, Any]:
    return migrator.make()(loader=queue_migrations("queue"), table="queue_migrations")


def _event_log_encrypted() -> fx.Effect[Any, Any, Any]:
    return fx.scoped(
        sql_event_log_server_encrypted.make_storage(
            entry_table_prefix="enc_events", remote_id_table="enc_remote_id"
        )
    ).pipe(fx.provide(digest.layer_web_crypto))


def _event_log_unencrypted() -> fx.Effect[Any, Any, Any]:
    return fx.scoped(
        sql_event_log_server_unencrypted.make_storage(
            entry_table_prefix="plain_events", remote_id_table="plain_remote_id"
        )
    )


@dataclass(frozen=True)
class Schema:
    module: str
    """The module of ``src/pyfect`` holding the DDL."""
    build: Build
    dialects: frozenset[str] = frozenset({"mysql", "mssql"})


SCHEMAS: dict[str, Schema] = {
    "persistence single table": Schema(
        "persistence/persistence/_sql.py", _persistence(layer_backing_sql)
    ),
    "persistence multi table": Schema(
        "persistence/persistence/_sql.py", _persistence(layer_backing_sql_multi_table)
    ),
    "key value store": Schema("persistence/key_value_store/_sql.py", _key_value_store),
    "persisted queue": Schema("persistence/persisted_queue/_sql_migrations.py", _queue),
    "cluster messages": Schema(
        "cluster/sql_message_storage.py",
        lambda: sql_message_storage.run_migrations(prefix="cluster"),
    ),
    "cluster runners": Schema(
        "cluster/sql_runner_storage.py",
        lambda: sql_runner_storage.run_migrations(prefix="cluster"),
    ),
    "event log server (encrypted)": Schema(
        "eventlog/_sql_server_encrypted/tables.py", _event_log_encrypted
    ),
    # SqlEventLogServerUnencrypted runs on SQLite, PostgreSQL and MySQL
    "event log server (unencrypted)": Schema(
        "eventlog/sql_event_log_server_unencrypted.py",
        _event_log_unencrypted,
        frozenset({"mysql"}),
    ),
}

NEITHER_SERVER = {
    "eventlog/sql_event_journal.py": "SqlEventJournal runs on SQLite and PostgreSQL only",
    "sql/migrator.py": "the history table's only text column is the migration's name, never a key",
}
"""Modules with DDL that never runs on MySQL or SQL Server, or whose tables
hold no key text."""

KEY_NAME = re.compile(r"(^|_)(id|key|name|type|address)$")

_GENERATED = "made by pyfect in one canonical form (a lowercase UUID or hex digest)"
_VOCABULARY = "a fixed lowercase vocabulary written only by pyfect"
NOT_KEYS: dict[tuple[str, str], str] = {
    (r".*_migrations", "name"): "a migration's name, recorded and never looked up",
    ("queue", "acquired_by"): _GENERATED + ": the claiming poll's lock",
    ("queue", "state"): _VOCABULARY,
    ("cluster_messages", "trace_id"): "a span's trace id, stored and read back, never compared",
    ("cluster_messages", "span_id"): "a span's id, stored and read back, never compared",
    (r"enc_events_compaction_\w+", "scope"): _GENERATED + ": the store's scope hash",
    (r"enc_events_compaction_\w+", "id"): _GENERATED,
    ("enc_events_compaction_stages", "state"): _VOCABULARY,
}
"""``(table pattern, column)``: text columns the rule would flag that hold
no key compared with outside input, with the reason."""


def _not_a_key(table: str, column: str) -> bool:
    return any(name == column and re.fullmatch(pattern, table) for pattern, name in NOT_KEYS)


MYSQL_TEXT = {"char", "varchar", "tinytext", "text", "mediumtext", "longtext"}
MYSQL_EXACT_COLLATIONS = {"utf8mb4_0900_bin"}
MSSQL_TEXT = {"char", "varchar", "nchar", "nvarchar", "text", "ntext"}
DATABASE = "exact_keys"


@dataclass(frozen=True)
class Column:
    table: str
    name: str
    type: str
    collation: str | None
    indexed: bool


def _mysql_columns(rows: Sequence[Any]) -> list[Column]:
    return [
        Column(str(r["t"]), str(r["c"]), str(r["d"]).lower(), r["k"], bool(int(str(r["i"]))))
        for r in rows
    ]


_MYSQL_COLUMNS = (
    "SELECT c.TABLE_NAME AS t, c.COLUMN_NAME AS c, c.DATA_TYPE AS d, c.COLLATION_NAME AS k, "
    "EXISTS (SELECT 1 FROM information_schema.STATISTICS s "
    "WHERE s.TABLE_SCHEMA = c.TABLE_SCHEMA AND s.TABLE_NAME = c.TABLE_NAME "
    "AND s.COLUMN_NAME = c.COLUMN_NAME) AS i "
    "FROM information_schema.COLUMNS c WHERE c.TABLE_SCHEMA = DATABASE()"
)
_MSSQL_COLUMNS = (
    "SELECT c.TABLE_NAME AS t, c.COLUMN_NAME AS c, c.DATA_TYPE AS d, c.COLLATION_NAME AS k, "
    "CASE WHEN EXISTS (SELECT 1 FROM sys.index_columns ic JOIN sys.columns sc "
    "ON sc.object_id = ic.object_id AND sc.column_id = ic.column_id "
    "WHERE ic.object_id = OBJECT_ID(QUOTENAME(c.TABLE_SCHEMA) + '.' + QUOTENAME(c.TABLE_NAME)) "
    "AND sc.name = c.COLUMN_NAME) THEN 1 ELSE 0 END AS i "
    "FROM INFORMATION_SCHEMA.COLUMNS c"
)


def _exact(dialect: str, column: Column) -> bool:
    if dialect == "mysql":
        return column.type not in MYSQL_TEXT or column.collation in MYSQL_EXACT_COLLATIONS
    return column.type not in MSSQL_TEXT or (column.collation or "").endswith("_BIN2")


def _is_key(column: Column) -> bool:
    return column.indexed or KEY_NAME.search(column.name) is not None


def _fresh_mysql(request: pytest.FixtureRequest) -> fx.Layer[Any, Any]:
    pytest.importorskip("asyncmy")
    from pyfect import redacted
    from pyfect.sql import mysql

    from ._mysql import MysqlServer, query_now

    server: MysqlServer = request.getfixturevalue("mysql_server")
    query_now(
        f"DROP DATABASE IF EXISTS {DATABASE}; CREATE DATABASE {DATABASE} "
        "CHARACTER SET utf8mb4 COLLATE utf8mb4_general_ci",
        root=True,
    )
    url = f"mysql://root:root@{server.host}:{server.port}/{DATABASE}"
    return mysql.layer(mysql.MysqlClientConfig(url=redacted.make(url)))


def _fresh_mssql(request: pytest.FixtureRequest) -> fx.Layer[Any, Any]:
    pytest.importorskip("pytds")
    from pyfect.sql import mssql

    from ._mssql import MssqlServer, query_now

    server: MssqlServer = request.getfixturevalue("mssql_server")
    query_now(
        f"DROP DATABASE IF EXISTS {DATABASE}; "
        f"CREATE DATABASE {DATABASE} COLLATE Latin1_General_100_CI_AI",
        database="master",
    )
    return mssql.layer(server.config(database=DATABASE))


@pytest.mark.parametrize("dialect", ["mysql", "mssql"])
def test_every_key_column_compares_exactly(request: pytest.FixtureRequest, dialect: str) -> None:
    client = _fresh_mysql(request) if dialect == "mysql" else _fresh_mssql(request)

    def body():
        for schema in SCHEMAS.values():
            if dialect in schema.dialects:
                yield from schema.build()
        sql = yield from SqlClient()
        return (yield from sql.unsafe(_MYSQL_COLUMNS if dialect == "mysql" else _MSSQL_COLUMNS))

    rows = fx.run_blocking(fx.gen(body).pipe(fx.provide(client)).or_die())
    columns = _mysql_columns(rows)
    assert columns
    inexact = sorted(
        f"{c.table}.{c.name} {c.type} {c.collation}"
        for c in columns
        if _is_key(c) and not _exact(dialect, c) and not _not_a_key(c.table, c.name)
    )
    assert not inexact, "inexact key columns:\n" + "\n".join(inexact)


def test_every_module_with_ddl_is_checked() -> None:
    with_ddl = {
        path.relative_to(SRC).as_posix()
        for path in SRC.rglob("*.py")
        if re.search(r"CREATE\s+TABLE", path.read_text(), re.IGNORECASE)
    }
    checked = {schema.module for schema in SCHEMAS.values()} | set(NEITHER_SERVER)
    assert with_ddl == checked
