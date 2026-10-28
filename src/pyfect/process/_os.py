"""Waiting on the operating system without blocking a fiber.

Threads watch a child process: one waits for it to exit and one per pipe
reads or writes when a fiber asks. Each wait has a thread of its own: a
shared, bounded pool would let waits that depend on each other (the two
writes of a pipeline) queue behind each other for good. A
fiber waiting for them suspends in ``os_wait`` and the thread resumes it
through the scheduler. While it waits, a timer stays pending on the
fiber's scheduler, so a synchronous run (a test's stall detection
included) knows the wait is outside work, not a deadlock.
"""

from __future__ import annotations

import threading
from collections.abc import Callable
from typing import Never

from pyfect._core import Effect
from pyfect.duration import Seconds
from pyfect.effect import callback, succeed, sync
from pyfect.scheduler import CurrentScheduler, Scheduler

type Resume[A, E] = Callable[[Effect[A, E]], None]
type Cancel = Callable[[], None]
type Register[A, E] = Callable[[Resume[A, E]], Cancel | None]

_KEEPALIVE = Seconds(0.25)
"""How often a waiting fiber's timer fires; below the test runtime's
one-second stall timeout."""


class _Waiting:
    __slots__ = ("active",)

    def __init__(self) -> None:
        self.active = True


def os_wait[A, E](register: Register[A, E]) -> Effect[A, E]:
    """Suspend until ``register``'s ``resume`` is called, from any thread.
    ``register`` runs on the fiber's thread and may resume at once; the
    cancel function it returns runs if the fiber is interrupted first."""
    return CurrentScheduler().flat_map(lambda scheduler: callback(_registered(scheduler, register)))


def _registered[A, E](
    scheduler: Scheduler, register: Register[A, E]
) -> Callable[[Resume[A, E]], Effect[None] | None]:
    def start(resume: Resume[A, E]) -> Effect[None] | None:
        waiting = _Waiting()

        def beat() -> None:
            if waiting.active:
                scheduler.call_later(_KEEPALIVE, beat)

        def finish(effect: Effect[A, E]) -> None:
            waiting.active = False
            resume(effect)

        cancel = register(finish)
        if not waiting.active:
            return None
        scheduler.call_later(_KEEPALIVE, beat)

        def interrupted() -> None:
            waiting.active = False
            if cancel is not None:
                cancel()

        return sync(interrupted)

    return start


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
