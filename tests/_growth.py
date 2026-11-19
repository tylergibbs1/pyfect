"""How a piece of work grows with its input, for inputs a peer chooses: the one helper for
tests that bound it (linear, not quadratic; cheap).

Count the work when you can (visits, comparisons, steps through a hook, as
``test_semaphore_queue_cost`` and ``test_equal_depth`` do). Measure it here when the work
that can blow up runs where nothing counts it: ``re`` backtracking, ``str.find`` over a
growing buffer, a buffer copied on every token, or a string attribute appended to (CPython's
in-place ``str +=`` only applies to a local variable; JavaScript's ropes, which Effect relies
on, make the same code linear there).

``growth`` measures a piece of work at a size and at ``factor`` times it (``FACTOR`` unless
given): linear work grows ``factor`` times, ``n log n`` a little more, quadratic work
``factor**2`` times; ``EXPONENT`` sits between. Times are the thread's CPU time (the
process's, ``clock=time.process_time``, for work that can move to other threads) with the
collector off, so waiting for a CPU on a loaded machine does not count; the two sizes are
measured in turn (the order flipping each round), the least of ``SAMPLES`` samples each, so
a slow sample or stretch does not decide it (a CPU time can only grow with interference, so
the least is the closest to the work's own). A sample lasts at least ``SAMPLE_SECONDS`` (the work
runs back to back until it does), and a sample of the smaller size runs it ``factor`` times
as often, so both samples of linear work last about as long and meet the same neighbours
(a short sample slips between a busy neighbour's bursts more often than a long one does).
The size first doubles until the small run takes ``MIN_SECONDS``, so fixed costs do not
hide the growth.

Work can cost more per unit past some size without growing faster: an input outgrowing a CPU
cache, or buffers that start to be faulted in from the OS on every run once the allocator
hands them back. Over one comparison that step can look superlinear, so a ratio over the
bound is judged again over a span of ``SPAN`` times the size, from a quarter of the smaller
size to twice the larger, the two ends in one comparison: the growth exponent over the span
(the log of the time ratio over the log of the size ratio) must stay within the bound's. Over
a wide span a constant step thins out toward exponent 1, while quadratic work stays at 2.
Never time a growth check with a wall clock (``tests/test_growth_checks.py``).
"""

from __future__ import annotations

import gc
import math
import os
import time
from collections.abc import Callable
from dataclasses import dataclass

FACTOR = 8
BOUND = 24
"""Linear work grows 8 times, ``n log n`` about 10, ``n ** 1.5`` about 23, quadratic 64."""
EXPONENT = math.log(BOUND, FACTOR)
"""The growth exponent ``BOUND`` allows, about 1.53, for steps of other factors."""
GUARD_MARGIN = float(os.environ.get("PYFECT_GUARD_MARGIN", "1"))
"""Bounds are this many times looser. ``scripts/check_regression_guards.py`` sets 1.5, so a
test caught its bug only if it would still have with a looser bound: big_decimal's digit run
grew 27x against 24 on macOS and under 24 on CI's runner."""
MIN_SECONDS = 0.002
MAX_SIZE = 1 << 22
RUNS = 3
SAMPLE_SECONDS = 0.002
"""Each sample of a comparison runs the work back to back until it lasts this long. On a
2-CPU container running four measuring processes, samples of a linear parser run shorter
than 0.5 ms spread up to 1.44 times their median, longer ones stayed within 1.06 at the 90th
percentile; 2 ms leaves a margin of four."""
SAMPLES = 4
"""Samples per side of a comparison; the least decides. Even, so each side runs first as often
as second, and a speed that flips between samples falls on both sides alike. Their median
would let a slow stretch over two samples of one side hide quadratic work
(``test_a_slow_stretch_anywhere_does_not_hide_quadratic_work``)."""
YOUNG = 1
"""The generations collected before measuring: the garbage earlier runs left. A full
collection walks the whole test process's heap (40 to 120 ms a call) and changes nothing
measured: the collector is off while the work runs."""

type Work = Callable[[], object]
type Make = Callable[[int], Work]
"""Given a size, the work at that size (built before the clock starts)."""
type Clock = Callable[[], float]
"""``time.thread_time`` unless the work can move to other threads: then ``time.process_time``."""


def cpu(work: Work, runs: int = RUNS, *, clock: Clock = time.thread_time) -> float:
    """The least CPU time (the thread's, by default) of ``runs`` runs of ``work``."""
    return _least((work,), runs, clock)[0]


def cpu_pair(
    first: Work, second: Work, runs: int = RUNS, *, clock: Clock = time.thread_time
) -> tuple[float, float]:
    """The least CPU time of each of two pieces of work, run in turn, so a stretch in
    which the machine runs slower (a lower clock speed, a busy neighbour sharing its cache)
    falls on both instead of inflating their ratio. The order flips each round (a b, b a,
    a b), so a speed that alternates between runs does not slow every run of one side."""
    a, b = _least((first, second), runs, clock)
    return a, b


def _least(works: tuple[Work, ...], runs: int, clock: Clock) -> list[float]:
    best = [float("inf")] * len(works)
    enabled = gc.isenabled()
    gc.collect(YOUNG)
    gc.disable()
    try:
        order = list(enumerate(works))
        for _ in range(runs):
            for index, work in order:
                start = clock()
                work()
                best[index] = min(best[index], clock() - start)
            order.reverse()  # a b, b a, a b: each side runs both first and second
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
    bound: float = BOUND
    """The ratio past which the work is superlinear."""

    @property
    def ratio(self) -> float:
        return self.large / max(self.small, 1e-6)

    @property
    def superlinear(self) -> bool:
        return self.ratio > self.bound

    @property
    def exponent(self) -> float:
        """The growth exponent the ratio shows: 1 for linear work, 2 for quadratic."""
        return math.log(max(self.ratio, 1e-9), self.factor)

    def __str__(self) -> str:
        return (
            f"size {self.size}: {self.small * 1000:.2f} ms, size {self.size * self.factor}: "
            f"{self.large * 1000:.2f} ms, {self.ratio:.1f}x (linear is {self.factor}x, "
            f"the bound {self.bound:.1f}x; exponent {self.exponent:.2f}, the bound's "
            f"{math.log(self.bound, self.factor):.2f})"
        )


def _compare(make: Make, size: int, factor: int, clock: Clock) -> tuple[float, float]:
    """The CPU time of one run at ``size`` and of one at ``factor`` times it: the least of
    ``SAMPLES`` samples each, taken in turn. A sample of each size runs the work until it
    lasts as long as one run of the larger size, and at least ``SAMPLE_SECONDS``, so both
    samples last about as long, however the work grows: a neighbour that slows only runs
    longer than its quiet stretches slows both alike."""
    small, large = make(size), make(size * factor)
    once = cpu(small, 1, clock=clock), cpu(large, 1, clock=clock)
    length = max(SAMPLE_SECONDS, once[1])
    runs = tuple(max(1, math.ceil(length / max(seconds, 1e-9))) for seconds in once)
    return _least_pair((small, large), (runs[0], runs[1]), clock)


def _least_pair(
    works: tuple[Work, Work], runs: tuple[int, int], clock: Clock
) -> tuple[float, float]:
    times: tuple[list[float], list[float]] = ([], [])
    enabled = gc.isenabled()
    gc.collect(YOUNG)
    gc.disable()
    try:
        order = [0, 1]
        for _ in range(SAMPLES):
            for index in order:
                work, count = works[index], runs[index]
                start = clock()
                for _ in range(count):
                    work()
                times[index].append((clock() - start) / count)
            order.reverse()  # each side runs both first and second
    finally:
        if enabled:
            gc.enable()
    return min(times[0]), min(times[1])


def growth(
    make: Make,
    size: int,
    max_size: int = MAX_SIZE,
    *,
    factor: int = FACTOR,
    bound: float | None = None,
    clock: Clock = time.thread_time,
) -> Growth:
    """``make``'s work at ``size`` (doubled until it takes ``MIN_SECONDS``, while
    ``factor`` times it stays within ``max_size``) and at ``factor`` times that size.
    ``bound`` is ``factor ** EXPONENT`` unless given. However quick one run is, the work
    repeats until a sample lasts ``SAMPLE_SECONDS``, so every comparison is judged, on a fast
    machine as on a slow one."""
    while size * 2 * factor <= max_size and cpu(make(size), clock=clock) < MIN_SECONDS:
        size *= 2
    small, large = _compare(make, size, factor, clock)
    limit = factor**EXPONENT if bound is None else bound
    return Growth(size, small, large, factor, limit * GUARD_MARGIN)


SPAN = 64
"""The size ratio over which a flagged comparison is judged again; it ends at twice the larger
size, as far as the first comparison's own doubling went. A step in the cost per unit of up
to ``SPAN ** (exponent - 1)`` passes: 8.6 times at the default exponent (1.53, 8 times at
1.5), where CI measured steps of 2.8 and 3.8 (exponent 1.25 and 1.32 over the span), while
quadratic work shows 2."""


def superlinear(
    make: Make,
    size: int,
    max_size: int = MAX_SIZE,
    *,
    factor: int = FACTOR,
    bound: float | None = None,
    clock: Clock = time.thread_time,
) -> str | None:
    """How ``make``'s work grows past ``bound`` over ``factor`` times the size, and at the
    same exponent over ``SPAN`` times the size, or ``None``."""
    found = growth(make, size, max_size, factor=factor, bound=bound, clock=clock)
    if not found.superlinear:
        return None
    largest = found.size * factor * 2
    smallest = max(1, largest // SPAN)
    span = largest // smallest
    allowed = span ** math.log(found.bound, factor)
    wide = Growth(smallest, *_compare(make, smallest, span, clock), span, allowed)
    return f"superlinear: {found}; over the span {wide}" if wide.superlinear else None


def is_near_linear(
    make: Make,
    size: int,
    max_size: int = MAX_SIZE,
    *,
    factor: int = FACTOR,
    bound: float | None = None,
    clock: Clock = time.thread_time,
) -> bool:
    return superlinear(make, size, max_size, factor=factor, bound=bound, clock=clock) is None


def assert_near_linear(
    make: Make,
    size: int,
    max_size: int = MAX_SIZE,
    *,
    factor: int = FACTOR,
    bound: float | None = None,
    clock: Clock = time.thread_time,
) -> None:
    """Fails when ``make``'s work grows past ``bound`` (see ``superlinear``)."""
    problem = superlinear(make, size, max_size, factor=factor, bound=bound, clock=clock)
    assert problem is None, problem
