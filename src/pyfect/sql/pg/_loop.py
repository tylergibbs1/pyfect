"""The asyncio loop psycopg runs on: one per process, on a daemon thread of
its own, started on first use.

Fibers never run on it. ``call`` starts a coroutine there and waits for its
outcome through ``Latch.wait`` (an ``os_wait``), so no fiber blocks and a
synchronous run knows the wait is outside work. Interrupting the fiber asks
the coroutine to stop (``stop``) and then waits for it to finish, so
whatever it was doing to a connection is over before the fiber goes on; a
value the coroutine made all the same (a session that finished connecting)
goes to ``release`` instead of being lost.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import contextlib
import threading
from collections.abc import Callable, Coroutine
from typing import Any, Never

from pyfect import _background as background
from pyfect._core import Effect, _FailCause, _Succeed, _Suspend
from pyfect._loop_thread import LoopThread
from pyfect._os_wait import WaitsFor
from pyfect.cause import die, fail
from pyfect.effect import sync
from pyfect.process._os import Latch
from pyfect.sql.error import SqlError


class _Shared:
    lock = threading.Lock()
    loop: asyncio.AbstractEventLoop | None = None


def get_loop() -> asyncio.AbstractEventLoop:
    with _Shared.lock:
        if _Shared.loop is None:
            _Shared.loop = LoopThread("pyfect-pg").loop
        return _Shared.loop


type Stop = Callable[[asyncio.Task[Any]], Coroutine[Any, Any, None]]
"""Ends a running task early; it runs on the loop and returns once the
task has finished."""


async def cancel_task(task: asyncio.Task[Any]) -> None:
    task.cancel()
    await asyncio.wait([task])


def _failed(
    catch: Callable[[BaseException], SqlError], error: BaseException
) -> Effect[Never, SqlError]:
    """``error`` as a failure (a defect unless it is an ``Exception``);
    never raises, so the loop always settles."""
    if not isinstance(error, Exception):
        return _FailCause(die(error))
    try:
        return _FailCause(fail(catch(error)))
    except BaseException as defect:
        return _FailCause(die(defect))


def call[A](
    make: Callable[[], Coroutine[Any, Any, A]],
    catch: Callable[[BaseException], SqlError],
    stop: Stop = cancel_task,
    release: Callable[[A], Coroutine[Any, Any, None]] | None = None,
    *,
    waits_for: WaitsFor,
) -> Effect[A, SqlError]:
    """Run ``make()`` on the loop; an exception it raises fails with
    ``catch`` of it. Interrupting runs ``stop`` on the task and waits; a
    value ``make()`` produced all the same goes to ``release``.
    ``waits_for`` says whether ``make()`` is work (a statement) or waits
    for an event (a notification), as ``pyfect._os_wait`` explains."""

    def start() -> Effect[A, SqlError]:
        loop = get_loop()
        settled: Latch[Effect[A, SqlError]] = Latch(waits_for=waits_for)
        tasks: list[asyncio.Task[None]] = []

        async def run() -> None:
            try:
                value = await make()
            except asyncio.CancelledError:
                settled.set(_FailCause(die(asyncio.CancelledError())))
                raise
            except BaseException as exc:
                settled.set(_failed(catch, exc))
            else:
                settled.set(_Succeed(value))

        def begin() -> None:
            task = loop.create_task(run())
            # A task cancelled before its first step never enters ``run``.
            task.add_done_callback(lambda _: settled.set(_FailCause(die(asyncio.CancelledError()))))
            tasks.append(task)

        stopped: Latch[None] = Latch(waits_for="work")

        async def stopping() -> None:
            try:
                await stop(tasks[0])
                outcome = settled.get()
                if release is not None and outcome is not None:
                    made = outcome[0]
                    if isinstance(made, _Succeed):
                        with contextlib.suppress(Exception):
                            await release(made.value)
            finally:
                stopped.set(None)

        def interrupted() -> None:
            # Calls run in order, so ``begin`` has run by now.
            loop.call_soon_threadsafe(lambda: background.start(stopping(), loop))

        loop.call_soon_threadsafe(begin)
        result = settled.wait().flat_map(lambda effect: effect)
        return result.on_interrupt(sync(interrupted).and_then(stopped.wait()))

    return _Suspend(start)


def submit[A](make: Callable[[], Coroutine[Any, Any, A]]) -> None:
    """Start ``make()`` on the loop without waiting for it."""
    loop = get_loop()
    loop.call_soon_threadsafe(lambda: background.start(make(), loop))


__all__ = ["Stop", "call", "cancel_task", "get_loop", "submit"]
