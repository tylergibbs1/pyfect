"""A scheduler that only collects its tasks, for ports of Effect tests that
hand a fiber a dispatcher whose tasks the test runs by hand.

A task that resumes a fiber runs it at once, as Effect's synchronous
resume does; ``run_all`` yields between tasks so fibers queued on the run's
own scheduler get their turn too.
"""

from collections.abc import Callable

import pyfect as fx
from pyfect._wake_tracking import WakeTracker
from pyfect.duration import Seconds
from pyfect.scheduler import Cancel, Task


class TaskQueue:
    def __init__(self) -> None:
        self.tasks: list[Task] = []

    def schedule(self, task: Task) -> None:
        self.tasks.append(task)

    def call_later(self, delay: Seconds, task: Task, *, daemon: bool = False) -> Cancel:
        raise AssertionError("a TaskQueue has no timers")

    def track(self, tracker: WakeTracker, f: Callable[[], None]) -> None:
        f()

    def run_next(self) -> None:
        self.tasks.pop(0)()

    def run_all(self) -> fx.Effect[None]:
        """Run tasks, letting the fibers they resume run, until none are left."""

        @fx.gen
        def drain():
            while self.tasks:
                self.run_next()
                yield from fx.yield_now()

        return drain

    def provide[A, E, R](self, eff: fx.Effect[A, E, R]) -> fx.Effect[A, E, R]:
        return eff.pipe(fx.provide_service(fx.CurrentScheduler, self))
