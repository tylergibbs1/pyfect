"""A ``Mailbox``: items put from any thread, taken in order by a fiber.

The threads of a worker's transport (a reader, another runtime's
scheduler) put what arrives; one fiber takes it, so everything a worker
receives is handled on its runtime's own thread. A waiting take suspends
in ``os_wait``; a put wakes it to retry, never handing it the item.
"""

from __future__ import annotations

import threading
from collections import deque
from typing import Never

from pyfect._core import Effect
from pyfect.effect import succeed, suspend
from pyfect.process._os import Cancel, Resume, os_wait


class Mailbox[A]:
    __slots__ = ("_items", "_lock", "_waiters")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._items: deque[A] = deque()
        self._waiters: list[Resume[A, Never]] = []

    def put(self, item: A) -> None:
        with self._lock:
            self._items.append(item)
            waiters, self._waiters = self._waiters, []
        for resume in waiters:
            resume(suspend(self.take))

    def take(self) -> Effect[A]:
        def register(resume: Resume[A, Never]) -> Cancel | None:
            with self._lock:
                taken = (self._items.popleft(),) if self._items else None
                if taken is None:
                    self._waiters.append(resume)
            if taken is not None:
                resume(succeed(taken[0]))
                return None
            return lambda: self._forget(resume)

        return os_wait(register)

    def _forget(self, resume: Resume[A, Never]) -> None:
        with self._lock:
            if resume in self._waiters:
                self._waiters.remove(resume)
