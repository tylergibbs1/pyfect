"""Transactions and the shared SQLite connection, beyond Effect's tests:
concurrent savepoints of one transaction, and ``make_sqlite_acquirers``
without ``is_transaction``."""

from collections.abc import Sequence
from typing import Any, cast

import pyfect as fx
from pyfect import testing
from pyfect.sql import client as sql_client
from pyfect.sql.connection import Connection, Row, TransformRows
from pyfect.sql.error import SqlError, UnknownError


def _harness(calls: list[str]) -> sql_client.WithTransaction:
    conn = cast("Connection", object())

    def record(name: str) -> fx.Effect[None, SqlError]:
        return fx.sync(lambda: calls.append(name))

    def acquire(_restore: Any) -> fx.Effect[Connection, SqlError, fx.Scope]:
        return fx.succeed(conn)

    return sql_client.make_with_transaction(
        sql_client.TransactionOptions(
            transaction_service=sql_client.transaction_connection(),
            span_attributes=(),
            acquire_connection=acquire,
            begin=lambda _conn, _statement: record("begin"),
            savepoint=lambda _conn, depth: record(f"savepoint({depth})"),
            commit=lambda _conn: record("commit"),
            rollback=lambda _conn: record("rollback"),
            rollback_savepoint=lambda _conn, depth: record(f"rollbackSavepoint({depth})"),
            release_savepoint=lambda _conn, depth: record(f"release({depth})"),
        )
    )


@testing.effect
def test_concurrent_savepoints_of_one_transaction_run_one_at_a_time():
    """They share the connection, so each savepoint ends before the next
    begins."""
    calls: list[str] = []
    with_transaction = _harness(calls)

    def nested(name: str) -> fx.Effect[None, SqlError]:
        body = (
            fx.sync(lambda: calls.append(f"{name} start"))
            .and_then(fx.yield_now())
            .and_then(fx.sync(lambda: calls.append(f"{name} end")))
        )
        return with_transaction(body)

    yield from with_transaction(fx.all(nested("a"), nested("b"), concurrency="unbounded"))

    assert calls == [
        "begin",
        "savepoint(1)",
        "a start",
        "a end",
        "release(1)",
        "savepoint(1)",
        "b start",
        "b end",
        "release(1)",
        "commit",
    ]


# --- make_sqlite_acquirers without is_transaction ---------------------------------


class _Conn:
    """Answers ``ROLLBACK`` with the next scripted outcome."""

    def __init__(self, rollbacks: list[SqlError | None]) -> None:
        self.rollbacks = rollbacks
        self.calls: list[str] = []

    def execute_unprepared(
        self, sql: str, params: Sequence[object], transform_rows: TransformRows | None, /
    ) -> fx.Effect[Sequence[Row], SqlError]:
        def run() -> fx.Effect[Sequence[Row], SqlError]:
            self.calls.append(sql)
            outcome = self.rollbacks.pop(0) if self.rollbacks else None
            return fx.succeed([]) if outcome is None else fx.fail(outcome)

        return fx.suspend(run)


def _error(message: str) -> SqlError:
    return SqlError(reason=UnknownError(cause=Exception(message), message=message))


def _acquirers(conn: _Conn, semaphore: fx.Semaphore | None = None) -> sql_client.SqliteAcquirers:
    return sql_client.make_sqlite_acquirers(
        connection=fx.succeed(cast("Connection", conn)),
        semaphore=semaphore or fx.Semaphore(1),
    )


def _use(acquirers: sql_client.SqliteAcquirers) -> fx.Effect[None, SqlError]:
    return fx.scoped(acquirers.acquirer).as_void()


@testing.effect
def test_a_rollback_with_no_transaction_active_counts_as_clean():
    conn = _Conn([_error("cannot rollback - no transaction is active")])
    acquirers = _acquirers(conn)
    yield from acquirers.on_commit_failure(cast("Connection", conn))
    yield from _use(acquirers)

    assert conn.calls == ["ROLLBACK"]


@testing.effect
def test_a_poisoned_connection_is_clean_again_once_a_rollback_succeeds():
    """The failed cleanup is retried on the next acquisition only; once it
    succeeds, later acquisitions don't roll back again."""
    conn = _Conn([_error("disk I/O error"), _error("disk I/O error"), None])
    acquirers = _acquirers(conn)

    cleanup = yield from acquirers.on_commit_failure(cast("Connection", conn)).flip()
    assert isinstance(cleanup, SqlError)
    rejected = yield from _use(acquirers).flip()
    assert isinstance(rejected, SqlError)
    yield from _use(acquirers)
    yield from _use(acquirers)

    assert conn.calls == ["ROLLBACK", "ROLLBACK", "ROLLBACK"]


@testing.effect
def test_waiting_for_the_connection_can_be_interrupted():
    semaphore = fx.Semaphore(1)
    acquirers = _acquirers(_Conn([]), semaphore)
    yield from semaphore.take(1)

    waiting = yield from _use(acquirers).fork()
    yield from fx.yield_now()
    yield from waiting.interrupt()
    # Were the wait uninterruptible, the lease would now succeed.
    yield from semaphore.release(1)
    ex = yield from waiting.await_exit()

    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_interrupts_only
