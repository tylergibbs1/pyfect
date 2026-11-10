"""Durations (Effect's ``Duration``), parsed once at the boundary.

A ``Duration`` is a whole number of milliseconds (a float, as Effect's ``Millis``), a
whole number of nanoseconds (an ``int`` of any size, Effect's ``bigint`` ``Nanos``),
``infinity`` or ``negative_infinity``. Public APIs accept an ``Input`` (milliseconds as a
number, a string such as ``"10 seconds"``, a ``timedelta``, a ``(seconds, nanos)`` pair, a
``DurationObject`` of units, or a ``Duration``) and parse it with ``from_input_unsafe``;
everything past the boundary (clocks, timers, schedules) takes a ``Duration``::

    d = duration.from_input_unsafe("1.5 seconds")
    d + duration.millis(500)      # duration.millis(2000)
    d.format()                    # "1s 500ms"
    d.to_nanos_unsafe()           # 1_500_000_000

``==``, ``hash`` and ``<`` compare the exact length (``millis(1) == nanos(1_000_000)``),
as Effect's ``Equal`` and ``Order`` do. Arithmetic follows Effect: two ``Millis`` add as
floats (past float range the sum is infinite), anything with ``Nanos`` exactly.
"""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import timedelta
from typing import TYPE_CHECKING, Final, Literal, TypedDict, cast, final

from pyfect import _js
from pyfect._duration_iso import format_iso_nanos, parse_iso_nanos
from pyfect._js import SPACE, int_text, js_number

_E3: Final = 1_000
_E6: Final = 1_000_000
_E9: Final = 1_000_000_000
_NANOS_PER_MINUTE: Final = 60 * _E9
_NANOS_PER_HOUR: Final = 3_600 * _E9
_NANOS_PER_DAY: Final = 86_400 * _E9
_NANOS_PER_WEEK: Final = 604_800 * _E9
_MAX_SAFE: Final = 2**53 - 1


class DurationObject(TypedDict, total=False):
    """Effect's ``DurationObject``: the units add up."""

    weeks: float
    days: float
    hours: float
    minutes: float
    seconds: float
    milliseconds: float
    microseconds: float
    nanoseconds: float


type Unit = Literal[
    "nano",
    "nanos",
    "micro",
    "micros",
    "milli",
    "millis",
    "second",
    "seconds",
    "minute",
    "minutes",
    "hour",
    "hours",
    "day",
    "days",
    "week",
    "weeks",
]


@final
@dataclass(frozen=True, slots=True)
class Millis:
    """``Duration.value`` of a whole number of milliseconds."""

    millis: float


@final
@dataclass(frozen=True, slots=True)
class Nanos:
    """``Duration.value`` of a whole number of nanoseconds."""

    nanos: int


@final
@dataclass(frozen=True, slots=True)
class Infinity:
    """``Duration.value`` of ``infinity``."""


@final
@dataclass(frozen=True, slots=True)
class NegativeInfinity:
    """``Duration.value`` of ``negative_infinity``."""


type DurationValue = Millis | Nanos | Infinity | NegativeInfinity


class Parts(TypedDict):
    """``Duration.parts``: the length split into units (all infinite for an infinity)."""

    days: float
    hours: float
    minutes: float
    seconds: float
    millis: float
    nanos: float


def _number(n: int) -> float:
    """JavaScript's ``Number(bigint)``: the nearest float, infinite past float range."""
    try:
        return float(n)
    except OverflowError:
        return math.inf if n > 0 else -math.inf


def _js_float(x: float) -> float:
    """A Python number as a JavaScript number (an ``int`` past float range is infinite)."""
    return x if isinstance(x, float) else _number(int(x))


def _tdiv(a: int, b: int) -> int:
    """``bigint`` division: truncated toward zero."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _round_ties_away(x: float) -> int:
    """Effect's ``roundTiesAwayFromZero`` on a finite number."""
    return int(math.copysign(_js.round(abs(x)), x))


def _divide_ties_away(numerator: int, denominator: int) -> int:
    absolute = abs(numerator)
    q, r = divmod(absolute, denominator)
    rounded = q + 1 if r * 2 >= denominator else q
    return -rounded if numerator < 0 else rounded


@final
class Duration:
    """A length of time: whole milliseconds, whole nanoseconds or an infinity.

    Build one with ``millis``, ``nanos``, ``seconds`` (and the other unit functions),
    ``from_input_unsafe``, ``zero``, ``infinity`` or ``negative_infinity``."""

    __slots__ = ("_millis", "_nanos")
    # ``_nanos`` is the exact length (an ``int``, or ``±math.inf``); ``_millis`` is the
    # float a ``Millis`` duration holds, or ``None``.
    _millis: float | None
    _nanos: int | float

    def __init__(self) -> None:
        raise TypeError("build a Duration with duration.millis, duration.nanos, ...")

    def __setattr__(self, name: str, value: object) -> None:
        raise AttributeError("Duration is immutable")

    def __delattr__(self, name: str) -> None:
        raise AttributeError("Duration is immutable")

    def __reduce__(self) -> tuple[Callable[..., Duration], tuple[float | int]]:
        if self._millis is not None:
            return (millis, (self._millis,))
        if isinstance(self._nanos, float):
            return (_make_number, (self._nanos,))
        return (nanos, (self._nanos,))

    # --- the representation ------------------------------------------------------------

    @property
    def value(self) -> DurationValue:
        """Effect's ``value``: which of the four forms this is."""
        if self._millis is not None:
            return Millis(self._millis)
        n = self._nanos
        if isinstance(n, int):
            return Nanos(n)
        return _INFINITY_VALUE if n > 0 else _NEGATIVE_INFINITY_VALUE

    def match[A, B, C, D = C](
        self,
        *,
        on_millis: Callable[[float], A],
        on_nanos: Callable[[int], B],
        on_infinity: Callable[[], C],
        on_negative_infinity: Callable[[], D] | None = None,
    ) -> A | B | C | D:
        """Effect's ``Duration.match``; ``on_infinity`` handles ``negative_infinity`` too
        unless ``on_negative_infinity`` is given."""
        if self._millis is not None:
            return on_millis(self._millis)
        n = self._nanos
        if isinstance(n, int):
            return on_nanos(n)
        if n < 0 and on_negative_infinity is not None:
            return on_negative_infinity()
        return on_infinity()

    def pipe[B](self, f: Callable[[Duration], B], /) -> B:
        return f(self)

    # --- predicates --------------------------------------------------------------------

    def is_finite(self) -> bool:
        return isinstance(self._nanos, int)

    def is_zero(self) -> bool:
        return self._nanos == 0

    def is_negative(self) -> bool:
        return self._nanos < 0

    def is_positive(self) -> bool:
        return self._nanos > 0

    # --- arithmetic --------------------------------------------------------------------

    def sum(self, that: Duration) -> Duration:
        """Effect's ``Duration.sum``: ``infinity + negative_infinity`` is ``zero``."""
        a, b = self._millis, that._millis
        if a is not None and b is not None:
            return _make_number(a + b)
        x, y = self._nanos, that._nanos
        if isinstance(x, int):
            return _make_int(x + y) if isinstance(y, int) else that
        return zero if not isinstance(y, int) and x != y else self

    def subtract(self, that: Duration) -> Duration:
        """Effect's ``Duration.subtract``: an infinity minus itself is ``zero``."""
        a, b = self._millis, that._millis
        if a is not None and b is not None:
            return _make_number(a - b)
        x, y = self._nanos, that._nanos
        if isinstance(x, int):
            return _make_int(x - y) if isinstance(y, int) else that.negate()
        return zero if x == y else self

    def times(self, times: float) -> Duration:
        """Effect's ``Duration.times``: ``Nanos`` scale exactly, rounding ties away from
        zero; an infinity times zero (or NaN) is ``zero``."""
        t = _js_float(times)
        if self._millis is not None:
            return _make_number(self._millis * t)
        n = self._nanos
        if not isinstance(n, int):
            return _scale_infinity(n, t)
        if t.is_integer():
            return _make_int(n * int(t))
        n_number = _number(n)
        scaled = n_number * t
        if not math.isfinite(t) or (abs(n_number) <= _MAX_SAFE and abs(scaled) <= _MAX_SAFE):
            return _from_nanos_number(scaled)
        numerator, denominator = t.as_integer_ratio()
        return _make_int(_divide_ties_away(n * numerator, denominator))

    def divide(self, by: float) -> Duration | None:
        """Effect's ``Duration.divide``: ``None`` for a zero or infinite ``by``, and for a
        fractional one on ``Nanos``; ``Nanos`` divide truncating toward zero."""
        b = _js_float(by)
        if not math.isfinite(b) or b == 0:
            return None
        if self._millis is not None:
            return _make_number(self._millis / b)
        n = self._nanos
        if not isinstance(n, int):
            return infinity if (b > 0) == (n > 0) else negative_infinity
        if not b.is_integer():
            return None
        return _make_int(_tdiv(n, int(b)))

    def divide_unsafe(self, by: float) -> Duration:  # noqa: PLR0911
        """Effect's ``Duration.divideUnsafe``: dividing by zero follows IEEE 754's signs,
        an infinite ``by`` (or a fractional one on ``Nanos``) gives ``zero``."""
        b = _js_float(by)
        if not math.isfinite(b):
            return zero
        if self._millis is not None:
            return _make_number(_js.divide(self._millis, b))
        n = self._nanos
        if not isinstance(n, int):
            return _scale_infinity(n, b)
        if b == 0:
            if n == 0:
                return zero
            return infinity if (n > 0) == (math.copysign(1.0, b) > 0) else negative_infinity
        if not b.is_integer():
            return zero
        return _make_int(_tdiv(n, int(b)))

    def abs(self) -> Duration:
        if not self.is_finite():
            return infinity
        return self.negate() if self._nanos < 0 else self

    def negate(self) -> Duration:
        if self._millis is not None:
            return self if self._millis == 0 else _make_number(-self._millis)
        n = self._nanos
        if isinstance(n, int):
            return self if n == 0 else _make_int(-n)
        return negative_infinity if n > 0 else infinity

    def __add__(self, that: Duration) -> Duration:
        return self.sum(that)

    def __sub__(self, that: Duration) -> Duration:
        return self.subtract(that)

    def __mul__(self, times: float) -> Duration:
        return self.times(times)

    def __rmul__(self, times: float) -> Duration:
        return self.times(times)

    def __neg__(self) -> Duration:
        return self.negate()

    def __pos__(self) -> Duration:
        return self

    def __abs__(self) -> Duration:
        return self.abs()

    # --- comparison --------------------------------------------------------------------

    def compare(self, that: Duration) -> Literal[-1, 0, 1]:
        """Effect's ``Order``: ``-1``, ``0`` or ``1``."""
        x, y = self._nanos, that._nanos
        return -1 if x < y else 1 if x > y else 0

    def between(self, *, minimum: Duration, maximum: Duration) -> bool:
        """``minimum <= self <= maximum``."""
        return minimum._nanos <= self._nanos <= maximum._nanos

    def clamp(self, *, minimum: Duration, maximum: Duration) -> Duration:
        """``self`` held within ``minimum`` and ``maximum``."""
        return min(max(self, minimum), maximum)

    def min(self, that: Duration) -> Duration:
        return that if that._nanos < self._nanos else self

    def max(self, that: Duration) -> Duration:
        return that if that._nanos > self._nanos else self

    def __bool__(self) -> bool:
        """``False`` for ``zero``, as ``timedelta(0)`` and ``0`` are."""
        return self._nanos != 0

    # Hidden from the type checker, so pyright keeps reporting ``d == 0`` (never true:
    # compare with ``d.is_zero()`` or ``zero``) as a comparison of unrelated types.
    if not TYPE_CHECKING:

        def __eq__(self, other: object) -> bool:
            if not isinstance(other, Duration):
                if isinstance(other, int | float) and not isinstance(other, bool):  # AUDIT-TRAP
                    raise TypeError(f"AUDIT-TRAP: Duration == {other!r}")  # AUDIT-TRAP
                return NotImplemented
            return self._nanos == other._nanos

    def __hash__(self) -> int:
        return hash(self._nanos)

    def __lt__(self, other: Duration) -> bool:
        return self._nanos < other._nanos

    def __le__(self, other: Duration) -> bool:
        return self._nanos <= other._nanos

    def __gt__(self, other: Duration) -> bool:
        return self._nanos > other._nanos

    def __ge__(self, other: Duration) -> bool:
        return self._nanos >= other._nanos

    # --- conversions -------------------------------------------------------------------

    def _to_unit(self, millis_divisor: float, nanos_divisor: int) -> float:
        if self._millis is not None:
            return self._millis / millis_divisor
        n = self._nanos
        if not isinstance(n, int):
            return n
        value = _number(n)
        if math.isfinite(value):
            return value / nanos_divisor
        return (
            _number(_tdiv(n, nanos_divisor))
            + _number(n - nanos_divisor * _tdiv(n, nanos_divisor)) / nanos_divisor
        )

    def to_micros(self) -> float:
        if self._millis is not None:
            return self._millis * 1_000
        return self._to_unit(1, 1_000)

    def to_millis(self) -> float:
        return self._to_unit(1, 1_000_000)

    def to_seconds(self) -> float:
        return self._to_unit(1_000, 1_000_000_000)

    def to_minutes(self) -> float:
        return self._to_unit(60_000, 60_000_000_000)

    def to_hours(self) -> float:
        return self._to_unit(3_600_000, 3_600_000_000_000)

    def to_days(self) -> float:
        return self._to_unit(86_400_000, 86_400_000_000_000)

    def to_weeks(self) -> float:
        return self._to_unit(604_800_000, 604_800_000_000_000)

    def to_nanos(self) -> int | None:
        """The exact nanoseconds, or ``None`` for an infinity (Effect's ``toNanos``)."""
        n = self._nanos
        return n if isinstance(n, int) else None

    def to_nanos_unsafe(self) -> int:
        """The exact nanoseconds; raises ``ValueError`` for an infinity."""
        n = self._nanos
        if isinstance(n, int):
            return n
        raise ValueError("Cannot convert infinite duration to nanos")

    def to_hr_time(self) -> tuple[float, float]:
        """``(seconds, nanos)`` as Node's ``process.hrtime`` (Effect's ``toHrTime``)."""
        n = self._nanos
        if not isinstance(n, int):
            return (n, 0)
        seconds, rest = divmod(abs(n), _E9)
        sign = -1 if n < 0 else 1
        return (_number(sign * seconds), _number(sign * rest))

    def to_timedelta(self) -> timedelta:
        """The nearest ``timedelta`` (whole microseconds, ties to even). Raises
        ``ValueError`` for an infinity and ``OverflowError`` past ``timedelta``'s range."""
        n = self.to_nanos_unsafe()
        micros, rest = divmod(n, _E3)
        if rest * 2 > _E3 or (rest * 2 == _E3 and micros % 2):
            micros += 1
        return timedelta(microseconds=micros)

    def parts(self) -> Parts:
        """Effect's ``Duration.parts``: days, hours, minutes, seconds, millis and the
        remaining nanoseconds, each signed as the duration."""
        n = self._nanos
        if not isinstance(n, int):
            return Parts(days=n, hours=n, minutes=n, seconds=n, millis=n, nanos=n)
        sign = -1.0 if n < 0 else 1.0
        ms, ns = divmod(abs(n), _E6)
        sec, ms = divmod(ms, 1_000)
        minutes, sec = divmod(sec, 60)
        hours, minutes = divmod(minutes, 60)
        days, hours = divmod(hours, 24)
        return Parts(
            days=sign * _number(days),
            hours=sign * hours,
            minutes=sign * minutes,
            seconds=sign * sec,
            millis=sign * ms,
            nanos=sign * ns,
        )

    def format(self) -> str:
        """Human-readable, as Effect's ``Duration.format``: ``"1s 500ms"``."""
        n = self._nanos
        if not isinstance(n, int):
            return "Infinity" if n > 0 else "-Infinity"
        if n == 0:
            return "0"
        if n < 0:
            return "-" + self.abs().format()
        p = self.parts()
        values = (p["days"], p["hours"], p["minutes"], p["seconds"], p["millis"], p["nanos"])
        pieces = [
            f"{js_number(v)}{suffix}"
            for v, suffix in zip(values, _FORMAT_SUFFIXES, strict=True)
            if v
        ]
        return " ".join(pieces)

    def format_iso(self) -> str | None:
        """An ISO 8601 duration (``"P1DT2H3M4.5S"``: days of 24 hours, no years, months
        or weeks), or ``None`` for an infinity (Effect's ``Duration.formatIso``)."""
        n = self._nanos
        return format_iso_nanos(n) if isinstance(n, int) else None

    def to_json(self) -> dict[str, object]:
        """Effect's ``toJSON``."""
        if self._millis is not None:
            return {"_id": "Duration", "_tag": "Millis", "millis": self._millis}
        n = self._nanos
        if isinstance(n, int):
            return {"_id": "Duration", "_tag": "Nanos", "nanos": int_text(n)}
        return {"_id": "Duration", "_tag": "Infinity" if n > 0 else "NegativeInfinity"}

    def __str__(self) -> str:
        if self._millis is not None:
            return f"{js_number(self._millis)} millis"
        n = self._nanos
        if isinstance(n, int):
            return f"{int_text(n)} nanos"
        return "Infinity" if n > 0 else "-Infinity"

    def __repr__(self) -> str:
        if self._millis is not None:
            return f"duration.millis({int(self._millis)})"
        n = self._nanos
        if isinstance(n, int):
            return f"duration.nanos({int_text(n)})"
        return "duration.infinity" if n > 0 else "duration.negative_infinity"


_FORMAT_SUFFIXES: Final = ("d", "h", "m", "s", "ms", "ns")
_INFINITY_VALUE: Final = Infinity()
_NEGATIVE_INFINITY_VALUE: Final = NegativeInfinity()
_new = object.__new__
_set = object.__setattr__


def _build(millis_value: float | None, nanos_value: int | float) -> Duration:
    d = _new(Duration)
    _set(d, "_millis", millis_value)
    _set(d, "_nanos", nanos_value)
    return d


zero: Final = _build(0.0, 0)
infinity: Final = _build(None, math.inf)
negative_infinity: Final = _build(None, -math.inf)


def _make_number(x: float) -> Duration:
    """Effect's ``make`` on a number of milliseconds: NaN and -0 are ``zero``, a fraction
    rounds to whole nanoseconds (ties away from zero)."""
    if x == 0 or math.isnan(x):
        return zero
    if x == math.inf:
        return infinity
    if x == -math.inf:
        return negative_infinity
    if x.is_integer():
        return _build(x, int(x) * _E6)
    return _build(None, _round_ties_away(x * 1_000_000))


def _make_int(n: int) -> Duration:
    """Effect's ``make`` on a ``bigint`` of nanoseconds."""
    return zero if n == 0 else _build(None, n)


def _from_nanos_number(x: float) -> Duration:
    return _make_number(x) if not math.isfinite(x) else _make_int(_round_ties_away(x))


def _scale_infinity(n: float, by: float) -> Duration:
    """An infinity times (or divided by) ``by``: its sign flips with ``by``'s, and a
    zero or NaN ``by`` gives ``zero``."""
    if by > 0:
        return infinity if n > 0 else negative_infinity
    if by < 0:
        return negative_infinity if n > 0 else infinity
    return zero


# --- constructors --------------------------------------------------------------------


def nanos(nanos: int) -> Duration:
    """Whole nanoseconds, exactly."""
    return _make_int(nanos)


def micros(micros: int) -> Duration:
    """Whole microseconds, exactly."""
    return _make_int(micros * _E3)


def millis(millis: float) -> Duration:
    """Milliseconds; a fraction rounds to whole nanoseconds, ties away from zero."""
    return _make_number(_js_float(millis))


def seconds(seconds: float) -> Duration:
    return _make_number(_js_float(seconds) * 1000)


def minutes(minutes: float) -> Duration:
    return _make_number(_js_float(minutes) * 60_000)


def hours(hours: float) -> Duration:
    return _make_number(_js_float(hours) * 3_600_000)


def days(days: float) -> Duration:
    return _make_number(_js_float(days) * 86_400_000)


def weeks(weeks: float) -> Duration:
    return _make_number(_js_float(weeks) * 604_800_000)


def nanos_or_infinite(duration: Duration) -> int | float:
    """The exact nanoseconds, or ``±math.inf`` for an infinity: deadline arithmetic
    (``now_nanos + nanos_or_infinite(d)``) stays exact and an infinite timer never fires."""
    return duration._nanos  # pyright: ignore[reportPrivateUsage]


def from_nanos_or_infinite(nanos: int | float) -> Duration:
    """The inverse of ``nanos_or_infinite``: an ``int`` of nanoseconds or ``±math.inf``."""
    if isinstance(nanos, int):
        return _make_int(nanos)
    return infinity if nanos > 0 else negative_infinity if nanos < 0 else zero


# --- parsing -------------------------------------------------------------------------

type Input = Duration | float | str | tuple[float, float] | DurationObject | timedelta
"""Effect's ``Duration.Input``: milliseconds as a number, a string (``"10 seconds"``,
``"Infinity"``), a ``(seconds, nanos)`` pair, a ``DurationObject``, a ``timedelta`` or a
``Duration``. JavaScript's ``bigint`` of nanoseconds is ``duration.nanos(n)``, since
Python has one ``int``."""

_DURATION_TEXT: Final = re.compile(
    rf"(-?[0-9]+(?:\.[0-9]+)?)[{SPACE}]+"
    r"(nanos?|micros?|millis?|seconds?|minutes?|hours?|days?|weeks?)"
)
_MILLIS_PER_UNIT: Final = {
    "milli": 1,
    "second": 1_000,
    "minute": 60_000,
    "hour": 3_600_000,
    "day": 86_400_000,
    "week": 604_800_000,
}


def _parse_nanos(text: str, scale: int) -> int:
    """Effect's ``parseNanos``: a decimal string times ``scale``, rounded to whole
    nanoseconds with ties away from zero."""
    whole, dot, fraction = text.partition(".")
    if not dot:
        return int(whole) * scale
    negative = whole.startswith("-")
    fraction_scale = 10 ** len(fraction)
    scaled = (int(whole.removeprefix("-")) * fraction_scale + int(fraction)) * scale
    return _divide_ties_away(-scaled if negative else scaled, fraction_scale)


def _from_millis_text(text: str, scale: int) -> Duration:
    millis_value = float(text) * scale
    if not math.isfinite(millis_value):
        return _make_number(millis_value)
    exact = _parse_nanos(text, scale * _E6)
    if millis_value.is_integer() and int(millis_value) * _E6 == exact:
        return _make_number(millis_value)
    return _make_int(exact)


def _from_text(text: str) -> Duration:
    if text == "Infinity":
        return infinity
    if text == "-Infinity":
        return negative_infinity
    match = _DURATION_TEXT.fullmatch(text)
    if match is None:
        raise ValueError(f"Invalid Input: {text}")
    amount, unit = match.groups()
    unit = unit.removesuffix("s")
    if unit == "nano":
        return _make_int(_parse_nanos(amount, 1))
    if unit == "micro":
        return _make_int(_parse_nanos(amount, _E3))
    return _from_millis_text(amount, _MILLIS_PER_UNIT[unit])


def _from_pair(pair: tuple[float, float]) -> Duration:
    s, n = _js_float(pair[0]), _js_float(pair[1])
    if math.isnan(s) or math.isnan(n):
        return zero
    if -math.inf in (s, n):
        return negative_infinity
    if math.inf in (s, n):
        return infinity
    total = s * 1_000_000_000 + n
    if math.isfinite(total) and s.is_integer() and n.is_integer():
        return _make_int(int(s) * _E9 + int(n))
    return _from_nanos_number(total)


_OBJECT_MILLIS: Final = (
    ("weeks", 604_800_000),
    ("days", 86_400_000),
    ("hours", 3_600_000),
    ("minutes", 60_000),
    ("seconds", 1_000),
    ("milliseconds", 1),
)
_OBJECT_NANOS: Final = (
    ("weeks", _NANOS_PER_WEEK),
    ("days", _NANOS_PER_DAY),
    ("hours", _NANOS_PER_HOUR),
    ("minutes", _NANOS_PER_MINUTE),
    ("seconds", _E9),
    ("milliseconds", _E6),
    ("microseconds", _E3),
    ("nanoseconds", 1),
)


def _set_units(obj: Mapping[str, float]) -> dict[str, float]:
    """The units that count: Effect skips falsy ones (zero and NaN)."""
    units: dict[str, float] = {}
    for key, _ in _OBJECT_NANOS:
        x = _js_float(obj.get(key, 0))
        if x and not math.isnan(x):
            units[key] = x
    return units


def _sum_object_nanos(units: Mapping[str, float]) -> int | None:
    """Effect's ``sumObjectNanos``: the units summed exactly, or ``None`` when one is
    fractional."""
    if not all(x.is_integer() for x in units.values()):
        return None
    return sum(int(units[key]) * scale for key, scale in _OBJECT_NANOS if key in units)


def _from_object(obj: Mapping[str, float]) -> Duration:
    units = _set_units(obj)
    total_millis = 0.0
    for key, scale in _OBJECT_MILLIS:
        if key in units:
            total_millis += units[key] * scale
    if "microseconds" not in units and "nanoseconds" not in units:
        if not math.isfinite(total_millis):
            return _make_number(total_millis)
        exact = _sum_object_nanos(units)
        if exact is None or int(total_millis) * _E6 == exact:
            return _make_number(total_millis)
        return _make_int(exact)
    # ``?? 0``, not a truthy check: a NaN unit makes the total NaN.
    micros_value = _js_float(obj.get("microseconds", 0))
    nanos_value = _js_float(obj.get("nanoseconds", 0))
    total = total_millis * 1_000_000 + micros_value * 1_000 + nanos_value
    exact = _sum_object_nanos(units) if math.isfinite(total) else None
    return _from_nanos_number(total) if exact is None else _make_int(exact)


def _from_timedelta(td: timedelta) -> Duration:
    return _from_object({"days": td.days, "seconds": td.seconds, "microseconds": td.microseconds})


def from_input_unsafe(input: Input) -> Duration:
    """Parse an ``Input``; raises ``ValueError`` for one that is not a duration (Effect's
    ``Duration.fromInputUnsafe``)."""
    match input:
        case Duration():
            return input
        case bool():
            raise ValueError(f"Invalid Input: {_js.js_string(input)}")
        case float() | int():
            return _make_number(_js_float(input))
        case str():
            return _from_text(input)
        case timedelta():
            return _from_timedelta(input)
        case (float() | int(), float() | int()):
            return _from_pair(input)
        case Mapping():
            return _from_object(cast("Mapping[str, float]", input))
        case _:
            raise ValueError(f"Invalid Input: {_js.js_string(input)}")


def from_input(input: Input) -> Duration | None:
    """``from_input_unsafe``, or ``None`` for an input that is not a duration (Effect's
    ``Duration.fromInput``)."""
    try:
        return from_input_unsafe(input)
    except ValueError:
        return None


def from_iso(text: str) -> Duration | None:
    """An ISO 8601 duration (weeks, days, hours, minutes and seconds, a fraction of up to
    nine digits on the last time unit), or ``None`` (Effect's ``Duration.fromIso``)."""
    n = parse_iso_nanos(text)
    if n is None:
        return None
    ms, rest = divmod(abs(n), _E6)
    if rest == 0 and ms <= _MAX_SAFE:
        return _make_number(float(-ms if n < 0 else ms))
    return _make_int(n)


# --- conversions of an Input ---------------------------------------------------------


def to_micros(input: Input) -> float:
    return from_input_unsafe(input).to_micros()


def to_millis(input: Input) -> float:
    return from_input_unsafe(input).to_millis()


def to_seconds(input: Input) -> float:
    return from_input_unsafe(input).to_seconds()


def to_minutes(input: Input) -> float:
    return from_input_unsafe(input).to_minutes()


def to_hours(input: Input) -> float:
    return from_input_unsafe(input).to_hours()


def to_days(input: Input) -> float:
    return from_input_unsafe(input).to_days()


def to_weeks(input: Input) -> float:
    return from_input_unsafe(input).to_weeks()


def to_nanos(input: Input) -> int | None:
    """The exact nanoseconds, or ``None`` for an infinity or an invalid input (Effect's
    ``Duration.toNanos``)."""
    parsed = from_input(input)
    return None if parsed is None else parsed.to_nanos()


def to_nanos_unsafe(input: Input) -> int:
    return from_input_unsafe(input).to_nanos_unsafe()


def to_hr_time(input: Input) -> tuple[float, float]:
    return from_input_unsafe(input).to_hr_time()


__all__ = [
    "Duration",
    "DurationObject",
    "DurationValue",
    "Infinity",
    "Input",
    "Millis",
    "Nanos",
    "NegativeInfinity",
    "Parts",
    "Unit",
    "days",
    "from_input",
    "from_input_unsafe",
    "from_iso",
    "from_nanos_or_infinite",
    "hours",
    "infinity",
    "micros",
    "millis",
    "minutes",
    "nanos",
    "nanos_or_infinite",
    "negative_infinity",
    "seconds",
    "to_days",
    "to_hours",
    "to_hr_time",
    "to_micros",
    "to_millis",
    "to_minutes",
    "to_nanos",
    "to_nanos_unsafe",
    "to_seconds",
    "to_weeks",
    "weeks",
    "zero",
]
