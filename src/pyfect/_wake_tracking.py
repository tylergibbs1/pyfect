"""Knowing which tasks a wake-up caused.

The test clock wakes a sleeper inside ``scheduler.track``. Every task
scheduled while that runs, and every task those tasks schedule, is counted
against the wake's ``WakeTracker``. When the count drops to zero the woken
fiber (and anything it resumed or forked) has suspended, so the clock can
move on. Unrelated fibers are never counted, so a busy one cannot stall it.

A scheduler also counts outside work: a fiber waiting on work it handed
to a thread (``pyfect._os_wait``), and what that work's resume schedules.
The test clock waits for it to be idle before moving time, so thread-backed
work takes no virtual time, as Effect's synchronous drivers do.

Every scheduler tracks, so a ``TestClock`` works on whatever runs it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from pyfect.scheduler import Cancel, Task


class WakeTracker:
    __slots__ = ("on_idle", "pending")

    def __init__(self) -> None:
        self.pending = 0
        self.on_idle: Callable[[], None] | None = None

    def when_idle(self, task: Task) -> Cancel:
        """Run ``task`` once every counted task has finished: now, if none
        is left (the last may have finished between the caller's look at
        ``pending`` and this call, which a fiber can pause between)."""
        if self.pending == 0:
            task()
            return _no_op
        self.on_idle = task

        def cancel() -> None:
            self.on_idle = None

        return cancel

    def finish_one(self) -> None:
        """One counted task finished; runs ``on_idle`` once none is left."""
        self.pending -= 1
        if self.pending == 0 and self.on_idle is not None:
            self.on_idle()


def _no_op() -> None:
    pass


class _Current(threading.local):
    tracker: WakeTracker | None = None


class Tracking:
    """Base class of the schedulers: ``schedule`` passes each task through
    ``_tracked`` before queueing it."""

    def __init__(self) -> None:
        self._tracking = _Current()
        self._outside = WakeTracker()

    def runs_here(self) -> bool:
        """Whether this thread is the one running the scheduler's tasks
        now. An interrupt sent from there is delivered at once."""
        return False

    def driver(self) -> int | None:
        """The ident of the thread running the scheduler's tasks now, if
        one is (and known)."""
        return None

    def outside_work(self) -> WakeTracker:
        """Counts fibers waiting on work handed to another thread, and the
        tasks their resumes schedule."""
        return self._outside

    def track(self, tracker: WakeTracker, f: Callable[[], None]) -> None:
        """Run ``f``, counting what it schedules against ``tracker``."""
        previous = self._tracking.tracker
        self._tracking.tracker = tracker
        try:
            f()
        finally:
            self._tracking.tracker = previous

    def _tracked(self, task: Task) -> Task:
        tracker = self._tracking.tracker
        if tracker is None:
            return task
        tracker.pending += 1

        def tracked() -> None:
            try:
                self.track(tracker, task)
            finally:
                tracker.finish_one()

        return tracked
