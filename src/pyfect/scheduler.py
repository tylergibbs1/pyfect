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

``EffectScheduler`` is Effect's own ``Scheduler`` interface
(``execution_mode``, ``should_yield``, ``make_dispatcher``), which replaces
how a fiber decides to yield and where its tasks wait; ``MixedScheduler`` is
Effect's default implementation of it. Provided as ``CurrentScheduler``, it
is bound to the run, whose scheduler still owns the timers.
"""

from __future__ import annotations

import asyncio
import heapq
import itertools
import threading
import time
from abc import ABC, abstractmethod
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Literal, Protocol

from pyfect._wake_tracking import Tracking, WakeTracker
from pyfect.context import Reference
from pyfect.duration import Duration

if TYPE_CHECKING:
    from pyfect._fiber import Fiber

type Task = Callable[[], None]
type Cancel = Callable[[], None]


class Scheduler(Protocol):
    def schedule(self, task: Task, priority: int = 0) -> None:
        """Run ``task`` soon. Each batch runs lowest priority first, in order
        within a priority."""
        ...

    def call_later(self, delay: Duration, task: Task, *, daemon: bool = False) -> Cancel:
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
        raise RuntimeError("no scheduler: run effects with run_blocking, run_async or run_main")


class MaxOpsBeforeYield(Reference[int]):
    """How many steps a fiber takes before giving other fibers a turn; a
    budget below 1 counts as 1."""

    @classmethod
    def default(cls) -> int:
        return 2048


class PreventSchedulerYield(Reference[bool]):
    """When ``True``, a fiber never yields because of its step budget. It
    still yields when it waits or calls ``yield_now``."""

    @classmethod
    def default(cls) -> bool:
        return False


class SchedulerDispatcher(Protocol):
    """Holds the tasks of a fiber (Effect's ``SchedulerDispatcher``)."""

    def schedule_task(self, task: Task, priority: int) -> None: ...

    def flush(self) -> None: ...


type ExecutionMode = Literal["sync", "async"]


class EffectScheduler(ABC):
    """Effect's ``Scheduler`` interface. Provide one as ``CurrentScheduler``
    to decide when a fiber yields and where its tasks wait. A fiber reads it
    bound to its run, so these ``Scheduler`` methods only serve the type."""

    execution_mode: ExecutionMode = "async"

    @abstractmethod
    def should_yield(self, fiber: Fiber[Any, Any]) -> bool: ...

    @abstractmethod
    def make_dispatcher(self) -> SchedulerDispatcher: ...

    def schedule(self, task: Task, priority: int = 0) -> None:
        raise RuntimeError("an EffectScheduler schedules through its run: provide it to a fiber")

    def call_later(self, delay: Duration, task: Task, *, daemon: bool = False) -> Cancel:
        raise RuntimeError("an EffectScheduler schedules through its run: provide it to a fiber")

    def track(self, tracker: WakeTracker, f: Callable[[], None]) -> None:
        raise RuntimeError("an EffectScheduler schedules through its run: provide it to a fiber")

    def outside_work(self) -> WakeTracker:
        raise RuntimeError("an EffectScheduler schedules through its run: provide it to a fiber")


class _PriorityBuckets:
    __slots__ = ("buckets",)

    def __init__(self) -> None:
        self.buckets: list[tuple[int, list[Task]]] = []

    def schedule_task(self, task: Task, priority: int) -> None:
        buckets = self.buckets
        for index, (bucket_priority, tasks) in enumerate(buckets):
            if bucket_priority == priority:
                tasks.append(task)
                return
            if bucket_priority > priority:
                buckets.insert(index, (priority, [task]))
                return
        buckets.append((priority, [task]))

    def drain(self) -> list[tuple[int, list[Task]]]:
        buckets, self.buckets = self.buckets, []
        return buckets


class _Binding(threading.local):
    """The run of the ``BoundScheduler`` handing a task to its dispatcher."""

    run: Scheduler | None = None


_binding = _Binding()


def _run_soon(task: Task) -> Cancel:
    """``setImmediate`` of a ``MixedScheduler``: the tasks of the run it is
    bound to; a dispatcher used by hand, outside any run, waits for ``flush``."""
    run = _binding.run
    if run is None:
        return lambda: None
    cancelled = False

    def cancel() -> None:
        nonlocal cancelled
        cancelled = True

    def go() -> None:
        if not cancelled:
            task()

    run.schedule(go)
    return cancel


class _MixedDispatcher:
    __slots__ = ("_running", "_set_immediate", "_tasks")

    def __init__(self, set_immediate: Callable[[Task], Cancel]) -> None:
        self._set_immediate = set_immediate
        self._tasks = _PriorityBuckets()
        self._running: Cancel | None = None

    def schedule_task(self, task: Task, priority: int) -> None:
        self._tasks.schedule_task(task, priority)
        if self._running is None:
            self._running = self._set_immediate(self._after_scheduled)

    def _after_scheduled(self) -> None:
        self._running = None
        self._run_tasks()

    def _run_tasks(self) -> None:
        for _, to_run in self._tasks.drain():
            for task in to_run:
                task()

    def flush(self) -> None:
        while self._tasks.buckets:
            if self._running is not None:
                self._running()
                self._running = None
            self._run_tasks()


class MixedScheduler(EffectScheduler):
    """Effect's default scheduler: priority buckets, drained after each tick
    of the run, and a yield once ``MaxOpsBeforeYield`` steps are spent."""

    def __init__(
        self,
        execution_mode: ExecutionMode = "async",
        set_immediate: Callable[[Task], Cancel] = _run_soon,
    ) -> None:
        self.execution_mode = execution_mode
        self._set_immediate = set_immediate

    def should_yield(self, fiber: Fiber[Any, Any]) -> bool:
        return fiber.current_op_count >= fiber.get_ref(MaxOpsBeforeYield)

    def make_dispatcher(self) -> SchedulerDispatcher:
        return _MixedDispatcher(self._set_immediate)


class BoundScheduler:
    """An ``EffectScheduler`` as a fiber of a run reads it: tasks wait in its
    dispatcher, made at the first task, as Effect's ``currentDispatcher``;
    timers and the test clock's tracking stay with the run."""

    __slots__ = ("_dispatcher", "effect_scheduler", "run")

    def __init__(self, effect_scheduler: EffectScheduler, run: Scheduler) -> None:
        self.effect_scheduler = effect_scheduler
        self.run = run
        self._dispatcher: SchedulerDispatcher | None = None

    def schedule(self, task: Task, priority: int = 0) -> None:
        run = self.run
        if isinstance(run, Tracking) and run.driver() not in (None, threading.get_ident()):
            run.schedule(lambda: self.schedule(task, priority))
            return
        if self._dispatcher is None:
            self._dispatcher = self.effect_scheduler.make_dispatcher()
        outer, _binding.run = _binding.run, run
        try:
            self._dispatcher.schedule_task(task, priority)
        finally:
            _binding.run = outer

    def call_later(self, delay: Duration, task: Task, *, daemon: bool = False) -> Cancel:
        return self.run.call_later(delay, task, daemon=daemon)

    def track(self, tracker: WakeTracker, f: Callable[[], None]) -> None:
        self.run.track(tracker, f)

    def outside_work(self) -> WakeTracker:
        return self.run.outside_work()


class _Timer:
    __slots__ = ("alive", "daemon", "task", "when")

    def __init__(self, when: float, task: Task, *, daemon: bool = False) -> None:
        self.when = when
        self.task = task
        self.daemon = daemon
        self.alive = True

    def cancel(self) -> None:
        self.alive = False


def _merged(ready: deque[Task], prioritized: _PriorityBuckets | None) -> deque[Task]:
    """One batch: lower priorities, then priority 0, then higher ones."""
    if prioritized is None:
        return ready
    batch: deque[Task] = deque()
    placed = False
    for priority, tasks in prioritized.drain():
        if priority > 0 and not placed:
            batch.extend(ready)
            placed = True
        batch.extend(tasks)
    if not placed:
        batch.extend(ready)
    return batch


class StalledError(RuntimeError):
    """Every fiber is waiting and nothing can wake them up."""


class SyncScheduler(Tracking):
    """Runs tasks on the thread that calls ``run_until``."""

    def __init__(self) -> None:
        super().__init__()
        self._last_activity = time.monotonic()
        self._ready: deque[Task] = deque()
        self._prioritized: _PriorityBuckets | None = None
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

    def schedule(self, task: Task, priority: int = 0) -> None:
        task = self._tracked(task)
        with self._cond:
            if priority == 0:
                self._ready.append(task)
            else:
                self._prioritized = self._prioritized or _PriorityBuckets()
                self._prioritized.schedule_task(task, priority)
            self._last_activity = time.monotonic()
            self._cond.notify()

    def call_later(self, delay: Duration, task: Task, *, daemon: bool = False) -> Cancel:
        timer = _Timer(time.monotonic() + max(delay.to_seconds(), 0.0), task, daemon=daemon)
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
                if not self._ready and not self._prioritized:
                    self._cond.wait(self._wait_time(stall_timeout))
                    continue
                batch = self._take_batch()
            self._run_tasks(batch)
            if stall_timeout is not None:
                # The stall clock counts time with nothing running, not a long task or a
                # collector pause inside one.
                self._last_activity = time.monotonic()

    def flush(self) -> None:
        """Run what is ready, and what that schedules, without waiting or
        firing a timer: ``run_blocking``'s drain (Effect's ``dispatcher.flush``)."""
        driver, self._driver = self._driver, threading.get_ident()
        try:
            while self._ready or self._prioritized:
                with self._cond:
                    batch = self._take_batch()
                self._run_tasks(batch)
        finally:
            self._driver = driver

    def _take_batch(self) -> deque[Task]:
        """What is ready, in order; the caller holds the lock."""
        batch = self._ready
        self._ready = deque()
        if self._prioritized is None:
            return batch
        prioritized, self._prioritized = self._prioritized, None
        return _merged(batch, prioritized)

    def _run_tasks(self, batch: deque[Task]) -> None:
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


class SyncOnlyScheduler(SyncScheduler):
    """A scheduler that can run a ``run_sync``: flushed once, firing no timer,
    with nothing waiting on a loop, as ``MixedScheduler("sync")`` in
    ``runSync``, whose timers do fire but too late for the run. Each Effect
    fiber has its own dispatcher and ``runSync`` flushes its root's alone, so
    while one runs, what another fiber schedules waits for the next time the
    scheduler is driven: a child that yields is asynchronous."""

    def __init__(self) -> None:
        super().__init__()
        self.root: object = None
        self._held: list[tuple[Task, int]] = []

    def schedule(self, task: Task, priority: int = 0) -> None:
        if self.root is not None:
            from pyfect._fiber import current_fiber, current_run_scheduler

            if current_run_scheduler() is self and current_fiber() is not self.root:
                self._held.append((task, priority))
                return
        super().schedule(task, priority)

    def schedule_as_root(self, task: Task) -> None:
        """A task on the root's dispatcher, whichever fiber is running."""
        super().schedule(task)

    def flush_as(self, root: object) -> None:
        """``flush``, with ``root`` as the run's root fiber."""
        self.root = root
        try:
            self.flush()
        finally:
            self.root = None
            held, self._held = self._held, []
            for task, priority in held:
                super().schedule(task, priority)


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
        self._prioritized: _PriorityBuckets | None = None
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

    def schedule(self, task: Task, priority: int = 0) -> None:
        if threading.get_ident() != self._thread:
            self._call_soon_threadsafe(self.schedule, task, priority)
            return
        if priority == 0:
            self._ready.append(self._tracked(task))
        else:
            self._prioritized = self._prioritized or _PriorityBuckets()
            self._prioritized.schedule_task(self._tracked(task), priority)
        self._drain_soon()

    def _call_soon_threadsafe(self, f: Callable[..., None], *args: object) -> None:
        try:
            self._loop.call_soon_threadsafe(f, *args)
        except RuntimeError:
            if not self._loop.is_closed():
                raise
            raise LoopClosedError("the asyncio loop this fiber runs on has closed") from None

    def call_later(self, delay: Duration, task: Task, *, daemon: bool = False) -> Cancel:
        return self._loop.call_later(max(delay.to_seconds(), 0.0), task).cancel

    def _drain_soon(self) -> None:
        if not self._draining_scheduled:
            self._draining_scheduled = True
            self._loop.call_soon(self._drain)

    def _drain(self) -> None:
        # Run only what was queued before this tick so asyncio callbacks
        # (I/O, other tasks) are never starved by a busy fiber.
        self._draining_scheduled = False
        if self._prioritized is not None:
            self._ready = _merged(self._ready, self._prioritized)
            self._prioritized = None
        try:
            for _ in range(len(self._ready)):
                self._ready.popleft()()
        finally:
            # Also when a task raised (Ctrl-C): what is left still runs.
            if self._ready or self._prioritized:
                self._drain_soon()


__all__ = [
    "AsyncioScheduler",
    "BoundScheduler",
    "Cancel",
    "CurrentScheduler",
    "EffectScheduler",
    "ExecutionMode",
    "LoopClosedError",
    "MaxOpsBeforeYield",
    "MixedScheduler",
    "PreventSchedulerYield",
    "Scheduler",
    "SchedulerDispatcher",
    "StalledError",
    "SyncOnlyScheduler",
    "SyncScheduler",
    "Task",
]
