"""Trend tests that ignore noise, outliers and the garbage collector's sawtooth.

A series is cut into equal time bins and each bin is summarised by a low
percentile (its floor: a leak raises the floor, a GC cycle only the peaks) or by
its median (latency). Over the bin summaries, the Theil-Sen slope (the median of
every pairwise slope) gives the growth rate and Kendall's tau how consistently
the series moves one way: a steady leak has tau near 1, noise near 0.
"""

from __future__ import annotations

import math
import statistics
from collections.abc import Callable, Sequence
from dataclasses import dataclass

type Point = tuple[float, float]


def percentile(values: Sequence[float], q: float) -> float:
    """The ``q`` quantile (0..1) of ``values``, interpolated."""
    ordered = sorted(values)
    if len(ordered) == 1:
        return ordered[0]
    position = q * (len(ordered) - 1)
    low = int(position)
    high = min(low + 1, len(ordered) - 1)
    return ordered[low] + (ordered[high] - ordered[low]) * (position - low)


def bins(
    points: Sequence[Point], count: int, summary: Callable[[Sequence[float]], float]
) -> list[Point]:
    """``points`` cut into ``count`` equal time spans, each summarised as (its middle
    time, ``summary`` of its values). Empty spans are left out."""
    if not points:
        return []
    start, end = points[0][0], points[-1][0]
    width = (end - start) / count or 1.0
    grouped: list[list[float]] = [[] for _ in range(count)]
    for t, value in points:
        grouped[min(int((t - start) / width), count - 1)].append(value)
    return [
        (start + width * (index + 0.5), summary(values))
        for index, values in enumerate(grouped)
        if values
    ]


def floor(values: Sequence[float]) -> float:
    return percentile(values, 0.1)


def median(values: Sequence[float]) -> float:
    return statistics.median(values)


def theil_sen(points: Sequence[Point]) -> float:
    """The median slope over every pair of points with different times."""
    slopes = [
        (y2 - y1) / (t2 - t1)
        for i, (t1, y1) in enumerate(points)
        for t2, y2 in points[i + 1 :]
        if t2 != t1
    ]
    return statistics.median(slopes) if slopes else 0.0


def kendall_tau(points: Sequence[Point]) -> float:
    """Kendall's tau between time and value: 1 when every later point is higher."""
    concordant = discordant = 0
    for i, (t1, y1) in enumerate(points):
        for t2, y2 in points[i + 1 :]:
            sign = (t2 - t1) * (y2 - y1)
            if sign > 0:
                concordant += 1
            elif sign < 0:
                discordant += 1
    pairs = len(points) * (len(points) - 1) // 2
    return (concordant - discordant) / pairs if pairs else 0.0


@dataclass(frozen=True)
class Trend:
    start: float
    """The fitted level at the start of the window."""
    growth: float
    """How much the fitted line rises across the window."""
    tau: float
    rising: bool
    """Mann-Kendall's test finds the bins rising (one-sided, p < 0.01)."""

    @property
    def relative(self) -> float:
        return self.growth / self.start if self.start > 0 else float("inf")


def mann_kendall_rising(points: Sequence[Point]) -> bool:
    """Whether the values rise with time, one-sided at p < 0.01 (ties ignored)."""
    n = len(points)
    s = kendall_tau(points) * n * (n - 1) / 2
    deviation = math.sqrt(n * (n - 1) * (2 * n + 5) / 18)
    return deviation > 0 and (s - 1) / deviation > _Z_99


def trend(points: Sequence[Point], summary: Callable[[Sequence[float]], float]) -> Trend | None:
    """The trend of ``points`` over between ``MIN_BINS`` and ``MAX_BINS`` bins of at
    least ``POINTS_PER_BIN`` points, or ``None`` with too few points to tell."""
    count = min(MAX_BINS, len(points) // POINTS_PER_BIN)
    summarised = bins(points, count, summary) if count >= MIN_BINS else []
    if len(summarised) < MIN_BINS:
        return None
    slope = theil_sen(summarised)
    span = points[-1][0] - points[0][0]
    # Theil-Sen's intercept: the median of each point's own intercept.
    intercept = statistics.median(y - slope * t for t, y in summarised)
    start = intercept + slope * points[0][0]
    return Trend(
        start=start,
        growth=slope * span,
        tau=kendall_tau(summarised),
        rising=mann_kendall_rising(summarised),
    )


MAX_BINS = 12
MIN_BINS = 6
POINTS_PER_BIN = 10
_Z_99 = 2.326
