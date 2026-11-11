"""Running effects.

- ``run_sync``: as Effect's ``runSync``. Runs what can finish without
  waiting, yields included; an effect that waits (a sleep, ``blocking``, a
  ``Deferred`` nobody completes, ``from_async``) dies with
  ``AsyncFiberError``, leaving its fiber where it stopped.
- ``run_blocking``: blocks the calling thread until the effect is done, on
  pyfect's own scheduler (JavaScript has no way to do this). Sleeps, forks,
  races and ``blocking`` all work; ``from_async`` does not (there is no
  asyncio loop; called from a coroutine, ``run_blocking`` blocks its loop, so
  ``from_async`` dies with ``AsyncioRequiredError`` instead of hanging).
- ``run_async``: inside a running asyncio loop. Cancelling the awaiting
  task interrupts the fiber and waits for its finalizers.
- ``run_fork``: start the effect and get its ``Fiber`` back at once, on the
  current fiber's run or the running asyncio loop. ``run_callback`` is the
  same with an exit callback, returning a function that interrupts it.
- ``run_main``: for a script's main program, like Effect's ``runMain``.
  Runs on a fresh asyncio loop; SIGINT and SIGTERM interrupt the fiber so
  finalizers run. It accepts effects that can fail, as Effect's does: the
  failure is logged through the loggers, and ``teardown`` turns the exit into
  the process status;
  ``default_teardown`` gives 0 on success, 130 when interrupted, or the
  error's ``exit_code`` (``get_error_exit_code``: ``TaggedError.exit_code``
  or any error's ``exit_code`` attribute, default 1).

Each of ``run_sync``, ``run_blocking`` and ``run_async`` has an ``_exit`` variant that
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
import threading
from collections.abc import Callable, Generator
from contextlib import contextmanager
from typing import Any, Never, Protocol, overload

from pyfect._core import Effect, _Succeed
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect._root import ambient_run, new_root, start_root
from pyfect.cause import Cause
from pyfect.context import Context
from pyfect.errors import AsyncFiberError
from pyfect.exit import Exit, Success
from pyfect.exit import die as exit_die
from pyfect.logger import log_error
from pyfect.scheduler import AsyncioScheduler, Scheduler, SyncOnlyScheduler, SyncScheduler

_EMPTY: Context[Never] = Context.empty()
_VOID: Effect[None] = _Succeed(None)

type Teardown = Callable[[Exit[Any, Any]], int]
"""Turns ``run_main``'s exit into the process status."""


@overload
def run_sync_exit[A, E](eff: Effect[A, E, Never]) -> Exit[A, E]: ...
@overload
def run_sync_exit[A, E, R](eff: Effect[A, E, R], *, context: Context[R]) -> Exit[A, E]: ...
def run_sync_exit(eff: Effect[Any, Any, Any], *, context: Context = _EMPTY) -> Exit[Any, Any]:
    """The effect's ``Exit``, run on this thread without waiting (Effect's
    ``runSyncExit``): an effect that waits dies with ``AsyncFiberError``."""
    require_effect(eff, "eff")
    scheduler = SyncOnlyScheduler()
    fiber: Fiber[Any, Any] = new_root(scheduler, context)
    fiber._start(eff)
    return flush_exit(scheduler, fiber)


def flush_exit[A, E](scheduler: SyncOnlyScheduler, fiber: Fiber[A, E]) -> Exit[A, E]:
    """What ``fiber`` comes to without waiting on anything."""
    scheduler.flush_as(fiber)
    return exit_die(AsyncFiberError(fiber=fiber)) if fiber._exit is None else fiber._exit


@overload
def run_sync[A](eff: Effect[A, Never, Never]) -> A: ...
@overload
def run_sync[A, R](eff: Effect[A, Never, R], *, context: Context[R]) -> A: ...
def run_sync(eff: Effect[Any, Never, Any], *, context: Context = _EMPTY) -> Any:
    """The effect's value, run on this thread without waiting (Effect's
    ``runSync``); a defect or interruption is raised, and an effect that
    waits dies with ``AsyncFiberError``."""
    return unwrap(run_sync_exit(eff, context=context))


@overload
def run_blocking_exit[A, E](eff: Effect[A, E, Never]) -> Exit[A, E]: ...
@overload
def run_blocking_exit[A, E, R](eff: Effect[A, E, R], *, context: Context[R]) -> Exit[A, E]: ...
def run_blocking_exit(eff: Effect[Any, Any, Any], *, context: Context = _EMPTY) -> Exit[Any, Any]:
    """The effect's ``Exit``, blocking this thread until it is done; sleeps,
    forks and ``blocking`` work, ``from_async`` does not (no asyncio loop)."""
    require_effect(eff, "eff")
    scheduler = SyncScheduler()
    fiber: Fiber[Any, Any] = new_root(scheduler, context)
    fiber._start(eff)
    return drive(scheduler, fiber)


@overload
def run_blocking[A](eff: Effect[A, Never, Never]) -> A: ...
@overload
def run_blocking[A, R](eff: Effect[A, Never, R], *, context: Context[R]) -> A: ...
def run_blocking(eff: Effect[Any, Never, Any], *, context: Context = _EMPTY) -> Any:
    """The effect's value, blocking this thread until it is done; a defect or
    interruption is raised. Sleeps, forks and ``blocking`` work,
    ``from_async`` does not (no asyncio loop). Use ``run_blocking_exit``
    for an effect that can fail, ``run_async`` inside a coroutine."""
    return unwrap(run_blocking_exit(eff, context=context))


def drive[A, E](scheduler: SyncScheduler, fiber: Fiber[A, E]) -> Exit[A, E]:
    """Run ``scheduler`` on this thread until ``fiber`` is done. On Ctrl-C
    the fiber is interrupted and its finalizers run before the
    ``KeyboardInterrupt`` propagates; a second Ctrl-C aborts."""
    try:
        scheduler.run_until(lambda: fiber._exit is not None)
    except KeyboardInterrupt:
        fiber.interrupt_as_unsafe(None)
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
    """The effect's ``Exit``, run on the running asyncio loop; cancelling the
    awaiting task interrupts the fiber and waits for its finalizers."""
    require_effect(eff, "eff")
    fiber: Fiber[Any, Any] = new_root(AsyncioScheduler.current(), context)
    fiber._start(eff)
    return await await_fiber(fiber)


@overload
async def run_async[A](eff: Effect[A, Never, Never]) -> A: ...
@overload
async def run_async[A, R](eff: Effect[A, Never, R], *, context: Context[R]) -> A: ...
async def run_async(eff: Effect[Any, Never, Any], *, context: Context = _EMPTY) -> Any:
    """The effect's value, run on the running asyncio loop (Effect's
    ``runPromise``); a defect or interruption is raised, and cancelling the
    awaiting task interrupts the fiber and waits for its finalizers."""
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
    require_effect(eff, "eff")
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
        fiber.add_observer_unsafe(on_exit)

    def interrupt(by: int | None = None, /) -> None:
        fiber.interrupt_as_unsafe(by)

    return interrupt


def default_teardown(ex: Exit[Any, Any]) -> int:
    """Effect's ``defaultTeardown``: 0 on success, 130 when only
    interrupted, otherwise the squashed error's ``get_error_exit_code``."""
    if isinstance(ex, Success):
        return 0
    if ex.cause.has_interrupts_only:
        return 130
    error = ex.cause.raisable()
    if isinstance(error, SystemExit):
        return _exit_status(error)
    return get_error_exit_code(error)


def get_error_exit_code(error: object) -> int:
    """The process status ``error`` asks for when it ends the program: its
    ``exit_code`` attribute when that is an ``int``, else 1. Any value may
    set one (``TaggedError`` declares it)."""
    code = getattr(error, "exit_code", None)
    return code if isinstance(code, int) and not isinstance(code, bool) else 1


def get_error_reported(error: object) -> bool:
    """Whether ``run_main`` logs ``error`` when it ends the program: its
    ``error_reported`` attribute when that is a ``bool``, else ``True``."""
    reported = getattr(error, "error_reported", True)
    return reported if isinstance(reported, bool) else True


def _exit_status(exit: SystemExit) -> int:
    """The status Python exits with for ``exit``: its code, 0 for none,
    1 for anything else (which Python prints)."""
    if exit.code is None:
        return 0
    return exit.code if isinstance(exit.code, int) else 1


def run_main[A, E](
    eff: Effect[A, E, Never],
    *,
    teardown: Teardown = default_teardown,
    disable_error_reporting: bool = False,
) -> A:
    """Run as the program's main fiber; see the module docstring.

    Returns the value when the program succeeds and ``teardown`` gives 0;
    otherwise ends the process with ``teardown``'s status. A failure that
    is not only an interrupt is first logged at ``ERROR`` through the
    default loggers (its pretty cause), as Effect's ``runMain`` does,
    unless ``disable_error_reporting`` or the squashed error's
    ``error_reported`` is ``False``."""
    require_effect(eff, "eff")
    main = eff if disable_error_reporting else eff.tap_cause(_log_failure)
    signalled = _Signalled()
    started: list[Fiber[A, E]] = []
    try:
        ex = asyncio.run(_run_main_exit(main, signalled, started))
    except KeyboardInterrupt:
        # Ctrl-C (or a raised KeyboardInterrupt) while user code ran: the
        # fiber was interrupted and finished as asyncio.run shut down.
        ex = started[0]._exit if started else None
        if ex is None:
            raise
        signalled.received = True
    code = teardown(ex)
    if isinstance(ex, Success) and code == 0 and not signalled.received:
        return ex.value
    raise SystemExit(code)


class _Signalled:
    """Whether SIGINT or SIGTERM arrived: then ``run_main`` ends the process
    with the teardown's status even when it is 0, as Node's ``runMain``
    exits on a signal."""

    __slots__ = ("received",)

    def __init__(self) -> None:
        self.received = False


def _log_failure(cause: Cause[object]) -> Effect[None]:
    error = cause.raisable()
    # ``sys.exit`` ends the program with its status; it is no error to log.
    if cause.has_interrupts_only or isinstance(error, SystemExit) or not get_error_reported(error):
        return _VOID
    return log_error(cause)


async def _run_main_exit[A, E](
    eff: Effect[A, E, Never], signalled: _Signalled, started: list[Fiber[A, E]]
) -> Exit[A, E]:
    fiber: Fiber[A, E] = new_root(AsyncioScheduler.current(), Context.empty())
    started.append(fiber)
    fiber._start(eff)
    with _interrupt_on_signals(fiber, signalled):
        return await await_fiber(fiber)


@contextmanager
def _interrupt_on_signals(fiber: Fiber[Any, Any], signalled: _Signalled) -> Generator[None]:
    """While open, SIGINT and SIGTERM interrupt ``fiber`` as itself, as
    Effect's ``runMain`` does (from the loop, not inside the signal
    handler). Python only delivers signals to the main thread, so elsewhere
    this does nothing."""
    if threading.current_thread() is not threading.main_thread():
        yield
        return
    loop = asyncio.get_running_loop()

    def on_signal(_signum: int, _frame: object) -> None:
        signalled.received = True
        loop.call_soon_threadsafe(fiber.interrupt_as_unsafe, fiber.id)

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
    fiber.add_observer_unsafe(done.set_result)
    try:
        return await asyncio.shield(done)
    except asyncio.CancelledError:
        fiber.interrupt_as_unsafe(None)
        await done
        raise


def unwrap[A](ex: Exit[A, Any]) -> A:
    """The value, or raise the squashed error (with the full cause as a
    note when there is more than one reason)."""
    if isinstance(ex, Success):
        return ex.value
    error = ex.cause.raisable()
    if len(ex.cause.reasons) > 1:
        error.add_note("Full cause:\n" + ex.cause.pretty())
    raise error


__all__ = [
    "Interruptor",
    "Teardown",
    "await_fiber",
    "default_teardown",
    "drive",
    "flush_exit",
    "get_error_exit_code",
    "get_error_reported",
    "run_async",
    "run_async_exit",
    "run_blocking",
    "run_blocking_exit",
    "run_callback",
    "run_fork",
    "run_main",
    "run_sync",
    "run_sync_exit",
    "unwrap",
]
