"""Waiting for something outside the scheduler (a thread, another loop)
without blocking a fiber.

The fiber suspends in ``os_wait`` and the outside resumes it through the
scheduler, from any thread. While it waits, a timer stays pending on the
fiber's scheduler, so a synchronous run (a test's stall detection
included) knows the wait is outside work, not a deadlock. Every wait on
another thread goes through here (``tests/test_os_wait_guard.py``).

Each wait says what it waits for, and the test clock treats the two apart:

- ``"work"``: work the wait itself started, which finishes on its own (a
  call on a thread, a query, a request). The scheduler counts it in its
  ``outside_work``, and its resume too, so ``TestClock.adjust`` waits for it
  before moving time: thread-backed work takes no virtual time, as Effect's
  synchronous drivers do.
- ``"event"``: something that may never come (a socket read, a message, a
  child exiting). The test clock does not wait for it.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Literal

from pyfect._core import Effect, _Callback, _Sync
from pyfect._wake_tracking import WakeTracker
from pyfect.duration import millis
from pyfect.scheduler import CurrentScheduler, Scheduler

type Resume[A, E] = Callable[[Effect[A, E]], None]
type Cancel = Callable[[], object]
type Register[A, E] = Callable[[Resume[A, E]], Cancel | None]
type WaitsFor = Literal["work", "event"]

_KEEPALIVE = millis(250)

"""How often a waiting fiber's timer fires; below the test runtime's
one-second stall timeout."""


class _Waiting:
    __slots__ = ("active", "counted", "registering")

    def __init__(self, *, counted: bool) -> None:
        self.active = True
        # Whether the scheduler's outside work still counts this wait; only
        # read and written on the scheduler's thread.
        self.counted = counted
        # The thread running ``register``, while it runs: a resume from it
        # happens at once.
        self.registering: int | None = threading.get_ident()

    def uncount(self, outside: WakeTracker) -> None:
        if self.counted:
            self.counted = False
            outside.finish_one()


def os_wait[A, E](register: Register[A, E], *, waits_for: WaitsFor) -> Effect[A, E]:
    """Suspend until ``register``'s ``resume`` is called, from any thread.
    ``register`` runs on the fiber's thread and may resume at once; the
    cancel function it returns runs if the fiber is interrupted first.
    ``waits_for`` says whether the outside is work this wait started or an
    event that may never come (see the module)."""
    return CurrentScheduler().flat_map(
        lambda scheduler: _Callback(_registered(scheduler, register, waits_for))
    )


def _registered[A, E](
    scheduler: Scheduler, register: Register[A, E], waits_for: WaitsFor
) -> Callable[[Resume[A, E]], Effect[None] | None]:
    def start(resume: Resume[A, E]) -> Effect[None] | None:
        outside = scheduler.outside_work()
        waiting = _Waiting(counted=waits_for == "work")
        if waiting.counted:
            outside.pending += 1

        def beat() -> None:
            if waiting.active:
                scheduler.call_later(_KEEPALIVE, beat)

        def settle(effect: Effect[A, E]) -> None:
            # On the scheduler's thread: the resume and what it schedules
            # count as outside work until the fiber suspends again.
            if waiting.counted:
                scheduler.track(outside, lambda: resume(effect))
                waiting.uncount(outside)
            else:
                resume(effect)

        def finish(effect: Effect[A, E]) -> None:
            waiting.active = False
            if waits_for == "event":
                resume(effect)
            elif waiting.registering == threading.get_ident():
                resume(effect)
                waiting.uncount(outside)
            else:
                scheduler.schedule(lambda: settle(effect))

        cancel = register(finish)
        waiting.registering = None
        if not waiting.active:
            return None
        scheduler.call_later(_KEEPALIVE, beat)

        def interrupted() -> None:
            waiting.active = False
            waiting.uncount(outside)
            if cancel is not None:
                cancel()

        return _Sync(interrupted)

    return start
