"""SQL Server migrations (Effect's ``sql-mssql`` ``MssqlMigrator``, which is
``effect/sql/Migrator``'s runner), on the session's SQL Server
(``_mssql.mssql_server``; skipped without Docker).

Effect has no SQL Server migrator test; the ``(pyfect)`` titles pin Effect's
behaviour."""

import pytest

pytest.importorskip("pytds")

import pyfect as fx
from pyfect import scope, testing
from pyfect.exit import Failure, Success
from pyfect.result import Ok
from pyfect.sql import SqlClient, mssql
from pyfect.sql.error import SqlError, SqlSyntaxError
from pyfect.sql.mssql import migrator as mssql_migrator

from ._mssql import MssqlServer

_TABLE = "race_migrations"


@testing.live(timeout="30 seconds")
def test_two_migrators_that_find_no_migrations_table_both_create_it_and_one_fails(
    mssql_server: MssqlServer,
):
    """(pyfect) two migrators that both find no migrations table both create it, and one fails

    Effect's SQL Server DDL for the table is ``IF OBJECT_ID(...) IS NULL CREATE
    TABLE`` (``Migrator.ts`` ``createMigrationsTable``): a check, then a create,
    with nothing held between them. A session creating the table holds both
    migrators at that check (``OBJECT_ID`` waits for the uncommitted table) and
    then rolls back, so both find no table and both go on to create it. One
    fails with SQL Server's error 2714, as in Effect, where only PostgreSQL
    looks for the table again after a failed create (``ensureMigrationsTable``)."""

    def body():
        sql = yield from SqlClient()
        held = yield from fx.Deferred[object].make()
        release = yield from fx.Deferred[None].make()

        def holding():
            yield from sql("CREATE TABLE {} (held INT)", sql.identifier(_TABLE))
            [row] = yield from sql("SELECT OBJECT_ID({}) AS id", _TABLE)
            yield from held.succeed(row["id"])
            yield from release.wait()
            yield from fx.fail("roll back")

        holder = yield from scope.fork_scoped(sql.with_transaction(fx.gen(holding)).exit())
        table_id = yield from held.wait()
        run = mssql_migrator.run(
            table=_TABLE, loader=mssql_migrator.from_record({"1_init": fx.void})
        )
        first = yield from scope.fork_scoped(run.exit())
        second = yield from scope.fork_scoped(run.exit())

        def both_held():
            while True:
                [row] = yield from sql(
                    "SELECT count(*) AS n FROM sys.dm_exec_requests"
                    " WHERE wait_type = 'LCK_M_SCH_S' AND wait_resource LIKE {}",
                    f"OBJECT: %:{table_id}:%",
                )
                if row["n"] == 2:
                    return

        yield from fx.gen(both_held)
        yield from release.succeed(None)
        yield from holder.join()
        exits = [(yield from first.join()), (yield from second.join())]
        assert [exit_ for exit_ in exits if isinstance(exit_, Success)] == [Success([(1, "init")])]
        [failed] = [exit_ for exit_ in exits if isinstance(exit_, Failure)]
        error = failed.cause.find_error()
        assert isinstance(error, Ok), failed
        assert isinstance(error.value, SqlError), failed
        assert isinstance(error.value.reason, SqlSyntaxError), failed
        assert f"There is already an object named '{_TABLE}'" in str(error.value.reason.cause)

    def dropped():
        sql = yield from SqlClient()
        yield from sql("DROP TABLE IF EXISTS {}", sql.identifier(_TABLE))

    config = mssql_server.config(max_connections=4)
    yield from (
        fx.gen(dropped)
        .and_then(fx.scoped(fx.gen(body)))
        .ensuring(fx.gen(dropped).ignore())
        .pipe(fx.provide(mssql.layer(config)))
    )
