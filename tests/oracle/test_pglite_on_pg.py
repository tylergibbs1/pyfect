"""Ports of the titles of Effect's ``sql-pglite/test`` whose behavior is
PostgreSQL's rather than PGlite's, run on ``pyfect.sql.pg`` against the
throwaway local PostgreSQL (``_postgres.pg_server``; skipped without one).
PGlite itself is not ported (docs/PARITY.md §4: no Python PGlite exists).

Each test's docstring is the Effect test title. The client and migrator
titles of these files that ``sql-pg`` shares (insert, update, updateValues,
in, and helpers, identifier transform, releases completed nested
transaction locks, preserves successful concurrent nested transactions,
the PersistedQueue SQL migrations, error classification) are ported in
``test_pg_client.py``, ``test_pg_persisted_queue.py`` and
``test_pg_sql_error_classification.py``.

Omitted: "provider extras" (PGlite's ``dumpDataDir``); "identifies the
pglite driver on directly constructed clients" (PGlite's ``driver`` name;
pg's is pinned in ``test_pg_client.py``); "refreshArrayTypes" (PGlite
refreshes its JavaScript array parsers; psycopg loads array types itself);
"works" under ``fromClient`` (a caller-owned PGlite instance); "does not
starve the shared PGlite connection" (PGlite's single connection, see
``test_sql_runner_storage.py``).
"""

from collections.abc import Callable, Generator
from typing import Any, Literal

import pytest

pytest.importorskip("psycopg")

import pyfect as fx
from pyfect import scope, testing
from pyfect.sql import BeginTransaction, migrator, pg
from pyfect.sql.client import SqlClient

from ._postgres import PgServer

type Body = Callable[[], Generator[Any, Any, Any]]


def _with_pool(server: PgServer, body: Body) -> fx.Effect[Any, Any]:
    layer = pg.layer(pg.PgPoolConfig(url=server.url))
    return fx.scoped(fx.gen(body)).pipe(fx.provide(layer))


def _setup(sql: pg.PgClientService, table: str) -> fx.Effect[None, Any]:
    return (
        sql.unsafe(f"DROP TABLE IF EXISTS {table}")
        .and_then(sql.unsafe(f"CREATE TABLE {table} (id SERIAL PRIMARY KEY, name TEXT)"))
        .as_(None)
    )


# --- Client.test.ts -------------------------------------------------------------


@testing.effect
def test_basic_insert_select(pg_server: PgServer):
    """basic insert/select"""

    def body():
        sql = yield from pg.PgClient()
        yield from _setup(sql, "pglite_basic")
        yield from sql("INSERT INTO pglite_basic (name) VALUES ('hello')")
        assert (yield from sql("SELECT * FROM pglite_basic")) == [{"id": 1, "name": "hello"}]
        assert (yield from sql("SELECT * FROM pglite_basic").values) == [(1, "hello")]

    yield from _with_pool(pg_server, body)


@testing.effect
def test_in_helper_is_not_rewritten_inside_a_line_comment(pg_server: PgServer):
    """in helper is not rewritten inside a line comment"""

    def body():
        sql = yield from pg.PgClient()
        query, _ = sql("SELECT 2 -- check in\n{} AS x", sql.in_([])).compile()
        assert query == "SELECT 2 -- check in\n() AS x"

    yield from _with_pool(pg_server, body)


@testing.effect
def test_json_fragment(pg_server: PgServer):
    """json fragment"""

    def body():
        sql = yield from pg.PgClient()
        rows = yield from sql("SELECT {}::jsonb AS json", sql.json({"a": 1}))
        assert rows[0]["json"] == {"a": 1}

    yield from _with_pool(pg_server, body)


@testing.live
def test_listen_notify(pg_server: PgServer):
    """listen + notify"""

    def body():
        sql = yield from pg.PgClient()
        notifications = yield from sql.listen("pglite_ch1")
        yield from sql.notify("pglite_ch1", "hello")
        assert (yield from notifications.take()).payload == "hello"
        yield from sql.notify("pglite_ch1", "")
        assert (yield from notifications.take()).payload == ""

    yield from _with_pool(pg_server, body).timeout("15 seconds")


@testing.live
def test_listen_shuts_down_with_its_scope(pg_server: PgServer):
    """listen shuts down with its scope"""

    def body():
        sql = yield from pg.PgClient()
        listen_scope = yield from scope.make()
        notifications = yield from sql.listen("pglite_ch1").pipe(scope.provide(listen_scope))
        yield from listen_scope.close(fx.Success(None))
        exit_ = yield from notifications.take().exit()
        assert isinstance(exit_, fx.Failure)
        assert exit_.cause.has_interrupts

    yield from _with_pool(pg_server, body).timeout("15 seconds")


# --- Json.test.ts ---------------------------------------------------------------


@testing.effect
@pytest.mark.parametrize("kind", ["json", "jsonb"])
@pytest.mark.parametrize("value", ["null", "123", "hello", "", '"quoted"\\\n'])
def test_json_preserves_the_string(pg_server: PgServer, kind: Literal["json", "jsonb"], value: str):
    """${type} preserves the string %j"""

    def body():
        sql = yield from pg.PgClient()
        rows = yield from sql("SELECT {}::{} AS value", sql.json(value), sql.literal(kind))
        assert rows == [{"value": value}]

    yield from _with_pool(pg_server, body)


# --- Transaction.test.ts --------------------------------------------------------


@testing.effect
def test_with_transaction_commit(pg_server: PgServer):
    """withTransaction commit"""

    def body():
        sql = yield from pg.PgClient()
        yield from _setup(sql, "pglite_tx_commit")
        yield from sql.with_transaction(
            sql.unsafe("INSERT INTO pglite_tx_commit (name) VALUES ('hello')")
        )
        assert (yield from sql.unsafe("SELECT name FROM pglite_tx_commit")) == [{"name": "hello"}]

    yield from _with_pool(pg_server, body)


@testing.effect
def test_with_transaction_rollback(pg_server: PgServer):
    """withTransaction rollback"""

    def body():
        sql = yield from pg.PgClient()
        yield from _setup(sql, "pglite_tx_rollback")
        yield from sql.with_transaction(
            sql.unsafe("INSERT INTO pglite_tx_rollback (name) VALUES ('hello')").and_then(
                fx.fail("boom")
            )
        ).ignore()
        assert (yield from sql.unsafe("SELECT * FROM pglite_tx_rollback")) == []

    yield from _with_pool(pg_server, body)


@testing.effect
def test_with_transaction_with_begin_transaction_sets_the_isolation_level(pg_server: PgServer):
    """withTransaction with BeginTransaction sets the isolation level"""

    def body():
        sql = yield from pg.PgClient()
        level = sql("SHOW transaction_isolation")
        serializable = yield from sql.with_transaction(level).pipe(
            fx.provide_service(BeginTransaction, "BEGIN ISOLATION LEVEL SERIALIZABLE")
        )
        assert serializable == [{"transaction_isolation": "serializable"}]
        default = yield from sql.with_transaction(level)
        assert default == [{"transaction_isolation": "read committed"}]

    yield from _with_pool(pg_server, body)


@testing.effect
def test_nested_transaction_commits_both(pg_server: PgServer):
    """nested transaction commits both"""

    def body():
        sql = yield from pg.PgClient()
        yield from _setup(sql, "pglite_tx_nested_commit")
        stmt = sql.unsafe("INSERT INTO pglite_tx_nested_commit (name) VALUES ('hello')")
        yield from sql.with_transaction(stmt.and_then(sql.with_transaction(stmt)))
        rows = yield from sql.unsafe("SELECT count(*)::int AS total FROM pglite_tx_nested_commit")
        assert rows[0]["total"] == 2

    yield from _with_pool(pg_server, body)


@testing.effect
def test_nested_transaction_rollback_via_savepoint(pg_server: PgServer):
    """nested transaction rollback via savepoint"""

    def body():
        sql = yield from pg.PgClient()
        yield from _setup(sql, "pglite_tx_nested_rollback")
        stmt = sql.unsafe("INSERT INTO pglite_tx_nested_rollback (name) VALUES ('hello')")
        inner = sql.with_transaction(stmt.and_then(fx.fail("boom"))).ignore()
        yield from sql.with_transaction(stmt.and_then(inner))
        rows = yield from sql.unsafe("SELECT count(*)::int AS total FROM pglite_tx_nested_rollback")
        assert rows[0]["total"] == 1

    yield from _with_pool(pg_server, body)


# --- Migrator.test.ts -----------------------------------------------------------


@testing.effect
def test_runs_migrations_and_records_them(pg_server: PgServer):
    """runs migrations and records them"""
    table = "pglite_migrations_recorded"

    def init():
        sql = yield from SqlClient()
        yield from sql("DROP TABLE IF EXISTS pglite_migrator_test")
        yield from sql("CREATE TABLE pglite_migrator_test (id SERIAL PRIMARY KEY, value TEXT)")

    def insert():
        sql = yield from SqlClient()
        yield from sql("INSERT INTO pglite_migrator_test (value) VALUES ('hello')")

    loader = fx.succeed(
        [(1, "init", fx.succeed(fx.gen(init))), (2, "insert", fx.succeed(fx.gen(insert)))]
    )

    def body():
        sql = yield from pg.PgClient()
        yield from sql.unsafe(f"DROP TABLE IF EXISTS {table}")
        yield from migrator.make()(loader=loader, table=table)
        rows = yield from sql("SELECT value FROM pglite_migrator_test")
        assert rows == [{"value": "hello"}]
        migrations = yield from sql(
            "SELECT migration_id, name FROM {} ORDER BY migration_id", sql.identifier(table)
        )
        assert [(m["migration_id"], m["name"]) for m in migrations] == [(1, "init"), (2, "insert")]

    yield from _with_pool(pg_server, body)


@testing.effect
def test_reuses_a_migrations_table_whose_name_needs_quoting(pg_server: PgServer):
    """reuses a migrations table whose name needs quoting"""
    table = "MixedCase_make_migrations"

    def body():
        sql = yield from pg.PgClient()
        yield from sql("DROP TABLE IF EXISTS {}", sql.identifier(table))
        loader = migrator.from_record({"1_first": fx.void})
        yield from migrator.make()(loader=loader, table=table)
        completed = yield from migrator.make()(loader=loader, table=table)
        assert completed == []

    yield from _with_pool(pg_server, body)
