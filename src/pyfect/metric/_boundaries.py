"""Histogram boundaries. Each helper keeps the positive boundaries, drops
repeats and ends with ``math.inf``, so the last bucket counts every
value."""

from __future__ import annotations

import math
from collections.abc import Iterable

from pyfect._js import power


def boundaries_from_iterable(boundaries: Iterable[float]) -> tuple[float, ...]:
    """The distinct positive ``boundaries``, in order, then ``math.inf``."""
    return (*(b for b in dict.fromkeys(boundaries) if b > 0), math.inf)


def linear_boundaries(*, start: float, width: float, count: int) -> tuple[float, ...]:
    """``count - 1`` boundaries (at least one) ``width`` apart from
    ``start``, then ``math.inf``."""
    return boundaries_from_iterable(start + n * width for n in range(max(1, count - 1)))


def exponential_boundaries(*, start: float, factor: float, count: int) -> tuple[float, ...]:
    """``count - 1`` boundaries (at least one) growing by ``factor`` from
    ``start``, then ``math.inf``."""
    return boundaries_from_iterable(start * power(factor, i) for i in range(max(1, count - 1)))
