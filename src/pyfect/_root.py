"""Root fibers: the fibers the run functions and runtimes start."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import asyncio
from typing import Any

from pyfect._core import Effect
from pyfect._fiber import Fiber, current_run_scheduler
from pyfect.context import Context
from pyfect.scheduler import AsyncioScheduler, CurrentScheduler, Scheduler


def new_root(
    run_scheduler: Scheduler,
    context: Context,
    *,
    scheduler: Scheduler | None = None,
    uninterruptible: bool = False,
) -> Fiber[Any, Any]:
    """An unstarted fiber with no parent, of the run on ``run_scheduler``.
    ``scheduler`` is provided as its ``CurrentScheduler``."""
    if scheduler is not None:
        context = context.add(CurrentScheduler, scheduler)
    return Fiber(run_scheduler, context, None, interruptible=not uninterruptible)


def start_root(fiber: Fiber[Any, Any], eff: Effect[Any, Any, Any], *, now: bool = False) -> None:
    """Start a root fiber. Called from a fiber of the same run, or with
    ``now`` (the caller is on the run's thread and no fiber of it is
    running), it runs at once, up to its first wait, before this returns
    (Effect evaluates it synchronously); otherwise it is scheduled."""
    if now or current_run_scheduler() is fiber._run_scheduler:
        fiber._evaluate(eff)
    else:
        fiber._start(eff)


def run_loop() -> asyncio.AbstractEventLoop | None:
    """The asyncio loop driving the run of the fiber running on this thread,
    or ``None`` (no fiber, or a ``run_sync`` run). A loop merely running on
    this thread does not count: ``run_sync`` blocks it until it returns, so
    nothing scheduled on it runs before then."""
    run = current_run_scheduler()
    return run.loop if isinstance(run, AsyncioScheduler) else None


def loop_running_here() -> bool:
    """Whether an asyncio loop is running on this thread."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return False
    return True


def run_identity(run_scheduler: Scheduler) -> object:
    """What fibers of one run share: the asyncio loop for runs on a loop
    (each ``run_async`` has a scheduler of its own, all driven by the
    loop), else the run's scheduler, which stops when its run ends."""
    return run_scheduler._loop if isinstance(run_scheduler, AsyncioScheduler) else run_scheduler


def ambient_run(scheduler: Scheduler | None) -> tuple[Scheduler, bool]:
    """The run a root fiber started here joins, and whether it can start
    at once: the current fiber's (it can), else the running asyncio loop's
    (it can: this is the loop's thread), else ``scheduler``, which the
    caller then drives (it is scheduled)."""
    run = current_run_scheduler()
    if run is not None:
        return run, True
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        if scheduler is None:
            raise NoRunError(
                "run_fork needs a running fiber, a running asyncio loop, or a scheduler "
                "to run on; use run_sync or run_async otherwise"
            ) from None
        return scheduler, False
    return AsyncioScheduler(loop), True


class NoRunError(RuntimeError):
    """``run_fork`` or ``run_callback`` was called with nothing to run the
    fiber: no fiber, no asyncio loop and no scheduler."""
