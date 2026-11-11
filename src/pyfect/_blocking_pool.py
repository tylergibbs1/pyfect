"""The threads ``fx.blocking`` runs on.

Effect has no thread pool (Node runs such work on libuv's), so this follows
Python's norms for work a program may abandon: daemon threads, started as work
arrives beyond the idle ones (up to ``ThreadPoolExecutor``'s default count), each
exiting after ``idle`` with nothing to do. Interrupting ``blocking`` abandons its
thread, and a daemon thread does not hold the process open at exit, where a
``ThreadPoolExecutor`` worker would be joined for ever.
"""

from __future__ import annotations

import os
import threading
from collections import deque
from collections.abc import Callable
from concurrent.futures import Future
from typing import Any

from pyfect.duration import Input, to_seconds


class BlockingPool:
    """Runs thunks on daemon threads that exit when idle."""

    __slots__ = ("_idle_seconds", "_idle_threads", "_lock", "_max", "_name", "_work", "threads")

    def __init__(self, *, max_workers: int, idle: Input, name: str) -> None:
        self._max = max_workers
        self._idle_seconds = to_seconds(idle)
        self._name = name
        self._lock = threading.Condition()
        self._work: deque[tuple[Callable[[], Any], Future[Any]]] = deque()
        self._idle_threads = 0
        self.threads = 0
        """Threads alive now."""

    def submit[A](self, thunk: Callable[[], A]) -> Future[A]:
        """Run ``thunk`` on an idle thread, or a new one while under the
        limit, or the next to free up."""
        future: Future[A] = Future()
        with self._lock:
            self._work.append((thunk, future))
            start = len(self._work) > self._idle_threads and self.threads < self._max
            if start:
                self.threads += 1
            else:
                self._lock.notify()
        if start:
            name = f"{self._name}-{id(future):x}"
            threading.Thread(target=self._worker, name=name, daemon=True).start()
        return future

    def _next(self) -> tuple[Callable[[], Any], Future[Any]] | None:
        with self._lock:
            while not self._work:
                self._idle_threads += 1
                woken = self._lock.wait(self._idle_seconds)
                self._idle_threads -= 1
                if not woken and not self._work:
                    self.threads -= 1
                    return None
            return self._work.popleft()

    def _worker(self) -> None:
        while (item := self._next()) is not None:
            thunk, future = item
            if not future.set_running_or_notify_cancel():
                continue
            try:
                result = thunk()
            except BaseException as error:  # the future carries it to the fiber
                future.set_exception(error)
            else:
                future.set_result(result)
            del thunk, future, item


def _make() -> BlockingPool:
    return BlockingPool(
        max_workers=min(32, (os.process_cpu_count() or 1) + 4),
        idle="10 seconds",
        name="pyfect-blocking",
    )


class _Shared:
    pool = _make()


def _reset_after_fork() -> None:
    # A forked child has none of the parent's threads.
    _Shared.pool = _make()


if hasattr(os, "register_at_fork"):
    os.register_at_fork(after_in_child=_reset_after_fork)


def pool() -> BlockingPool:
    """The process's pool."""
    return _Shared.pool
