"""Servers that start at once on a new database agree on its remote id, on
SQLite, PostgreSQL, MySQL and SQL Server (each server skipped without one),
and on a PostgreSQL database whose transactions default to REPEATABLE READ.

Effect's ``makeStorage`` reads the remote id table and inserts a new id if
it finds none. Two starts that both read before either inserts each wrote
their own id (its primary key is the id itself, so both inserts succeed),
and the servers then disagreed about which log they serve. A barrier holds
each start between its read and its insert until the other gets there too.

At REPEATABLE READ, PostgreSQL reads a transaction's first snapshot after a
lock wait, and aborts an ``INSERT ... ON CONFLICT DO NOTHING`` that meets a
row it can't see, so the storage's transactions run at READ COMMITTED.
"""

from __future__ import annotations

import ast
import contextlib
import os
import re
import threading
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any, LiteralString

import _source
import pytest

import pyfect as fx
from pyfect import redacted
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog._sql_server_encrypted import db as db_module
from pyfect.eventlog._sql_server_encrypted import upgrade
from pyfect.eventlog.event_journal import RemoteId, StoreId
from pyfect.persistence._columns import column_bytes
from pyfect.sql.client import SqlClient, SqlClientService
from pyfect.sql.error import SqlError

from ._legacy_eventlog import DIALECTS, OWNER, LegacyDb, any_db, batch

REPEATABLE_READ = "pg at repeatable read"
"""A PostgreSQL database of its own whose transactions default to REPEATABLE READ."""


def _repeatable_read_pg(request: pytest.FixtureRequest) -> LegacyDb:
    pytest.importorskip("psycopg")
    from pyfect.sql import pg

    from ._postgres import PgServer, query_now

    server: PgServer = request.getfixturevalue("pg_server")
    name = f"rr_{os.getpid()}_{uuid.uuid4().hex[:8]}"
    query_now(f'CREATE DATABASE "{name}"')
    request.addfinalizer(lambda: query_now(f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))
    query_now(f"ALTER DATABASE \"{name}\" SET default_transaction_isolation = 'repeatable read'")
    url = redacted.make(f"{server.uri.rpartition('/')[0]}/{name}")
    return LegacyDb(lambda: pg.layer(pg.PgPoolConfig(url=url)))


def _db(request: pytest.FixtureRequest, tmp_path: Path) -> LegacyDb:
    if request.param == REPEATABLE_READ:
        return _repeatable_read_pg(request)
    return any_db(request, tmp_path)


@pytest.fixture(params=[*DIALECTS, REPEATABLE_READ])
def db(request: pytest.FixtureRequest, tmp_path: Path) -> LegacyDb:
    return _db(request, tmp_path)


@pytest.fixture(params=[d for d in [*DIALECTS, REPEATABLE_READ] if d != "SQLite"])
def server_db(request: pytest.FixtureRequest, tmp_path: Path) -> LegacyDb:
    """A database whose transactions run side by side (SQLite's
    ``BEGIN IMMEDIATE`` makes a second one wait for the first)."""
    return _db(request, tmp_path)


def _start(db: LegacyDb, logs: list[str] | None = None) -> RemoteId:
    def body():
        return (yield from (yield from Server.Storage()).get_id)

    started = db.run(body, logs)
    assert isinstance(started, fx.Success)
    return started.value


def _query(db: LegacyDb, statement: LiteralString, table: str, *args: object) -> list[Any]:
    def body():
        sql = (yield from SqlClient()).without_transforms()
        return (yield from sql(statement, sql.identifier(table), *args))

    found = db.tool(fx.gen(body))
    assert isinstance(found, fx.Success)
    return found.value


def _stored_ids(db: LegacyDb) -> list[bytes]:
    rows = _query(db, "SELECT remote_id FROM {}", db.remote_id_table)
    return [column_bytes(row["remote_id"]) for row in rows]


def _hold_until_both_found_none(monkeypatch: pytest.MonkeyPatch) -> None:
    both_found_none = threading.Barrier(2, timeout=5)

    def make_once_both_found_none() -> RemoteId:
        with contextlib.suppress(threading.BrokenBarrierError):
            both_found_none.wait()
        return J.make_remote_id_unsafe()

    monkeypatch.setattr(upgrade, "make_remote_id_unsafe", make_once_both_found_none)


def _two_starts(db: LegacyDb) -> list[RemoteId]:
    with ThreadPoolExecutor(2) as pool:
        return [started.result() for started in [pool.submit(_start, db) for _ in "ab"]]


def test_servers_starting_at_once_on_a_new_database_share_one_remote_id(
    db: LegacyDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    _hold_until_both_found_none(monkeypatch)
    ids = _two_starts(db)
    assert ids[0] == ids[1]
    assert _stored_ids(db) == [ids[0]]
    assert _start(db) == ids[0]


def test_servers_starting_at_once_both_start_when_both_began_recording_the_upgrade(
    server_db: LegacyDb, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Both starts are inside the transaction that records the upgrade
    before either inserts its row: at REPEATABLE READ the second insert met
    a row its snapshot could not see, and failed with a serialization error."""
    both_began = threading.Barrier(2, timeout=5)
    held = threading.local()
    table_exists = upgrade._table_exists  # pyright: ignore[reportPrivateUsage]

    def wait_once(found: bool) -> bool:
        if not getattr(held, "done", False):
            held.done = True
            with contextlib.suppress(threading.BrokenBarrierError):
                both_began.wait()
        return found

    def exists_then_wait(sql: SqlClientService, name: str) -> fx.Effect[bool, SqlError]:
        found = table_exists(sql, name)
        return found.map(wait_once) if name.endswith("_scope_aliases") else found

    monkeypatch.setattr(upgrade, "_table_exists", exists_then_wait)
    _hold_until_both_found_none(monkeypatch)
    ids = _two_starts(server_db)
    assert not both_began.broken
    assert ids[0] == ids[1]
    assert _stored_ids(server_db) == [ids[0]]
    assert len(_query(server_db, "SELECT id FROM {}", f"{server_db.prefix}_legacy_upgrade")) == 1


@pytest.mark.parametrize("server_db", [REPEATABLE_READ], indirect=True)
def test_servers_writing_one_store_at_once_at_repeatable_read_store_every_batch(
    server_db: LegacyDb,
) -> None:
    """A write waits on the store row's lock; at REPEATABLE READ PostgreSQL
    aborted it once the other writer committed."""
    server_db.start()

    def writes(name: str) -> fx.Exit[None, Any]:
        def body():
            storage = yield from Server.Storage()
            for n in range(20):
                yield from storage.write(OWNER[0], StoreId(OWNER[1]), [batch(f"{name}{n}")])

        return server_db.run(body)

    with ThreadPoolExecutor(2) as pool:
        done = [w.result() for w in [pool.submit(writes, name) for name in "ab"]]
    assert done == [fx.Success(None), fx.Success(None)]
    assert sorted(server_db.read(OWNER)) == sorted(f"{x}{n}" for x in "ab" for n in range(20))


def test_a_database_holding_two_remote_ids_serves_the_lowest_and_warns(db: LegacyDb) -> None:
    """Up to 0.6.22, and in Effect, servers that started at once could each
    store an id; which one a server then served was the database's choice."""
    first = _start(db)
    lowest = bytes(16)
    _query(db, "INSERT INTO {} (remote_id) VALUES ({})", db.remote_id_table, lowest)
    logs: list[str] = []
    assert _start(db, logs) == lowest
    assert _start(db) == lowest
    assert sorted(_stored_ids(db)) == sorted([lowest, bytes(first)])
    assert logs == [
        (
            f"{db.remote_id_table} holds 2 remote ids; serving the lowest, {lowest.hex()}. "
            "Delete the others: https://pyfect.dev/docs/eventlog#one-remote-id-per-database"
        )
    ]

    deleted = db.tool(SqlClient().flat_map(lambda sql: sql.unsafe(_documented_delete(db))))
    assert isinstance(deleted, fx.Success)
    assert _stored_ids(db) == [lowest]
    logs.clear()
    assert _start(db, logs) == lowest
    assert logs == []


def _documented_delete(db: LegacyDb) -> str:
    """The event log docs' statement that keeps the lowest id, for ``db``'s
    dialect and remote id table."""
    docs = Path(__file__).parents[2] / "website/content/docs/eventlog.mdx"
    section = docs.read_text().split("## One remote id per database")[1].split("\n## ")[0]
    others, mssql = re.findall(r"```sql\n(.*?)```", section, re.DOTALL)
    found = db.tool(SqlClient().map(lambda sql: sql.dialect))
    assert isinstance(found, fx.Success)
    statement = mssql if found.value == "mssql" else others
    return statement.replace("effect_remote_id", db.remote_id_table)


def test_the_storage_starts_every_transaction_through_db_transaction() -> None:
    """``Db.transaction`` pins READ COMMITTED on PostgreSQL, which the
    storage's locks rely on whatever the database's default level."""
    package = Path(db_module.__file__).parent
    callers = [
        path.name
        for path in _source.files(package, recursive=False)
        for node in _source.walk(path)
        if isinstance(node, ast.Attribute) and node.attr == "with_transaction"
    ]
    assert callers == ["db.py"]
