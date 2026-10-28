"""The SQLite worker thread and error classification of driver errors."""

import sqlite3
import threading

import pyfect as fx
from pyfect import testing
from pyfect.sql.error import SqlError, UnknownError, classify_sqlite_error
from pyfect.sql.sqlite._worker import Worker


def test_classifies_a_sqlite_error_raised_outside_a_statement():
    """``sqlite3`` raises some errors (``load_extension``) without codes."""
    reason = classify_sqlite_error(sqlite3.OperationalError("no such file"))
    assert isinstance(reason, UnknownError)


@testing.effect
def test_runs_calls_on_one_thread_other_than_the_fibers():
    worker = Worker()
    fiber_thread = threading.get_ident()
    threads = yield from fx.all(
        worker.call(threading.get_ident, _unknown),
        worker.call(threading.get_ident, _unknown),
    )
    worker.shutdown()
    assert threads[0] == threads[1] != fiber_thread


@testing.effect
def test_a_raising_catch_dies_instead_of_leaving_the_fiber_waiting():
    worker = Worker()

    def boom() -> None:
        raise ValueError("driver")

    def bad_catch(_exc: Exception) -> SqlError:
        raise RuntimeError("catch failed")

    ex = yield from worker.call(boom, bad_catch).exit()
    worker.shutdown()
    assert isinstance(ex, fx.Failure)
    assert ex.cause.has_dies
    assert "catch failed" in ex.cause.pretty()


def _unknown(exc: Exception) -> SqlError:
    return SqlError(reason=UnknownError(cause=exc))
