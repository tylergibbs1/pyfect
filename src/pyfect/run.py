"""Running effects.

- ``run_sync``: on the calling thread, with pyfect's own scheduler. Sleeps,
  forks, races and ``blocking`` all work; ``from_async`` does not (there is
  no asyncio loop).
- ``run_async``: inside a running asyncio loop. Cancelling the awaiting
  task interrupts the fiber and waits for its finalizers.
- ``run_main``: for a script's main program, like Effect's ``runMain``.
  Runs on a fresh asyncio loop; SIGINT and SIGTERM interrupt the fiber so
  finalizers run. Ends the process with status 130 when interrupted, or the
  error's ``exit_code`` (``TaggedError.exit_code``, default 1) on failure.

Each has an ``_exit`` variant that returns the ``Exit`` instead of raising,
and accepts effects that can fail. The plain variants only accept effects
whose errors are handled (``E = Never``) and whose services are provided
(``R = Never``); anything else is a type error at the call.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import signal
import sys
import threading
from collections.abc import Generator
from contextlib import contextmanager
from typing import Any, Never

from pyfect._core import Effect
from pyfect._fiber import Fiber, root_fiber
from pyfect.context import Context
from pyfect.errors import TaggedError
from pyfect.exit import Exit, Success
from pyfect.scheduler import AsyncioScheduler, SyncScheduler


def run_sync_exit[A, E](eff: Effect[A, E, Never]) -> Exit[A, E]:
    scheduler = SyncScheduler()
    fiber: Fiber[A, E] = root_fiber(scheduler, Context.empty())
    fiber._start(eff)
    try:
        scheduler.run_until(lambda: fiber._exit is not None)
    except KeyboardInterrupt:
        # Let finalizers run, then re-raise. A second Ctrl-C aborts.
        fiber.unsafe_interrupt_as(None)
        scheduler.run_until(lambda: fiber._exit is not None)
        raise
    ex = fiber._exit
    assert ex is not None
    return ex


def run_sync[A](eff: Effect[A, Never, Never]) -> A:
    return _unwrap(run_sync_exit(eff))


async def run_async_exit[A, E](eff: Effect[A, E, Never]) -> Exit[A, E]:
    fiber, done = _start_async(eff)
    return await _await_fiber(fiber, done)


async def run_async[A](eff: Effect[A, Never, Never]) -> A:
    return _unwrap(await run_async_exit(eff))


def run_main[A](eff: Effect[A, Never, Never]) -> A:
    """Run as the program's main fiber; see the module docstring."""
    ex = asyncio.run(_run_main_exit(eff))
    if isinstance(ex, Success):
        return ex.value
    if ex.cause.has_interrupts_only:
        raise SystemExit(130)
    error = ex.cause.squash()
    code = error.exit_code if isinstance(error, TaggedError) else 1
    if code == 1:
        # Python prints the traceback and exits 1 for an uncaught exception.
        return _unwrap(ex)
    print(ex.cause.pretty(), file=sys.stderr)
    raise SystemExit(code)


async def _run_main_exit[A](eff: Effect[A, Never, Never]) -> Exit[A, Never]:
    fiber, done = _start_async(eff)
    with _interrupt_on_signals(fiber):
        return await _await_fiber(fiber, done)


@contextmanager
def _interrupt_on_signals(fiber: Fiber[Any, Any]) -> Generator[None]:
    """While open, SIGINT and SIGTERM interrupt ``fiber`` (from the loop, not
    inside the signal handler). Python only delivers signals to the main
    thread, so elsewhere this does nothing."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    loop = asyncio.get_running_loop()

    def on_signal(_signum: int, _frame: object) -> None:
        loop.call_soon_threadsafe(fiber.unsafe_interrupt_as, None)

    previous = {sig: signal.signal(sig, on_signal) for sig in (signal.SIGINT, signal.SIGTERM)}
    try:
        yield
    finally:
        for sig, handler in previous.items():
            signal.signal(sig, handler)


def _start_async[A, E](eff: Effect[A, E, Never]) -> tuple[Fiber[A, E], asyncio.Future[Exit[A, E]]]:
    loop = asyncio.get_running_loop()
    fiber: Fiber[A, E] = root_fiber(AsyncioScheduler(loop), Context.empty())
    done: asyncio.Future[Exit[A, E]] = loop.create_future()
    fiber.unsafe_add_observer(done.set_result)
    fiber._start(eff)
    return fiber, done


async def _await_fiber[A, E](fiber: Fiber[A, E], done: asyncio.Future[Exit[A, E]]) -> Exit[A, E]:
    """Cancelling the awaiting task interrupts the fiber and waits for it."""
    try:
        return await asyncio.shield(done)
    except asyncio.CancelledError:
        fiber.unsafe_interrupt_as(None)
        await done
        raise


def _unwrap[A](ex: Exit[A, Any]) -> A:
    if isinstance(ex, Success):
        return ex.value
    error = ex.cause.squash()
    if len(ex.cause.reasons) > 1:
        error.add_note("Full cause:\n" + ex.cause.pretty())
    raise error
