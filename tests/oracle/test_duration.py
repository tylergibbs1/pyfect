"""Effect's `Duration.test.ts`: the input forms of `Duration.fromInput`.

A `Duration` is `duration.Seconds` once parsed; Effect's `Duration.nanos(n)` is compared
through `to_nanos`, and `Duration.millis(n)` is the bare number `n`. JavaScript's `bigint`
input (`10n`, nanoseconds) has no Python counterpart, since Python has one `int`: it is the
pair `(0, 10)` or `{"nanoseconds": 10}`. The other titles of the file are arithmetic and
comparisons on a float, so they test Python (`tests/_effect_title_omissions.py`).

Adapted: `Seconds` is a float, exact to the nanosecond below 2**53 ns (about 104 days); past
that Effect keeps a `bigint` and pyfect the float nearest it (PARITY section 4, "Duration
precision"), so those cases assert `nearest(n)`, the correctly rounded `n / 1e9`.
"""

from __future__ import annotations

import math
from datetime import timedelta

import pytest

from pyfect.duration import (
    Duration,
    Seconds,
    from_input,
    nanos_or_infinite,
    to_millis,
    to_nanos,
    to_seconds,
)

INFINITY = Seconds(math.inf)
NEGATIVE_INFINITY = Seconds(-math.inf)


def nanos(duration: Duration) -> int | float:
    return nanos_or_infinite(to_seconds(duration))


def nearest(exact_nanos: int) -> float:
    """The float nearest Effect's exact duration of ``exact_nanos``, in seconds."""
    return exact_nanos / 10**9


_STRINGS: list[tuple[str, int]] = [
    ("1 nano", 1),
    ("10 nanos", 10),
    ("1 micro", 1_000),
    ("10 micros", 10_000),
    ("1 milli", 1_000_000),
    ("10 millis", 10_000_000),
    ("1 second", 1_000_000_000),
    ("10 seconds", 10_000_000_000),
    ("1 minute", 60_000_000_000),
    ("10 minutes", 600_000_000_000),
    ("1 hour", 3_600_000_000_000),
    ("10 hours", 36_000_000_000_000),
    ("1 day", 86_400_000_000_000),
    ("10 days", 864_000_000_000_000),
    ("1 week", 604_800_000_000_000),
    ("10 weeks", 6_048_000_000_000_000),
    ("1.5 seconds", 1_500_000_000),
    ("-1.5 seconds", -1_500_000_000),
]


def test_from_input_unsafe() -> None:
    """fromInputUnsafe"""
    millis100 = to_seconds(100)
    assert to_seconds(millis100) is millis100
    assert nanos(100) == 100_000_000
    assert nanos((0, 10)) == 10

    for text, expected in _STRINGS:
        assert nanos(text) == expected, text
    assert nanos("1.5 nanos") == 2
    assert nanos("-1.5 nanos") == -2
    assert to_seconds("9007199254740993.1 nanos") == nearest(9_007_199_254_740_993)
    assert to_seconds("-9007199254740993.5 nanos") == nearest(-9_007_199_254_740_994)
    assert nanos("1.5 micros") == 1_500
    assert nanos("-1.5 micros") == -1_500
    assert to_seconds("9007199254740993.1 micros") == nearest(9_007_199_254_740_993_100)
    assert to_seconds("-9007199254740993.0005 micros") == nearest(-9_007_199_254_740_993_001)
    assert to_seconds("Infinity") == INFINITY
    assert to_seconds("-Infinity") == NEGATIVE_INFINITY

    assert nanos((500, 123456789)) == 500_123_456_789
    assert nanos((-500, 123456789)) == -500_000_000_000 + 123_456_789
    assert nanos((0, 1.5)) == 2
    assert nanos((0, -1.5)) == -2
    assert nanos((0.0000000005, 0.5)) == 1
    assert to_seconds((math.inf, 0)) == INFINITY
    assert to_seconds((-math.inf, 0)) == NEGATIVE_INFINITY
    assert to_seconds((math.nan, 0)) == 0
    assert to_seconds((0, math.inf)) == INFINITY
    assert to_seconds((0, -math.inf)) == NEGATIVE_INFINITY
    assert to_seconds((0, math.nan)) == 0

    assert to_seconds({}) == 0
    assert to_seconds({"hours": 2}) == 7_200
    assert to_seconds({"weeks": 1}) == 604_800
    assert to_seconds({"days": 3}) == 259_200
    assert to_seconds({"minutes": 45}) == 2_700
    assert to_seconds({"seconds": 30}) == 30
    assert to_seconds({"milliseconds": 500}) == to_seconds(500)
    assert to_seconds({"hours": 1, "minutes": 30}) == 5_400
    assert to_seconds({"hours": -1}) == -3_600
    assert nanos({"seconds": 1, "nanoseconds": 500}) == 1_000_000_500
    assert nanos({"microseconds": 100}) == 100_000
    assert nanos({"microseconds": -1.5}) == -1_500
    assert nanos({"nanoseconds": 1.5}) == 2
    assert nanos({"nanoseconds": -1.5}) == -2
    assert nanos({"milliseconds": 0.0000005, "nanoseconds": 0.5}) == 1
    assert to_seconds({"days": 1, "hours": 2, "minutes": 30, "seconds": 15}) == 95_415


def test_a_bare_number_is_milliseconds() -> None:
    """A number is `Duration.millis`: a whole one exactly, a fraction rounded to the
    nanosecond with ties away from zero (`Duration.make`)."""
    assert to_seconds(1500) == 1.5
    assert to_seconds(-5) == -0.005
    assert nanos(1.0005) == 1_000_500
    assert nanos(0.0000015) == 2
    assert nanos(-0.0000015) == -2
    assert to_seconds(math.inf) == INFINITY
    assert to_seconds(-math.inf) == NEGATIVE_INFINITY
    assert to_seconds(math.nan) == 0
    assert to_seconds(10**400) == INFINITY
    assert to_millis(1_760_450_000_123) == 1_760_450_000_123
    assert to_seconds(timedelta(milliseconds=5)) == to_seconds(5)


def test_from_input_unsafe_preserves_nanoseconds_in_large_decimal_second_strings() -> None:
    """fromInputUnsafe preserves nanoseconds in large decimal second strings"""
    assert to_seconds("17280000.000000001 seconds") == nearest(17_280_000_000_000_001)
    assert to_seconds("-17280000.000000001 seconds") == nearest(-17_280_000_000_000_001)


@pytest.mark.parametrize("sign", [1, -1])
def test_converts_large_finite_millisecond_strings(sign: int) -> None:
    """converts large finite millisecond strings without overflow (sign %s)"""
    text = f"{'-' if sign < 0 else ''}1{'0' * 302}1 millis"
    parsed = to_seconds(text)
    assert math.isfinite(parsed)
    assert (to_millis(text), float(parsed)) == (sign * 1e303, sign * 1e300)


def test_from_input_unsafe_preserves_integer_nanoseconds_in_large_tuple_and_object_inputs() -> None:
    """fromInputUnsafe preserves integer nanoseconds in large tuple and object inputs"""
    assert to_seconds((10_368_000, 123_456_789)) == nearest(10_368_000_123_456_789)
    assert to_seconds({"days": 200, "nanoseconds": 1}) == nearest(17_280_000_000_000_001)
    assert to_seconds({"days": 200_000_000, "milliseconds": 1, "nanoseconds": 1}) == nearest(
        17_280_000_000_000_001_000_001
    )
    assert to_seconds({"days": 200_000_000, "milliseconds": 1}) == nearest(
        17_280_000_000_000_001_000_000
    )


def test_from_input_unsafe_normalizes_infinite_nanosecond_totals() -> None:
    """fromInputUnsafe normalizes infinite nanosecond totals"""
    assert to_seconds((1e300, 1)) == INFINITY
    assert to_seconds({"seconds": -math.inf, "nanoseconds": 1}) == NEGATIVE_INFINITY


def test_from_input() -> None:
    """fromInput"""
    millis100 = to_seconds(100)
    assert from_input(millis100) is millis100
    assert from_input(100) == millis100
    assert from_input((0, 10)) == Seconds(10e-9)
    for text, expected in _STRINGS:
        parsed = from_input(text)
        assert parsed is not None and to_nanos(parsed) == expected, text
    assert from_input("Infinity") == INFINITY
    assert from_input("-Infinity") == NEGATIVE_INFINITY
    assert from_input((500, 123456789)) == Seconds(500.123456789)
    assert from_input((math.inf, 0)) == INFINITY
    assert from_input((-math.inf, 0)) == NEGATIVE_INFINITY
    assert from_input((math.nan, 0)) == 0
    assert from_input((0, math.inf)) == INFINITY
    assert from_input((0, -math.inf)) == NEGATIVE_INFINITY
    assert from_input((0, math.nan)) == 0
    assert from_input("invalid") is None


def test_to_millis() -> None:
    """toMillis"""
    assert to_millis(1) == 1
    assert to_millis((0, 1)) == 0.000001
    assert to_millis("Infinity") == math.inf


def test_to_seconds() -> None:
    """toSeconds"""
    assert to_seconds(1) == 0.001
    assert to_seconds((0, 1)) == 1e-9
    assert to_seconds("Infinity") == math.inf
