"""Ports of Effect's ``sql-sqlite-node/test/SqliteMigrator.test.ts``.

Each test's docstring is the Effect test title.
"""

from pathlib import Path

import pyfect as fx
from pyfect import testing
from pyfect.sql.client import SqlClient
from pyfect.sql.error import LockTimeoutError, SqlError, is_sql_error
from pyfect.sql.migrator import MigrationError
from pyfect.sql.sqlite import migrator as sqlite_migrator

from ._sqlite import make_client


@testing.effect
def test_fails_with_a_typed_migration_error_and_rolls_back_failed_migrations(tmp_path: Path):
    """fails with a typed MigrationError and rolls back failed migrations"""
    migrator_client = yield from make_client(tmp_path)

    def bad():
        sql = yield from SqlClient()
        yield from sql("INSERT INTO missing_table (id) VALUES (1)")

    error = yield from (
        sqlite_migrator.run(loader=sqlite_migrator.from_record({"1_bad": fx.gen(bad)}))
        .pipe(fx.provide_service(SqlClient, migrator_client))
        .flip()
    )

    assert isinstance(error, MigrationError)
    assert error.kind == "Failed"
    assert is_sql_error(error.cause)
    assert (yield from migrator_client("SELECT migration_id FROM effect_sql_migrations")) == []


@testing.effect
def test_fails_on_lock_errors(tmp_path: Path):
    """fails on lock errors"""
    lock_client = yield from make_client(tmp_path)
    migrator_client = yield from make_client(tmp_path)

    yield from migrator_client("PRAGMA busy_timeout = 1")
    yield from sqlite_migrator.run(loader=sqlite_migrator.from_record({})).pipe(
        fx.provide_service(SqlClient, migrator_client)
    )
    yield from fx.acquire_release(
        lock_client("BEGIN IMMEDIATE"), lambda _a, _e: lock_client("ROLLBACK").ignore()
    )

    error = yield from (
        sqlite_migrator.run(loader=sqlite_migrator.from_record({"1_test": fx.void}))
        .pipe(fx.provide_service(SqlClient, migrator_client))
        .flip()
    )

    assert isinstance(error, SqlError)
    assert isinstance(error.reason, LockTimeoutError)
