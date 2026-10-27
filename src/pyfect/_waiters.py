"""A list of parked fibers waiting for a state change.

Waiters are woken to *retry*, never handed a value: whatever they wait
for is taken in their own step. That way an interrupt that lands between
the wake-up and the retry cannot lose anything. A woken fiber that is
interrupted before retrying passes the wake-up on, so nobody sleeps
through available work. Spurious wake-ups are harmless: a woken fiber that
finds nothing simply waits again.

``wait`` takes the condition the caller is waiting for and checks it again as
the fiber parks: a fiber can pause between its own check and the park, and a
notify landing in that gap would otherwise find nobody to wake.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import contextlib
from collections import deque
from collections.abc import Callable

from pyfect._core import Effect, _Callback, _Succeed, _Sync


class WaitList:
    __slots__ = ("_waiters",)

    def __init__(self) -> None:
        self._waiters: deque[Callable[[], None]] = deque()

    def wait(self, ready: Callable[[], bool]) -> Effect[None]:
        """Park until notified, or not at all if ``ready()`` already holds."""

        def register(resume: Callable[[Effect[None]], None]) -> Effect[None] | None:
            if ready():
                resume(_Succeed(None))
                return None

            def wake() -> None:
                resume(_Succeed(None))

            self._waiters.append(wake)
            return _Sync(lambda: self._discard(wake))

        return _Callback(register).on_interrupt(_Sync(self.notify_one))

    def notify_one(self) -> None:
        if self._waiters:
            self._waiters.popleft()()

    def notify_all(self) -> None:
        waiters, self._waiters = self._waiters, deque()
        for wake in waiters:
            wake()

    def __len__(self) -> int:
        return len(self._waiters)

    def _discard(self, wake: Callable[[], None]) -> None:
        with contextlib.suppress(ValueError):
            self._waiters.remove(wake)
