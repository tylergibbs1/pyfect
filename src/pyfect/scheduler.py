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

from pyfect.duration import Seconds

type Task = Callable[[], None]
type Cancel = Callable[[], None]


class Scheduler(Protocol):
    def schedule(self, task: Task) -> None: ...

    def call_later(self, delay: Seconds, task: Task) -> Cancel: ...


class _Timer:
    __slots__ = ("alive", "task", "when")

    def __init__(self, when: float, task: Task) -> None:
        self.when = when
        self.task = task
        self.alive = True

    def cancel(self) -> None:
        self.alive = False


class StalledError(RuntimeError):
    """Every fiber is waiting and nothing can wake them up."""


class SyncScheduler:
    """Runs tasks on the thread that calls ``run_until``."""

    def __init__(self) -> None:
        self._ready: deque[Task] = deque()
        self._idle: deque[_Timer] = deque()
        self._timers: list[tuple[float, int, _Timer]] = []
        self._seq = itertools.count()
        self._cond = threading.Condition()

    def when_idle(self, task: Task) -> Cancel:
        """Run ``task`` once no other task is ready. Lets test clocks wait
        until every fiber has settled. Call on the scheduler thread."""
        waiter = _Timer(0.0, task)
        self._idle.append(waiter)
        return waiter.cancel

    def schedule(self, task: Task) -> None:
        with self._cond:
            self._ready.append(task)
            self._cond.notify()

    def call_later(self, delay: Seconds, task: Task) -> Cancel:
        timer = _Timer(time.monotonic() + max(delay, 0.0), task)
        with self._cond:
            heapq.heappush(self._timers, (timer.when, next(self._seq), timer))
            self._cond.notify()
        return timer.cancel

    def run_until(self, done: Callable[[], bool], *, stall_timeout: float | None = None) -> None:
        """Run tasks and timers until ``done()`` is true.

        Blocks while nothing is ready. With ``stall_timeout``, raises
        ``StalledError`` if nothing is ready, no timer is pending, and no
        other thread schedules anything for that long.

        A ``KeyboardInterrupt`` raised while blocked propagates; the caller
        decides how to unwind.
        """
        while not done():
            with self._cond:
                self._move_due_timers()
                while not self._ready and self._idle:
                    waiter = self._idle.popleft()
                    if waiter.alive:
                        self._ready.append(waiter.task)
                if not self._ready:
                    timeout = self._next_timeout()
                    stalled = timeout is None and stall_timeout is not None
                    notified = self._cond.wait(stall_timeout if stalled else timeout)
                    if stalled and not notified and not self._ready:
                        raise StalledError("every fiber is waiting and nothing can wake them")
                    continue
                batch, self._ready = self._ready, deque()
            for task in batch:
                task()

    def _move_due_timers(self) -> None:
        now = time.monotonic()
        while self._timers and self._timers[0][0] <= now:
            _, _, timer = heapq.heappop(self._timers)
            if timer.alive:
                self._ready.append(timer.task)

    def _next_timeout(self) -> float | None:
        while self._timers and not self._timers[0][2].alive:
            heapq.heappop(self._timers)
        if not self._timers:
            return None
        # An infinite (or absurdly far) deadline still has to fit a lock wait.
        return min(max(self._timers[0][0] - time.monotonic(), 0.0), threading.TIMEOUT_MAX)


class AsyncioScheduler:
    """Runs tasks on an asyncio event loop, batching them per loop tick."""

    def __init__(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop
        self._thread = threading.get_ident()
        self._ready: deque[Task] = deque()
        self._draining_scheduled = False

    @classmethod
    def current(cls) -> AsyncioScheduler:
        """The scheduler for the running loop. Must be called on the loop."""
        return cls(asyncio.get_running_loop())

    def schedule(self, task: Task) -> None:
        if threading.get_ident() != self._thread:
            self._loop.call_soon_threadsafe(self.schedule, task)
            return
        self._ready.append(task)
        if not self._draining_scheduled:
            self._draining_scheduled = True
            self._loop.call_soon(self._drain)

    def call_later(self, delay: Seconds, task: Task) -> Cancel:
        return self._loop.call_later(max(delay, 0.0), task).cancel

    def _drain(self) -> None:
        # Run only what was queued before this tick so asyncio callbacks
        # (I/O, other tasks) are never starved by a busy fiber.
        self._draining_scheduled = False
        for _ in range(len(self._ready)):
            self._ready.popleft()()
        if self._ready and not self._draining_scheduled:
            self._draining_scheduled = True
            self._loop.call_soon(self._drain)
