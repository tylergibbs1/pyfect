"""A list of parked fibers waiting for a state change.

Waiters are woken to *retry*, never handed a value: whatever they wait
for is taken in their own step. That way an interrupt that lands between
the wake-up and the retry cannot lose anything. Spurious wake-ups are
harmless: a woken fiber that finds nothing simply waits again.

``wait`` takes the condition the caller is waiting for and checks it again as
the fiber parks: a fiber can pause between its own check and the park, and a
notify landing in that gap would otherwise find nobody to wake. The list keeps
the condition, and ``notify_ready`` wakes every waiter whose condition holds,
as Effect's ``releaseTakers`` does. There is no "wake exactly one": a woken
fiber can pause for its step budget before it retries and be interrupted
there, and a wake-up spent on it would leave the waiter behind it parked next
to the item it was waiting for.

A wake-up resumes the fiber at once (fibers resume synchronously, as in
Effect). Where Effect defers it to a scheduled task instead (a queue's
``scheduleReleaseTaker``, a semaphore release), use ``notify_ready_soon``
or ``wake_soon_from_here``, so the notifier finishes its step first.

Runs on other threads share these lists. A list belongs to a primitive and
takes its lock: ``wait`` checks and registers holding it, the notifiers are
called holding it and let it go while they wake fibers, since a woken fiber
of the run on this thread runs at once and may come back for the lock. A
deferred wake of a fiber of another run goes to that run at once rather
than to a task here: the notifier's run may end before running its tasks.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import contextlib
import threading
from collections import deque
from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pyfect._core import Effect, _Callback, _Succeed, _Sync

if TYPE_CHECKING:
    from pyfect._fiber import Fiber
    from pyfect.scheduler import Scheduler

type Lock = threading.Lock
"""A primitive's lock: held only while reading and changing its own fields."""


class _Waiter:
    __slots__ = ("fiber", "ready", "wake")

    def __init__(
        self, ready: Callable[[], bool], wake: Callable[[], None], fiber: Fiber[Any, Any] | None
    ) -> None:
        self.ready = ready
        self.wake = wake
        self.fiber = fiber


def unlocked(lock: Lock, wakes: list[Callable[[], None]]) -> None:
    """Call ``wakes`` with ``lock``, which the caller holds, let go meanwhile: a woken
    fiber of the run on this thread runs at once and may take it."""
    if not wakes:
        return
    lock.release()
    try:
        for wake in wakes:
            wake()
    finally:
        lock.acquire()


def of_this_run(fiber: Fiber[Any, Any] | None) -> bool:
    """Whether ``fiber`` belongs to the run of the fiber running on this thread."""
    from pyfect._fiber import current_run_scheduler

    return fiber is not None and fiber._run_scheduler is current_run_scheduler()


def wake_soon_from_here(waiter: Fiber[Any, Any] | None, task: Callable[[], None]) -> None:
    """``wake_soon(task)`` for a wake-up of ``waiter``, if it belongs to the run of the
    fiber running here; otherwise ``task`` in a task of ``waiter``'s own run."""
    if waiter is None or of_this_run(waiter):
        wake_soon(task)
    else:
        waiter._scheduler.schedule(task)


def wake_soon(task: Callable[[], None]) -> None:
    """Run ``task`` in a task scheduled on the running fiber's scheduler
    (Effect's ``fiber.currentDispatcher.scheduleTask``), or now when no
    fiber is running here."""
    from pyfect._fiber import current_fiber

    fiber = current_fiber()
    if fiber is None:
        task()
    else:
        fiber.dispatcher().schedule(task)


class WaitList:
    """Fibers waiting on ``lock``'s primitive. Call the notifiers holding ``lock``."""

    __slots__ = ("_lock", "_soon", "_waiters")

    def __init__(self, lock: Lock) -> None:
        self._lock = lock
        self._waiters: deque[_Waiter] = deque()
        # Whether a ``notify_ready_soon`` task is pending.
        self._soon = False  # pragma: no mutate, falsy either way

    def wait(self, ready: Callable[[], bool]) -> Effect[None]:
        """Park until notified, or not at all if ``ready()`` already holds."""

        def register(resume: Callable[[Effect[None]], None]) -> Effect[None] | None:
            from pyfect._fiber import current_fiber

            with self._lock:
                if ready():
                    resume(_Succeed(None))
                    return None
                waiter = _Waiter(ready, lambda: resume(_Succeed(None)), current_fiber())
                self._waiters.append(waiter)
            return _Sync(lambda: self._discard(waiter))

        return _Callback(register)

    def notify_ready(self) -> None:
        """Wake every waiter whose condition holds now."""
        unlocked(self._lock, [waiter.wake for waiter in self._take(lambda _: True)])

    def _take(self, which: Callable[[_Waiter], bool]) -> list[_Waiter]:
        """Take out the waiters ``which`` picks whose condition holds now."""
        ready: list[_Waiter] = []
        parked: deque[_Waiter] = deque()
        for waiter in self._waiters:
            # pragma: no mutate, wakes retry
            (ready if which(waiter) and waiter.ready() else parked).append(waiter)
        self._waiters = parked
        return ready

    def notify_ready_soon(self, scheduler: Scheduler | None = None) -> None:
        """``notify_ready`` in a task on ``scheduler``, else as ``wake_soon``;
        several calls before it runs share it, as Effect's
        ``scheduleReleaseTaker``. Waiters of other runs are woken now, through
        their own runs."""
        if not self._waiters:
            return
        foreign = self._take(lambda waiter: not of_this_run(waiter.fiber))
        unlocked(self._lock, [waiter.wake for waiter in foreign])
        if self._soon or not self._waiters:
            return
        self._soon = True

        def flush() -> None:
            with self._lock:
                self._soon = False  # pragma: no mutate, falsy either way
                self.notify_ready()

        if scheduler is not None:
            scheduler.schedule(flush)
            return
        from pyfect._fiber import current_fiber
        from pyfect.scheduler import SyncOnlyScheduler

        fiber = current_fiber()
        if fiber is None:
            # No fiber runs here to wait for, as ``wake_soon``: now.
            self._soon = False  # pragma: no mutate, falsy either way
            self.notify_ready()
        elif isinstance(fiber._scheduler, SyncOnlyScheduler):
            # Effect's queue holds the dispatcher of the fiber that made it,
            # whichever fiber offers: under a ``run_sync`` the root flushes it.
            fiber._scheduler.schedule_as_root(flush)
        else:
            fiber.dispatcher().schedule(flush)

    def notify_all(self) -> None:
        waiters, self._waiters = self._waiters, deque()
        unlocked(self._lock, [waiter.wake for waiter in waiters])

    def __len__(self) -> int:
        return len(self._waiters)

    def _discard(self, waiter: _Waiter) -> None:
        with self._lock, contextlib.suppress(ValueError):
            self._waiters.remove(waiter)
