"""The thread a SQL Server connection's blocking calls run on.

Each connection gets one worker thread: its calls run there in the order
sent while the fiber that sent one waits without blocking others.
Interrupting the fiber drops a call that has not started; one that has
gets ``cancel`` (called while it runs, never after) and the fiber waits
for it to end, so the connection is never used by two calls at once. A
call given ``release`` (one that opens something, with nothing else to
protect yet) is left to finish on the thread instead. When a call ends,
its ``Cancellable`` forgets any cancel asked for it, under the same lock,
so a cancel that came after its request ended never reaches the next
call's. A call after ``shutdown`` fails with an ``SqlError`` saying so.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections.abc import Callable
from concurrent.futures import Future, ThreadPoolExecutor
from typing import Literal, Protocol

from pyfect._core import Effect, _FailCause, _Succeed, _Suspend
from pyfect._released import Lifetime, Released
from pyfect.cause import die, fail, interrupt
from pyfect.process._os import Latch
from pyfect.sql.error import SqlError, UnknownError

type _Phase = Literal["queued", "running", "dropped", "abandoned", "done"]


def _outcome[A](
    thunk: Callable[[], A], catch: Callable[[Exception], SqlError]
) -> Effect[A, SqlError]:
    """``thunk()`` as an effect; never raises."""
    try:
        return _Succeed(thunk())
    except Exception as exc:
        try:
            return _FailCause(fail(catch(exc)))
        except BaseException as defect:
            return _FailCause(die(defect))
    except BaseException as defect:
        return _FailCause(die(defect))


class Cancellable(Protocol):
    """What an interrupted call is cancelled through."""

    def cancel(self) -> None:
        """Stop the call's request: in flight, or about to be sent."""
        ...

    def forget_cancel(self) -> None:
        """The call ended: a cancel asked for it no longer applies."""
        ...


class _Call[A]:
    """One call's progress; ``phase`` changes under ``lock``."""

    __slots__ = ("lock", "phase", "settled")

    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.phase: _Phase = "queued"
        self.settled: Latch[Effect[A, SqlError]] = Latch(waits_for="work")

    def end(self) -> bool:
        """The call ended; whether its fiber had stopped waiting for it."""
        abandoned = self.phase == "abandoned"
        self.phase = "done"
        return abandoned


class Worker:
    """One thread running a connection's calls in order."""

    __slots__ = ("_executor", "_lifetime")

    def __init__(self) -> None:
        self._executor = ThreadPoolExecutor(1, thread_name_prefix="pyfect-mssql")
        self._lifetime = Lifetime("SQL Server connection")

    def call[A](
        self,
        thunk: Callable[[], A],
        catch: Callable[[Exception], SqlError],
        cancel: Cancellable | None = None,
        release: Callable[[A], None] | None = None,
    ) -> Effect[A, SqlError]:
        """Run ``thunk`` on the thread; an exception it raises fails with
        ``catch`` of it. Interrupted while it runs, ``cancel`` runs and the
        fiber waits for ``thunk`` to end. With ``release`` the fiber does not
        wait: a value ``thunk`` makes all the same goes to ``release``."""

        def start() -> Effect[A, SqlError]:
            call: _Call[A] = _Call()

            def run() -> None:
                with call.lock:
                    if call.phase == "dropped":
                        call.settled.set(_FailCause(interrupt()))
                        return
                    call.phase = "running"
                outcome = _outcome(thunk, catch)
                with call.lock:
                    abandoned = call.end()
                    if cancel is not None:
                        cancel.forget_cancel()
                call.settled.set(outcome)
                if abandoned:
                    made(outcome)

            def made(outcome: Effect[A, SqlError]) -> None:
                if release is not None and isinstance(outcome, _Succeed):
                    release(outcome.value)

            def released(done: Future[None]) -> None:
                error = done.exception()
                if isinstance(error, Released):
                    reason = UnknownError(cause=error, message=str(error))
                    call.settled.set(_FailCause(fail(SqlError(reason=reason))))

            self._lifetime.submit(lambda: self._executor.submit(run)).add_done_callback(released)

            def interrupted() -> Effect[None]:
                with call.lock:
                    if call.phase == "queued":
                        call.phase = "dropped"
                        return _Succeed(None)
                    if call.phase == "running":
                        if release is not None:
                            call.phase = "abandoned"
                            return _Succeed(None)
                        if cancel is not None:
                            cancel.cancel()

                return call.settled.wait().map(made)

            return (
                call.settled.wait()
                .flat_map(lambda outcome: outcome)
                .on_interrupt(_Suspend(interrupted))
            )

        return _Suspend(start)

    def shutdown(self) -> None:
        """Stop the thread once its queued calls ran."""
        self._lifetime.close()
        self._executor.shutdown(wait=False)


__all__ = ["Cancellable", "Worker"]
