"""Waiting on the operating system without blocking a fiber.

Threads watch a child process: one waits for it to exit and one per pipe
reads or writes when a fiber asks. Each wait has a thread of its own: a
shared, bounded pool would let waits that depend on each other (the two
writes of a pipeline) queue behind each other for good. A
fiber waiting for them suspends in ``pyfect._os_wait.os_wait``.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Never

from pyfect._core import Effect
from pyfect._os_wait import Cancel, Resume, os_wait
from pyfect.effect import succeed


class Latch[A]:
    """A value set once, from any thread, that fibers wait for."""

    __slots__ = ("_callbacks", "_lock", "_value", "_waiters")

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._value: tuple[A] | None = None
        self._waiters: list[Resume[A, Never]] = []
        self._callbacks: list[Callable[[], None]] = []

    def set(self, value: A) -> None:
        with self._lock:
            if self._value is not None:
                return
            self._value = (value,)
            waiters, self._waiters = self._waiters, []
            callbacks, self._callbacks = self._callbacks, []
        for call in callbacks:
            call()
        for resume in waiters:
            resume(succeed(value))

    def on_set(self, call: Callable[[], None]) -> None:
        """Run ``call`` once set: on the setting thread, or now if already
        set."""
        with self._lock:
            pending = self._value is None
            if pending:
                self._callbacks.append(call)
        if not pending:
            call()

    def get(self) -> tuple[A] | None:
        """``(value,)`` once set, else ``None``."""
        return self._value

    def wait(self) -> Effect[A]:
        def register(resume: Resume[A, Never]) -> Cancel | None:
            with self._lock:
                value = self._value
                if value is None:
                    self._waiters.append(resume)
            if value is not None:
                resume(succeed(value[0]))
                return None
            return lambda: self._forget(resume)

        return os_wait(register)

    def _forget(self, resume: Resume[A, Never]) -> None:
        with self._lock:
            if resume in self._waiters:
                self._waiters.remove(resume)
