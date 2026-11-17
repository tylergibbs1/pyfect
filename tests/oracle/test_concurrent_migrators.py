"""(pyfect) A migrator that finds another running the same migrations returns
only once they are in place, on MySQL and PostgreSQL (the session's
servers; skipped without them).

MySQL commits each DDL statement as it runs, so the rows a migrator records
up front are visible after its first ``CREATE TABLE``. A second migrator
starting then found them, returned ``[]`` and let its process use a table
the first had not finished (``Unknown column 'state'`` on the first offer of
a ``persisted_queue`` worker). PostgreSQL's ``LOCK TABLE`` already held the
second back; the same test pins both, so a dialect whose DDL is not
transactional cannot slip through.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, LiteralString

import pytest

import pyfect as fx
from pyfect import scope, testing
from pyfect.exit import Success
from pyfect.sql import SqlClient, migrator

_TABLE = "concurrent_migrators"


def _mysql(request: pytest.FixtureRequest) -> tuple[fx.Layer[Any, Any], LiteralString]:
    pytest.importorskip("asyncmy")
    from pyfect.sql import mysql

    from ._mysql import MysqlServer, query_now

    server: MysqlServer = request.getfixturevalue("mysql_server")
    query_now(f"DROP TABLE IF EXISTS {_TABLE}, {_TABLE}_migrations")
    return (
        mysql.layer(mysql.MysqlClientConfig(url=server.url)),
        "SELECT count(*) AS n FROM information_schema.processlist WHERE state = 'User lock'",
    )


def _pg(request: pytest.FixtureRequest) -> tuple[fx.Layer[Any, Any], LiteralString]:
    pytest.importorskip("psycopg")
    from pyfect.sql import pg

    from ._postgres import PgServer, query_now

    server: PgServer = request.getfixturevalue("pg_server")
    query_now(f"DROP TABLE IF EXISTS {_TABLE}, {_TABLE}_migrations")
    return (
        pg.layer(pg.PgPoolConfig(url=server.url)),
        "SELECT count(*) AS n FROM pg_stat_activity WHERE wait_event_type = 'Lock'",
    )


SERVERS: dict[str, Callable[[pytest.FixtureRequest], tuple[fx.Layer[Any, Any], LiteralString]]] = {
    "mysql": _mysql,
    "pg": _pg,
}


@pytest.fixture(params=list(SERVERS))
def server(request: pytest.FixtureRequest) -> tuple[fx.Layer[Any, Any], LiteralString]:
    """A client layer on the server, started before the test's timeout runs,
    and the query counting the sessions waiting for a lock."""
    return SERVERS[request.param](request)


@pytest.fixture
def mysql_layers(request: pytest.FixtureRequest) -> tuple[fx.Layer[Any, Any], fx.Layer[Any, Any]]:
    """Two client layers on the MySQL server, each with its own pool."""
    first, _ = _mysql(request)
    second, _ = _mysql(request)
    return first, second


@testing.live
def test_a_second_migrator_returns_once_the_first_has_run_every_migration(
    server: tuple[fx.Layer[Any, Any], LiteralString],
):
    """(pyfect) a second migrator returns once the first has run every migration"""
    layer, waiters = server

    def body():
        sql = yield from SqlClient()
        inside = yield from fx.Deferred[None].make()
        release = yield from fx.Deferred[None].make()

        def add_column():
            yield from inside.succeed(None)
            yield from release.wait()
            yield from sql("ALTER TABLE {} ADD COLUMN b INTEGER", sql.identifier(_TABLE))

        run = migrator.make()(
            table=f"{_TABLE}_migrations",
            loader=migrator.from_record(
                {
                    "1_create": sql("CREATE TABLE {} (a INTEGER)", sql.identifier(_TABLE)),
                    "2_add_column": fx.gen(add_column),
                }
            ),
        )
        first = yield from scope.fork_scoped(run.exit())
        started = yield from inside.wait().as_(None).race_first(first.await_exit())
        assert started is None, started
        # the second uses the table as soon as its run returns
        second = yield from scope.fork_scoped(
            run.and_then(sql("SELECT b FROM {}", sql.identifier(_TABLE))).exit()
        )

        def second_done_or_waiting():
            while second.poll_unsafe() is None:
                [row] = yield from sql(waiters)
                if int(str(row["n"])) > 0:
                    return
                yield from fx.sleep("10 millis")

        yield from fx.gen(second_done_or_waiting)
        yield from release.succeed(None)
        assert (yield from first.join()) == Success([(1, "create"), (2, "add_column")])
        assert (yield from second.join()) == Success([])

    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(layer)).pipe(fx.provide(fx.platform.layer))


@testing.live
def test_a_failed_mysql_migration_releases_the_lock(
    mysql_layers: tuple[fx.Layer[Any, Any], fx.Layer[Any, Any]],
):
    """(pyfect) a failed MySQL migration releases the lock for other migrators"""
    layer, other = mysql_layers
    table = f"{_TABLE}_migrations"

    def failing():
        sql = yield from SqlClient()
        loader = migrator.from_record({"1_fail": sql("SELECT * FROM missing_table")})
        return (yield from migrator.make()(table=table, loader=loader).exit())

    def passing():
        return (
            yield from migrator.make()(table=table, loader=migrator.from_record({"1_ok": fx.void}))
        )

    def body():
        failed = yield from fx.gen(failing)
        assert not isinstance(failed, Success)
        # another pool, while the first is open: a lock left on one of its
        # connections would hold this run back
        return (yield from fx.gen(passing).pipe(fx.provide(other)))

    assert (yield from fx.gen(body).pipe(fx.provide(layer))) == [(1, "ok")]


@pytest.fixture
def one_connection_mysql(request: pytest.FixtureRequest) -> fx.Layer[Any, Any]:
    """A client on the MySQL server whose pool has one connection: the lock
    has to be released on the transaction's own connection, and this pool
    can't give a second one."""
    pytest.importorskip("asyncmy")
    from pyfect.sql import mysql

    from ._mysql import MysqlServer, query_now

    server: MysqlServer = request.getfixturevalue("mysql_server")
    query_now(f"DROP TABLE IF EXISTS {_TABLE}, {_TABLE}_migrations")
    return mysql.layer(mysql.MysqlClientConfig(url=server.url, max_connections=1))


@testing.live
def test_a_mysql_migrator_keeps_its_lock_until_its_transaction_commits(
    one_connection_mysql: fx.Layer[Any, Any],
):
    """(pyfect) a MySQL migrator releases its lock only after its transaction commits"""
    from ._mysql import query_now

    def body():
        sql = yield from SqlClient()
        [row] = yield from sql("SELECT CONNECTION_ID() AS id")
        loader = migrator.from_record(
            {
                "1_create": sql("CREATE TABLE {} (a INTEGER)", sql.identifier(_TABLE)),
                # not DDL: only the commit makes this row visible to others
                "2_seed": sql("INSERT INTO {} VALUES (1)", sql.identifier(_TABLE)),
            }
        )
        done = yield from migrator.make()(table=f"{_TABLE}_migrations", loader=loader)
        # read while the pool still holds the connection: its history goes with it
        history = yield from fx.sync(
            lambda: query_now(
                "SELECT h.SQL_TEXT FROM performance_schema.events_statements_history h"
                " JOIN performance_schema.threads t ON t.THREAD_ID = h.THREAD_ID"
                f" WHERE t.PROCESSLIST_ID = {int(str(row['id']))} ORDER BY h.EVENT_ID",
                root=True,
            )
        )
        return done, [str(text).upper() for (text,) in history]

    done, statements = yield from fx.gen(body).pipe(fx.provide(one_connection_mysql))
    assert done == [(1, "create"), (2, "seed")]
    commit = statements.index("COMMIT")
    release = next(i for i, text in enumerate(statements) if "RELEASE_LOCK" in text)
    # Released before the commit, another migrator could find the
    # migrations recorded but miss the rows written after the last DDL.
    assert commit < release, statements
