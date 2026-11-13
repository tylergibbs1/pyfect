"""On MySQL and SQL Server the SQL PersistedQueue store compares element ids
and queue names exactly, as the memory, Redis, SQLite and PostgreSQL stores
do (GitHub issue #1).

Both servers' default collations (``utf8mb4_0900_ai_ci``, ``*_CI_AS``)
ignore case, and MySQL's also accents; every SQL Server collation and
MySQL's ``PAD SPACE`` ones ignore trailing spaces in ``=`` and in unique
indexes. Ids or queue names differing only in one of these were one id:
the second offer was dropped as a duplicate, and a queue's poller claimed
the other queue's elements. Run on the session's MySQL (``mysql:lts``) and
SQL Server (Azure SQL Edge on ARM) containers; skipped without Docker.
"""

from __future__ import annotations

from collections.abc import Generator, Sequence
from typing import Any

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.persistence import persisted_queue as pq
from pyfect.persistence.persisted_queue._sql_migrations import migrations
from pyfect.sql import SqlClient, migrator

pytestmark = pytest.mark.filterwarnings("ignore::pyfect.testing.ClockNotAdvancedWarning")

VARIANTS = {
    "case": ("job-abc", "job-ABC"),
    "accents": ("resume", "résumé"),
    "trailing spaces": ("job", "job "),
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


@pytest.fixture(params=sorted(SERVERS))
def client(request: pytest.FixtureRequest) -> fx.Layer[Any, Any]:
    name: str = request.param
    collation = SERVERS[name]
    return _mysql(request, collation) if name.startswith("mysql") else _mssql(request, collation)


def _run(client: fx.Layer[Any, Any], body: Any) -> Any:
    program = testing.with_live(fx.scoped(fx.gen(body)))
    return testing.run_test(program.pipe(fx.provide(client)).or_die())


def _drop(table: str) -> Generator[Any, Any]:
    sql = yield from SqlClient()
    for name in (table, f"{table}_migrations"):
        yield from sql("DROP TABLE IF EXISTS {}", sql.identifier(name))


def _queue(table: str, name: str) -> Generator[Any, Any, pq.PersistedQueue[str]]:
    store = yield from pq.make_store_sql(table_name=table, poll_interval="10 millis")
    factory = yield from pq.make_factory.pipe(fx.provide_service(pq.PersistedQueueStore, store))
    return (yield from factory.make(name=name, schema=S.String))


def _take(queue: pq.PersistedQueue[str]) -> Generator[Any, Any, tuple[str, str]]:
    taken = queue.take(lambda value, meta: fx.succeed((meta.id, value)))
    found = yield from taken.timeout("10 seconds")
    assert found is not None, "no element to take"
    return found


def _rows(table: str) -> Generator[Any, Any, int]:
    sql = yield from SqlClient()
    rows: Sequence[Any] = yield from sql("SELECT COUNT(*) AS n FROM {}", sql.identifier(table))
    return int(str(rows[0]["n"]))


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_ids_differing_only_in_case_accents_or_trailing_spaces_stay_distinct(
    client: fx.Layer[Any, Any], variant: str
) -> None:
    first, second = VARIANTS[variant]
    table = "effect_queue_exact_ids"

    def body():
        yield from _drop(table)
        queue = yield from _queue(table, "jobs")
        assert (yield from queue.offer("first", id=first)) == first
        assert (yield from queue.offer("second", id=second)) == second
        assert (yield from _rows(table)) == 2
        taken = {(yield from _take(queue)), (yield from _take(queue))}
        assert taken == {(first, "first"), (second, "second")}

    _run(client, body)


@pytest.mark.parametrize("variant", sorted(VARIANTS))
def test_queue_names_differing_only_in_case_accents_or_trailing_spaces_stay_distinct(
    client: fx.Layer[Any, Any], variant: str
) -> None:
    first, second = VARIANTS[variant]
    table = "effect_queue_exact_names"

    def body():
        yield from _drop(table)
        one = yield from _queue(table, first)
        other = yield from _queue(table, second)
        yield from one.offer("for one", id="same-id")
        yield from other.offer("for other", id="same-id")
        assert (yield from _rows(table)) == 2
        assert (yield from _take(other)) == ("same-id", "for other")
        assert (yield from _take(one)) == ("same-id", "for one")

    _run(client, body)


def test_upgrades_a_table_that_already_has_rows(client: fx.Layer[Any, Any]) -> None:
    """A table made by the first two migrations keeps its rows, and its
    unclaimed ones are still taken, after the store's later migrations."""
    table = "effect_queue_exact_upgrade"

    def first_two() -> migrator.Loader:
        return migrations(table).map(lambda loaded: [m for m in loaded if m[0] <= 2])

    def body():
        yield from _drop(table)
        yield from migrator.make()(loader=first_two(), table=f"{table}_migrations")
        sql = yield from SqlClient()
        now = sql.on_dialect_or_else(
            mssql=lambda: sql.literal("SYSDATETIME()"), or_else=lambda: sql.literal("NOW()")
        )
        for id, element in (("old-a", '"a"'), ("old-b", '"b"')):
            yield from sql(
                "INSERT INTO {} (id, queue_name, element, state, attempts, visible_at, "
                "created_at, updated_at) VALUES ({}, 'jobs', {}, 'pending', 0, {}, {}, {})",
                sql.identifier(table),
                id,
                element,
                now,
                now,
                now,
            )
        queue = yield from _queue(table, "jobs")
        yield from queue.offer("new", id="OLD-A")
        assert (yield from _rows(table)) == 3
        taken = {(yield from _take(queue)), (yield from _take(queue)), (yield from _take(queue))}
        assert taken == {("old-a", "a"), ("old-b", "b"), ("OLD-A", "new")}

    _run(client, body)
