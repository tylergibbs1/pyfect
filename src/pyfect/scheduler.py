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

Both also serve the test clock: ``track`` counts the work a wake-up causes,
and ``when_idle`` runs a task once no fiber has anything ready to run.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import threading
import time
from collections import deque
from collections.abc import Callable
from typing import Protocol

from pyfect._wake_tracking import Tracking, WakeTracker
from pyfect.duration import Seconds

type Task = Callable[[], None]
type Cancel = Callable[[], None]


class Scheduler(Protocol):
    def schedule(self, task: Task) -> None: ...

    def call_later(self, delay: Seconds, task: Task, *, daemon: bool = False) -> Cancel:
        """Run ``task`` after ``delay``. A ``daemon`` timer (a diagnostic)
        does not count as pending work: it never hides a stall."""
        ...

    def when_idle(self, task: Task) -> Cancel:
        """Run ``task`` once no other task is ready. Call on the scheduler
        thread."""
        ...

    def track(self, tracker: WakeTracker, f: Callable[[], None]) -> None:
        """Run ``f``, counting what it schedules (transitively) against
        ``tracker``."""
        ...


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
        self._idle: deque[_Timer] = deque()
        self._timers: list[tuple[float, int, _Timer]] = []
        self._seq = itertools.count()
        self._cond = threading.Condition()

    def when_idle(self, task: Task) -> Cancel:
        waiter = _Timer(0.0, task)
        self._idle.append(waiter)
        return waiter.cancel

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
        while not done():
            with self._cond:
                self._move_due_timers()
                while not self._ready and self._idle:
                    waiter = self._idle.popleft()
                    if waiter.alive:
                        self._ready.append(waiter.task)
                if not self._ready:
                    self._cond.wait(self._wait_time(stall_timeout))
                    continue
                batch, self._ready = self._ready, deque()
            for task in batch:
                task()

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


class AsyncioScheduler(Tracking):
    """Runs tasks on an asyncio event loop, batching them per loop tick."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        super().__init__()
        self._loop = loop
        self._thread = threading.get_ident()
        self._ready: deque[Task] = deque()
        self._idle: deque[_Timer] = deque()
        self._draining_scheduled = False

    @classmethod
    def current(cls) -> AsyncioScheduler:
        """The scheduler for the running loop. Must be called on the loop."""
        return cls(asyncio.get_running_loop())

    def schedule(self, task: Task) -> None:
        if threading.get_ident() != self._thread:
            self._loop.call_soon_threadsafe(self.schedule, task)
            return
        self._ready.append(self._tracked(task))
        self._drain_soon()

    def call_later(self, delay: Seconds, task: Task, *, daemon: bool = False) -> Cancel:
        return self._loop.call_later(max(delay, 0.0), task).cancel

    def when_idle(self, task: Task) -> Cancel:
        waiter = _Timer(0.0, task)
        self._idle.append(waiter)
        self._drain_soon()
        return waiter.cancel

    def _drain_soon(self) -> None:
        if not self._draining_scheduled:
            self._draining_scheduled = True
            self._loop.call_soon(self._drain)

    def _drain(self) -> None:
        # Run only what was queued before this tick so asyncio callbacks
        # (I/O, other tasks) are never starved by a busy fiber.
        self._draining_scheduled = False
        for _ in range(len(self._ready)):
            self._ready.popleft()()
        while not self._ready and self._idle:
            waiter = self._idle.popleft()
            if waiter.alive:
                waiter.task()
        if self._ready:
            self._drain_soon()
