"""Durations, parsed once at the boundary.

Public APIs accept a ``Duration`` (seconds as a number, a ``timedelta``, a
string such as ``"10 seconds"``, a ``(seconds, nanos)`` pair or a mapping of
units, as Effect's ``Duration.Input``) and parse it with ``to_seconds`` into
``Seconds``. Everything past the
boundary (clocks, schedulers, schedule decisions) takes ``Seconds``, so a
raw float cannot reach a timer without being parsed.

Parsing follows Effect's ``Duration.make``: NaN and -0 become 0.
Infinities are kept (an infinite sleep never wakes); negative values are
kept (a negative sleep wakes at once).

Arithmetic saturates as JavaScript's numbers do: a delay that grows past
float range is infinite, never an ``OverflowError``. Nanosecond counts
(``nanos_or_infinite``) are ints within float range or infinities, so
they mix with float times freely.
"""

from __future__ import annotations

import math
import re
import sys
from datetime import timedelta
from decimal import ROUND_HALF_UP, Context, Decimal
from typing import TypedDict, final

from pyfect import _js
from pyfect._js import SPACE


class DurationParts(TypedDict, total=False):
    """Effect's ``DurationObject``: the units add up."""

    weeks: float
    days: float
    hours: float
    minutes: float
    seconds: float
    milliseconds: float
    microseconds: float
    nanoseconds: float


type Duration = float | timedelta | str | tuple[float, float] | DurationParts
"""Seconds as a number, a ``timedelta``, a string (``"10 seconds"``,
``"Infinity"``), a ``(seconds, nanos)`` pair or a mapping of units."""


@final
class Seconds(float):
    """A parsed duration in seconds. Never NaN or -0.

    Arithmetic on ``Seconds`` gives a plain ``float``; wrap the result in
    ``Seconds(...)`` to use it as a duration again."""

    __slots__ = ()

    def __new__(cls, value: float) -> Seconds:
        return super().__new__(cls, 0.0 if math.isnan(value) or value == 0 else value)


ZERO: Seconds = Seconds(0.0)
_NANOS = 1_000_000_000


_DURATION_TEXT = re.compile(
    rf"(-?[0-9]+(?:\.[0-9]+)?)[{SPACE}]+"
    r"(nanos?|micros?|millis?|seconds?|minutes?|hours?|days?|weeks?)"
)
_UNIT_NANOS = {
    "nano": 1,
    "micro": 1_000,
    "milli": 1_000_000,
    "second": _NANOS,
    "minute": 60 * _NANOS,
    "hour": 3_600 * _NANOS,
    "day": 86_400 * _NANOS,
    "week": 604_800 * _NANOS,
}
_EXACT = Context(prec=4_000)


def parse_duration_text(text: str) -> Seconds | None:
    """A duration string as Effect's ``Duration.fromInput`` reads it (rounded
    to the nearest nanosecond, ties away from zero), or ``None``."""
    if text == "Infinity":
        return Seconds(math.inf)
    if text == "-Infinity":
        return Seconds(-math.inf)
    match = _DURATION_TEXT.fullmatch(text)
    if match is None:
        return None
    amount, unit = match.groups()
    scaled = _EXACT.multiply(Decimal(amount), Decimal(_UNIT_NANOS[unit.removesuffix("s")]))
    nanos = scaled.to_integral_value(rounding=ROUND_HALF_UP)
    return Seconds(float(_EXACT.divide(nanos, Decimal(_NANOS))))


def _round_nanos(nanos: float) -> Seconds:
    """A whole number of nanoseconds, ties away from zero (Effect's
    ``fromNanosNumber``); NaN stays NaN, which ``Seconds`` reads as zero."""
    if not math.isfinite(nanos):
        return Seconds(nanos)
    return Seconds(math.copysign(_js.round(abs(nanos)), nanos) / _NANOS)


def _pair_seconds(seconds: float, nanos: float) -> Seconds:
    if math.isnan(seconds) or math.isnan(nanos):
        return Seconds(0.0)
    if -math.inf in (seconds, nanos):
        return Seconds(-math.inf)
    if math.inf in (seconds, nanos):
        return Seconds(math.inf)
    if float(seconds).is_integer() and float(nanos).is_integer():
        return Seconds((int(seconds) * _NANOS + int(nanos)) / _NANOS)
    return _round_nanos(seconds * _NANOS + nanos)


def _parts_seconds(parts: DurationParts) -> Seconds:
    def millis_of(key: str, scale: float) -> float:
        # A NaN unit is skipped, as Effect's truthy check on each unit.
        value = parts.get(key, 0)
        return 0.0 if math.isnan(value) else value * scale

    millis = (
        millis_of("weeks", 604_800_000)
        + millis_of("days", 86_400_000)
        + millis_of("hours", 3_600_000)
        + millis_of("minutes", 60_000)
        + millis_of("seconds", 1_000)
        + millis_of("milliseconds", 1)
    )
    micros = parts.get("microseconds", 0)
    nanos = parts.get("nanoseconds", 0)
    if (not micros or math.isnan(micros)) and (not nanos or math.isnan(nanos)):
        return Seconds(millis / 1e3)
    return _round_nanos(millis * 1e6 + micros * 1e3 + nanos)


def to_seconds(duration: Duration) -> Seconds:
    """Parse a ``Duration``; a string that is not one raises ``ValueError``
    (Effect's ``Duration.fromInputUnsafe``)."""
    match duration:
        case float() | int():
            return Seconds(duration)
        case timedelta():
            return Seconds(duration.total_seconds())
        case str():
            parsed = parse_duration_text(duration)
            if parsed is None:
                raise ValueError(f"Invalid Input: {duration}")
            return parsed
        case (seconds, nanos):
            return _pair_seconds(seconds, nanos)
        case _:
            return _parts_seconds(duration)


def to_nanos(seconds: float) -> int:
    """Whole nanoseconds (floored) in a finite number of seconds; raises
    ``ValueError`` for an infinity (use ``nanos_or_infinite``).

    The float is read as the shortest decimal that prints it, so
    ``1_000_000_000.001`` is exactly ``1_000_000_000_001_000_000``;
    multiplying by ``1e9`` in floating point would be off by tens of
    nanoseconds at epoch-sized values."""
    if not math.isfinite(seconds):
        raise ValueError(f"to_nanos needs a finite duration, got {seconds}")
    return math.floor(_exact_nanos(seconds))


_MAX_NANOS = math.floor(sys.float_info.max)


def nanos_or_infinite(seconds: float) -> int | float:
    """``to_nanos``, keeping an infinite duration infinite (a timer that
    never fires). A count past float range (over about 1.8e299 seconds) is
    infinite too, so the result always mixes with floats: deadlines are
    ``now_nanos + nanos_or_infinite(d)``."""
    if math.isnan(seconds):
        return 0
    if math.isinf(seconds):
        return float(seconds)
    return _in_float_range(to_nanos(seconds))


def from_nanos(nanos: int | float) -> Seconds:
    """A sleep of ``nanos`` whole nanoseconds; ``to_nanos`` reads it back
    exactly (below 10**15 ns, about 11 days), so a timer computed in
    nanoseconds never floors to a 0 ns sleep that leaves time unmoved.
    A count past float range is infinite."""
    return Seconds(_in_float_range(nanos) / _NANOS)


def add_nanos(a: int | float, b: int | float) -> int | float:
    """``a + b`` for ``nanos_or_infinite`` counts (a deadline is ``now +
    delay``), staying within float range: a sum past it is infinite, as
    JavaScript's millisecond sums are."""
    return _in_float_range(_in_float_range(a) + _in_float_range(b))


def _in_float_range(nanos: int | float) -> int | float:
    """An int count past float range as the infinity it saturates to."""
    if isinstance(nanos, int) and abs(nanos) > _MAX_NANOS:
        return math.inf if nanos > 0 else -math.inf
    return nanos


def from_millis(millis: float) -> Seconds:
    """Effect's ``Duration.millis``: a delay computed in float milliseconds
    (infinite once it passes float range, as in JavaScript)."""
    return Seconds(millis / 1000)


def round_nanos(nanos: float) -> int:
    """The whole nanoseconds nearest ``nanos``, ties away from zero
    (Effect's ``roundTiesAwayFromZero``, as ``Math.round`` on the size).
    Raises ``ValueError`` for an infinity or NaN."""
    if not math.isfinite(nanos):
        raise ValueError(f"round_nanos needs a finite count, got {nanos}")
    size = abs(nanos)
    whole = math.floor(size)
    rounded = whole + 1 if size - whole >= 0.5 else whole
    return -rounded if nanos < 0 else rounded


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


def _effect_nanos(seconds: float) -> int:
    """Whole nanoseconds in Effect's ``Duration.seconds(seconds)``: the
    milliseconds ``seconds * 1000``, kept whole, else rounded to the
    nanosecond with ties away from zero (``2.5e-9`` is 3 ns)."""
    millis = seconds * 1000
    return int(millis) * 10**6 if millis.is_integer() else round_nanos(millis * 1_000_000)


_UNITS = (
    ("d", 86_400 * 10**9),
    ("h", 3_600 * 10**9),
    ("m", 60 * 10**9),
    ("s", 10**9),
    ("ms", 10**6),
)


def format_duration(seconds: Seconds) -> str:
    """Human-readable, as Effect's ``Duration.format``: ``"1s 500ms"``."""
    if math.isinf(seconds * 1000):
        return "Infinity" if seconds > 0 else "-Infinity"
    nanos = _effect_nanos(abs(seconds))
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


__all__ = [
    "ZERO",
    "Duration",
    "DurationParts",
    "Seconds",
    "add_nanos",
    "format_duration",
    "from_millis",
    "from_nanos",
    "nanos_or_infinite",
    "parse_duration_text",
    "round_nanos",
    "to_millis",
    "to_nanos",
    "to_seconds",
]
