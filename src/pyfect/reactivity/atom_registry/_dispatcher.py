"""Effect's per-fiber dispatcher flush for the fibers a registry forks.

Effect runs an atom's effect with ``runForkWith`` and then flushes the
fiber's dispatcher, so what the fiber yields (``yieldNow``, its step
budget, a child it starts) runs before the build returns; only a real wait
leaves the atom waiting. ``Dispatcher`` is the forked fiber's
``CurrentScheduler``: inside ``run_flushed`` it queues what this thread
schedules and runs it there, until nothing is left; otherwise it hands
everything to the registry's scheduler.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Callable

from pyfect._wake_tracking import WakeTracker
from pyfect.duration import Seconds
from pyfect.scheduler import Cancel, Scheduler, Task


class Dispatcher:
    __slots__ = ("_flushing", "_queue", "scheduler")

    def __init__(self, scheduler: Scheduler) -> None:
        self.scheduler = scheduler
        self._queue: deque[Task] = deque()
        self._flushing: int | None = None

    def schedule(self, task: Task, priority: int = 0) -> None:
        if self._flushing == threading.get_ident():
            self._queue.append(task)
        else:
            self.scheduler.schedule(task)

    def call_later(self, delay: Seconds, task: Task, *, daemon: bool = False) -> Cancel:
        return self.scheduler.call_later(delay, task, daemon=daemon)

    def track(self, tracker: WakeTracker, f: Callable[[], None]) -> None:
        self.scheduler.track(tracker, f)

    def outside_work(self) -> WakeTracker:
        return self.scheduler.outside_work()

    def run_flushed(self, start: Callable[[], None]) -> None:
        """Run ``start``, then what it scheduled on this thread, until
        nothing is left."""
        outer = self._flushing
        self._flushing = threading.get_ident()
        try:
            start()
            while self._queue:
                self._queue.popleft()()
        finally:
            self._flushing = outer
            if outer is None:
                # a task raised: the rest runs on the registry's scheduler
                while self._queue:
                    self.scheduler.schedule(self._queue.popleft())
