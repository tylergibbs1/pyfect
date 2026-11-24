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
from pyfect.sql import SqlClient, SqlClientService, migrator

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

    def first_two(sql: SqlClientService) -> migrator.Loader:
        return migrations(table, sql).map(lambda loaded: [m for m in loaded if m[0] <= 2])

    def body():
        yield from _drop(table)
        sql = yield from SqlClient()
        yield from migrator.make()(loader=first_two(sql), table=f"{table}_migrations")
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


def test_an_id_longer_than_its_column_fails_instead_of_being_cut(
    client: fx.Layer[Any, Any],
) -> None:
    """Cut to the column, two long ids sharing its first bytes were one: the
    second offer was dropped while it reported the id stored (MySQL's
    ``INSERT IGNORE``)."""
    table = "effect_queue_exact_long_ids"
    long = "x" * 1100

    def body():
        yield from _drop(table)
        queue = yield from _queue(table, "jobs")
        for suffix in ("a", "b"):
            failed = yield from queue.offer(suffix, id=long + suffix).flip()
            assert isinstance(failed, pq.PersistedQueueError)
        yield from queue.offer("short", id="short")
        yield from queue.offer("again", id="short")
        assert (yield from _rows(table)) == 1

    _run(client, body)


MYSQL_DATABASES = pytest.mark.parametrize(
    "collation", [None, "utf8mb4_general_ci"], ids=["mysql", "mysql-pad-space"]
)


def _as_of_0_6_35(table: str, sql: SqlClientService) -> migrator.Loader:
    """The migrations 0.6.35 ran on MySQL, SQL Server and SQLite: ``0004`` is
    PostgreSQL's alone."""
    return migrations(table, sql).map(lambda loaded: [m for m in loaded if m[0] <= 3])


def _recorded(table: str) -> Generator[Any, Any, list[tuple[object, object]]]:
    sql = (yield from SqlClient()).without_transforms()
    rows: Sequence[Any] = yield from sql(
        "SELECT migration_id, name FROM {} ORDER BY migration_id",
        sql.identifier(f"{table}_migrations"),
    )
    return [(row["migration_id"], row["name"]) for row in rows]


_RELEASED = [(1, "create_table"), (2, "upgrade_schema"), (3, "exact_ids")]
UPGRADED = {"mysql": [*_RELEASED, (5, "exact_text_ids")], "mssql": _RELEASED, "sqlite": _RELEASED}
"""What each dialect's migrations table records after a 0.6.35 table
upgrades. A name is permanent in users' databases; PostgreSQL's (``0004``)
is pinned by ``test_pg_persisted_queue``."""


def _upgrade_from_0_6_35(table: str) -> Generator[Any, Any, list[tuple[object, object]]]:
    yield from _drop(table)
    sql = yield from SqlClient()
    yield from migrator.make()(loader=_as_of_0_6_35(table, sql), table=f"{table}_migrations")
    assert (yield from _recorded(table)) == _RELEASED
    queue = yield from _queue(table, "jobs")
    yield from queue.offer("element", id="job")
    assert (yield from _take(queue)) == ("job", "element")
    return (yield from _recorded(table))


def test_a_0_6_35_table_upgrades_with_its_dialects_migrations(
    client: fx.Layer[Any, Any], request: pytest.FixtureRequest
) -> None:
    """(pyfect) MySQL alone runs ``0005_exact_text_ids``; SQL Server keeps
    0.6.35's migrations."""
    dialect = "mysql" if request.node.callspec.params["client"].startswith("mysql") else "mssql"
    recorded = _run(client, lambda: _upgrade_from_0_6_35("effect_queue_upgrade_0635"))
    assert recorded == UPGRADED[dialect]


def test_a_0_6_35_sqlite_table_keeps_its_migrations() -> None:
    from pyfect.sql import sqlite

    client = sqlite.layer(sqlite.SqliteClientConfig(filename=":memory:"))
    recorded = _run(client, lambda: _upgrade_from_0_6_35("effect_queue_upgrade_0635"))
    assert recorded == UPGRADED["sqlite"]


def _raw_ids(table: str) -> Generator[Any, Any, list[tuple[object, object]]]:
    sql = (yield from SqlClient()).without_transforms()
    rows: Sequence[Any] = yield from sql(
        "SELECT id, queue_name FROM {} ORDER BY sequence", sql.identifier(table)
    )
    return [(row["id"], row["queue_name"]) for row in rows]


@MYSQL_DATABASES
def test_mysql_ids_are_exact_text_as_in_effects_table(
    request: pytest.FixtureRequest, collation: str | None
) -> None:
    """(pyfect) On MySQL the id and queue name columns hold text, as Effect's
    ``VARCHAR(255)`` do, in ``utf8mb4_0900_bin``: a pyfect from before
    ``0003_exact_ids`` (or Effect) reading the table gets ``"job"``, never
    ``b"job"``, during a rolling upgrade or after a downgrade."""
    client = _mysql(request, collation)
    table = "effect_queue_text_ids"

    def body():
        yield from _drop(table)
        queue = yield from _queue(table, "jobs")
        yield from queue.offer("element", id="job")
        assert (yield from _raw_ids(table)) == [("job", "jobs")]
        sql = yield from SqlClient()
        columns: Sequence[Any] = yield from sql(
            "SELECT COLUMN_NAME AS name, COLUMN_TYPE AS type, COLLATION_NAME AS collation "
            "FROM information_schema.COLUMNS WHERE TABLE_SCHEMA = DATABASE() "
            "AND TABLE_NAME = {} AND COLUMN_NAME IN ('id', 'queue_name') ORDER BY COLUMN_NAME",
            table,
        ).without_transform
        assert [(c["name"], c["type"], c["collation"]) for c in columns] == [
            ("id", "varchar(255)", "utf8mb4_0900_bin"),
            ("queue_name", "varchar(255)", "utf8mb4_0900_bin"),
        ]

    _run(client, body)


@MYSQL_DATABASES
def test_mysql_upgrades_a_varbinary_table_and_keeps_its_rows(
    request: pytest.FixtureRequest, collation: str | None
) -> None:
    """(pyfect) A table ``0003_exact_ids`` made ``VARBINARY`` (0.6.4 to 0.6.10)
    goes back to text with its rows, which are taken as before."""
    client = _mysql(request, collation)
    table = "effect_queue_text_upgrade"

    def body():
        yield from _drop(table)
        sql = yield from SqlClient()
        yield from migrator.make()(loader=_as_of_0_6_35(table, sql), table=f"{table}_migrations")
        for id, element in (("old-a", '"a"'), ("OLD-A", '"A"'), ("résumé", '"r"')):
            yield from sql(
                "INSERT INTO {} (id, queue_name, element, state, attempts, visible_at, "
                "created_at, updated_at) VALUES ({}, 'jobs', {}, 'pending', 0, NOW(), NOW(), "
                "NOW())",
                sql.identifier(table),
                id,
                element,
            )
        varbinary: Sequence[Any] = yield from sql(
            "SELECT id FROM {}", sql.identifier(table)
        ).without_transform
        assert all(isinstance(row["id"], bytes) for row in varbinary)
        queue = yield from _queue(table, "jobs")
        assert (yield from _raw_ids(table)) == [
            ("old-a", "jobs"),
            ("OLD-A", "jobs"),
            ("résumé", "jobs"),
        ]
        yield from queue.offer("again", id="old-a")
        assert (yield from _rows(table)) == 3
        taken = {(yield from _take(queue)), (yield from _take(queue)), (yield from _take(queue))}
        assert taken == {("old-a", "a"), ("OLD-A", "A"), ("résumé", "r")}

    _run(client, body)


def test_mysql_an_id_of_more_than_255_characters_fails_instead_of_being_cut(
    request: pytest.FixtureRequest,
) -> None:
    """(pyfect) ``VARCHAR(255)`` holds 255 characters, however many bytes
    they take; ``INSERT IGNORE`` would cut a longer id."""
    client = _mysql(request, None)
    table = "effect_queue_text_long_ids"

    def body():
        yield from _drop(table)
        queue = yield from _queue(table, "jobs")
        yield from queue.offer("wide", id="é" * 255)
        for id in ("x" * 256, "é" * 256):
            failed = yield from queue.offer("long", id=id).flip()
            assert isinstance(failed, pq.PersistedQueueError), id
        assert (yield from _raw_ids(table)) == [("é" * 255, "jobs")]

    _run(client, body)


def test_mysql_upgrading_a_table_holding_an_id_of_more_than_255_characters_fails(
    request: pytest.FixtureRequest,
) -> None:
    """(pyfect) ``0003_exact_ids`` took ids of up to 1020 bytes; one longer
    than ``VARCHAR(255)`` stops the upgrade, saying so, instead of being
    cut."""
    client = _mysql(request, None)
    table = "effect_queue_text_long_upgrade"

    def body():
        yield from _drop(table)
        sql = yield from SqlClient()
        yield from migrator.make()(loader=_as_of_0_6_35(table, sql), table=f"{table}_migrations")
        yield from sql(
            "INSERT INTO {} (id, queue_name, element, state, attempts, visible_at, created_at, "
            "updated_at) VALUES ({}, 'jobs', {}, 'pending', 0, NOW(), NOW(), NOW())",
            sql.identifier(table),
            "x" * 300,
            '"a"',
        )
        failed = yield from pq.make_store_sql(table_name=table).exit()
        assert "1 rows of effect_queue_text_long_upgrade have an id or queue name" in str(failed)
        assert (yield from _raw_ids(table))[0][0] == b"x" * 300

    _run(client, body)
