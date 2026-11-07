"""Ports of Effect's ``effect/test/eventlog/SqlEventLogServerEncryptedStorageTest.ts``
suite for ``pyfect.eventlog.sql_event_log_server_encrypted``, as ``sql-pg``,
``sql-mysql2`` and ``sql-mssql`` run it: on the session's PostgreSQL server
and MySQL and SQL Server containers (each skipped without one), the MySQL
client logging in as ``root`` to see other connections' lock waits, as
Effect's does.

Each test's docstring is the Effect test title, ``{dialect}`` standing for
the suite's name (``pg``, ``mysql2``, ``mssql``).
"""

import itertools
import os
import time
import uuid
from collections.abc import Callable, Generator, Sequence
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.eventlog import event_journal as J
from pyfect.eventlog import event_log_server_encrypted as Server
from pyfect.eventlog import sql_event_log_server_encrypted as SqlE
from pyfect.eventlog.event_journal import EntryId, StoreId
from pyfect.eventlog.event_log_encryption import EncryptedBatch, layer_subtle
from pyfect.reactivity import layer as reactivity_layer
from pyfect.sql.client import SqlClient, SqlClientService

_namespaces = itertools.count()
store_id = StoreId("store-a")

type Connect = Callable[[], fx.Effect[SqlClientService, Any, Any]]


@pytest.fixture(params=["pg", "mysql2", "mssql"])
def connect(request: pytest.FixtureRequest) -> Connect:
    """A new pool on the session's PostgreSQL server, MySQL container or SQL
    Server container."""
    if request.param == "mssql":
        pytest.importorskip("pytds")
        from pyfect.sql import mssql

        from ._mssql import MssqlServer

        mssql_server: MssqlServer = request.getfixturevalue("mssql_server")
        return lambda: mssql.make(mssql_server.config())
    if request.param == "pg":
        pytest.importorskip("psycopg")
        from pyfect.sql import pg

        from ._postgres import PgServer

        server: PgServer = request.getfixturevalue("pg_server")
        return lambda: pg.make(pg.PgPoolConfig(url=server.url))
    pytest.importorskip("asyncmy")
    from pyfect.sql import mysql

    from ._mysql import MysqlServer

    mysql_server: MysqlServer = request.getfixturevalue("mysql_server")
    return lambda: mysql.make(mysql.MysqlClientConfig(url=mysql_server.root_url))


def _run(body: Callable[[], Generator[Any, Any, Any]]) -> fx.Effect[Any, Any, Any]:
    return fx.gen(body).pipe(fx.provide(fx.layer.merge(reactivity_layer, layer_subtle)))


def make_batch(*entry_ids: EntryId) -> EncryptedBatch:
    return EncryptedBatch(
        entry_ids=entry_ids, iv=bytes(12), encrypted_batch=bytes([len(entry_ids) % 256])
    )


def ids(batches: Sequence[Any]) -> list[list[bytes]]:
    return [list(batch.entry_ids) for batch in batches]


def _encrypted_options(prefix: str) -> dict[str, str]:
    # Own tables, so other suites sharing the database don't race on creating them.
    namespace = f"{prefix}_{os.getpid()}_{next(_namespaces)}"
    return {
        "entry_table_prefix": f"{namespace}_events",
        "remote_id_table": f"{namespace}_remote_id",
    }


def _encrypted_storage(
    sql: SqlClientService, options: dict[str, str]
) -> fx.Effect[Server.StorageService, Any, Any]:
    return SqlE.make_storage(**options).pipe(fx.provide_service(SqlClient, sql))


def _await_lock_wait(sql: SqlClientService) -> Generator[Any, Any]:
    """Waits until another connection is blocked on a lock held by an open
    transaction."""
    waiting = sql.on_dialect_or_else(
        mysql=lambda: sql("SELECT COUNT(*) AS n FROM performance_schema.data_lock_waits"),
        mssql=lambda: sql(
            "SELECT COUNT(*) AS n FROM sys.dm_exec_requests WHERE blocking_session_id <> 0"
        ),
        or_else=lambda: sql(
            "SELECT COUNT(*)::int AS n FROM pg_stat_activity "
            "WHERE wait_event_type = 'Lock' AND datname = current_database()"
        ),
    )
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        rows = yield from waiting
        if rows[0]["n"] != 0:
            return
        yield from fx.sleep("10 millis")
    yield from fx.die(RuntimeError("the competing writer never waited on a lock"))


def competing_writes(
    sql: SqlClientService, first: EncryptedBatch, second: EncryptedBatch
) -> Generator[Any, Any, tuple[list[Any], list[Any]]]:
    """Writer A holds its write open in a transaction until writer B, a
    separate storage standing in for another server process, is blocked on
    it. B retries once if it loses, as a client retries a failed write."""
    public_key = str(uuid.uuid4())
    options = _encrypted_options("competing")
    storage_a = yield from _encrypted_storage(sql, options)
    storage_b = yield from _encrypted_storage(sql, options)
    # Create the scope's tables first, so only the writes compete.
    yield from storage_a.write(public_key, store_id, [make_batch(J.make_entry_id_unsafe())])
    yield from storage_b.changes(public_key, store_id, 0).take(1).run_drain()

    written = yield from fx.Deferred[None].make()
    commit = yield from fx.Deferred[None].make()

    def transaction():
        yield from storage_a.write(public_key, store_id, [first])
        yield from written.succeed(None)
        yield from commit.wait()

    writer_a = yield from sql.with_transaction(fx.gen(transaction)).fork()
    yield from written.wait()
    writer_b = yield from storage_b.write(public_key, store_id, [second]).fork()
    yield from _await_lock_wait(sql)
    yield from commit.succeed(None)
    yield from writer_a.join()
    attempt = yield from writer_b.await_exit()
    if isinstance(attempt, fx.Success):
        stored = attempt.value
    else:
        stored = yield from storage_b.write(public_key, store_id, [second])
    persisted = yield from storage_a.changes(public_key, store_id, 0).take(3).run_collect()
    return stored, persisted[1:]


@testing.live(timeout="1 minute")
def test_stores_a_batch_with_more_ids_than_one_statement_can_bind(connect: Connect):
    """SqlEventLogServerEncrypted storage ({dialect}) / stores a batch with more ids than one
    statement can bind"""

    def body():
        sql = yield from connect()
        public_key = str(uuid.uuid4())
        storage = yield from _encrypted_storage(sql, _encrypted_options("oversized"))
        # Above the PostgreSQL client's bind parameter limit of 32767.
        batch = make_batch(*(J.make_entry_id_unsafe() for _ in range(65_536)))
        stored = yield from storage.write(public_key, store_id, [batch])
        retried = yield from storage.write(public_key, store_id, [batch])
        persisted = yield from storage.changes(public_key, store_id, 0).take(1).run_collect()
        assert ids(stored) == ids([batch])
        assert retried == []
        assert ids(persisted) == ids([batch])
        assert persisted[0].sequence == stored[0].sequence

    yield from _run(body)


@testing.live(timeout="30 seconds")
def test_stores_a_competing_write_after_its_writer_retries(connect: Connect):
    """SqlEventLogServerEncrypted storage ({dialect}) / stores a competing write after its writer
    retries"""

    def body():
        sql = yield from connect()
        a, b = J.make_entry_id_unsafe(), J.make_entry_id_unsafe()
        stored, persisted = yield from competing_writes(sql, make_batch(a), make_batch(b))
        assert ids(stored) == ids([make_batch(b)])
        assert ids(persisted) == ids([make_batch(a), make_batch(b)])
        assert [p.sequence for p in persisted] == [persisted[0].sequence, persisted[0].sequence + 1]

    yield from _run(body)


@testing.live(timeout="30 seconds")
def test_stores_a_competing_partly_known_batch_whole_once(connect: Connect):
    """SqlEventLogServerEncrypted storage ({dialect}) / stores a competing partly known batch whole,
    once"""

    def body():
        sql = yield from connect()
        a, b = J.make_entry_id_unsafe(), J.make_entry_id_unsafe()
        stored, persisted = yield from competing_writes(sql, make_batch(a), make_batch(b, a))
        assert ids(stored) == ids([make_batch(b, a)])
        assert ids(persisted) == ids([make_batch(a), make_batch(b, a)])
        assert [p.sequence for p in persisted] == [persisted[0].sequence, persisted[0].sequence + 1]

    yield from _run(body)
