"""How a parser's cost grows with its input, for inputs a peer chooses.

A parser that copies its buffer on every token, rescans what it already read, or appends to a
string attribute takes time quadratic in input a peer controls (CPython's in-place ``str +=``
only applies to a local variable; JavaScript's ropes, which Effect relies on, make the same
code linear there). ``growth`` measures a piece of work at a size and at ``FACTOR`` times it:
linear work grows ``FACTOR`` times, ``n log n`` a little more, quadratic work ``FACTOR**2``
times. ``BOUND`` sits between. Times are the thread's CPU time, the least of a few runs with
the collector off, the two sizes run in turn, so a loaded machine does not decide the outcome
(``clock=time.process_time`` for work that moves to other threads, such as a walk on fresh
stacks); the size first doubles until the small run takes ``MIN_SECONDS``, so fixed costs do
not hide the growth.

An input that outgrows a CPU cache between the two sizes costs more per unit once, which can
look superlinear over one step; a ratio over ``BOUND`` is checked again over the next doubling
past the large size, which superlinear work also exceeds and a one-time step does not.
"""

from __future__ import annotations

import gc
import math
import time
from collections.abc import Callable
from dataclasses import dataclass

FACTOR = 8
BOUND = 24
"""Linear work grows 8 times, ``n log n`` about 10, ``n ** 1.5`` about 23, quadratic 64."""
EXPONENT = math.log(BOUND, FACTOR)
"""The growth exponent ``BOUND`` allows, about 1.53, for steps of other factors."""
MIN_SECONDS = 0.002
MAX_SIZE = 1 << 22
RUNS = 3
YOUNG = 1
"""The generations ``cpu`` collects before measuring: the garbage earlier runs left. A full
collection walks the whole test process's heap, which cost 40 to 120 ms a call, about 90% of
each parser case's time, and changed nothing measured: the collector is off while it runs."""

type Work = Callable[[], object]
type Clock = Callable[[], float]
type Make = Callable[[int], Work]
"""Given a size, the work of parsing an input of that size (built before the clock starts)."""


def cpu(work: Work, runs: int = RUNS, clock: Clock = time.thread_time) -> float:
    """The least CPU time (the thread's, by default) of ``runs`` runs of ``work``."""
    return _least((work,), runs, clock)[0]


def cpu_pair(
    first: Work, second: Work, runs: int = RUNS, clock: Clock = time.thread_time
) -> tuple[float, float]:
    """The least CPU time of each of two pieces of work, run in turn, so a stretch in
    which the machine runs slower (a lower clock speed, a busy neighbour sharing its cache)
    falls on both instead of inflating their ratio."""
    a, b = _least((first, second), runs, clock)
    return a, b


def _least(works: tuple[Work, ...], runs: int, clock: Clock) -> list[float]:
    best = [float("inf")] * len(works)
    enabled = gc.isenabled()
    gc.collect(YOUNG)
    gc.disable()
    try:
        for _ in range(runs):
            for index, work in enumerate(works):
                start = clock()
                work()
                best[index] = min(best[index], clock() - start)
    finally:
        if enabled:
            gc.enable()
    return best


@dataclass(frozen=True, slots=True)
class Growth:
    size: int
    small: float
    large: float
    factor: int = FACTOR

    @property
    def ratio(self) -> float:
        return self.large / max(self.small, 1e-6)

    @property
    def superlinear(self) -> bool:
        return self.ratio > self.factor**EXPONENT

    @property
    def cheap(self) -> bool:
        """Both runs are too quick to measure: the input is refused or bounded early."""
        return self.large < MIN_SECONDS * FACTOR

    def __str__(self) -> str:
        return (
            f"size {self.size}: {self.small * 1000:.2f} ms, size {self.size * self.factor}: "
            f"{self.large * 1000:.2f} ms, {self.ratio:.1f}x (linear is {self.factor}x, "
            f"the bound {self.factor**EXPONENT:.1f}x)"
        )


def growth(
    make: Make, size: int, max_size: int = MAX_SIZE, clock: Clock = time.thread_time
) -> Growth:
    """``make``'s work at ``size`` (doubled until it takes ``MIN_SECONDS``) and at ``FACTOR``
    times that size, measured in turn."""
    while cpu(make(size), clock=clock) < MIN_SECONDS and size * 2 * FACTOR <= max_size:
        size *= 2
    small, large = cpu_pair(make(size), make(size * FACTOR), clock=clock)
    return Growth(size, small, large)


def assert_near_linear(
    make: Make, size: int, max_size: int = MAX_SIZE, clock: Clock = time.thread_time
) -> Growth:
    """Fails when ``make``'s work grows faster than ``BOUND`` over ``FACTOR`` times the size."""
    found = growth(make, size, max_size, clock)
    if found.cheap or not found.superlinear:
        return found
    large = found.size * FACTOR
    beyond = Growth(large, *cpu_pair(make(large), make(large * 2), clock=clock), factor=2)
    assert not beyond.superlinear, f"superlinear: {found}; then {beyond}"
    return found
