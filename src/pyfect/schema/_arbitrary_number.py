"""The interval a number, integer or bigint node draws from, read from its
constraint (Effect's ``numberBounds`` and its ``BigInt`` case in
``Arbitrary.schema``). An interval holding no value raises ``ValueError``
here, when the strategy is derived, never when it is drawn.
"""

from __future__ import annotations

import math
import sys
from dataclasses import dataclass

from pyfect.schema._arbitrary_constraint import ArbitraryConstraint


@dataclass(frozen=True, slots=True)
class FloatInterval:
    """Inclusive float bounds (``None`` is open), and whether the values are
    finite. ``-0.0`` is below ``0.0``, so an interval from ``0`` holds both
    zeros."""

    low: float | None
    high: float | None
    finite: bool


@dataclass(frozen=True, slots=True)
class IntInterval:
    """Inclusive integer bounds (``None`` is open), never empty."""

    low: int | None
    high: int | None


def _error(what: str) -> ValueError:
    return ValueError(f"Unable to derive an arbitrary for {what} constraints")


def _is_nan(bound: object) -> bool:
    return isinstance(bound, float) and math.isnan(bound)


def float_interval(constraint: ArbitraryConstraint) -> FloatInterval:
    """The floats of a ``Number`` node; raises when there are none."""
    low, high = constraint.minimum, constraint.maximum
    if _is_nan(low) or _is_nan(high):
        raise _error("number")
    finite = constraint.number == "finite"
    lo = None if low is None else float(low)
    hi = None if high is None else float(high)
    if lo is not None:
        if constraint.exclusive_minimum:
            if lo == math.inf:
                raise _error("number")
            lo = math.nextafter(lo, math.inf)
        elif lo == 0:
            lo = -0.0
    if hi is not None:
        if constraint.exclusive_maximum:
            if hi == -math.inf:
                raise _error("number")
            hi = math.nextafter(hi, -math.inf)
        elif hi == 0:
            hi = 0.0
    if finite:
        if lo == math.inf or hi == -math.inf:
            raise _error("number")
        lo = None if lo is None else max(lo, -sys.float_info.max)
        hi = None if hi is None else min(hi, sys.float_info.max)
    if lo is not None and hi is not None and lo > hi:
        raise _error("number")
    return FloatInterval(lo, hi, finite)


def integers_within(constraint: ArbitraryConstraint) -> IntInterval | None:
    """The integers within ``constraint``'s bounds, ``None`` when there are
    none."""
    low, high = constraint.minimum, constraint.maximum
    if _is_nan(low) or _is_nan(high) or low == math.inf or high == -math.inf:
        return None
    lo = (
        None
        if low is None or low == -math.inf
        else math.floor(low) + 1
        if constraint.exclusive_minimum
        else math.ceil(low)
    )
    hi = (
        None
        if high is None or high == math.inf
        else math.ceil(high) - 1
        if constraint.exclusive_maximum
        else math.floor(high)
    )
    return None if lo is not None and hi is not None and lo > hi else IntInterval(lo, hi)


def integer_interval(constraint: ArbitraryConstraint) -> IntInterval:
    """The integers of a ``Number`` node checked to be integers; raises when
    there are none."""
    interval = integers_within(constraint)
    if interval is None:
        raise _error("integer")
    return interval


def big_int_interval(constraint: ArbitraryConstraint) -> IntInterval:
    """The integers of a ``BigInt`` node; raises when there are none."""
    interval = integers_within(constraint)
    if interval is None:
        raise _error("bigint")
    return interval
