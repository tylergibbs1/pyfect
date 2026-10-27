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
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import contextlib
from collections import deque
from collections.abc import Callable

from pyfect._core import Effect, _Callback, _Succeed, _Sync


class _Waiter:
    __slots__ = ("ready", "wake")

    def __init__(self, ready: Callable[[], bool], wake: Callable[[], None]) -> None:
        self.ready = ready
        self.wake = wake


class WaitList:
    __slots__ = ("_waiters",)

    def __init__(self) -> None:
        self._waiters: deque[_Waiter] = deque()

    def wait(self, ready: Callable[[], bool]) -> Effect[None]:
        """Park until notified, or not at all if ``ready()`` already holds."""

        def register(resume: Callable[[Effect[None]], None]) -> Effect[None] | None:
            if ready():
                resume(_Succeed(None))
                return None

            waiter = _Waiter(ready, lambda: resume(_Succeed(None)))
            self._waiters.append(waiter)
            return _Sync(lambda: self._discard(waiter))

        return _Callback(register)

    def notify_ready(self) -> None:
        """Wake every waiter whose condition holds now."""
        ready: list[_Waiter] = []
        parked: deque[_Waiter] = deque()
        for waiter in self._waiters:
            (ready if waiter.ready() else parked).append(waiter)
        self._waiters = parked
        for waiter in ready:
            waiter.wake()

    def notify_all(self) -> None:
        waiters, self._waiters = self._waiters, deque()
        for waiter in waiters:
            waiter.wake()

    def __len__(self) -> int:
        return len(self._waiters)

    def _discard(self, waiter: _Waiter) -> None:
        with contextlib.suppress(ValueError):
            self._waiters.remove(waiter)
