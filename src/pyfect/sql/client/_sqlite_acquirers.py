"""Sharing one SQLite connection between fibers (Effect's
``SqlClient.makeSqliteAcquirers``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pyfect._core import Effect, _FailCause, _MatchCause, _Succeed, _Sync, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._primitives import uninterruptible_mask
from pyfect.cause import Cause
from pyfect.cause import fail as fail_cause
from pyfect.scope import CloseableScope, Scope
from pyfect.semaphore import Semaphore
from pyfect.sql.connection import Acquirer, Borrower, Connection
from pyfect.sql.error import ConnectionError, SqlError

_NO_TRANSACTION = re.compile(r"no transaction is active", re.IGNORECASE)


def _is_no_transaction_error(error: SqlError) -> bool:
    cause = error.reason.cause
    message = cause if isinstance(cause, str) else getattr(cause, "message", None)
    if not isinstance(message, str):
        message = str(cause) if isinstance(cause, BaseException) else ""
    return _NO_TRANSACTION.search(message) is not None


@dataclass(frozen=True, slots=True)
class SqliteAcquirers:
    """What ``SqlClient.make`` needs to share one connection: leases and a
    borrower that hold the semaphore, and the cleanup of a failed
    ``COMMIT``."""

    acquirer: Acquirer
    borrower: Borrower
    transaction_acquirer: Acquirer
    on_commit_failure: Callable[[Connection], Effect[None, SqlError]]
    is_transaction: Callable[[Connection], bool] | None


def make_sqlite_acquirers[C: Connection](
    *,
    connection: Effect[C, SqlError],
    semaphore: Semaphore,
    is_transaction: Callable[[C], bool] | None = None,
) -> SqliteAcquirers:
    """Leases of ``connection`` that hold ``semaphore`` until their scope
    closes, and a borrower that holds it for one statement.

    SQLite can keep a transaction open after ``COMMIT`` fails (a deferred
    foreign key violation), so ``on_commit_failure`` rolls it back. If that
    fails too, the connection is rejected until a ``ROLLBACK`` retried on
    each later acquisition succeeds. Without ``is_transaction``,
    ``ROLLBACK`` always runs and "no transaction is active" counts as
    clean."""
    require_effect(connection, "connection")
    poisoned: list[SqlError] = []

    def poison(cause: Cause[SqlError]) -> SqlError:
        error = SqlError(
            reason=ConnectionError(
                message="SQLite connection cannot be reused after failed COMMIT cleanup",
                operation="rollback",
                cause=cause,
            )
        )
        poisoned[:] = [error]
        return error

    def rollback(conn: C) -> Effect[None, SqlError]:
        if is_transaction is not None:
            if is_transaction(conn):
                return conn.execute_unprepared("ROLLBACK", [], None).as_void()
            return _Succeed(None)
        return (
            conn.execute_unprepared("ROLLBACK", [], None)
            .as_void()
            .catch_if(_is_no_transaction_error, lambda _: _Succeed(None))
        )

    def check(conn: C) -> Effect[C, SqlError]:
        if not poisoned:
            return _Succeed(conn)

        def recovered(_: object) -> Effect[C]:
            poisoned.clear()
            return _Succeed(conn)

        return _MatchCause(rollback(conn), lambda c: _FailCause(fail_cause(poison(c))), recovered)

    available = connection.flat_map(check)

    def lease_body(fiber: Any) -> Effect[C, SqlError, Scope]:
        scope: CloseableScope = fiber._context.get_unsafe(Scope)
        return uninterruptible_mask(
            lambda restore: (
                restore(semaphore.take(1))
                .and_then(scope.add_finalizer(lambda _: semaphore.release(1)))
                .and_then(available)
            )
        )

    lease: Effect[C, SqlError, Scope] = _WithFiber(lease_body)

    def borrow[A, E, R](f: Callable[[Connection], Effect[A, E, R]]) -> Effect[A, E | SqlError, R]:
        return semaphore.with_permits(available.flat_map(f))

    def on_commit_failure(conn: Connection) -> Effect[None, SqlError]:
        conn_c: Any = conn
        return rollback(conn_c).tap_cause(lambda cause: _Sync(lambda: poison(cause)))

    def is_open(conn: Connection) -> bool:
        conn_c: Any = conn
        return is_transaction is not None and is_transaction(conn_c)

    return SqliteAcquirers(
        acquirer=lease,
        borrower=borrow,
        transaction_acquirer=lease,
        on_commit_failure=on_commit_failure,
        is_transaction=None if is_transaction is None else is_open,
    )


__all__ = ["SqliteAcquirers", "make_sqlite_acquirers"]
