"""Durations, parsed once at the boundary.

Public APIs accept a ``Duration`` (seconds as a float, or a ``timedelta``)
and parse it with ``to_seconds`` into ``Seconds``. Everything past the
boundary (clocks, schedulers, schedule decisions) takes ``Seconds``, so a
raw float cannot reach a timer without being parsed.

Parsing follows Effect's ``Duration.make``: NaN and -0 become 0.
Infinities are kept (an infinite sleep never wakes); negative values are
kept (a negative sleep wakes at once).
"""

from __future__ import annotations

import math
from datetime import timedelta
from decimal import Decimal
from typing import final

type Duration = float | timedelta
"""Seconds as a float, or a ``timedelta``."""


@final
class Seconds(float):
    """A parsed duration in seconds. Never NaN or -0.

    Arithmetic on ``Seconds`` gives a plain ``float``; wrap the result in
    ``Seconds(...)`` to use it as a duration again."""

    __slots__ = ()

    def __new__(cls, value: float) -> Seconds:
        return super().__new__(cls, 0.0 if math.isnan(value) or value == 0 else value)


ZERO: Seconds = Seconds(0.0)


def to_seconds(duration: Duration) -> Seconds:
    return Seconds(duration.total_seconds() if isinstance(duration, timedelta) else duration)


def to_nanos(seconds: float) -> int:
    """Whole nanoseconds (floored) in a finite number of seconds.

    The float is read as the shortest decimal that prints it, so
    ``1_000_000_000.001`` is exactly ``1_000_000_000_001_000_000``;
    multiplying by ``1e9`` in floating point would be off by tens of
    nanoseconds at epoch-sized values."""
    return math.floor(_exact_nanos(seconds))


def to_millis(duration: Duration) -> float:
    """Milliseconds in ``duration``, read as the shortest decimal that
    prints it (as ``to_nanos`` does), so a duration measured in whole
    nanoseconds gives ``nanos / 1e6`` as Effect's ``Duration.toMillis``
    does, not a float product one ulp off."""
    if isinstance(duration, timedelta):
        return duration / timedelta(milliseconds=1)
    seconds = to_seconds(duration)
    if math.isinf(seconds):
        return float(seconds)
    return float(Decimal(repr(float(seconds))) * 1000)


def _exact_nanos(seconds: float) -> Decimal:
    return Decimal(repr(float(seconds))) * 10**9


_UNITS = (
    ("d", 86_400 * 10**9),
    ("h", 3_600 * 10**9),
    ("m", 60 * 10**9),
    ("s", 10**9),
    ("ms", 10**6),
)


def format_duration(seconds: Seconds) -> str:
    """Human-readable, as Effect's ``Duration.format``: ``"1s 500ms"``."""
    if math.isinf(seconds):
        return "Infinity" if seconds > 0 else "-Infinity"
    nanos = round(_exact_nanos(abs(seconds)))  # Effect keeps whole nanoseconds
    if nanos == 0:
        return "0"
    pieces: list[str] = []
    for suffix, size in _UNITS:
        count, nanos = divmod(nanos, size)
        if count:
            pieces.append(f"{count}{suffix}")
    if nanos:
        pieces.append(f"{nanos}ns")
    return ("-" if seconds < 0 else "") + " ".join(pieces)


__all__ = ["ZERO", "Duration", "Seconds", "format_duration", "to_millis", "to_nanos", "to_seconds"]
