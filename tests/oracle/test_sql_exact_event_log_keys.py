"""On MySQL and SQL Server the SQL event log server storages compare
session auth public keys, store ids, events and primary keys exactly, as
their SQLite and PostgreSQL storages do (GitHub issue #1).

Both servers' default collations (``utf8mb4_0900_ai_ci``, ``*_CI_AS``)
ignore case, and MySQL's also accents; every SQL Server collation and
MySQL's ``PAD SPACE`` ones ignore trailing spaces in ``=`` and in unique
indexes. Keys differing only in one of these were one key: a public key
found another client's signing key bound to it (or the client was locked
out by a duplicate key error), entries written to store ``Alice`` were
numbered and read with store ``alice``'s, and a batch lookup by primary key
returned another key's entries. Run on the session's MySQL (``mysql:lts``)
and SQL Server (Azure SQL Edge on ARM) containers; skipped without Docker.
The unencrypted storage runs on neither SQL Server nor in these tests'
SQL Server databases.
"""

from __future__ import annotations

import itertools
from collections.abc import Callable, Generator
from typing import Any

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.crypto import digest
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log_server_unencrypted as U
from pyfect.eventlog import sql_event_log_server_encrypted as SqlE
from pyfect.eventlog import sql_event_log_server_unencrypted as SqlU
from pyfect.eventlog.event_journal import Entry, StoreId
from pyfect.eventlog.event_log_server_encrypted import StorageService as EncryptedStorage
from pyfect.sql import SqlClient

pytestmark = pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")

VARIANTS = {
    "case": ("Alice", "alice"),
    "accents": ("resume", "résumé"),
    "trailing spaces": ("alice", "alice "),
}

# each server's default database, and one whose default collation ignores
# what the server's default does not: MySQL's ``utf8mb4_0900_ai_ci`` is
# ``NO PAD``, so ``utf8mb4_general_ci`` (``PAD SPACE``) adds trailing spaces;
# SQL Server's ``SQL_Latin1_General_CP1_CI_AS`` keeps accents, which
# ``Latin1_General_100_CI_AI`` ignores
SERVERS = {
    "mysql": None,
    "mysql-pad-space": "utf8mb4_general_ci",
    "mssql": None,
    "mssql-ci-ai": "Latin1_General_100_CI_AI",
}
MYSQL_SERVERS = sorted(name for name in SERVERS if name.startswith("mysql"))

KEY_1 = bytes([1]) * 32
KEY_2 = bytes([2]) * 32
KEY_3 = bytes([3]) * 32

_prefixes = itertools.count(1)


def _prefix() -> str:
    # Unique per session: the servers are shared by the session's tests.
    return f"exact_events_{next(_prefixes)}"


def _mysql(request: pytest.FixtureRequest, collation: str | None) -> fx.Layer[Any, Any]:
    pytest.importorskip("asyncmy")
    from pyfect import redacted
    from pyfect.sql import mysql

    from ._mysql import MysqlServer
    from ._mysql import query_now as mysql_query

    server: MysqlServer = request.getfixturevalue("mysql_server")
    if collation is None:
        return mysql.layer(mysql.MysqlClientConfig(url=server.url))
    database = f"exact_{collation}"
    mysql_query(
        f"CREATE DATABASE IF NOT EXISTS {database} CHARACTER SET utf8mb4 COLLATE {collation}",
        root=True,
    )
    url = f"mysql://root:root@{server.host}:{server.port}/{database}"
    return mysql.layer(mysql.MysqlClientConfig(url=redacted.make(url)))


def _mssql(request: pytest.FixtureRequest, collation: str | None) -> fx.Layer[Any, Any]:
    pytest.importorskip("pytds")
    from pyfect.sql import mssql

    from ._mssql import MssqlServer
    from ._mssql import query_now as mssql_query

    server: MssqlServer = request.getfixturevalue("mssql_server")
    if collation is None:
        return mssql.layer(server.config())
    database = f"exact_{collation}"
    mssql_query(
        f"IF DB_ID('{database}') IS NULL CREATE DATABASE {database} COLLATE {collation}",
        database="master",
    )
    return mssql.layer(server.config(database=database))


def _client(request: pytest.FixtureRequest) -> fx.Layer[Any, Any]:
    name: str = request.param
    collation = SERVERS[name]
    return _mysql(request, collation) if name.startswith("mysql") else _mssql(request, collation)


@pytest.fixture(params=sorted(SERVERS))
def client(request: pytest.FixtureRequest) -> fx.Layer[Any, Any]:
    return _client(request)


@pytest.fixture(params=MYSQL_SERVERS)
def mysql_client(request: pytest.FixtureRequest) -> fx.Layer[Any, Any]:
    return _client(request)


def _run(client: fx.Layer[Any, Any], body: Callable[[], Generator[Any, Any, Any]]) -> None:
    program = testing.with_live(fx.scoped(fx.gen(body)))
    testing.run_test(
        program.pipe(fx.provide(fx.layer.merge(client, digest.layer_web_crypto))).or_die()
    )


def _encrypted(prefix: str) -> fx.Effect[EncryptedStorage, Any, Any]:
    return SqlE.make_storage(entry_table_prefix=prefix, remote_id_table=f"{prefix}_remote_id")


def _unencrypted(prefix: str) -> fx.Effect[U.StorageService, Any, Any]:
    return SqlU.make_storage(entry_table_prefix=prefix, remote_id_table=f"{prefix}_remote_id")


def _entry(primary_key: str, event: str = "UserNameSet") -> Entry:
    return S.new(Entry, disable_checks=True)(
        id=J.make_entry_id_unsafe(), event=event, primary_key=primary_key, payload=b"payload"
    )


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_encrypted_bindings_of_public_keys_differing_only_in_case_accents_or_trailing_spaces(
    client: fx.Layer[Any, Any], variant: str
) -> None:
    first, second = VARIANTS[variant]

    def body():
        storage = yield from _encrypted(_prefix())
        assert (yield from storage.get_or_create_session_auth_binding(first, KEY_1)) == KEY_1
        assert (yield from storage.get_or_create_session_auth_binding(second, KEY_2)) == KEY_2
        assert (yield from storage.get_or_create_session_auth_binding(first, KEY_3)) == KEY_1
        assert (yield from storage.get_or_create_session_auth_binding(second, KEY_3)) == KEY_2

    _run(client, body)


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_unencrypted_bindings_of_public_keys_differing_only_in_case_accents_or_trailing_spaces(
    mysql_client: fx.Layer[Any, Any], variant: str
) -> None:
    first, second = VARIANTS[variant]

    def body():
        storage = yield from _unencrypted(_prefix())
        assert (yield from storage.get_or_create_session_auth_binding(first, KEY_1)) == KEY_1
        assert (yield from storage.get_or_create_session_auth_binding(second, KEY_2)) == KEY_2
        assert (yield from storage.get_or_create_session_auth_binding(first, KEY_3)) == KEY_1

    _run(mysql_client, body)


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_unencrypted_store_ids_differing_only_in_case_accents_or_trailing_spaces(
    mysql_client: fx.Layer[Any, Any], variant: str
) -> None:
    first, second = (StoreId(store) for store in VARIANTS[variant])

    def body():
        storage = yield from _unencrypted(_prefix())
        one, other = _entry("user-1"), _entry("user-1")
        written = yield from storage.write(first, [one])
        assert [w.remote_sequence for w in written] == [1]
        written = yield from storage.write(second, [other])
        assert [w.remote_sequence for w in written] == [1]
        assert (yield from storage.latest_sequence(first)) == 1
        assert (yield from storage.latest_sequence(second)) == 1
        found = yield from storage.entries_after(second, one)
        assert [f.entry.id for f in found] == [other.id]
        backlog = yield from storage.changes(first, 0, {}).take(1).run_collect()
        assert [b.entry.id for b in backlog] == [one.id]

    _run(mysql_client, body)


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_unencrypted_primary_keys_differing_only_in_case_accents_or_trailing_spaces(
    mysql_client: fx.Layer[Any, Any], variant: str
) -> None:
    first, second = VARIANTS[variant]
    store = StoreId("store")

    def body():
        storage = yield from _unencrypted(_prefix())
        probe = _entry(second)
        same_key_probe = _entry(first)
        written = _entry(first)
        yield from storage.write(store, [written])
        found = yield from storage.entries_after(store, probe, [probe])
        assert found == []
        found = yield from storage.entries_after(store, same_key_probe, [same_key_probe])
        assert [(f.entry.id, f.entry.primary_key) for f in found] == [(written.id, first)]

    _run(mysql_client, body)


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_unencrypted_events_differing_only_in_case_accents_or_trailing_spaces(
    mysql_client: fx.Layer[Any, Any], variant: str
) -> None:
    first, second = VARIANTS[variant]
    store = StoreId("store")

    def body():
        storage = yield from _unencrypted(_prefix())
        probe = _entry("user-1", event=second)
        written = _entry("user-1", event=first)
        yield from storage.write(store, [written])
        assert (yield from storage.entries_after(store, probe, [probe])) == []
        found = yield from storage.entries_after(store, written, [written])
        assert [f.entry.event for f in found] == [first]

    _run(mysql_client, body)


# the bindings table as earlier versions (and Effect) make it


def _old_bindings(prefix: str) -> Generator[Any, Any]:
    sql = yield from SqlClient()
    table = sql.identifier(f"{prefix}_session_auth_bindings")
    if sql.dialect == "mysql":
        yield from sql(
            "CREATE TABLE {} (public_key VARCHAR(191) PRIMARY KEY, "
            "signing_public_key BINARY(32) NOT NULL)",
            table,
        )
    else:
        yield from sql(
            "CREATE TABLE {} (public_key NVARCHAR(191) PRIMARY KEY, "
            "signing_public_key VARBINARY(32) NOT NULL)",
            table,
        )
    yield from sql(
        "INSERT INTO {} (public_key, signing_public_key) VALUES ({}, {})", table, "Alice", KEY_1
    )


def test_encrypted_storage_converts_an_existing_bindings_table_with_rows(
    client: fx.Layer[Any, Any],
) -> None:
    """Two storages opening at once convert a table made by earlier
    versions; its bindings stay bound."""
    prefix = _prefix()

    def body():
        yield from _old_bindings(prefix)
        storage, _ = yield from fx.all(
            _encrypted(prefix), _encrypted(prefix), concurrency="unbounded"
        )
        assert (yield from storage.get_or_create_session_auth_binding("Alice", KEY_3)) == KEY_1
        assert (yield from storage.get_or_create_session_auth_binding("alice", KEY_2)) == KEY_2
        assert (yield from storage.get_or_create_session_auth_binding("Alice ", KEY_3)) == KEY_3
        assert (yield from storage.get_or_create_session_auth_binding("Alicé", KEY_2)) == KEY_2
        reopened = yield from _encrypted(prefix)
        assert (yield from reopened.get_or_create_session_auth_binding("alice", KEY_3)) == KEY_2

    _run(client, body)


def test_unencrypted_storage_converts_existing_tables_with_rows(
    mysql_client: fx.Layer[Any, Any],
) -> None:
    """Two storages opening at once convert tables made by earlier versions
    (and Effect); their entries, store sequences and bindings stay."""
    prefix = _prefix()
    old = _entry("Alice", event="Renamed")

    def body():
        sql = yield from SqlClient()
        entries = sql.identifier(prefix)
        stores = sql.identifier(f"{prefix}_stores")
        yield from sql(
            "CREATE TABLE {} (store_id VARCHAR(191) NOT NULL, "
            "sequence BIGINT NOT NULL, entry_id BINARY(16) NOT NULL, event TEXT NOT NULL, "
            "primary_key TEXT NOT NULL, payload BLOB NOT NULL, "
            "PRIMARY KEY (store_id, sequence), UNIQUE (store_id, entry_id))",
            entries,
        )
        yield from sql(
            "CREATE INDEX {} ON {} (store_id, event(191), primary_key(191), entry_id)",
            sql.identifier(f"{prefix}_event_key_idx"),
            entries,
        )
        yield from sql(
            "CREATE TABLE {} (store_id VARCHAR(191) PRIMARY KEY, next_sequence BIGINT NOT NULL)",
            stores,
        )
        yield from _old_bindings(prefix)
        yield from sql(
            "INSERT INTO {} (store_id, sequence, entry_id, event, primary_key, payload) "
            "VALUES ('Alice', 1, {}, 'Renamed', 'Alice', 'payload')",
            entries,
            old.id,
        )
        yield from sql("INSERT INTO {} VALUES ('Alice', 2)", stores)
        storage, _ = yield from fx.all(
            _unencrypted(prefix), _unencrypted(prefix), concurrency="unbounded"
        )
        alice, lower = StoreId("Alice"), StoreId("alice")
        found = yield from storage.entries_after(alice, old, [old])
        assert [(f.remote_sequence, f.entry.event, f.entry.primary_key) for f in found] == [
            (1, "Renamed", "Alice")
        ]
        assert [w.remote_sequence for w in (yield from storage.write(lower, [_entry("x")]))] == [1]
        assert [w.remote_sequence for w in (yield from storage.write(alice, [_entry("x")]))] == [2]
        probe = _entry("alice", event="Renamed")
        assert (yield from storage.entries_after(alice, probe, [probe])) == []
        assert (yield from storage.get_or_create_session_auth_binding("Alice", KEY_3)) == KEY_1
        assert (yield from storage.get_or_create_session_auth_binding("alice", KEY_2)) == KEY_2

    _run(mysql_client, body)
