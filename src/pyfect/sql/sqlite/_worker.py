"""The thread a SQLite connection lives on.

``sqlite3`` calls block, so each connection gets one worker thread: every
call on it runs there, in the order sent, while the fiber that sent it
waits without blocking others. Interrupting the fiber abandons the call;
the next call still runs after it. A call after the connection closed
fails with an ``SqlError`` saying so.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor

from pyfect._core import Effect, _FailCause, _Succeed
from pyfect._os_wait import os_wait
from pyfect._released import Lifetime, Released
from pyfect.cause import die, fail
from pyfect.sql.error import SqlError, UnknownError


class Worker:
    """One thread running a connection's calls in order."""

    __slots__ = ("_executor", "_lifetime")

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(1, thread_name_prefix="pyfect-sqlite")
        self._lifetime = Lifetime("SQLite connection")

    def call[A](
        self, thunk: Callable[[], A], catch: Callable[[Exception], SqlError]
    ) -> Effect[A, SqlError]:
        """Run ``thunk`` on the thread; an exception it raises fails with
        ``catch`` of it."""

        def outcome() -> Effect[A, SqlError]:
            # Runs on the worker thread and never raises, so the callback
            # below always resumes the fiber.
            try:
                return _Succeed(thunk())
            except Exception as exc:
                try:
                    return _FailCause(fail(catch(exc)))
                except BaseException as defect:
                    return _FailCause(die(defect))
            except BaseException as defect:
                return _FailCause(die(defect))

        def settle(done: Future[Effect[A, SqlError]]) -> Effect[A, SqlError]:
            error = done.exception()
            if isinstance(error, Released):
                return _FailCause(
                    fail(SqlError(reason=UnknownError(cause=error, message=str(error))))
                )
            return done.result()

        def register(resume: Callable[[Effect[A, SqlError]], None]) -> None:
            submitted = self._lifetime.submit(lambda: self._executor.submit(outcome))
            submitted.add_done_callback(lambda done: resume(settle(done)))

        return os_wait(register, waits_for="work")

    def shutdown(self) -> None:
        """Stop the thread once its queued calls ran."""
        self._lifetime.close()
        self._executor.shutdown(wait=False)


__all__ = ["Worker"]
