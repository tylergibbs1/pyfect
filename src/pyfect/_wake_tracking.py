"""Knowing which tasks a wake-up caused.

The test clock wakes a sleeper inside ``scheduler.track``. Every task
scheduled while that runs, and every task those tasks schedule, is counted
against the wake's ``WakeTracker``. When the count drops to zero the woken
fiber (and anything it resumed or forked) has suspended, so the clock can
move on. Unrelated fibers are never counted, so a busy one cannot stall it.

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
        """Run ``task`` once every counted task has finished."""
        self.on_idle = task

        def cancel() -> None:
            self.on_idle = None

        return cancel


class _Current(threading.local):
    tracker: WakeTracker | None = None


class Tracking:
    """Base class of the schedulers: ``schedule`` passes each task through
    ``_tracked`` before queueing it."""

    def __init__(self) -> None:
        self._tracking = _Current()

    def runs_here(self) -> bool:
        """Whether this thread is the one running the scheduler's tasks
        now. An interrupt sent from there is delivered at once."""
        return False

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
                tracker.pending -= 1
                if tracker.pending == 0 and tracker.on_idle is not None:
                    tracker.on_idle()

        return tracked
