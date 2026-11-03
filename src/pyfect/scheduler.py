"""Where fibers run.

A scheduler runs short tasks one at a time and fires timers. Fibers never
touch threads or event loops directly; they only call ``schedule`` and
``call_later``. That keeps the fiber runtime the same no matter what drives
it:

- ``SyncScheduler`` runs everything on the calling thread and blocks while
  it waits for timers or for callbacks from other threads.
- ``AsyncioScheduler`` runs on an asyncio event loop.

``schedule`` is safe to call from any thread. ``call_later`` is only called
from fibers, which always run on the scheduler's own thread.

Both also serve the test clock: ``track`` counts the work a wake-up causes.

A fiber reads its scheduler and its yield budget from its context, as
Effect does, so they can be provided per effect::

    eff.pipe(provide_service(MaxOpsBeforeYield, 16))

``ShouldYield`` replaces the budget with a function deciding when the
fiber yields (Effect's ``Scheduler.shouldYield``).
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Protocol

from pyfect._wake_tracking import Tracking, WakeTracker
from pyfect.context import Reference
from pyfect.duration import Seconds

if TYPE_CHECKING:
    from pyfect._fiber import Fiber

type Task = Callable[[], None]
type Cancel = Callable[[], None]


class Scheduler(Protocol):
    def schedule(self, task: Task) -> None: ...

    def call_later(self, delay: Seconds, task: Task, *, daemon: bool = False) -> Cancel:
        """Run ``task`` after ``delay``. A ``daemon`` timer (a diagnostic)
        does not count as pending work: it never hides a stall."""
        ...

    def track(self, tracker: WakeTracker, f: Callable[[], None]) -> None:
        """Run ``f``, counting what it schedules (transitively) against
        ``tracker``."""
        ...

    def outside_work(self) -> WakeTracker:
        """Counts fibers waiting on work handed to another thread, and the
        tasks their resumes schedule (``pyfect._os_wait``)."""
        ...


class CurrentScheduler(Reference[Scheduler]):
    """The scheduler the current fiber runs on. The run functions provide
    it; providing another moves an effect's tasks, and its children's, onto
    that scheduler. The run still drives only its own scheduler, so a
    provided one must hand its tasks to it, as a wrapper around the current
    scheduler does."""

    @classmethod
    def default(cls) -> Scheduler:
        raise RuntimeError("no scheduler: run effects with run_sync, run_async or run_main")


class MaxOpsBeforeYield(Reference[int]):
    """How many steps a fiber takes before giving other fibers a turn. A
    budget below 1 counts as 1, so a fiber always makes progress."""

    @classmethod
    def default(cls) -> int:
        return 2048


class PreventSchedulerYield(Reference[bool]):
    """When ``True``, a fiber never yields because of its step budget. It
    still yields when it waits or calls ``yield_now``."""

    @classmethod
    def default(cls) -> bool:
        return False


type YieldCheck = Callable[[Fiber[Any, Any], int], bool]
"""Whether a fiber yields now, given the fiber and the steps it has taken
since it last started running."""


class ShouldYield(Reference[YieldCheck | None]):
    """Decides when a fiber gives other fibers a turn, in place of
    ``MaxOpsBeforeYield`` (Effect's ``Scheduler.shouldYield``). It is asked
    before each step but the first of every run, so a fiber always makes
    progress; ``PreventSchedulerYield`` turns it off. A raise is a defect
    of the fiber. ``None`` (the default) compares the steps with the
    budget."""

    @classmethod
    def default(cls) -> YieldCheck | None:
        return None


class _Timer:
    __slots__ = ("alive", "daemon", "task", "when")

    def __init__(self, when: float, task: Task, *, daemon: bool = False) -> None:
        self.when = when
        self.task = task
        self.daemon = daemon
        self.alive = True

    def cancel(self) -> None:
        self.alive = False


class StalledError(RuntimeError):
    """Every fiber is waiting and nothing can wake them up."""


class SyncScheduler(Tracking):
    """Runs tasks on the thread that calls ``run_until``."""

    def __init__(self) -> None:
        super().__init__()
        self._last_activity = time.monotonic()
        self._ready: deque[Task] = deque()
        self._timers: list[tuple[float, int, _Timer]] = []
        self._seq = itertools.count()
        self._cond = threading.Condition()
        # The thread inside ``run_until``, if any.
        self._driver: int | None = None

    def runs_here(self) -> bool:
        """Whether this thread is the one running the scheduler's tasks."""
        return self._driver == threading.get_ident()

    def driver(self) -> int | None:
        return self._driver

    def schedule(self, task: Task) -> None:
        task = self._tracked(task)
        with self._cond:
            self._ready.append(task)
            self._last_activity = time.monotonic()
            self._cond.notify()

    def call_later(self, delay: Seconds, task: Task, *, daemon: bool = False) -> Cancel:
        timer = _Timer(time.monotonic() + max(delay, 0.0), task, daemon=daemon)
        with self._cond:
            heapq.heappush(self._timers, (timer.when, next(self._seq), timer))
            self._cond.notify()
        return timer.cancel

    def run_until(self, done: Callable[[], bool], *, stall_timeout: float | None = None) -> None:
        """Run tasks and timers until ``done()`` is true.

        Blocks while nothing is ready. With ``stall_timeout``, raises
        ``StalledError`` once nothing has been ready, no timer but daemon
        timers has been pending, and no other thread has scheduled anything
        for that long.

        A ``KeyboardInterrupt`` raised while blocked propagates; the caller
        decides how to unwind.
        """
        self._last_activity = time.monotonic()
        driver, self._driver = self._driver, threading.get_ident()
        try:
            self._run_until(done, stall_timeout)
        finally:
            self._driver = driver

    def _run_until(self, done: Callable[[], bool], stall_timeout: float | None) -> None:
        while not done():
            with self._cond:
                self._move_due_timers()
                if not self._ready:
                    self._cond.wait(self._wait_time(stall_timeout))
                    continue
                batch, self._ready = self._ready, deque()
            try:
                while batch:
                    batch.popleft()()
            finally:
                if batch:  # a task raised (Ctrl-C): the rest still runs first
                    with self._cond:
                        self._ready.extendleft(reversed(batch))

    def _wait_time(self, stall_timeout: float | None) -> float | None:
        """How long to block with nothing ready; raises once stalled."""
        timeout = self._next_timeout()
        if stall_timeout is None or self._has_live_timers():
            self._last_activity = time.monotonic()
            return timeout
        remaining = stall_timeout - (time.monotonic() - self._last_activity)
        if remaining <= 0:
            raise StalledError("every fiber is waiting and nothing can wake them")
        return remaining if timeout is None else min(timeout, remaining)

    def _has_live_timers(self) -> bool:
        return any(t.alive and not t.daemon for _, _, t in self._timers)

    def _move_due_timers(self) -> None:
        now = time.monotonic()
        while self._timers and self._timers[0][0] <= now:
            _, _, timer = heapq.heappop(self._timers)
            if timer.alive:
                self._ready.append(timer.task)
                if not timer.daemon:
                    self._last_activity = now

    def _next_timeout(self) -> float | None:
        while self._timers and not self._timers[0][2].alive:
            heapq.heappop(self._timers)
        if not self._timers:
            return None
        # An infinite (or absurdly far) deadline still has to fit a lock wait.
        return min(max(self._timers[0][0] - time.monotonic(), 0.0), threading.TIMEOUT_MAX)


class LoopClosedError(RuntimeError):
    """A task was handed to an ``AsyncioScheduler`` whose loop has closed:
    the fibers on it can never run again. Raised where the task was handed
    over, so the lost wake-up is a defect there rather than a silent hang."""


class AsyncioScheduler(Tracking):
    """Runs tasks on an asyncio event loop, batching them per loop tick. A
    task handed over once the loop has closed raises ``LoopClosedError``."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._loop = loop
        self._thread = threading.get_ident()
        self._ready: deque[Task] = deque()
        self._draining_scheduled = False

    @property
    def loop(self) -> asyncio.AbstractEventLoop:
        """The loop this scheduler runs tasks on."""
        return self._loop

    def runs_here(self) -> bool:
        """Whether this thread is the one running the scheduler's tasks."""
        return threading.get_ident() == self._thread and self._loop.is_running()

    def driver(self) -> int | None:
        return self._thread if self._loop.is_running() else None

    @classmethod
    def current(cls) -> AsyncioScheduler:
        """The scheduler for the running loop. Must be called on the loop."""
        return cls(asyncio.get_running_loop())

    def schedule(self, task: Task) -> None:
        if threading.get_ident() != self._thread:
            self._call_soon_threadsafe(self.schedule, task)
            return
        self._ready.append(self._tracked(task))
        self._drain_soon()

    def _call_soon_threadsafe(self, f: Callable[..., None], *args: object) -> None:
        try:
            self._loop.call_soon_threadsafe(f, *args)
        except RuntimeError:
            if not self._loop.is_closed():
                raise
            raise LoopClosedError("the asyncio loop this fiber runs on has closed") from None

    def call_later(self, delay: Seconds, task: Task, *, daemon: bool = False) -> Cancel:
        return self._loop.call_later(max(delay, 0.0), task).cancel

    def _drain_soon(self) -> None:
        if not self._draining_scheduled:
            self._draining_scheduled = True
            self._loop.call_soon(self._drain)

    def _drain(self) -> None:
        # Run only what was queued before this tick so asyncio callbacks
        # (I/O, other tasks) are never starved by a busy fiber.
        self._draining_scheduled = False
        try:
            for _ in range(len(self._ready)):
                self._ready.popleft()()
        finally:
            # Also when a task raised (Ctrl-C): what is left still runs.
            if self._ready:
                self._drain_soon()


__all__ = [
    "AsyncioScheduler",
    "Cancel",
    "CurrentScheduler",
    "LoopClosedError",
    "MaxOpsBeforeYield",
    "PreventSchedulerYield",
    "Scheduler",
    "ShouldYield",
    "StalledError",
    "SyncScheduler",
    "Task",
    "YieldCheck",
]
