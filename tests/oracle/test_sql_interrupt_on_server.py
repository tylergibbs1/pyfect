"""(pyfect) Interrupting a statement ends it on the server: PostgreSQL, SQL Server and
ClickHouse, each read over another connection (MySQL's are in
``test_mysql_interrupt_on_server``). libSQL has nothing to cancel with: Hrana has no cancel,
so an interrupted statement finishes on the server, here and in Effect."""

import uuid
from typing import Any

import pyfect as fx
from pyfect import redacted, testing
from pyfect.sql import clickhouse, mssql, pg

from . import _clickhouse, _mssql, _postgres
from ._clickhouse import ClickhouseServer, clickhouse_server
from ._interrupt_on_server import gone_soon, interrupted_and_gone, until_running
from ._mssql import MssqlServer, mssql_server
from ._postgres import PgServer, pg_server

__all__ = ["clickhouse_server", "mssql_server", "pg_server"]


def _marker() -> str:
    return f"interrupt_{uuid.uuid4().hex}"


# --- PostgreSQL -----------------------------------------------------------------------------


def _on_pg(marker: str) -> list[tuple[object, ...]]:
    return _postgres.query_now(
        "SELECT pid, state FROM pg_stat_activity "
        f"WHERE query LIKE '%{marker}%' AND state = 'active' AND pid <> pg_backend_pid()"
    )


@testing.live(timeout=30)
def test_postgres(pg_server: PgServer):
    marker = _marker()

    def body():
        sql = yield from pg.PgClient()
        statement = sql.unsafe(f"SELECT pg_sleep(30) AS {marker}")
        yield from interrupted_and_gone(statement, lambda: _on_pg(marker))

    yield from fx.scoped(fx.gen(body)).pipe(
        fx.provide(pg.layer(pg.PgPoolConfig(url=pg_server.url)))
    )


@testing.live(timeout=30)
def test_postgres_row_lock_is_free_soon_after(pg_server: PgServer):
    table = _marker()
    _postgres.query_now(f"CREATE TABLE {table} (id INT PRIMARY KEY)")
    _postgres.query_now(f"INSERT INTO {table} VALUES (1)")

    def locked() -> bool:
        try:
            _postgres.query_now(f"SELECT id FROM {table} FOR UPDATE NOWAIT")
        except Exception:
            return True
        return False

    def body():
        sql = yield from pg.PgClient()

        def holder():
            yield from sql.unsafe(f"SELECT id FROM {table} FOR UPDATE")
            yield from sql("SELECT pg_sleep(30)")

        fiber = yield from sql.with_transaction(fx.gen(holder)).fork()
        yield from until_running(locked)
        yield from fx.sleep(0.2)
        yield from fiber.interrupt()
        yield from gone_soon(locked)

    yield from fx.scoped(fx.gen(body)).pipe(
        fx.provide(pg.layer(pg.PgPoolConfig(url=pg_server.url)))
    )


# --- SQL Server -----------------------------------------------------------------------------


def _on_mssql(marker: str) -> list[tuple[Any, ...]]:
    return _mssql.query_now(
        "SELECT r.session_id, r.command FROM sys.dm_exec_requests r "
        "CROSS APPLY sys.dm_exec_sql_text(r.sql_handle) t "
        f"WHERE t.text LIKE '%{marker}%' AND r.session_id <> @@SPID"
    )


@testing.live(timeout=60)
def test_sql_server(mssql_server: MssqlServer):
    marker = _marker()

    def body():
        sql = yield from mssql.MssqlClient()
        statement = sql.unsafe(f"/* {marker} */ WAITFOR DELAY '00:00:30'")
        yield from interrupted_and_gone(statement, lambda: _on_mssql(marker))

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(mssql.layer(mssql_server.config())))


@testing.live(timeout=60)
def test_sql_server_row_lock_is_free_soon_after(mssql_server: MssqlServer):
    table = _marker()
    _mssql.query_now(f"CREATE TABLE {table} (id INT PRIMARY KEY)")
    _mssql.query_now(f"INSERT INTO {table} VALUES (1)")

    def locked() -> bool:
        return not _mssql.query_now(
            f"SELECT id FROM {table} WITH (UPDLOCK, ROWLOCK, READPAST) WHERE id = 1"
        )

    def body():
        sql = yield from mssql.MssqlClient()

        def holder():
            yield from sql.unsafe(f"UPDATE {table} SET id = 1 WHERE id = 1")
            yield from sql("WAITFOR DELAY '00:00:30'")

        fiber = yield from sql.with_transaction(fx.gen(holder)).fork()
        yield from until_running(locked)
        yield from fx.sleep(0.2)
        yield from fiber.interrupt()
        yield from gone_soon(locked)

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(mssql.layer(mssql_server.config())))


# --- ClickHouse -----------------------------------------------------------------------------


@testing.live(timeout=30)
def test_clickhouse(clickhouse_server: ClickhouseServer):
    query_id = _marker()

    def on_server() -> bool:
        found = _clickhouse.query_now(
            f"SELECT count() FROM system.processes WHERE query_id = '{query_id}'"
        )
        return found.strip() != "0"

    def body():
        sql = yield from clickhouse.ClickhouseClient()
        endless = sql("SELECT sum(number) FROM numbers(100000000000)")
        yield from interrupted_and_gone(sql.with_query_id(endless, query_id), on_server)

    yield from fx.scoped(fx.gen(body)).pipe(
        fx.provide(
            clickhouse.layer(
                clickhouse.ClickhouseClientConfig(
                    url=clickhouse_server.url,
                    username=_clickhouse.USER,
                    password=redacted.make(_clickhouse.PASSWORD),
                )
            )
        )
    )
