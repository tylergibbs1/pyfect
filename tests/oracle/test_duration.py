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
    format_iso,
    from_input,
    from_input_unsafe,
    from_iso,
    from_nanos,
    infinity,
    nanos,
    nanos_or_infinite,
    to_micros,
    to_millis,
    to_nanos,
)
from pyfect.duration import (
    Input as DurationInput,
)

INFINITY = infinity
NEGATIVE_INFINITY = Duration(-math.inf)


def nanos(duration: DurationInput) -> int | float:
    return nanos_or_infinite(from_input_unsafe(duration))


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
    millis100 = from_input_unsafe(100)
    assert from_input_unsafe(millis100) is millis100
    assert nanos(100) == 100_000_000
    assert nanos((0, 10)) == 10

    for text, expected in _STRINGS:
        assert nanos(text) == expected, text
    assert nanos("1.5 nanos") == 2
    assert nanos("-1.5 nanos") == -2
    assert from_input_unsafe("9007199254740993.1 nanos") == nearest(9_007_199_254_740_993)
    assert from_input_unsafe("-9007199254740993.5 nanos") == nearest(-9_007_199_254_740_994)
    assert nanos("1.5 micros") == 1_500
    assert nanos("-1.5 micros") == -1_500
    assert from_input_unsafe("9007199254740993.1 micros") == nearest(9_007_199_254_740_993_100)
    assert from_input_unsafe("-9007199254740993.0005 micros") == nearest(-9_007_199_254_740_993_001)
    assert from_input_unsafe("Infinity") == INFINITY
    assert from_input_unsafe("-Infinity") == NEGATIVE_INFINITY

    assert nanos((500, 123456789)) == 500_123_456_789
    assert nanos((-500, 123456789)) == -500_000_000_000 + 123_456_789
    assert nanos((0, 1.5)) == 2
    assert nanos((0, -1.5)) == -2
    assert nanos((0.0000000005, 0.5)) == 1
    assert from_input_unsafe((math.inf, 0)) == INFINITY
    assert from_input_unsafe((-math.inf, 0)) == NEGATIVE_INFINITY
    assert from_input_unsafe((math.nan, 0)) == 0
    assert from_input_unsafe((0, math.inf)) == INFINITY
    assert from_input_unsafe((0, -math.inf)) == NEGATIVE_INFINITY
    assert from_input_unsafe((0, math.nan)) == 0

    assert from_input_unsafe({}) == 0
    assert from_input_unsafe({"hours": 2}) == 7_200
    assert from_input_unsafe({"weeks": 1}) == 604_800
    assert from_input_unsafe({"days": 3}) == 259_200
    assert from_input_unsafe({"minutes": 45}) == 2_700
    assert from_input_unsafe({"seconds": 30}) == 30
    assert from_input_unsafe({"milliseconds": 500}) == from_input_unsafe(500)
    assert from_input_unsafe({"hours": 1, "minutes": 30}) == 5_400
    assert from_input_unsafe({"hours": -1}) == -3_600
    assert nanos({"seconds": 1, "nanoseconds": 500}) == 1_000_000_500
    assert nanos({"microseconds": 100}) == 100_000
    assert nanos({"microseconds": -1.5}) == -1_500
    assert nanos({"nanoseconds": 1.5}) == 2
    assert nanos({"nanoseconds": -1.5}) == -2
    assert nanos({"milliseconds": 0.0000005, "nanoseconds": 0.5}) == 1
    assert from_input_unsafe({"days": 1, "hours": 2, "minutes": 30, "seconds": 15}) == 95_415


def test_a_bare_number_is_milliseconds() -> None:
    """A number is `Duration.millis`: a whole one exactly, a fraction rounded to the
    nanosecond with ties away from zero (`Duration.make`)."""
    assert from_input_unsafe(1500) == 1.5
    assert from_input_unsafe(-5) == -0.005
    assert nanos(1.0005) == 1_000_500
    assert nanos(0.0000015) == 2
    assert nanos(-0.0000015) == -2
    assert from_input_unsafe(math.inf) == INFINITY
    assert from_input_unsafe(-math.inf) == NEGATIVE_INFINITY
    assert from_input_unsafe(math.nan) == 0
    assert from_input_unsafe(10**400) == INFINITY
    assert to_millis(1_760_450_000_123) == 1_760_450_000_123
    assert from_input_unsafe(timedelta(milliseconds=5)) == from_input_unsafe(5)


def test_from_input_unsafe_preserves_nanoseconds_in_large_decimal_second_strings() -> None:
    """fromInputUnsafe preserves nanoseconds in large decimal second strings"""
    assert from_input_unsafe("17280000.000000001 seconds") == nearest(17_280_000_000_000_001)
    assert from_input_unsafe("-17280000.000000001 seconds") == nearest(-17_280_000_000_000_001)


@pytest.mark.parametrize("sign", [1, -1])
def test_converts_large_finite_millisecond_strings(sign: int) -> None:
    """converts large finite millisecond strings without overflow (sign %s)"""
    text = f"{'-' if sign < 0 else ''}1{'0' * 302}1 millis"
    parsed = from_input_unsafe(text)
    assert math.isfinite(parsed)
    assert (to_millis(text), float(parsed)) == (sign * 1e303, sign * 1e300)


def test_from_input_unsafe_preserves_integer_nanoseconds_in_large_tuple_and_object_inputs() -> None:
    """fromInputUnsafe preserves integer nanoseconds in large tuple and object inputs"""
    assert from_input_unsafe((10_368_000, 123_456_789)) == nearest(10_368_000_123_456_789)
    assert from_input_unsafe({"days": 200, "nanoseconds": 1}) == nearest(17_280_000_000_000_001)
    assert from_input_unsafe({"days": 200_000_000, "milliseconds": 1, "nanoseconds": 1}) == nearest(
        17_280_000_000_000_001_000_001
    )
    assert from_input_unsafe({"days": 200_000_000, "milliseconds": 1}) == nearest(
        17_280_000_000_000_001_000_000
    )


def test_from_input_unsafe_normalizes_infinite_nanosecond_totals() -> None:
    """fromInputUnsafe normalizes infinite nanosecond totals"""
    assert from_input_unsafe((1e300, 1)) == INFINITY
    assert from_input_unsafe({"seconds": -math.inf, "nanoseconds": 1}) == NEGATIVE_INFINITY


def test_from_input() -> None:
    """fromInput"""
    millis100 = from_input_unsafe(100)
    assert from_input(millis100) is millis100
    assert from_input(100) == millis100
    assert from_input((0, 10)) == Duration(10e-9)
    for text, expected in _STRINGS:
        parsed = from_input(text)
        assert parsed is not None and to_nanos(parsed) == expected, text
    assert from_input("Infinity") == INFINITY
    assert from_input("-Infinity") == NEGATIVE_INFINITY
    assert from_input((500, 123456789)) == nanos(500_123_456_789)
    assert from_input((math.inf, 0)) == INFINITY
    assert from_input((-math.inf, 0)) == NEGATIVE_INFINITY
    assert from_input((math.nan, 0)) == 0
    assert from_input((0, math.inf)) == INFINITY
    assert from_input((0, -math.inf)) == NEGATIVE_INFINITY
    assert from_input((0, math.nan)) == 0
    assert from_input("invalid") is None


def test_to_micros() -> None:
    """toMicros"""
    assert to_micros(1) == 1000
    assert to_micros((0, 1)) == 0.001
    assert to_micros("Infinity") == math.inf


def test_format_iso() -> None:
    """ISO 8601 > formatIso"""
    for duration, expected in [
        (0, "PT0S"),
        (-0.0, "PT0S"),
        ("1 week", "P7D"),
        ("26 hours", "P1DT2H"),
        ("90 minutes", "PT1H30M"),
        (1500, "PT1.5S"),
        (86_400_001, "P1DT0.001S"),
        ((0, 1), "PT0.000000001S"),
        (-93_784_500, "-P1DT2H3M4.5S"),
    ]:
        assert format_iso(from_input_unsafe(duration)) == expected, duration
    assert format_iso(INFINITY) is None
    assert format_iso(NEGATIVE_INFINITY) is None


def test_from_iso() -> None:
    """ISO 8601 > fromIso"""
    valid: list[tuple[str, DurationInput]] = [
        ("PT0S", 0),
        ("P0D", 0),
        ("-PT0S", 0),
        ("+P1D", "1 day"),
        ("-P1D", {"days": -1}),
        ("P1W2D", "9 days"),
        ("PT1.5H", "90 minutes"),
        ("PT1H0.5M", "3630 seconds"),
        ("PT1,5S", 1500),
        ("PT1.123456789S", (0, 1_123_456_789)),
        ("-P1DT2H3M4.5S", -93_784_500),
        ("P400D", "400 days"),
    ]
    for text, expected in valid:
        assert from_iso(text) == from_input_unsafe(expected), text
    for text in [
        "",
        "P",
        "PT",
        "-P",
        "P1DT",
        "P1.5D",
        "P1.5W",
        "PT1.5H1M",
        "PT.5S",
        "PT1.S",
        "PT1.1234567891S",
        "P1D1W",
        "PT1S1M",
        "P-1D",
        " P1D",
        "pt1s",
        "P1Y",
        "P1M",
        "P1MT1H",
        "-P1M",
        "PT1S\n",
        "PT\u0661S",
    ]:
        assert from_iso(text) is None, text
    assert from_iso("PT1.5S") == from_input_unsafe(1500)
    assert from_iso("PT0.000000001S") == from_input_unsafe((0, 1))
    assert from_iso("PT9007199254740.993S") == nearest(9_007_199_254_740_993_000_000)


def test_format_iso_from_iso_round_trip() -> None:
    """ISO 8601 > formatIso / fromIso round trip"""
    for duration in [
        from_input_unsafe((0, 1)),
        from_input_unsafe(0.5),
        from_input_unsafe("90 minutes"),
        from_input_unsafe("400 days"),
        from_input_unsafe(-1500),
        from_nanos(123_456_789_012_345_678),
    ]:
        text = format_iso(duration)
        assert text is not None
        assert from_iso(text) == duration, text


def test_to_millis() -> None:
    """toMillis"""
    assert to_millis(1) == 1
    assert to_millis((0, 1)) == 0.000001
    assert to_millis("Infinity") == math.inf


def test_to_seconds() -> None:
    """toSeconds"""
    assert from_input_unsafe(1) == 0.001
    assert from_input_unsafe((0, 1)) == 1e-9
    assert from_input_unsafe("Infinity") == math.inf
