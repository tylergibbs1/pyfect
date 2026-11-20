"""The asyncio loop the asyncio database drivers (psycopg, asyncmy, libsql)
run on: one per process, on a daemon thread of its own, started on first use
(``pyfect._loop_bridge``).

``call`` runs a coroutine there for a fiber. Interrupting the fiber asks the
coroutine to stop (``stop``) and then waits for it to finish, so whatever it
was doing to a connection is over before the fiber goes on; a value the
coroutine made all the same (a session that finished connecting) goes to
``release`` instead of being lost.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from collections.abc import Callable
from typing import Never

from pyfect._core import Effect, _FailCause
from pyfect._loop_bridge import LoopBridge, Make, Release, Stop, cancel_task, stop_with
from pyfect._os_wait import WaitsFor
from pyfect.cause import die, fail
from pyfect.sql.error import SqlError

_SQL = LoopBridge("pyfect-sql")


def get_loop() -> asyncio.AbstractEventLoop:
    return _SQL.loop


def _failed(
    catch: Callable[[BaseException], SqlError],
) -> Callable[[BaseException], Effect[Never, SqlError]]:
    """An error as a failure: a defect unless it is an ``Exception``."""

    def failed(error: BaseException) -> Effect[Never, SqlError]:
        if not isinstance(error, Exception):
            return _FailCause(die(error))
        return _FailCause(fail(catch(error)))

    return failed


def call[A](
    make: Make[A],
    catch: Callable[[BaseException], SqlError],
    stop: Stop = cancel_task,
    release: Release[A] | None = None,
    *,
    waits_for: WaitsFor,
) -> Effect[A, SqlError]:
    """Run ``make()`` on the loop; an exception it raises fails with
    ``catch`` of it. Interrupting runs ``stop`` on the task and waits; a
    value ``make()`` produced all the same goes to ``release``.
    ``waits_for`` says whether ``make()`` is work (a statement) or waits
    for an event (a notification), as ``pyfect._os_wait`` explains."""
    return _SQL.run(
        make, _failed(catch), waits_for=waits_for, release=release, on_interrupt=stop_with(stop)
    )


def submit(make: Make[object]) -> None:
    """Start ``make()`` on the loop without waiting for it."""
    _SQL.start(make)


__all__ = ["Stop", "call", "cancel_task", "get_loop", "submit"]
