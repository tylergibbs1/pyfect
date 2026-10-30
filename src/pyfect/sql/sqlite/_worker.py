"""The thread a SQLite connection lives on.

``sqlite3`` calls block, so each connection gets one worker thread: every
call on it runs there, in the order sent, while the fiber that sent it
waits without blocking others. Interrupting the fiber abandons the call;
the next call still runs after it.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor

from pyfect._core import Effect, _FailCause, _Succeed
from pyfect._os_wait import os_wait
from pyfect.cause import die, fail
from pyfect.sql.error import SqlError


class Worker:
    """One thread running a connection's calls in order."""

    __slots__ = ("_executor",)

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(1, thread_name_prefix="pyfect-sqlite")

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

        def register(resume: Callable[[Effect[A, SqlError]], None]) -> None:
            self._executor.submit(outcome).add_done_callback(lambda f: resume(f.result()))

        return os_wait(register)

    def shutdown(self) -> None:
        """Stop the thread once its queued calls ran."""
        self._executor.shutdown(wait=False)


__all__ = ["Worker"]
