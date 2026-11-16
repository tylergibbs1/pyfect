"""The most memory a piece of work holds at once, for inputs a peer chooses: the one helper
for tests that bound it to a few bytes per input byte.

``re`` keeps one backtrack frame per iteration of a repeated group it may have to undo, and
``tracemalloc`` sees those frames where a timer only sees a constant factor. The peak counts
what the work allocates and still holds (its result included), not what was allocated
before it started.
"""

from __future__ import annotations

import gc
import tracemalloc
from collections.abc import Callable
from dataclasses import dataclass

PER_BYTE = 4
"""Bytes of peak memory allowed per input byte: room for the input's encoded copy, the
result and its text, not for anything kept per repetition."""
SLACK = 1 << 16
"""Fixed allocations (a few objects, a compiled pattern's state) that do not grow."""

type Work = Callable[[], object]


@dataclass(frozen=True, slots=True)
class Peak:
    size: int
    peak: int

    def __str__(self) -> str:
        return (
            f"peak {self.peak / 1e6:.1f} MB ({self.peak / max(self.size, 1):.1f} per input "
            f"byte) for a {self.size / 1e6:.2f} MB input"
        )


def peak(work: Work, size: int) -> Peak:
    """The peak memory ``work`` traced, for an input of ``size`` bytes."""
    gc.collect()
    tracemalloc.start()
    try:
        work()
        _, most = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return Peak(size, most)


def assert_bounded_memory(work: Work, size: int, per_byte: int = PER_BYTE) -> None:
    """``work`` on a ``size``-byte input holds at most ``per_byte`` bytes per input byte."""
    found = peak(work, size)
    assert found.peak <= per_byte * size + SLACK, f"{found}: over {per_byte} per input byte"
