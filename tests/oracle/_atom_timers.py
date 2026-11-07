"""Fake timers for the ports of Effect's reactivity tests (vitest's
``useFakeTimers``): a scheduler whose queued tasks run on ``flush()`` and
whose timers fire on ``advance(ms)``, with ``Date.now`` (``time.time_ns``
as the atoms read it) following its virtual clock.

``flush()`` is ``await Effect.runPromise(Effect.yieldNow)``;
``advance(ms)`` is ``await vitest.advanceTimersByTimeAsync(ms)``.
"""

import heapq
import itertools
from collections import deque
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

import pytest

from pyfect._wake_tracking import Tracking
from pyfect.duration import Seconds, nanos_or_infinite
from pyfect.reactivity import _time, atom_registry
from pyfect.reactivity.atom_registry import AtomRegistryService, InitialValue
from pyfect.scheduler import Cancel, Task

_START_NS = 1_700_000_000_000 * 1_000_000


class FakeTimers(Tracking):
    def __init__(self) -> None:
        super().__init__()
        self.now_ns = _START_NS
        self._ready: deque[Task] = deque()
        self._timers: list[tuple[float, int, list[Task | None]]] = []
        self._seq = itertools.count()

    def runs_here(self) -> bool:
        return True

    def time_ns(self) -> int:
        return self.now_ns

    def schedule(self, task: Task, priority: int = 0) -> None:
        self._ready.append(self._tracked(task))

    def call_later(self, delay: Seconds, task: Task, *, daemon: bool = False) -> Cancel:
        entry: list[Task | None] = [task]
        heapq.heappush(
            self._timers, (self.now_ns + nanos_or_infinite(delay), next(self._seq), entry)
        )

        def cancel() -> None:
            entry[0] = None

        return cancel

    def flush(self) -> None:
        while self._ready:
            self._ready.popleft()()

    def advance(self, ms: float) -> None:
        target = self.now_ns + int(ms * 1_000_000)
        self.flush()
        while self._timers and self._timers[0][0] <= target:
            due, _, entry = heapq.heappop(self._timers)
            task = entry[0]
            if task is None:
                continue
            self.now_ns = max(self.now_ns, int(due))
            task()
            self.flush()
        self.now_ns = target
        self.flush()

    def registry(
        self,
        *,
        initial_values: list[InitialValue[Any]] | None = None,
        default_idle_ttl: float | None = None,
        timeout_resolution: float | None = None,
    ) -> AtomRegistryService:
        """``AtomRegistry.make(...)`` on these timers (durations in
        seconds)."""
        return atom_registry.make(
            initial_values=initial_values,
            scheduler=self,
            default_idle_ttl=None if default_idle_ttl is None else Seconds(default_idle_ttl),
            timeout_resolution=None if timeout_resolution is None else Seconds(timeout_resolution),
        )


@pytest.fixture
def timers(monkeypatch: pytest.MonkeyPatch) -> FakeTimers:
    fake = FakeTimers()
    monkeypatch.setattr(_time, "time", SimpleNamespace(time_ns=fake.time_ns))
    return fake


def counting[A](f: Callable[[A], Any] | None = None) -> tuple[list[A], Callable[[A], None]]:
    """A listener that records what it is called with."""
    seen: list[A] = []

    def listener(value: A) -> None:
        seen.append(value)
        if f is not None:
            f(value)

    return seen, listener
