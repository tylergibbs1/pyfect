"""The ``Duration`` transformations (Effect's ``durationFromString``,
``durationFromNanos``, ``durationFromMillis``) between a ``timedelta`` and
its text, nanoseconds or milliseconds.

A ``timedelta`` counts whole microseconds within about 2.7 million years,
so a duration it cannot hold once rounded to whole nanoseconds as Effect
rounds it (infinite, ``1 nano``, out of range) fails to decode with
``Expected a duration a timedelta can hold``, where Effect's ``Duration``
would take it; a ``timedelta`` a float of milliseconds cannot hold
exactly (past about 285 years, with microseconds) fails to encode. Text
is Effect's ``Duration`` text: ``"<n> <unit>"`` with ``nanos``,
``micros``, ``millis``, ``seconds``, ``minutes``, ``hours``, ``days`` or
``weeks`` (singular too), written back as ``"<n> millis"``, or
``"<n> nanos"`` when it is not whole milliseconds.
"""

from __future__ import annotations

import math
import re
from datetime import timedelta
from fractions import Fraction
from typing import cast

from pyfect._digits import digits_value
from pyfect._js import js_number
from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.issue import InvalidValue, Issue, reported
from pyfect.schema.transformation._transformation import Transformation, transform_effect

_PATTERN = re.compile(
    r"(-?\d+(?:\.\d+)?)\s+(nanos?|micros?|millis?|seconds?|minutes?|hours?|days?|weeks?)\Z",
    re.ASCII,
)
_NANOS_PER = {
    "nano": 1,
    "micro": 1_000,
    "milli": 1_000_000,
    "second": 1_000_000_000,
    "minute": 60_000_000_000,
    "hour": 3_600_000_000_000,
    "day": 86_400_000_000_000,
    "week": 604_800_000_000_000,
}
_HOLDS = "a duration a timedelta can hold"


_INFINITIES = frozenset({"Infinity", "-Infinity"})


def _from_nanos(nanos: int) -> timedelta | None:
    micros, rest = divmod(nanos, 1000)
    if rest:
        return None
    try:
        return timedelta(microseconds=micros)
    except OverflowError:
        return None


def _exact(text: str) -> Fraction:
    """``-?digits(.digits)?`` exactly, however long."""
    negative = text.startswith("-")
    whole, _, fraction = text.removeprefix("-").partition(".")
    numerator = cast("int", digits_value(whole + fraction))
    value = Fraction(numerator, 10 ** len(fraction))
    return -value if negative else value


def _round_nanos(nanos: Fraction) -> int:
    """Whole nanoseconds, ties away from zero (Effect's ``parseNanos``)."""
    rounded = math.floor(abs(nanos) + Fraction(1, 2))
    return -rounded if nanos < 0 else rounded


def _millis_nanos(millis: float) -> int:
    """Whole nanoseconds, ties away from zero, of the float's shortest text
    (``0.1`` is 0.1 ms, not its binary value). Effect rounds the float
    product ``millis * 1e6``, which agrees but where its error crosses half
    a nanosecond; the text keeps every encoded ``timedelta`` decodable."""
    exact = Fraction(millis) if isinstance(millis, int) else Fraction(js_number(millis))
    return _round_nanos(exact * 1_000_000)


def _nanos_of(duration: timedelta) -> int:
    return (duration // timedelta(microseconds=1)) * 1000


def _invalid(expected: str, input: object, options: ParseOptions) -> Exit[timedelta, Issue]:
    return fail_exit(InvalidValue({"expected": expected}, reported(input, options)))


def _decode_text(text: str, options: ParseOptions) -> Exit[timedelta, Issue]:
    if text in _INFINITIES:
        return _invalid(_HOLDS, text, options)
    match = _PATTERN.match(text)
    if match is None:
        return _invalid("a valid Duration string", text, options)
    value, unit = match.groups()
    duration = _from_nanos(_round_nanos(_exact(value) * _NANOS_PER[unit.removesuffix("s")]))
    return _invalid(_HOLDS, text, options) if duration is None else Success(duration)


def _encode_text(duration: timedelta, _: ParseOptions) -> Exit[str, Issue]:
    nanos = _nanos_of(duration)
    millis, rest = divmod(nanos, 1_000_000)
    return Success(f"{nanos} nanos" if rest else f"{millis} millis")


def _decode_nanos(nanos: int, options: ParseOptions) -> Exit[timedelta, Issue]:
    duration = _from_nanos(nanos)
    return _invalid(_HOLDS, nanos, options) if duration is None else Success(duration)


def _encode_nanos(duration: timedelta, _: ParseOptions) -> Exit[int, Issue]:
    return Success(_nanos_of(duration))


def _decode_millis(millis: float, options: ParseOptions) -> Exit[timedelta, Issue]:
    if isinstance(millis, float) and math.isnan(millis):  # NaN is zero, as Effect's.
        return Success(timedelta(0))
    finite = isinstance(millis, int) or math.isfinite(millis)
    duration = _from_nanos(_millis_nanos(millis)) if finite else None
    return _invalid(_HOLDS, millis, options) if duration is None else Success(duration)


def _encode_millis(duration: timedelta, options: ParseOptions) -> Exit[float, Issue]:
    nanos = _nanos_of(duration)
    millis = nanos / 1_000_000
    if _millis_nanos(millis) != nanos:
        # Past about 285 years a float has no room for the microseconds.
        expected = "a duration a number of milliseconds can hold exactly"
        return fail_exit(InvalidValue({"expected": expected}, reported(duration, options)))
    return Success(int(millis) if millis.is_integer() else millis)


duration_from_string: Transformation[timedelta, str] = transform_effect(
    decode=_decode_text, encode=_encode_text
)
"""A ``timedelta`` from Effect's ``Duration`` text (``"5 seconds"``)."""
duration_from_nanos: Transformation[timedelta, int] = transform_effect(
    decode=_decode_nanos, encode=_encode_nanos
)
"""A ``timedelta`` from a count of nanoseconds."""
duration_from_millis: Transformation[timedelta, float] = transform_effect(
    decode=_decode_millis, encode=_encode_millis
)
"""A ``timedelta`` from a count of milliseconds."""
