"""A scheduler that knows which tasks a wake-up caused.

The test clock wakes a sleeper inside ``track``. Every task scheduled
while that runs, and every task those tasks schedule, is counted against
the wake's ``WakeTracker``. When the count drops to zero the woken fiber
(and anything it resumed or forked) has suspended, so the clock can move
on. Unrelated fibers are never counted, so a busy one cannot stall it.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

from pyfect.duration import Seconds
from pyfect.scheduler import Cancel, SyncScheduler, Task


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


class TrackingScheduler:
    """Wraps a ``SyncScheduler``; fibers in ``run_test`` run on this."""

    def __init__(self, inner: SyncScheduler) -> None:
        self.inner = inner
        self._current = _Current()

    def track(self, tracker: WakeTracker, f: Callable[[], None]) -> None:
        """Run ``f``, counting what it schedules against ``tracker``."""
        previous = self._current.tracker
        self._current.tracker = tracker
        try:
            f()
        finally:
            self._current.tracker = previous

    def schedule(self, task: Task) -> None:
        tracker = self._current.tracker
        if tracker is None:
            self.inner.schedule(task)
            return
        tracker.pending += 1

        def tracked() -> None:
            try:
                self.track(tracker, task)
            finally:
                tracker.pending -= 1
                if tracker.pending == 0 and tracker.on_idle is not None:
                    tracker.on_idle()

        self.inner.schedule(tracked)

    def call_later(self, delay: Seconds, task: Task) -> Cancel:
        return self.inner.call_later(delay, task)
