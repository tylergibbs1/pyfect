"""Ports of Effect's ``sql-sqlite-node/test/Client.test.ts``.

Each test's docstring is the Effect test title; ``it.effect.each`` cases
are parametrized. Patching ``executeUnprepared`` on the reserved
connection is setting ``execute_unprepared`` on it.

Adapted: the WAL retry tests wait until the client sleeps on the test
clock before moving it, since opening a connection is asynchronous here.
"works when node:sqlite does not provide enableLoadExtension"
checks that loading a missing extension fails with a ``SqlError`` whether
or not Python's ``sqlite3`` was built with extension loading (a C type's
method cannot be deleted to simulate its absence).
"""

import sqlite3
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.scheduler import MaxOpsBeforeYield
from pyfect.sql.connection import Row
from pyfect.sql.error import ConnectionError, ConstraintError, LockTimeoutError, SqlError
from pyfect.sql.sqlite import RunResult
from pyfect.sql.statement import Statement

from ._sqlite import make_client, make_memory_client


def _run_as(statement: Statement[Row], mode: str) -> fx.Effect[Sequence[object], SqlError]:
    """The statement's rows, or its values for ``mode == "values"``."""
    return statement.values if mode == "values" else statement


def _failure(ex: fx.Exit[Any, Any]) -> fx.Failure[Any]:
    assert isinstance(ex, fx.Failure)
    return ex


@testing.effect
def test_releases_completed_nested_savepoints(tmp_path: Path):
    """releases completed nested savepoints"""
    sql = yield from make_client(tmp_path)
    yield from sql("CREATE TABLE savepoint_release (value INTEGER)")

    def body():
        for rollback in (False, True):
            yield from sql.with_transaction(
                sql("INSERT INTO savepoint_release VALUES (1)").and_then(
                    fx.fail("rollback") if rollback else fx.void
                )
            ).ignore()
            error = yield from sql("RELEASE SAVEPOINT effect_sql_1").unprepared.flip()
            assert isinstance(error, SqlError)

    yield from sql.with_transaction(fx.gen(body))
    assert (yield from sql("SELECT value FROM savepoint_release")) == [{"value": 1}]
    error = yield from sql.with_transaction(
        sql.with_transaction(sql("INSERT INTO savepoint_release VALUES (2)")).and_then(
            fx.fail("outer rollback")
        )
    ).flip()
    assert error == "outer rollback"
    assert (yield from sql("SELECT value FROM savepoint_release")) == [{"value": 1}]


@testing.effect
def test_should_work(tmp_path: Path):
    """should work"""
    sql = yield from make_client(tmp_path)
    assert (yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")) == []
    assert (yield from sql("INSERT INTO test (name) VALUES ('hello')")) == []
    assert (yield from sql("SELECT * FROM test")) == [{"id": 1, "name": "hello"}]
    assert (yield from sql("SELECT * FROM test").values_unprepared) == [(1, "hello")]
    response = yield from sql.with_transaction(sql("INSERT INTO test (name) VALUES ('world')"))
    assert response == []
    assert (yield from sql("SELECT * FROM test")) == [
        {"id": 1, "name": "hello"},
        {"id": 2, "name": "world"},
    ]
    assert (yield from sql("INSERT INTO test (name) VALUES ('unprepared')").values_unprepared) == []
    assert (yield from sql("SELECT * FROM test WHERE id = 3")) == [{"id": 3, "name": "unprepared"}]


@pytest.mark.parametrize("mode", ["rows", "values"])
@testing.effect
def test_returns_cached_insert_across_count_changes_off_on_off(tmp_path: Path, mode: str):
    """returns cached INSERT %s across count_changes OFF → ON → OFF"""
    sql = yield from make_client(tmp_path)
    yield from sql("CREATE TABLE count_changes (value INTEGER)")
    yield from sql("PRAGMA count_changes = OFF")
    execute = _run_as(sql("INSERT INTO count_changes VALUES (1)"), mode)

    assert (yield from execute) == []
    yield from sql("PRAGMA count_changes = ON")
    assert len((yield from execute)) == 1
    yield from sql("PRAGMA count_changes = OFF")
    assert (yield from execute) == []
    assert (yield from sql("SELECT COUNT(*) AS count FROM count_changes")) == [{"count": 3}]


@pytest.mark.parametrize("mode", ["rows", "values"])
@testing.effect
def test_retries_queries_after_a_missing_table_is_created(tmp_path: Path, mode: str):
    """retries %s queries after a missing table is created"""
    sql = yield from make_client(tmp_path)
    execute = _run_as(sql("SELECT value FROM created_later"), mode)

    error = yield from execute.flip()
    assert isinstance(error, SqlError)
    yield from sql("CREATE TABLE created_later (value INTEGER)")
    yield from sql("INSERT INTO created_later VALUES (1)")

    assert (yield from execute) == ([(1,)] if mode == "values" else [{"value": 1}])


@testing.effect
def test_should_work_with_raw(tmp_path: Path):
    """should work with raw"""
    sql = yield from make_client(tmp_path)
    response = yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)").raw
    assert response == RunResult(changes=0, last_insert_rowid=0)
    response = yield from sql("INSERT INTO test (name) VALUES ('hello')").raw
    assert response == RunResult(changes=1, last_insert_rowid=1)
    assert (yield from sql("SELECT * FROM test").raw) == [{"id": 1, "name": "hello"}]
    response = yield from sql.with_transaction(sql("INSERT INTO test (name) VALUES ('world')").raw)
    assert response == RunResult(changes=1, last_insert_rowid=2)
    assert (yield from sql("SELECT * FROM test")) == [
        {"id": 1, "name": "hello"},
        {"id": 2, "name": "world"},
    ]


@pytest.mark.parametrize("mode", ["unprepared", "valuesUnprepared"])
@testing.effect
def test_captures_preparation_errors(tmp_path: Path, mode: str):
    """captures ${mode} preparation errors"""
    sql = yield from make_client(tmp_path)
    yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY)")

    statement = sql("CREATE TABLE test (id INTEGER PRIMARY KEY)")
    execution = (statement.unprepared if mode == "unprepared" else statement.values_unprepared).as_(
        False
    )
    recovered = yield from execution.pipe(fx.catch_tag(SqlError, lambda _: fx.succeed(True)))

    assert recovered is True


@testing.effect
def test_with_transaction(tmp_path: Path):
    """withTransaction"""
    sql = yield from make_client(tmp_path)
    yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
    yield from sql.with_transaction(sql("INSERT INTO test (name) VALUES ('hello')"))
    assert (yield from sql("SELECT * FROM test")) == [{"id": 1, "name": "hello"}]


@pytest.mark.parametrize("mode", ["ABORT", "ROLLBACK", "nested ROLLBACK"])
@testing.effect
def test_preserves_a_typed_constraint_failure_and_reuses_the_connection(mode: str):
    """preserves a typed constraint failure and reuses the connection after %s"""
    sql = yield from make_memory_client()
    yield from sql("CREATE TABLE items (id INTEGER PRIMARY KEY)")
    yield from sql("INSERT INTO items VALUES (1)")

    insert = (
        sql("INSERT INTO items VALUES (1)")
        if mode == "ABORT"
        else sql("INSERT OR ROLLBACK INTO items VALUES (1)")
    )
    transaction = sql.with_transaction(
        sql.with_transaction(insert) if mode == "nested ROLLBACK" else insert
    )
    ex = _failure((yield from transaction.exit()))
    assert not ex.cause.has_dies, ex.cause.pretty()
    error = ex.cause.find_error()
    assert isinstance(error, fx.Ok)
    assert isinstance(error.value, SqlError)
    assert isinstance(error.value.reason, ConstraintError)

    recovered = yield from transaction.as_(False).pipe(
        fx.catch_tag(SqlError, lambda _: fx.succeed(True))
    )
    assert recovered is True
    yield from sql.with_transaction(sql("INSERT INTO items VALUES (2)"))
    assert (yield from sql("SELECT id FROM items ORDER BY id")) == [{"id": 1}, {"id": 2}]


@pytest.mark.parametrize("mode", ["missing savepoint", "unrelated cleanup error"])
@testing.effect
def test_keeps_a_cleanup_failure_as_a_defect_and_rolls_back_the_outer_transaction(mode: str):
    """keeps a %s as a defect and rolls back the outer transaction"""
    sql = yield from make_memory_client()
    yield from sql("CREATE TABLE items (id INTEGER PRIMARY KEY)")
    error = SqlError(
        reason=ConnectionError(
            message="injected cleanup failure",
            operation="rollback",
            cause=Exception("injected cleanup failure"),
        )
    )
    if mode == "unrelated cleanup error":
        conn: Any = yield from fx.scoped(sql.reserve)
        execute_unprepared = conn.execute_unprepared

        def failing(sql_text: str, *args: Any) -> fx.Effect[Any, SqlError]:
            if sql_text.startswith("ROLLBACK TO SAVEPOINT"):
                return fx.fail(error)
            return execute_unprepared(sql_text, *args)

        conn.execute_unprepared = failing

    def inner():
        yield from sql("INSERT INTO items VALUES (1)")
        if mode == "missing savepoint":
            yield from sql("RELEASE SAVEPOINT effect_sql_1").unprepared
        return (yield from fx.fail(error))

    ex = yield from sql.with_transaction(
        sql.with_transaction(fx.gen(inner)).pipe(fx.catch_tag(SqlError, lambda _: fx.void))
    ).exit()

    assert (yield from sql("SELECT id FROM items")) == []
    failure = _failure(ex)
    assert failure.cause.has_dies
    expected = "no such savepoint" if mode == "missing savepoint" else "injected cleanup failure"
    assert expected in failure.cause.pretty().lower()


@testing.effect
def test_recovers_a_failed_deferred_commit_without_losing_an_in_memory_database():
    """recovers a failed deferred commit without losing an in-memory database"""
    sql = yield from make_memory_client()
    yield from sql("PRAGMA foreign_keys = ON")
    yield from sql("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
    yield from sql(
        "CREATE TABLE child (parent_id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)"
    )
    yield from sql("INSERT INTO parent VALUES (1)")

    failed_commit = _failure(
        (yield from sql.with_transaction(sql("INSERT INTO child VALUES (999)")).exit())
    )
    assert "foreign key constraint failed" in failed_commit.cause.pretty().lower()

    assert (yield from sql("SELECT * FROM parent")) == [{"id": 1}]
    assert (yield from sql("SELECT * FROM child")) == []
    yield from sql.with_transaction(sql("INSERT INTO child VALUES (1)"))
    assert (yield from sql("SELECT * FROM child")) == [{"parent_id": 1}]


@testing.effect
def test_poisons_the_connection_when_failed_commit_cleanup_fails(tmp_path: Path):
    """poisons the connection when failed-commit cleanup fails"""
    sql = yield from make_client(tmp_path)
    yield from sql("PRAGMA foreign_keys = ON")
    yield from sql("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
    yield from sql(
        "CREATE TABLE child (parent_id INTEGER REFERENCES parent(id) DEFERRABLE INITIALLY DEFERRED)"
    )
    yield from sql("INSERT INTO parent VALUES (1)")

    # Reserve lends the same SQLite connection used by transactions. Fail only
    # the cleanup ROLLBACK, leaving the deferred constraint failure real.
    conn: Any = yield from fx.scoped(sql.reserve)
    execute_unprepared = conn.execute_unprepared
    fail_rollback = [True]

    def patched(sql_text: str, *args: Any) -> fx.Effect[Any, SqlError]:
        if sql_text == "ROLLBACK" and fail_rollback[0]:
            return fx.fail(
                SqlError(
                    reason=ConnectionError(
                        message="injected rollback failure",
                        operation="rollback",
                        cause=Exception("injected rollback failure"),
                    )
                )
            )
        return execute_unprepared(sql_text, *args)

    conn.execute_unprepared = patched

    failed_commit = _failure(
        (yield from sql.with_transaction(sql("INSERT INTO child VALUES (999)")).exit())
    )
    cause = failed_commit.cause.pretty().lower()
    assert "foreign key constraint failed" in cause
    assert "injected rollback failure" in cause

    query = _failure((yield from sql("SELECT * FROM parent").exit()))
    assert "cannot be reused after failed commit cleanup" in query.cause.pretty().lower()
    transaction = yield from sql.with_transaction(
        fx.die(RuntimeError("transaction body ran"))
    ).exit()
    assert isinstance(transaction, fx.Failure)
    query_after_transaction = yield from sql("SELECT * FROM parent").exit()
    assert isinstance(query_after_transaction, fx.Failure)
    # Retry cleanup after the transient failure clears, without replacing the database.
    fail_rollback[0] = False
    assert (yield from sql("SELECT * FROM parent")) == [{"id": 1}]
    assert (yield from sql("SELECT * FROM child")) == []
    yield from sql("INSERT INTO child VALUES (1)")
    assert (yield from sql("SELECT * FROM child")) == [{"parent_id": 1}]


@testing.effect
def test_does_not_poison_a_connection_already_rolled_back_before_failed_commit_cleanup(
    tmp_path: Path,
):
    """does not poison a connection already rolled back before failed commit cleanup"""
    sql = yield from make_client(tmp_path)
    yield from sql("CREATE TABLE items (id INTEGER PRIMARY KEY)")

    def body():
        yield from sql("INSERT INTO items VALUES (1)")
        insert = yield from sql("INSERT OR ROLLBACK INTO items VALUES (1)").exit()
        assert isinstance(insert, fx.Failure)

    failed_commit = _failure((yield from sql.with_transaction(fx.gen(body)).exit()))
    assert "no transaction is active" in failed_commit.cause.pretty().lower()

    assert (yield from sql("SELECT * FROM items")) == []


@testing.effect
def test_with_transaction_rollback(tmp_path: Path):
    """withTransaction rollback"""
    sql = yield from make_client(tmp_path)
    yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
    yield from sql.with_transaction(
        sql("INSERT INTO test (name) VALUES ('hello')").and_then(fx.fail("boom"))
    ).ignore()
    assert (yield from sql("SELECT * FROM test")) == []


@testing.effect
def test_keeps_a_plain_write_out_of_another_fibers_rolled_back_transaction(tmp_path: Path):
    """keeps a plain write out of another fiber's rolled back transaction"""
    # Sweep the acquisition/execution gap without relying on one scheduler offset.
    for delay in range(31):
        directory = tmp_path / str(delay)
        directory.mkdir()

        def run(directory: Path = directory, delay: int = delay):
            sql = yield from make_client(directory)
            yield from sql("CREATE TABLE race (kind TEXT NOT NULL)")
            plain = yield from (
                sql("INSERT INTO race VALUES ('plain')")
                .pipe(fx.provide_service(MaxOpsBeforeYield, 3))
                .fork()
            )
            for _ in range(delay):
                yield from fx.yield_now()

            def rolled_back():
                yield from sql("INSERT INTO race VALUES ('rolled back')")
                for _ in range(1000):
                    yield from fx.yield_now()
                return (yield from fx.fail("rollback"))

            transaction = yield from sql.with_transaction(fx.gen(rolled_back)).ignore().fork()
            yield from plain.join()
            yield from transaction.join()
            assert (yield from sql("SELECT kind FROM race")) == [{"kind": "plain"}]

        yield from fx.scoped(fx.gen(run))


@testing.effect
def test_uses_a_5_second_busy_timeout(tmp_path: Path):
    """uses a 5 second busy timeout"""
    sql = yield from make_client(tmp_path)
    assert (yield from sql("PRAGMA busy_timeout")) == [{"timeout": 5000}]

    custom = yield from make_memory_client(busy_timeout="1 second")
    assert (yield from custom("PRAGMA busy_timeout")) == [{"timeout": 1000}]

    infinite = yield from make_memory_client(busy_timeout=float("inf"))
    assert (yield from infinite("PRAGMA busy_timeout")) == [{"timeout": 2_147_483_647}]


def _locked_message(error: SqlError) -> str:
    cause = error.reason.cause
    assert isinstance(cause, sqlite3.Error)
    return str(cause)


@testing.effect
def test_starts_transactions_immediately(tmp_path: Path):
    """starts transactions immediately"""
    client = yield from make_client(tmp_path)
    contender = yield from make_client(tmp_path)
    yield from contender("PRAGMA busy_timeout = 1")

    def body():
        error = yield from contender("BEGIN IMMEDIATE").flip()
        assert isinstance(error, SqlError)
        assert "database is locked" in _locked_message(error).lower()

    yield from client.with_transaction(fx.gen(body))


@testing.effect
def test_fails_a_contended_transaction_with_a_typed_error(tmp_path: Path):
    """fails a contended transaction with a typed error"""
    client = yield from make_client(tmp_path)
    contender = yield from make_client(tmp_path)
    yield from contender("PRAGMA busy_timeout = 1")

    ex = yield from client.with_transaction(contender.with_transaction(fx.void).exit())

    failure = _failure(ex)
    # ``BEGIN IMMEDIATE`` cannot take the write lock, so it fails before a
    # transaction exists. The failure has to stay a typed, retryable
    # ``SqlError`` instead of being replaced by a rollback defect.
    assert not failure.cause.has_dies, failure.cause.pretty()
    error = failure.cause.find_error()
    assert isinstance(error, fx.Ok)
    assert isinstance(error.value, SqlError)
    assert "database is locked" in _locked_message(error.value).lower()


@testing.effect
def test_supports_transactions_on_readonly_clients(tmp_path: Path):
    """supports transactions on readonly clients"""

    def create():
        sql = yield from make_client(tmp_path)
        yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY)")

    yield from fx.scoped(fx.gen(create))

    sql = yield from make_client(tmp_path, readonly=True)
    yield from sql("PRAGMA query_only = ON")
    assert (yield from sql.with_transaction(sql("SELECT * FROM test"))) == []


@testing.effect
def test_supports_backup_and_export(tmp_path: Path):
    """supports backup and export"""
    sql = yield from make_client(tmp_path)
    yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY, name TEXT)")
    yield from sql("INSERT INTO test (name) VALUES ('hello')")

    metadata = yield from sql.backup(sql.config.filename + ".backup")
    assert metadata.total_pages > 0
    assert metadata.remaining_pages == 0


def _locked_database(directory: Path) -> fx.Effect[tuple[str, sqlite3.Connection], Any, fx.Scope]:
    filename = str(directory / "test.db")

    def lock() -> sqlite3.Connection:
        db = sqlite3.connect(filename, isolation_level=None, check_same_thread=False)
        db.execute("BEGIN IMMEDIATE")
        return db

    return fx.acquire_release(fx.sync(lock), lambda db, _: fx.sync(db.close)).map(
        lambda db: (filename, db)
    )


def _until_sleeping() -> fx.Effect[None]:
    """Wait (in real time) until a fiber sleeps on the test clock. The Node
    driver opens synchronously, so Effect's ``startImmediately`` reaches the
    retry sleep at once; here opening runs on the worker thread."""

    def body():
        clock = yield from testing.test_clock()
        while clock.pending_sleeps == 0:
            yield from testing.with_live(fx.sleep("1 millis"))

    return fx.gen(body)


@testing.effect
def test_retries_enabling_wal_while_the_database_is_locked(tmp_path: Path):
    """retries enabling WAL while the database is locked"""
    _filename, lock = yield from _locked_database(tmp_path)
    fiber = yield from make_client(tmp_path).fork(start_immediately=True)
    yield from _until_sleeping()
    lock.execute("ROLLBACK")
    yield from testing.adjust("10 millis")
    sql = yield from fiber.join()
    assert (yield from sql("PRAGMA journal_mode")) == [{"journal_mode": "wal"}]


@testing.effect
def test_fails_to_enable_wal_with_a_typed_error_after_busy_timeout(tmp_path: Path):
    """fails to enable WAL with a typed error after busyTimeout"""
    yield from _locked_database(tmp_path)
    fiber = yield from make_client(tmp_path, busy_timeout="1 second").fork(start_immediately=True)
    yield from _until_sleeping()
    yield from testing.adjust("2 seconds")
    error = yield from fiber.join().flip()
    assert isinstance(error, SqlError)
    assert isinstance(error.reason, LockTimeoutError)


@testing.effect
def test_does_not_enable_wal_on_readonly_clients(tmp_path: Path):
    """does not enable WAL on readonly clients"""

    def create():
        sql = yield from make_client(tmp_path, disable_wal=True)
        yield from sql("CREATE TABLE test (id INTEGER PRIMARY KEY)")

    yield from fx.scoped(fx.gen(create))

    sql = yield from make_client(tmp_path, readonly=True)
    assert (yield from sql("PRAGMA journal_mode")) == [{"journal_mode": "delete"}]


@testing.effect
def test_works_when_node_sqlite_does_not_provide_enable_load_extension(tmp_path: Path):
    """works when node:sqlite does not provide enableLoadExtension"""
    sql = yield from make_client(tmp_path)
    assert (yield from sql("SELECT 1 AS value")) == [{"value": 1}]
    error = yield from sql.load_extension(sql.config.filename + ".missing-extension").flip()
    assert isinstance(error, SqlError)


@testing.live
def test_releases_the_connection_when_a_queued_transaction_is_interrupted():
    """releases the connection when a queued transaction is interrupted"""
    # Sweep the interrupt across the gap between taking the connection and
    # registering its release. Statements run on the driver's worker thread,
    # so the next statement is awaited (with a timeout) instead of polled.
    for delay in range(31):

        def attempt(delay: int = delay):
            sql = yield from make_memory_client()
            holder = yield from sql("SELECT 1").fork()
            queued = yield from (
                sql.with_transaction(sql("SELECT 2"))
                .pipe(fx.provide_service(MaxOpsBeforeYield, 3))
                .fork()
            )
            for _ in range(delay):
                yield from fx.yield_now()
            yield from queued.interrupt()
            yield from holder.join()
            leaked = yield from sql("SELECT 3").timeout("5 seconds").exit()
            assert isinstance(leaked, fx.Success), f"connection leaked at delay {delay}"

        yield from fx.scoped(fx.gen(attempt))
