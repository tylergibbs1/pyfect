"""Effect's ``makeHeldServerScheduler`` (``TestUtils/McpHeldScheduler.ts``):
a scheduler that holds the tasks scheduled on it until ``release``. Provided
to a registration, it holds the delivery of the list change the
registration makes, which runs on a fiber the registration forks."""

from __future__ import annotations

from collections.abc import Callable

import pyfect as fx
from pyfect._wake_tracking import WakeTracker
from pyfect.duration import Duration
from pyfect.scheduler import Cancel, Scheduler, Task


class HeldScheduler:
    def __init__(self, inner: Scheduler) -> None:
        self.inner = inner
        self.held: list[tuple[Task, int]] = []
        self.released = False

    def schedule(self, task: Task, priority: int = 0) -> None:
        if self.released:
            self.inner.schedule(task, priority)
        else:
            self.held.append((task, priority))

    def call_later(self, delay: Duration, task: Task, *, daemon: bool = False) -> Cancel:
        return self.inner.call_later(delay, lambda: self.schedule(task), daemon=daemon)

    def track(self, tracker: WakeTracker, f: Callable[[], None]) -> None:
        self.inner.track(tracker, f)

    def outside_work(self) -> WakeTracker:
        return self.inner.outside_work()

    @property
    def release(self) -> fx.Effect[None]:
        """Run the held tasks, and let the next ones run at once."""

        def run() -> None:
            self.released = True
            held, self.held = self.held, []
            for task, priority in held:
                self.inner.schedule(task, priority)

        return fx.sync(run).and_then(fx.yield_now())


def held_scheduler() -> fx.Effect[HeldScheduler]:
    return fx.CurrentScheduler().map(HeldScheduler)
