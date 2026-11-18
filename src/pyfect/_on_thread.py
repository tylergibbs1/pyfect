"""``fx.on_thread``: an effect as the root fiber of a run of its own, on a
thread of its own.

Effect has nothing like it: JavaScript runs every fiber on one thread. Every
fiber of a pyfect run takes turns on that run's thread too, so CPU-heavy
effects only overlap when they run in separate runs. On free-threaded Python
(3.14t) those runs go in parallel on separate cores.

The caller waits through ``os_wait``, so the inner fiber's exit resumes it
through its scheduler from the other thread. The wait is an ``"event"``, not
outside ``"work"``: the effect may sleep on the caller's ``TestClock``, which
must not wait for it before moving time. Interrupting the caller interrupts
the inner fiber and waits for its finalizers, as interrupting a forked child
does.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Any

from pyfect._core import Effect
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect._os_wait import os_wait
from pyfect._primitives import _FromExit, _Succeed, _Sync, _WithFiber, uninterruptible_mask
from pyfect._root import new_root
from pyfect.context import Context
from pyfect.exit import Exit
from pyfect.scheduler import SyncScheduler

type _Resume = Callable[[Effect[Any, Any, Any]], None]


def on_thread[A, E, R](eff: Effect[A, E, R]) -> Effect[A, E, R]:
    """Run ``eff`` on a new thread, as the root fiber of a run of its own,
    with the caller's services, and take on its result. Interrupting the
    caller interrupts it and waits for its finalizers.

    Fibers of one run take turns on its thread; on free-threaded Python,
    effects under ``on_thread`` run in parallel with the caller and with
    each other. What ``eff`` forks and leaves running goes on in the
    background, as after ``run_blocking``."""
    require_effect(eff, "eff")
    return _WithFiber(lambda caller: _run(eff, caller._context, caller.id))


def _run[A, E](eff: Effect[A, E, Any], context: Context, caller_id: int) -> Effect[A, E]:
    def body(restore: Callable[[Effect[A, E]], Effect[A, E]]) -> Effect[A, E]:
        inner: Fiber[A, E] = _start(eff, context)
        stop = _Sync(lambda: inner.interrupt_as_unsafe(caller_id)).flat_map(
            lambda _: _exited(inner).as_void()
        )
        return restore(_exited(inner).flat_map(_FromExit)).on_interrupt(stop)

    return uninterruptible_mask(body)


def _start[A, E](eff: Effect[A, E, Any], context: Context) -> Fiber[A, E]:
    from pyfect.run import drive

    scheduler = SyncScheduler()
    fiber: Fiber[A, E] = new_root(scheduler, context)
    fiber._start(eff)
    thread = threading.Thread(
        target=drive, args=(scheduler, fiber), name=f"pyfect-on-thread-{fiber.id}", daemon=True
    )
    thread.start()
    return fiber


def _exited[A, E](fiber: Fiber[A, E]) -> Effect[Exit[A, E]]:
    def register(resume: _Resume) -> Callable[[], None]:
        return fiber.add_observer_unsafe(lambda ex: resume(_Succeed(ex)))

    return os_wait(register, waits_for="event")


__all__ = ["on_thread"]
