"""The line of borrowers waiting for a pool item.

A waiter is woken to retry, or handed an acquisition failure; it stays in
line until it takes an item or leaves, so a woken waiter keeps its place
and later borrowers queue behind it. Waking goes one waiter per scheduler
task: in Effect a woken fiber runs inside the wake (its resume is
synchronous), so whatever it does, such as interrupting the waiter behind
it, happens before the next waiter is woken.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect._core import Effect, _Succeed
from pyfect.scheduler import Scheduler

_VOID: Effect[None] = _Succeed(None)

type Resume = Callable[[Effect[None, Any]], None]


class Waiter:
    """One parked borrower. Calling it wakes the borrower (or hands it
    ``failure``); a borrower already woken is not woken again."""

    __slots__ = ("resume",)

    def __init__(self) -> None:
        self.resume: Resume | None = None

    def __call__(self, failure: Effect[None, Any] | None = None) -> None:
        resume = self.resume
        if resume is None:
            return
        self.resume = None
        resume(_VOID if failure is None else failure)

    @property
    def is_sleeping(self) -> bool:
        return self.resume is not None


class PoolWaiters:
    """The waiters in arrival order."""

    __slots__ = ("_line",)

    def __init__(self) -> None:
        self._line: dict[Waiter, None] = {}

    def __len__(self) -> int:
        return len(self._line)

    def __contains__(self, waiter: Waiter) -> bool:
        return waiter in self._line

    def park(self, waiter: Waiter, resume: Resume) -> None:
        """Sleep until woken. A waiter already in line keeps its place."""
        waiter.resume = resume
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

    def first_sleeping(self) -> Waiter | None:
        return next((w for w in self._line if w.is_sleeping), None)

    def wake(self, scheduler: Scheduler, count: int, available: Callable[[], bool]) -> None:
        """Wake up to ``count`` sleeping waiters, in order, while
        ``available()`` holds."""
        if not self._line:
            return

        def wake(remaining: int) -> None:
            waiter = self.first_sleeping() if available() else None
            if waiter is None:
                return
            waiter()
            if remaining > 1:
                scheduler.schedule(lambda: wake(remaining - 1))

        scheduler.schedule(lambda: wake(count))

    def wake_all(self, scheduler: Scheduler) -> None:
        """Wake everyone in line now to retry."""
        waiters = list(self._line)
        if not waiters:
            return

        def wake(index: int) -> None:
            waiters[index]()
            if index + 1 < len(waiters):
                scheduler.schedule(lambda: wake(index + 1))

        scheduler.schedule(lambda: wake(0))

    def release_all(self) -> None:
        """Empty the line, waking everyone at once (the pool shuts down)."""
        waiters = list(self._line)
        self._line.clear()
        for waiter in waiters:
            waiter()
