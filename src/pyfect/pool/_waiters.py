"""The line of borrowers waiting for a pool item.

A waiter is woken to retry, or handed an acquisition failure; it stays in
line until it takes an item or leaves, so a woken waiter keeps its place
and later borrowers queue behind it. As in Effect, waking runs in one task
scheduled on the waking fiber's scheduler, and each woken fiber runs at
once (resumes are synchronous), so whatever it does, such as interrupting
the waiter behind it, happens before the next waiter is woken.
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

        def wake() -> None:
            # The live line: a waiter that leaves meanwhile uses up no wake.
            remaining = count
            for waiter in list(self._line):
                if remaining <= 0 or not available():
                    break
                if waiter in self._line and waiter.is_sleeping:
                    remaining -= 1
                    waiter()

        scheduler.schedule(wake)

    def wake_all(self, scheduler: Scheduler) -> None:
        """Wake everyone in line now to retry (Effect's ``wakeAll``)."""
        if not self._line:
            return

        def wake() -> None:
            for waiter in list(self._line):
                waiter()

        scheduler.schedule(wake)

    def release_all(self) -> None:
        """Empty the line, waking everyone at once (the pool shuts down)."""
        waiters = list(self._line)
        self._line.clear()
        for waiter in waiters:
            waiter()
