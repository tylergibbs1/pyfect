"""Running effects.

- ``run_sync``: on the calling thread, with pyfect's own scheduler. Sleeps,
  forks, races and ``blocking`` all work; ``from_async`` does not (there is
  no asyncio loop).
- ``run_async``: inside a running asyncio loop. Cancelling the awaiting
  task interrupts the fiber and waits for its finalizers.
- ``run_fork``: start the effect and get its ``Fiber`` back at once, on the
  current fiber's run or the running asyncio loop. ``run_callback`` is the
  same with an exit callback, returning a function that interrupts it.
- ``run_main``: for a script's main program, like Effect's ``runMain``.
  Runs on a fresh asyncio loop; SIGINT and SIGTERM interrupt the fiber so
  finalizers run. It accepts effects that can fail, as Effect's does: the
  failure is reported, and ``teardown`` turns the exit into the process status;
  ``default_teardown`` gives 0 on success, 130 when interrupted, or the
  error's ``exit_code`` (``TaggedError.exit_code``, default 1).

Each of ``run_sync`` and ``run_async`` has an ``_exit`` variant that
returns the ``Exit`` instead of raising, and accepts effects that can fail.
The plain variants only accept effects whose errors are handled
(``E = Never``). Every run function except ``run_main`` takes a
``context`` with the services the effect needs (Effect's ``run*With``);
without one, ``R`` must be ``Never``. Anything else is a type error at the
call.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
import signal
import sys
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, Never, Protocol, overload

from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect._root import ambient_run, new_root, start_root
from pyfect.context import Context
from pyfect.errors import TaggedError
from pyfect.exit import Exit, Success
from pyfect.scheduler import AsyncioScheduler, Scheduler, SyncScheduler

_EMPTY: Context[Never] = Context.empty()

type Teardown = Callable[[Exit[Any, Any]], int]
"""Turns ``run_main``'s exit into the process status."""


@overload
def run_sync_exit[A, E](eff: Effect[A, E, Never]) -> Exit[A, E]: ...
@overload
def run_sync_exit[A, E, R](eff: Effect[A, E, R], *, context: Context[R]) -> Exit[A, E]: ...
def run_sync_exit(eff: Effect[Any, Any, Any], *, context: Context = _EMPTY) -> Exit[Any, Any]:
    scheduler = SyncScheduler()
    fiber: Fiber[Any, Any] = new_root(scheduler, context)
    fiber._start(eff)
    return drive(scheduler, fiber)


@overload
def run_sync[A](eff: Effect[A, Never, Never]) -> A: ...
@overload
def run_sync[A, R](eff: Effect[A, Never, R], *, context: Context[R]) -> A: ...
def run_sync(eff: Effect[Any, Never, Any], *, context: Context = _EMPTY) -> Any:
    return unwrap(run_sync_exit(eff, context=context))


def drive[A, E](scheduler: SyncScheduler, fiber: Fiber[A, E]) -> Exit[A, E]:
    """Run ``scheduler`` on this thread until ``fiber`` is done. On Ctrl-C
    the fiber is interrupted and its finalizers run before the
    ``KeyboardInterrupt`` propagates; a second Ctrl-C aborts."""
    try:
        scheduler.run_until(lambda: fiber._exit is not None)
    except KeyboardInterrupt:
        fiber.unsafe_interrupt_as(None)
        scheduler.run_until(lambda: fiber._exit is not None)
        raise
    ex = fiber._exit
    assert ex is not None
    return ex


@overload
async def run_async_exit[A, E](eff: Effect[A, E, Never]) -> Exit[A, E]: ...
@overload
async def run_async_exit[A, E, R](eff: Effect[A, E, R], *, context: Context[R]) -> Exit[A, E]: ...
async def run_async_exit(
    eff: Effect[Any, Any, Any], *, context: Context = _EMPTY
) -> Exit[Any, Any]:
    fiber: Fiber[Any, Any] = new_root(AsyncioScheduler.current(), context)
    fiber._start(eff)
    return await await_fiber(fiber)


@overload
async def run_async[A](eff: Effect[A, Never, Never]) -> A: ...
@overload
async def run_async[A, R](eff: Effect[A, Never, R], *, context: Context[R]) -> A: ...
async def run_async(eff: Effect[Any, Never, Any], *, context: Context = _EMPTY) -> Any:
    return unwrap(await run_async_exit(eff, context=context))


@overload
def run_fork[A, E](
    eff: Effect[A, E, Never], *, scheduler: Scheduler | None = None, uninterruptible: bool = False
) -> Fiber[A, E]: ...
@overload
def run_fork[A, E, R](
    eff: Effect[A, E, R],
    *,
    context: Context[R],
    scheduler: Scheduler | None = None,
    uninterruptible: bool = False,
) -> Fiber[A, E]: ...
def run_fork(
    eff: Effect[Any, Any, Any],
    *,
    context: Context = _EMPTY,
    scheduler: Scheduler | None = None,
    uninterruptible: bool = False,
) -> Fiber[Any, Any]:
    """Start ``eff`` on a fiber with no parent and return the fiber.

    Called from a fiber, the new fiber joins that fiber's run and runs at
    once, up to its first wait. Otherwise it runs on the running asyncio
    loop, again at once. With neither, ``scheduler``
    runs it (driving it is up to the caller); without one this raises
    ``NoRunError``. Inside a run, ``scheduler`` is the fiber's
    ``CurrentScheduler``."""
    run, now = ambient_run(scheduler)
    fiber: Fiber[Any, Any] = new_root(
        run,
        context,
        scheduler=None if scheduler is run else scheduler,
        uninterruptible=uninterruptible,
    )
    start_root(fiber, eff, now=now)
    return fiber


class Interruptor(Protocol):
    """Interrupts a fiber started by ``run_callback``, attributed to the
    fiber with id ``by``. Does not wait."""

    def __call__(self, by: int | None = None, /) -> None: ...


@overload
def run_callback[A, E](
    eff: Effect[A, E, Never],
    *,
    on_exit: Callable[[Exit[A, E]], None] | None = None,
    scheduler: Scheduler | None = None,
    uninterruptible: bool = False,
) -> Interruptor: ...
@overload
def run_callback[A, E, R](
    eff: Effect[A, E, R],
    *,
    context: Context[R],
    on_exit: Callable[[Exit[A, E]], None] | None = None,
    scheduler: Scheduler | None = None,
    uninterruptible: bool = False,
) -> Interruptor: ...
def run_callback(
    eff: Effect[Any, Any, Any],
    *,
    context: Context = _EMPTY,
    on_exit: Callable[[Exit[Any, Any]], None] | None = None,
    scheduler: Scheduler | None = None,
    uninterruptible: bool = False,
) -> Interruptor:
    """``run_fork``, calling ``on_exit`` with the exit when the fiber is
    done. Returns a function that interrupts the fiber."""
    fiber = run_fork(eff, context=context, scheduler=scheduler, uninterruptible=uninterruptible)
    if on_exit is not None:
        fiber.unsafe_add_observer(on_exit)

    def interrupt(by: int | None = None, /) -> None:
        fiber.unsafe_interrupt_as(by)

    return interrupt


def default_teardown(ex: Exit[Any, Any]) -> int:
    """Effect's ``defaultTeardown``: 0 on success, 130 when only
    interrupted, otherwise the squashed error's ``exit_code`` (1 unless a
    ``TaggedError`` sets it)."""
    if isinstance(ex, Success):
        return 0
    if ex.cause.has_interrupts_only:
        return 130
    error = ex.cause.squash()
    return error.exit_code if isinstance(error, TaggedError) else 1


def run_main[A, E](
    eff: Effect[A, E, Never],
    *,
    teardown: Teardown = default_teardown,
    disable_error_reporting: bool = False,
) -> A:
    """Run as the program's main fiber; see the module docstring.

    Returns the value when the program succeeds and ``teardown`` gives 0;
    otherwise ends the process with ``teardown``'s status. A failure that
    is not only an interrupt is reported first, unless
    ``disable_error_reporting``: with status 1 by raising the error (Python
    prints its traceback), with any other status by printing the cause."""
    ex = asyncio.run(_run_main_exit(eff))
    code = teardown(ex)
    if isinstance(ex, Success):
        if code == 0:
            return ex.value
        raise SystemExit(code)
    if ex.cause.has_interrupts_only or disable_error_reporting:
        raise SystemExit(code)
    if code == 1:
        return unwrap(ex)
    print(ex.cause.pretty(), file=sys.stderr)
    raise SystemExit(code)


async def _run_main_exit[A, E](eff: Effect[A, E, Never]) -> Exit[A, E]:
    fiber: Fiber[A, E] = new_root(AsyncioScheduler.current(), Context.empty())
    fiber._start(eff)
    with _interrupt_on_signals(fiber):
        return await await_fiber(fiber)


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


async def await_fiber[A, E](fiber: Fiber[A, E]) -> Exit[A, E]:
    """Wait on the running loop for ``fiber``, whose run is the loop's.
    Cancelling the awaiting task interrupts the fiber and waits for it."""
    done: asyncio.Future[Exit[A, E]] = asyncio.get_running_loop().create_future()
    fiber.unsafe_add_observer(done.set_result)
    try:
        return await asyncio.shield(done)
    except asyncio.CancelledError:
        fiber.unsafe_interrupt_as(None)
        await done
        raise


def unwrap[A](ex: Exit[A, Any]) -> A:
    """The value, or raise the squashed error (with the full cause as a
    note when there is more than one reason)."""
    if isinstance(ex, Success):
        return ex.value
    error = ex.cause.squash()
    if len(ex.cause.reasons) > 1:
        error.add_note("Full cause:\n" + ex.cause.pretty())
    raise error
