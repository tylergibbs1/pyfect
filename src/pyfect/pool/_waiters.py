"""The line of borrowers waiting for a pool item.

A waiter is woken to retry, or handed an acquisition failure; it stays in
line until it takes an item or leaves, so a woken waiter keeps its place
and later borrowers queue behind it. As in Effect, waking runs in one task
scheduled on the waking fiber's scheduler, and each woken fiber runs at
once (resumes are synchronous), so whatever it does, such as interrupting
the waiter behind it, happens before the next waiter is woken.

Runs on other threads share a pool. The line belongs to the pool's lock:
call it holding the lock. A woken borrower of the run on this thread runs at
once and comes back for the lock, so a waiter is woken with the lock let go.
A borrower of another run is woken at once, not in the task: its wake goes
through its own run, and the waking run may end before running its tasks.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from pyfect._core import WOKEN, Effect
from pyfect._waiters import Lock, of_this_run, unlocked
from pyfect.scheduler import Scheduler

if TYPE_CHECKING:
    from pyfect._fiber import Fiber

type Resume = Callable[[Effect[None, Any]], None]


class Waiter:
    """One parked borrower. Calling it wakes the borrower (or hands it
    ``failure``); a borrower already woken is not woken again."""

    __slots__ = ("fiber", "resume")

    def __init__(self) -> None:
        self.resume: Resume | None = None
        # The parked fiber, while asleep.
        self.fiber: Fiber[Any, Any] | None = None

    def __call__(self, failure: Effect[None, Any] | None = None) -> None:
        wake = self.take(failure)
        if wake is not None:
            wake()

    def take(self, failure: Effect[None, Any] | None = None) -> Callable[[], None] | None:
        """Mark the waiter woken (holding the pool's lock); the call that
        resumes it, to make once the lock is let go."""
        resume = self.resume
        if resume is None:
            return None
        self.resume = None
        result = WOKEN if failure is None else failure
        return lambda: resume(result)

    @property
    def is_sleeping(self) -> bool:
        return self.resume is not None


class PoolWaiters:
    """The waiters in arrival order."""

    __slots__ = ("_line", "_lock")

    def __init__(self, lock: Lock) -> None:
        self._lock = lock
        self._line: dict[Waiter, None] = {}

    def __len__(self) -> int:
        return len(self._line)

    def __contains__(self, waiter: Waiter) -> bool:
        return waiter in self._line

    def is_next(self, waiter: Waiter) -> bool:
        """Whether ``waiter`` may take an available item now: a newcomer
        only when the line is empty; a waiter in line (woken, retrying)
        once nobody asleep is ahead of it, as the wake-ups that came while
        it was awake skipped it."""
        if waiter not in self._line:
            return not self._line
        for other in self._line:
            if other is waiter:
                return True
            if other.is_sleeping:
                return False
        return True

    def park(self, waiter: Waiter, resume: Resume, fiber: Fiber[Any, Any] | None) -> None:
        """Sleep until woken. A waiter already in line keeps its place."""
        waiter.resume = resume
        waiter.fiber = fiber
        self._line[waiter] = None

    def cancel(self, waiter: Waiter) -> None:
        """The waiter was interrupted. Asleep, it leaves at once, so no wake
        is spent on it; once woken, it stays until it passes the wake on."""
        if waiter.is_sleeping:
            waiter.resume = None
            del self._line[waiter]

    def leave(self, waiter: Waiter) -> bool:
        """Take ``waiter`` out of line; whether it was in it."""
        if waiter not in self._line:
            return False
        del self._line[waiter]
        return True

    @property
    def sleeping(self) -> int:
        """How many waiters are asleep; a woken one about to retry is not counted."""
        return sum(1 for w in self._line if w.is_sleeping)

    def first_sleeping(self) -> Waiter | None:
        return next((w for w in self._line if w.is_sleeping), None)

    def wake(self, scheduler: Scheduler, count: int, available: Callable[[], bool]) -> None:
        """Wake up to ``count`` sleeping waiters, in order, while
        ``available()`` holds (Effect's ``wakeWaiters``)."""
        if not self._line:
            return
        remaining = count - self._wake_other_runs(count, available)

        def wake() -> None:
            # The live line: a waiter that leaves meanwhile uses up no wake.
            left = remaining
            with self._lock:
                for waiter in list(self._line):
                    if left <= 0 or not available():
                        break
                    if waiter in self._line and waiter.is_sleeping:
                        left -= 1
                        unlocked(self._lock, [waiter.take() or _nothing])

        scheduler.schedule(wake)

    def _wake_other_runs(self, count: int, available: Callable[[], bool]) -> int:
        """Wake the waiters of other runs among the first ``count`` asleep;
        how many."""
        if not available():
            return 0
        picked = [w for w in self._line if w.is_sleeping][:count]
        wakes = [w.take() or _nothing for w in picked if not of_this_run(w.fiber)]
        unlocked(self._lock, wakes)
        return len(wakes)

    def wake_all(self, scheduler: Scheduler) -> None:
        """Wake everyone in line now to retry (Effect's ``wakeAll``)."""
        if not self._line:
            return
        self._wake_other_runs(len(self._line), lambda: True)

        def wake() -> None:
            with self._lock:
                for waiter in list(self._line):
                    unlocked(self._lock, [waiter.take() or _nothing])

        scheduler.schedule(wake)

    def release_all(self) -> None:
        """Empty the line, waking everyone at once (the pool shuts down)."""
        wakes = [waiter.take() or _nothing for waiter in self._line]
        self._line.clear()
        unlocked(self._lock, wakes)


def _nothing() -> None:
    pass
