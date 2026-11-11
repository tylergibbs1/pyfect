"""Ports of Effect's ``sql-pg/test/PgMigrator.test.ts`` and
``PgMigrator.integration.test.ts``.

As in Effect, the unit tests run the migrator on a client that does
nothing, record the ``pg_dump`` commands instead of running them and record
the files written. ``ssl: {rejectUnauthorized: false}`` is libpq's
``sslmode=require`` here (``ssl`` takes libpq parameters).

Omitted:
- "gives pg_dump the client's CA only while the dump runs": ``ssl`` takes
  libpq parameters (``sslrootcert`` is a path), so there is no CA text to
  write to a temporary file.
- "does not dump connections that libpq cannot reproduce": the client is
  libpq too (no ``stream`` factory), so ``pg_dump`` can reproduce every
  connection it makes.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import pytest

pytest.importorskip("psycopg")

from psycopg.conninfo import conninfo_to_dict

import pyfect as fx
from pyfect import path, redacted, scope, testing
from pyfect.file_system import NoopFileSystem, layer_noop
from pyfect.platform_error import PlatformError
from pyfect.process import ChildProcessSpawner, Command
from pyfect.process._command import StandardCommand
from pyfect.process._spawner import ChildProcessSpawnerService, Spawn
from pyfect.sql import SqlClient, pg
from pyfect.sql import client as sql_client
from pyfect.sql.pg import migrator as pg_migrator
from pyfect.stream import empty

from ._postgres import PgServer


class _NoRows:
    def execute(self, sql: str, params: Sequence[object], transform: object, /):
        return fx.succeed([])

    def execute_raw(self, sql: str, params: Sequence[object], /):
        return fx.succeed([])

    def execute_stream(self, sql: str, params: Sequence[object], transform: object, /):
        return empty

    def execute_values(self, sql: str, params: Sequence[object], /):
        return fx.succeed([])

    def execute_values_unprepared(self, sql: str, params: Sequence[object], /):
        return fx.succeed([])

    def execute_unprepared(self, sql: str, params: Sequence[object], transform: object, /):
        return fx.succeed([])


class _Files(NoopFileSystem):
    def __init__(self) -> None:
        self.written: list[str] = []

    def make_directory(self, path: str, *, recursive: bool = False, mode: int = 0o777):
        return fx.void

    def write_file_string(self, path: str, data: str, *, flag: Any = "w", mode: int = 0o666):
        return fx.sync(lambda: self.written.append(path))


class _Recorder(ChildProcessSpawnerService):
    __slots__ = ("commands",)

    def __init__(self, spawn: Spawn) -> None:
        super().__init__(spawn)
        self.commands: list[StandardCommand] = []

    def string(
        self, command: Command, *, include_stderr: bool = False
    ) -> fx.Effect[str, PlatformError]:
        assert isinstance(command, StandardCommand)
        self.commands.append(command)
        return fx.succeed("SELECT 1;")


@dataclass(frozen=True)
class _Migrator:
    commands: list[StandardCommand]
    files: list[str]
    run: fx.Effect[object, object]


def _make_migrator(config: pg.PgPoolConfig):
    def body():
        client = yield from pg.make(config)
        sql = yield from sql_client.make(
            acquirer=fx.succeed(_NoRows()),
            compiler=pg.make_compiler(),
            driver="test",
        )
        files = _Files()
        spawner = _Recorder(lambda _: fx.die(RuntimeError("unexpected spawn")))
        run = (
            pg_migrator.run(
                loader=pg_migrator.from_record({"1_init": fx.void}),
                schema_directory="migrations",
            )
            .pipe(fx.provide_service(pg.PgClient, client))
            .pipe(fx.provide_service(SqlClient, sql))
            .pipe(fx.provide_service(ChildProcessSpawner, spawner))
            .pipe(fx.provide(layer_noop(files)))
            .pipe(fx.provide(path.layer))
        )
        return _Migrator(spawner.commands, files.written, run)

    return fx.gen(body).pipe(fx.provide(fx.reactivity.layer))


def _dump_connection(command: StandardCommand) -> dict[str, Any]:
    [dbname] = [arg for arg in command.args if isinstance(arg, str) and arg.startswith("--dbname=")]
    return conninfo_to_dict(dbname.removeprefix("--dbname="))


def _env(command: StandardCommand) -> dict[str, object]:
    return dict(command.options.env or {})


@testing.effect
def test_shares_one_password_per_schema_dump_and_refreshes_it_for_the_next_dump():
    """shares one password per schema dump and refreshes it for the next dump"""
    calls: list[None] = []

    def password() -> redacted.Redacted[str]:
        calls.append(None)
        return redacted.make(f"secret-{len(calls)}")

    migrator = yield from _make_migrator(
        pg.PgPoolConfig(username="alice", password=fx.yield_now().map(lambda _: password()))
    )
    yield from migrator.run
    assert len(calls) == 1
    assert [c.command for c in migrator.commands] == ["pg_dump", "pg_dump"]
    assert [_env(c)["PGPASSWORD"] for c in migrator.commands] == ["secret-1", "secret-1"]
    yield from migrator.run
    assert len(calls) == 2
    assert [_env(c)["PGPASSWORD"] for c in migrator.commands] == [
        "secret-1",
        "secret-1",
        "secret-2",
        "secret-2",
    ]
    assert migrator.files == ["migrations/_schema.sql", "migrations/_schema.sql"]


@testing.effect
def test_passes_a_static_password_to_both_dump_processes():
    """passes a static password to both dump processes"""
    migrator = yield from _make_migrator(
        pg.PgPoolConfig(username="alice", password=redacted.make("static"))
    )
    yield from migrator.run
    assert [_env(c)["PGPASSWORD"] for c in migrator.commands] == ["static", "static"]
    assert migrator.files == ["migrations/_schema.sql"]


@testing.effect
def test_dumps_through_the_connection_resolved_from_the_url_and_explicit_fields():
    """dumps through the connection resolved from the url and explicit fields"""
    import os

    migrator = yield from _make_migrator(
        pg.PgPoolConfig(
            url=redacted.make("postgres://alice:s3cret@db.example.com:6543/app?sslmode=require"),
            database="reports",
        )
    )
    yield from migrator.run
    assert len(migrator.commands) == 2
    for command in migrator.commands:
        connection = _dump_connection(command)
        expected = {
            "host": "db.example.com",
            "port": "6543",
            "user": "alice",
            "dbname": "reports",
            "sslmode": "verify-full",
        }
        assert {key: connection.get(key) for key in expected} == expected
        assert not any(isinstance(arg, str) and "s3cret" in arg for arg in command.args)
        assert command.options.extend_env is False
        assert _env(command) == {"PATH": os.environ.get("PATH"), "PGPASSWORD": "s3cret"}


@testing.effect
def test_matches_the_clients_socket_and_unverified_tls_settings():
    """matches the client's socket and unverified TLS settings"""
    cases: list[tuple[pg.PgPoolConfig, dict[str, str]]] = [
        (
            pg.PgPoolConfig(username="alice", path="/var/run/postgresql/.s.PGSQL.5433"),
            {"host": "/var/run/postgresql", "port": "5433", "sslmode": "disable"},
        ),
        (
            pg.PgPoolConfig(username="alice", host="db.example.com", ssl={"sslmode": "require"}),
            {"sslmode": "require"},
        ),
    ]
    for config, expected in cases:
        migrator = yield from _make_migrator(config)
        yield from migrator.run
        assert len(migrator.commands) == 2
        for command in migrator.commands:
            connection = _dump_connection(command)
            assert {key: connection.get(key) for key in expected} == expected


@testing.live
def test_accepts_a_history_table_committed_by_a_concurrent_migrator(pg_server: PgServer):
    """accepts a history table committed by a concurrent migrator"""

    def body():
        sql = yield from SqlClient()
        created = yield from fx.Deferred[object].make()
        commit = yield from fx.Deferred[None].make()
        runs: list[None] = []

        def creating():
            [session] = yield from sql("SELECT pg_backend_pid() AS pid")
            yield from sql(
                "CREATE TABLE race_migrations ("
                " migration_id INTEGER PRIMARY KEY,"
                " created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),"
                " name TEXT NOT NULL)"
            )
            yield from sql("INSERT INTO race_migrations (migration_id, name) VALUES (1, 'init')")
            yield from created.succeed(session["pid"])
            yield from commit.wait()

        creator = yield from scope.fork_scoped(sql.with_transaction(fx.gen(creating)))

        def racing():
            creator_pid = yield from created.wait()
            migrator = yield from scope.fork_scoped(
                pg_migrator.run(
                    table="race_migrations",
                    loader=pg_migrator.from_record({"1_init": fx.sync(lambda: runs.append(None))}),
                )
            )

            def blocked():
                while True:
                    rows = yield from sql(
                        "SELECT pid FROM pg_stat_activity WHERE wait_event_type = 'Lock'"
                        " AND query LIKE 'CREATE TABLE \"race_migrations\"%'"
                        " AND {} = ANY(pg_blocking_pids(pid))",
                        creator_pid,
                    )
                    if rows:
                        return
                    yield from fx.sleep("10 millis")

            yield from fx.gen(blocked).timeout("10 seconds")
            yield from commit.succeed(None)
            yield from creator.join()
            assert (yield from migrator.join()) == []
            assert runs == []
            rows = yield from sql("SELECT migration_id, name FROM race_migrations")
            assert rows == [{"migration_id": 1, "name": "init"}]

        yield from fx.gen(racing).ensuring(commit.succeed(None))

    layer = pg.layer(pg.PgPoolConfig(url=pg_server.url))
    yield from fx.scoped(fx.gen(body)).pipe(fx.provide(layer)).pipe(fx.provide(fx.platform.layer))
