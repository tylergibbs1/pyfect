"""Epoch timestamps in float milliseconds (as Effect's clocks give them) as whole
nanoseconds."""

from __future__ import annotations

import math
from decimal import Decimal


def millis_to_nanos(millis: float) -> int:
    """Whole nanoseconds (floored) in a finite count of milliseconds, read as the
    shortest decimal that prints it: ``1_000.000001`` is exactly ``1_000_000_001``,
    where multiplying by ``1e6`` in floating point would be off."""
    return math.floor(Decimal(repr(float(millis))) * 10**6)
