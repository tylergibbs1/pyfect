"""Timers in deadline order that let go of a cancelled one at once.

Cancelling an entry drops its value, so whatever the timer would have run (a fiber's
resume and all it holds) is free before the deadline, as with ``clearTimeout``; once
cancelled entries are most of the heap, they are swept out, as asyncio does with
cancelled handles. Every timer heap in pyfect is one of these
(``tests/test_cancelled_timers.py``).
"""

from __future__ import annotations

import heapq
import itertools
from collections.abc import Iterator

_SWEEP_MIN = 64
"""Fewer cancelled entries than this are never swept: popping them is cheaper."""


class TimerEntry[T]:
    """A pushed timer. ``owner`` and ``value`` become ``None`` once it fires or is
    cancelled."""

    __slots__ = ("owner", "value", "when")

    def __init__(self, owner: TimerHeap[T], when: float, value: T) -> None:
        self.owner: TimerHeap[T] | None = owner
        self.value: T | None = value
        self.when = when

    def cancel(self) -> None:
        """Drop the entry and its value; nothing once it fired or was cancelled."""
        owner, self.owner, self.value = self.owner, None, None
        if owner is not None:
            owner.cancelled_one()


class TimerHeap[T]:
    """Not thread safe: its owner serializes ``push``, ``pop`` and ``cancel``."""

    __slots__ = ("_cancelled", "_entries", "_seq")

    def __init__(self) -> None:
        self._entries: list[tuple[float, int, TimerEntry[T]]] = []
        self._seq = itertools.count()
        self._cancelled = 0

    def push(self, when: float, value: T) -> TimerEntry[T]:
        entry = TimerEntry(self, when, value)
        heapq.heappush(self._entries, (when, next(self._seq), entry))
        return entry

    def _drop_cancelled_top(self) -> None:
        while self._entries and self._entries[0][2].owner is None:
            heapq.heappop(self._entries)
            self._cancelled -= 1

    def next_due(self) -> float | None:
        """The earliest deadline of an entry not cancelled."""
        self._drop_cancelled_top()
        return self._entries[0][0] if self._entries else None

    def pop(self) -> tuple[float, T] | None:
        """The earliest entry not cancelled, taken out of the heap."""
        self._drop_cancelled_top()
        if not self._entries:
            return None
        when, _, entry = heapq.heappop(self._entries)
        value = entry.value
        entry.owner = entry.value = None
        assert value is not None
        return when, value

    def pop_due(self, now: float) -> list[T]:
        """Every entry due by ``now``, earliest first."""
        due: list[T] = []
        while (when := self.next_due()) is not None and when <= now:
            popped = self.pop()
            assert popped is not None
            due.append(popped[1])
        return due

    def values(self) -> Iterator[T]:
        """The values of every entry not cancelled, in no particular order."""
        for _, _, entry in self._entries:
            if entry.value is not None:
                yield entry.value

    def __len__(self) -> int:
        return len(self._entries) - self._cancelled

    def __bool__(self) -> bool:
        return len(self) > 0

    def size_with_cancelled(self) -> int:
        """Entries held, cancelled ones not yet swept out included."""
        return len(self._entries)

    def cancelled_one(self) -> None:
        """Called by an entry of this heap as it is cancelled."""
        self._cancelled += 1
        if self._cancelled >= _SWEEP_MIN and self._cancelled * 2 > len(self._entries):
            self._entries = [e for e in self._entries if e[2].owner is not None]
            heapq.heapify(self._entries)
            self._cancelled = 0
