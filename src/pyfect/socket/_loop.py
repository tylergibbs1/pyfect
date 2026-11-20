"""The asyncio loop the live sockets run on: one per process, on a daemon
thread of its own, started on first use. Fibers never run on it: they ask
it to act (``call_soon``, ``run``) and wait through ``os_wait``, which keeps
a synchronous run (and its stall detection) aware of the outside work."""

from __future__ import annotations

import asyncio
import threading
from collections.abc import Callable, Coroutine
from concurrent.futures import Future
from typing import Any

from pyfect._core import Effect
from pyfect._loop_thread import LoopThread
from pyfect._os_wait import Resume, os_wait
from pyfect.effect import fail, succeed, suspend, sync


class _Shared:
    lock = threading.Lock()
    loop: asyncio.AbstractEventLoop | None = None


def _quiet(loop: asyncio.AbstractEventLoop, context: dict[str, Any]) -> None:
    """Connection errors are reported to the socket that saw them; the
    loop's own report of them (a failed TLS handshake, a reset during
    close) would only be noise."""
    if not isinstance(context.get("exception"), OSError):
        loop.default_exception_handler(context)


def get_loop() -> asyncio.AbstractEventLoop:
    with _Shared.lock:
        if _Shared.loop is None:
            _Shared.loop = LoopThread("pyfect-net", exception_handler=_quiet).loop
        return _Shared.loop


def call_soon(f: Callable[[], object]) -> None:
    """Run ``f`` on the loop thread."""
    get_loop().call_soon_threadsafe(f)


def run[A](make: Callable[[], Coroutine[Any, Any, A]]) -> Effect[A, BaseException]:
    """Run the coroutine ``make()`` on the loop and wait for its result.
    Interrupting cancels it and waits until it has ended, so whatever it
    was doing to a socket is over before the fiber goes on (its scope's
    finalizers close what it opened)."""

    def start() -> Effect[A, BaseException]:
        loop = get_loop()
        ended: Future[A] = Future()
        tasks: list[asyncio.Task[A]] = []

        def end(task: asyncio.Task[A]) -> None:
            if task.cancelled():
                ended.set_exception(asyncio.CancelledError())
            elif (error := task.exception()) is not None:
                ended.set_exception(error)
            else:
                ended.set_result(task.result())

        def begin() -> None:
            task = loop.create_task(make())
            task.add_done_callback(end)
            tasks.append(task)

        def cancel() -> None:
            # Calls run in order, so ``begin`` has run by now.
            tasks[0].cancel()

        def stop() -> None:
            loop.call_soon_threadsafe(cancel)

        loop.call_soon_threadsafe(begin)
        return _wait(ended).on_interrupt(sync(stop).and_then(_wait(ended).ignore()))

    return suspend(start)


def _wait[A](future: Future[A]) -> Effect[A, BaseException]:
    """``future``'s outcome, once the loop sets it."""

    def register(resume: Resume[A, BaseException]) -> None:
        def done(finished: Future[A]) -> None:
            error = finished.exception()
            resume(succeed(finished.result()) if error is None else fail(error))

        future.add_done_callback(done)

    return os_wait(register, waits_for="work")
