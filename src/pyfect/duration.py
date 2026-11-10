"""Durations, parsed once at the boundary.

Public APIs accept a ``Duration`` (milliseconds as a number, a ``timedelta``,
a string such as ``"10 seconds"``, a ``(seconds, nanos)`` pair, a mapping of
units or an already parsed ``Seconds``, as Effect's ``Duration.Input``) and
parse it with ``to_seconds`` into ``Seconds``. Everything past the
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
from typing import TypedDict, cast, final, overload

from pyfect import _js
from pyfect._duration_iso import format_iso_nanos, parse_iso_nanos
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
"""Milliseconds as a number (as in Effect), a ``timedelta``, a string
(``"10 seconds"``, ``"Infinity"``), a ``(seconds, nanos)`` pair, a mapping of
units, or a parsed ``Seconds``, which passes through unchanged."""


@final
class Seconds(float):
    """A parsed duration in seconds. Never NaN or -0.

    Arithmetic that keeps the unit stays ``Seconds``, as Effect's ``Duration``
    operations return a ``Duration``: ``Seconds`` plus or minus ``Seconds``,
    times or divided by a number, negated. Mixing in a bare number gives a
    plain ``float``, since a bare number as a ``Duration`` is milliseconds."""

    __slots__ = ()

    def __new__(cls, value: float) -> Seconds:
        return super().__new__(cls, 0.0 if math.isnan(value) or value == 0 else value)

    @overload
    def __add__(self, value: Seconds, /) -> Seconds: ...
    @overload
    def __add__(self, value: float, /) -> float: ...
    def __add__(self, value: float, /) -> float:
        total = super().__add__(value)
        return Seconds(total) if isinstance(value, Seconds) else total

    @overload
    def __sub__(self, value: Seconds, /) -> Seconds: ...
    @overload
    def __sub__(self, value: float, /) -> float: ...
    def __sub__(self, value: float, /) -> float:
        difference = super().__sub__(value)
        return Seconds(difference) if isinstance(value, Seconds) else difference

    def __mul__(self, value: float, /) -> Seconds:
        # A timedelta operand gives NotImplemented, so its own method runs.
        product = cast("object", super().__mul__(value))
        return Seconds(product) if isinstance(product, int | float) else NotImplemented

    def __rmul__(self, value: float, /) -> Seconds:
        # A timedelta operand gives NotImplemented, so its own method runs.
        product = cast("object", super().__rmul__(value))
        return Seconds(product) if isinstance(product, int | float) else NotImplemented

    # A ratio of two durations is a plain number; the first match wins.
    @overload
    def __truediv__(self, value: Seconds, /) -> float: ...  # pyright: ignore[reportOverlappingOverload]
    @overload
    def __truediv__(self, value: float, /) -> Seconds: ...
    def __truediv__(self, value: float, /) -> float:
        quotient = super().__truediv__(value)
        if quotient is NotImplemented or isinstance(value, Seconds):
            return quotient
        return Seconds(quotient)

    def __neg__(self) -> Seconds:
        return Seconds(-float(self))

    def __pos__(self) -> Seconds:
        return self

    def __abs__(self) -> Seconds:
        return Seconds(abs(float(self)))


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
    total = seconds * _NANOS + nanos
    if math.isfinite(total) and float(seconds).is_integer() and float(nanos).is_integer():
        return Seconds((int(seconds) * _NANOS + int(nanos)) / _NANOS)
    return _round_nanos(total)


_PART_NANOS = (
    ("weeks", 604_800 * _NANOS),
    ("days", 86_400 * _NANOS),
    ("hours", 3_600 * _NANOS),
    ("minutes", 60 * _NANOS),
    ("seconds", _NANOS),
    ("milliseconds", 1_000_000),
    ("microseconds", 1_000),
    ("nanoseconds", 1),
)


def _exact_parts_nanos(parts: DurationParts) -> int | None:
    """The units summed exactly, or ``None`` when one is fractional
    (Effect's ``sumObjectNanos``; a zero or NaN unit counts as unset)."""
    values = [(parts.get(key, 0), scale) for key, scale in _PART_NANOS]
    present = [(v, scale) for v, scale in values if v and not math.isnan(v)]
    if not all(float(v).is_integer() for v, _ in present):
        return None
    return sum(int(v) * scale for v, scale in present)


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
    only_millis = (not micros or math.isnan(micros)) and (not nanos or math.isnan(nanos))
    total = millis * 1e6 if only_millis else millis * 1e6 + micros * 1e3 + nanos
    exact = _exact_parts_nanos(parts) if math.isfinite(total) else None
    if exact is not None:
        return Seconds(exact / _NANOS)
    return Seconds(millis / 1e3) if only_millis else _round_nanos(total)


def _millis_seconds(millis: float) -> Seconds:
    """A bare number, read as milliseconds (Effect's ``Duration.millis``):
    whole milliseconds are kept exactly, others round to the nearest
    nanosecond, ties away from zero."""
    if isinstance(millis, int) or millis.is_integer():
        return Seconds(_in_float_range(int(millis)) / 1000)
    return _round_nanos(millis * 1e6)


def to_seconds(duration: Duration) -> Seconds:
    """Parse a ``Duration``; a string that is not one raises ``ValueError``
    (Effect's ``Duration.fromInputUnsafe``)."""
    match duration:
        case Seconds():
            return duration
        case float() | int():
            return _millis_seconds(duration)
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


def from_input(duration: Duration) -> Seconds | None:
    """``to_seconds``, or ``None`` for a string that is not a duration
    (Effect's ``Duration.fromInput``)."""
    try:
        return to_seconds(duration)
    except ValueError:
        return None


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


def millis_to_nanos(millis: float) -> int:
    """Whole nanoseconds (floored) in a finite number of milliseconds, such
    as an epoch timestamp from ``clock.current_time_millis``, read as the
    shortest decimal that prints it (as ``to_nanos`` reads seconds)."""
    if not math.isfinite(millis):
        raise ValueError(f"millis_to_nanos needs a finite count, got {millis}")
    return math.floor(Decimal(repr(float(millis))) * 10**6)


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


def to_micros(duration: Duration) -> float:
    """Microseconds in ``duration``, read as ``to_millis`` reads milliseconds
    (Effect's ``Duration.toMicros``)."""
    if isinstance(duration, timedelta):
        return duration / timedelta(microseconds=1)
    seconds = to_seconds(duration)
    if math.isinf(seconds):
        return float(seconds)
    return float(Decimal(repr(float(seconds))) * 1_000_000)


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


def format_iso(seconds: Seconds) -> str | None:
    """The duration as an ISO 8601 duration (``"P1DT2H3M4.5S"``, days of 24 hours,
    no years or months), or ``None`` for an infinite one (Effect's
    ``Duration.formatIso``)."""
    if not math.isfinite(seconds):
        return None
    return format_iso_nanos(int(_exact_nanos(seconds).to_integral_value(rounding=ROUND_HALF_UP)))


def from_iso(text: str) -> Seconds | None:
    """An ISO 8601 duration (weeks, days, hours, minutes and seconds, a fraction of up
    to nine digits on the last time unit), or ``None`` (Effect's ``Duration.fromIso``)."""
    nanos = parse_iso_nanos(text)
    return None if nanos is None else from_nanos(nanos)


__all__ = [
    "ZERO",
    "Duration",
    "DurationParts",
    "Seconds",
    "add_nanos",
    "format_duration",
    "format_iso",
    "from_input",
    "from_iso",
    "from_millis",
    "from_nanos",
    "millis_to_nanos",
    "nanos_or_infinite",
    "parse_duration_text",
    "round_nanos",
    "to_micros",
    "to_millis",
    "to_nanos",
    "to_seconds",
]
