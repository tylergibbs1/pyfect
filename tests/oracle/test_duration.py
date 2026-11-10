"""Effect's `Duration.test.ts`.

`deepStrictEqual` on two durations compares their representation (`Millis`, `Nanos` or an
infinity, and its number): `same` compares `.value`. `Equal.equals` is `==`, `Order` is
`compare`, `Option` is `X | None`, `Hash.hash` is `hash`, `HashSet` is `set`,
`ReducerSum` / `CombinerMax` / `CombinerMin` are `sum` / `max` / `min`, and `isDuration` is
`isinstance`. JavaScript's `bigint` input (`10n`) is `duration.nanos(10)`, since Python has one
`int` and a bare number is milliseconds.
"""

from __future__ import annotations

import math
from datetime import timedelta

import pytest

from pyfect import duration
from pyfect.duration import (
    Duration,
    DurationObject,
    Infinity,
    Millis,
    Nanos,
    NegativeInfinity,
    days,
    from_input,
    from_input_unsafe,
    from_iso,
    hours,
    infinity,
    micros,
    millis,
    minutes,
    nanos,
    negative_infinity,
    seconds,
    to_micros,
    to_millis,
    to_nanos,
    to_nanos_unsafe,
    to_seconds,
    weeks,
    zero,
)


def same(actual: Duration | None, expected: Duration) -> None:
    """`deepStrictEqual`: the same representation, not only the same length."""
    assert actual is not None
    assert actual.value == expected.value, (actual, expected)


def test_from_input_unsafe() -> None:  # noqa: PLR0915
    """fromInputUnsafe"""
    millis100 = millis(100)
    assert from_input_unsafe(millis100) is millis100
    same(from_input_unsafe(100), millis100)
    same(from_input_unsafe(nanos(10)), nanos(10))

    same(from_input_unsafe("1 nano"), nanos(1))
    same(from_input_unsafe("10 nanos"), nanos(10))
    same(from_input_unsafe("1.5 nanos"), nanos(2))
    same(from_input_unsafe("-1.5 nanos"), nanos(-2))
    same(from_input_unsafe("9007199254740993.1 nanos"), nanos(9_007_199_254_740_993))
    same(from_input_unsafe("-9007199254740993.5 nanos"), nanos(-9_007_199_254_740_994))
    same(from_input_unsafe("1 micro"), micros(1))
    same(from_input_unsafe("10 micros"), micros(10))
    same(from_input_unsafe("1.5 micros"), nanos(1500))
    same(from_input_unsafe("-1.5 micros"), nanos(-1500))
    same(from_input_unsafe("9007199254740993.1 micros"), nanos(9_007_199_254_740_993_100))
    same(from_input_unsafe("-9007199254740993.0005 micros"), nanos(-9_007_199_254_740_993_001))
    same(from_input_unsafe("1 milli"), millis(1))
    same(from_input_unsafe("10 millis"), millis(10))
    same(from_input_unsafe("1 second"), seconds(1))
    same(from_input_unsafe("10 seconds"), seconds(10))
    same(from_input_unsafe("1 minute"), minutes(1))
    same(from_input_unsafe("10 minutes"), minutes(10))
    same(from_input_unsafe("1 hour"), hours(1))
    same(from_input_unsafe("10 hours"), hours(10))
    same(from_input_unsafe("1 day"), days(1))
    same(from_input_unsafe("10 days"), days(10))
    same(from_input_unsafe("1 week"), weeks(1))
    same(from_input_unsafe("10 weeks"), weeks(10))

    same(from_input_unsafe("1.5 seconds"), seconds(1.5))
    same(from_input_unsafe("-1.5 seconds"), seconds(-1.5))
    same(from_input_unsafe("Infinity"), infinity)
    same(from_input_unsafe("-Infinity"), negative_infinity)

    same(from_input_unsafe((500, 123456789)), nanos(500123456789))
    same(from_input_unsafe((-500, 123456789)), nanos(-500000000000 + 123456789))
    same(from_input_unsafe((0, 1.5)), nanos(2))
    same(from_input_unsafe((0, -1.5)), nanos(-2))
    same(from_input_unsafe((0.0000000005, 0.5)), nanos(1))
    same(from_input_unsafe((math.inf, 0)), infinity)
    same(from_input_unsafe((-math.inf, 0)), negative_infinity)
    same(from_input_unsafe((math.nan, 0)), zero)
    same(from_input_unsafe((0, math.inf)), infinity)
    same(from_input_unsafe((0, -math.inf)), negative_infinity)
    same(from_input_unsafe((0, math.nan)), zero)

    same(from_input_unsafe({}), zero)
    same(from_input_unsafe({"hours": 2}), hours(2))
    same(from_input_unsafe({"weeks": 1}), weeks(1))
    same(from_input_unsafe({"days": 3}), days(3))
    same(from_input_unsafe({"minutes": 45}), minutes(45))
    same(from_input_unsafe({"seconds": 30}), seconds(30))
    same(from_input_unsafe({"milliseconds": 500}), millis(500))
    same(from_input_unsafe({"hours": 1, "minutes": 30}), hours(1).sum(minutes(30)))
    same(from_input_unsafe({"hours": -1}), hours(-1))
    same(from_input_unsafe({"seconds": 1, "nanoseconds": 500}), nanos(1_000_000_500))
    same(from_input_unsafe({"microseconds": 100}), micros(100))
    same(from_input_unsafe({"microseconds": -1.5}), nanos(-1500))
    same(from_input_unsafe({"nanoseconds": 1.5}), nanos(2))
    same(from_input_unsafe({"nanoseconds": -1.5}), nanos(-2))
    same(from_input_unsafe({"milliseconds": 0.0000005, "nanoseconds": 0.5}), nanos(1))
    same(
        from_input_unsafe({"days": 1, "hours": 2, "minutes": 30, "seconds": 15}),
        days(1).sum(hours(2)).sum(minutes(30).sum(seconds(15))),
    )


def test_python_inputs() -> None:
    """A `timedelta` reads as a `DurationObject` of its days, seconds and microseconds; an
    `int` past float range is the infinity a JavaScript number would be; a bool and other
    values are not durations."""
    same(from_input_unsafe(timedelta(milliseconds=5)), millis(5))
    same(from_input_unsafe(timedelta(microseconds=1)), micros(1))
    same(from_input_unsafe(timedelta(days=-1)), days(-1))
    same(from_input_unsafe(10**400), infinity)
    same(from_input_unsafe(-(10**400)), negative_infinity)
    same(from_input_unsafe(2**53 + 1), millis(2**53))
    for invalid in [True, None, "5", (1, 2, 3), [1]]:
        with pytest.raises(ValueError, match="Invalid Input"):
            from_input_unsafe(invalid)  # pyright: ignore[reportArgumentType]


def test_from_input_unsafe_preserves_nanoseconds_in_large_decimal_second_strings() -> None:
    """fromInputUnsafe preserves nanoseconds in large decimal second strings"""
    assert (
        to_nanos_unsafe(from_input_unsafe("17280000.000000001 seconds")) == 17_280_000_000_000_001
    )
    assert (
        to_nanos_unsafe(from_input_unsafe("-17280000.000000001 seconds")) == -17_280_000_000_000_001
    )


@pytest.mark.parametrize("sign", [1, -1])
def test_converts_large_finite_millisecond_strings(sign: int) -> None:
    """converts large finite millisecond strings without overflow (sign %s)"""
    text = f"{'-' if sign < 0 else ''}1{'0' * 302}1 millis"
    assert from_input_unsafe(text).is_finite()
    assert (to_millis(text), to_seconds(text)) == (sign * 1e303, sign * 1e300)


def test_from_input_unsafe_preserves_integer_nanoseconds_in_large_tuple_and_object_inputs() -> None:
    """fromInputUnsafe preserves integer nanoseconds in large tuple and object inputs"""
    same(from_input_unsafe((10_368_000, 123_456_789)), nanos(10_368_000_123_456_789))
    same(from_input_unsafe({"days": 200, "nanoseconds": 1}), nanos(17_280_000_000_000_001))
    same(
        from_input_unsafe({"days": 200_000_000, "milliseconds": 1, "nanoseconds": 1}),
        nanos(17_280_000_000_000_001_000_001),
    )
    same(
        from_input_unsafe({"days": 200_000_000, "milliseconds": 1}),
        nanos(17_280_000_000_000_001_000_000),
    )


def test_from_input_unsafe_normalizes_infinite_nanosecond_totals() -> None:
    """fromInputUnsafe normalizes infinite nanosecond totals"""
    same(from_input_unsafe((1e300, 1)), infinity)
    same(from_input_unsafe({"seconds": -math.inf, "nanoseconds": 1}), negative_infinity)


def test_from_input() -> None:
    """fromInput"""
    millis100 = millis(100)
    assert from_input(millis100) is millis100
    same(from_input(100), millis100)
    same(from_input(nanos(10)), nanos(10))
    for text, expected in [
        ("1 nano", nanos(1)),
        ("10 nanos", nanos(10)),
        ("1 micro", micros(1)),
        ("10 micros", micros(10)),
        ("1 milli", millis(1)),
        ("10 millis", millis(10)),
        ("1 second", seconds(1)),
        ("10 seconds", seconds(10)),
        ("1 minute", minutes(1)),
        ("10 minutes", minutes(10)),
        ("1 hour", hours(1)),
        ("10 hours", hours(10)),
        ("1 day", days(1)),
        ("10 days", days(10)),
        ("1 week", weeks(1)),
        ("10 weeks", weeks(10)),
        ("1.5 seconds", seconds(1.5)),
        ("-1.5 seconds", seconds(-1.5)),
        ("Infinity", infinity),
        ("-Infinity", negative_infinity),
    ]:
        same(from_input(text), expected)
    same(from_input((500, 123456789)), nanos(500123456789))
    same(from_input((-500, 123456789)), nanos(-500000000000 + 123456789))
    same(from_input((math.inf, 0)), infinity)
    same(from_input((-math.inf, 0)), negative_infinity)
    same(from_input((math.nan, 0)), zero)
    same(from_input((0, math.inf)), infinity)
    same(from_input((0, -math.inf)), negative_infinity)
    same(from_input((0, math.nan)), zero)
    assert from_input("invalid") is None


def test_order() -> None:
    """Order"""
    assert millis(1).compare(millis(2)) == -1
    assert millis(2).compare(millis(1)) == 1
    assert millis(2).compare(millis(2)) == 0
    assert millis(1).compare(nanos(2_000_000)) == -1

    assert nanos(1).compare(nanos(2)) == -1
    assert nanos(2).compare(nanos(1)) == 1
    assert nanos(2).compare(nanos(2)) == 0
    assert nanos(2_000_000).compare(millis(1)) == 1

    assert infinity.compare(infinity) == 0
    assert infinity.compare(millis(1)) == 1
    assert infinity.compare(nanos(1)) == 1
    assert millis(1).compare(infinity) == -1
    assert nanos(1).compare(infinity) == -1


def test_equivalence() -> None:
    """Equivalence"""
    assert millis(1) == millis(1)
    assert millis(1) == nanos(1_000_000)
    assert millis(1) != millis(2)

    assert nanos(1) == nanos(1)
    assert nanos(1_000_000) == millis(1)
    assert nanos(1) != nanos(2)

    assert infinity == infinity  # noqa: PLR0124
    assert infinity != millis(1)
    assert infinity != nanos(1)
    assert millis(1) != infinity
    assert nanos(1) != infinity


def test_max() -> None:
    """max"""
    same(millis(1).max(millis(2)), millis(2))
    same(minutes(1).max(millis(2)), minutes(1))


def test_min() -> None:
    """min"""
    same(millis(1).min(millis(2)), millis(1))
    same(minutes(1).min(millis(2)), millis(2))


def test_clamp() -> None:
    """clamp"""
    same(millis(1).clamp(minimum=millis(2), maximum=millis(3)), millis(2))
    same(minutes(1.5).clamp(minimum=minutes(1), maximum=minutes(2)), minutes(1.5))


def test_equals() -> None:
    """equals"""
    assert hours(1) == minutes(60)


def test_hash_agrees_with_equals_across_millis_and_nanos_representations() -> None:
    """Hash.symbol agrees with equals across Millis/Nanos representations"""
    millis_tagged = seconds(5)
    nanos_tagged = nanos(5_000_000_000)

    assert millis_tagged == nanos_tagged
    assert hash(millis_tagged) == hash(nanos_tagged)
    assert hash(millis(-5000)) == hash(nanos(-5_000_000_000))
    assert hash(infinity) == hash(infinity)
    assert infinity != negative_infinity

    assert nanos_tagged in {millis_tagged}
    assert millis(2**1023) == nanos(1_000_000 << 1023)


def test_hash_handles_finite_millis_too_large_to_convert_to_nanos() -> None:
    """Hash.symbol handles finite millis too large to convert to nanos"""
    large = millis(1e303)
    assert large == millis(1e303)
    assert millis(1e303) in {large}


def test_between() -> None:
    """between"""
    assert hours(1).between(minimum=minutes(59), maximum=minutes(61))
    assert minutes(1).between(minimum=seconds(59), maximum=seconds(61))


def test_divide() -> None:
    """divide"""
    same(minutes(1).divide(2), seconds(30))
    same(seconds(1).divide(3), nanos(333333333))
    same(zero.divide(2), zero)
    same(minutes(1).divide(0.5), minutes(2))
    same(minutes(1).divide(1.5), seconds(40))

    same(nanos(2).divide(2), nanos(1))
    same(nanos(1).divide(3), zero)
    assert nanos(1).divide(0.5) is None
    assert nanos(1).divide(1.5) is None

    same(infinity.divide(2), infinity)
    same(infinity.divide(-2), negative_infinity)
    same(negative_infinity.divide(-2), infinity)

    for by in [0.0, -0.0, math.nan, math.inf, -math.inf]:
        assert minutes(1).divide(by) is None
        assert nanos(1).divide(by) is None
    for by in [math.nan, math.inf, -math.inf]:
        assert infinity.divide(by) is None


def test_divide_unsafe() -> None:
    """divideUnsafe"""
    same(minutes(1).divide_unsafe(2), seconds(30))
    same(seconds(1).divide_unsafe(3), nanos(333333333))
    same(zero.divide_unsafe(2), zero)
    same(minutes(1).divide_unsafe(0.5), minutes(2))
    same(minutes(1).divide_unsafe(1.5), seconds(40))

    same(nanos(2).divide_unsafe(2), nanos(1))
    same(nanos(1).divide_unsafe(3), zero)
    same(nanos(1).divide_unsafe(0.5), zero)
    same(nanos(1).divide_unsafe(1.5), zero)

    same(infinity.divide_unsafe(2), infinity)

    same(minutes(1).divide_unsafe(0.0), infinity)
    same(minutes(1).divide_unsafe(-0.0), negative_infinity)
    same(nanos(1).divide_unsafe(0.0), infinity)
    same(nanos(1).divide_unsafe(-0.0), negative_infinity)
    same(nanos(-1).divide_unsafe(0.0), negative_infinity)
    same(nanos(-1).divide_unsafe(-0.0), infinity)
    same(zero.divide_unsafe(0.0), zero)
    same(zero.divide_unsafe(-0.0), zero)

    for by in [math.nan, math.inf, -math.inf]:
        same(minutes(1).divide_unsafe(by), zero)
        same(nanos(1).divide_unsafe(by), zero)
        same(infinity.divide_unsafe(by), zero)


def test_times() -> None:
    """times"""
    same(seconds(1).times(60), minutes(1))
    same(nanos(2).times(10), nanos(20))
    same(nanos(3).times(1.5), nanos(5))
    same(nanos(5_000_000).times(0.0000003), millis(5).times(0.0000003))
    same(nanos(3).times(-0.5), nanos(-2))
    same(nanos(9007199254740993).times(0.5), nanos(4503599627370497))
    same(nanos(9007199254740991).times(1.5), nanos(13510798882111487))
    same(nanos(3002399751580334).times(1.5), nanos(4503599627370501))
    same(nanos(10**400).times(0.5), nanos(10**400 // 2))
    same(nanos(1).times(math.inf), infinity)
    same(nanos(1).times(math.nan), zero)
    same(infinity.times(60), infinity)


def test_sum() -> None:
    """sum"""
    same(seconds(30).sum(seconds(30)), minutes(1))
    same(nanos(30).sum(nanos(30)), nanos(60))
    same(infinity.sum(seconds(30)), infinity)
    same(seconds(30).sum(infinity), infinity)
    same(infinity.sum(nanos(1)), infinity)
    same(nanos(1).sum(infinity), infinity)
    same(infinity.sum(infinity), infinity)


def test_subtract() -> None:
    """subtract"""
    same(seconds(30).subtract(seconds(10)), seconds(20))
    same(seconds(30).subtract(seconds(30)), zero)
    same(seconds(30).subtract(seconds(40)), seconds(-10))

    same(nanos(30).subtract(nanos(10)), nanos(20))
    same(nanos(30).subtract(nanos(30)), zero)
    same(nanos(30).subtract(nanos(40)), nanos(-10))

    same(infinity.subtract(seconds(30)), infinity)
    same(infinity.subtract(nanos(30)), infinity)
    same(seconds(30).subtract(infinity), negative_infinity)
    same(nanos(30).subtract(infinity), negative_infinity)
    same(infinity.subtract(infinity), zero)

    same(infinity.subtract(negative_infinity), infinity)
    same(negative_infinity.subtract(infinity), negative_infinity)
    same(negative_infinity.subtract(negative_infinity), zero)
    same(negative_infinity.subtract(seconds(5)), negative_infinity)
    same(seconds(5).subtract(negative_infinity), infinity)


def test_is_greater_than() -> None:
    """isGreaterThan"""
    assert seconds(30) > seconds(20)
    assert not seconds(30) > seconds(30)
    assert not seconds(30) > seconds(60)
    assert nanos(30) > nanos(20)
    assert not nanos(30) > nanos(30)
    assert not nanos(30) > nanos(60)
    assert millis(1) > nanos(1)
    assert infinity > seconds(20)
    assert not seconds(-math.inf) > infinity
    assert not nanos(1) > infinity


def test_is_greater_than_or_equal_to() -> None:
    """isGreaterThanOrEqualTo"""
    assert seconds(30) >= seconds(20)
    assert seconds(30) >= seconds(30)
    assert not seconds(30) >= seconds(60)
    assert nanos(30) >= nanos(20)
    assert nanos(30) >= nanos(30)
    assert not nanos(30) >= nanos(60)


def test_is_less_than() -> None:
    """isLessThan"""
    assert seconds(20) < seconds(30)
    assert not seconds(30) < seconds(30)
    assert not seconds(60) < seconds(30)
    assert nanos(20) < nanos(30)
    assert not nanos(30) < nanos(30)
    assert not nanos(60) < nanos(30)
    assert nanos(1) < millis(1)


def test_is_less_than_or_equal_to() -> None:
    """isLessThanOrEqualTo"""
    assert seconds(20) <= seconds(30)
    assert seconds(30) <= seconds(30)
    assert not seconds(60) <= seconds(30)
    assert nanos(20) <= nanos(30)
    assert nanos(30) <= nanos(30)
    assert not nanos(60) <= nanos(30)


def test_to_string() -> None:
    """toString()"""
    assert str(infinity) == "Infinity"
    assert str(nanos(10)) == "10 nanos"
    assert str(millis(2)) == "2 millis"
    assert str(millis(2.125)) == "2125000 nanos"
    assert str(seconds(2)) == "2000 millis"
    assert str(seconds(2.5)) == "2500 millis"


def test_format() -> None:
    """format"""
    assert infinity.format() == "Infinity"
    assert minutes(5).format() == "5m"
    assert minutes(5.325).format() == "5m 19s 500ms"
    assert hours(3).format() == "3h"
    assert hours(3.11125).format() == "3h 6m 40s 500ms"
    assert days(2).format() == "2d"
    assert days(2.25).format() == "2d 6h"
    assert weeks(1).format() == "7d"
    assert zero.format() == "0"


def test_format_iso() -> None:
    """ISO 8601 > formatIso"""
    assert zero.format_iso() == "PT0S"
    assert millis(-0.0).format_iso() == "PT0S"
    assert weeks(1).format_iso() == "P7D"
    assert hours(26).format_iso() == "P1DT2H"
    assert minutes(90).format_iso() == "PT1H30M"
    assert millis(1500).format_iso() == "PT1.5S"
    assert millis(86_400_001).format_iso() == "P1DT0.001S"
    assert nanos(1).format_iso() == "PT0.000000001S"
    assert millis(-93_784_500).format_iso() == "-P1DT2H3M4.5S"
    assert infinity.format_iso() is None
    assert negative_infinity.format_iso() is None


def test_from_iso() -> None:
    """ISO 8601 > fromIso"""
    valid = [
        ("PT0S", zero),
        ("P0D", zero),
        ("-PT0S", zero),
        ("+P1D", days(1)),
        ("-P1D", days(-1)),
        ("P1W2D", days(9)),
        ("PT1.5H", minutes(90)),
        ("PT1H0.5M", seconds(3630)),
        ("PT1,5S", millis(1500)),
        ("PT1.123456789S", nanos(1_123_456_789)),
        ("-P1DT2H3M4.5S", millis(-93_784_500)),
        ("P400D", days(400)),
    ]
    for text, expected in valid:
        assert from_iso(text) == expected, text
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
    same(from_iso("PT1.5S"), millis(1500))
    same(from_iso("PT0.000000001S"), nanos(1))
    same(from_iso("PT9007199254740.993S"), nanos(9_007_199_254_740_993_000_000))


def test_format_iso_from_iso_round_trip() -> None:
    """ISO 8601 > formatIso / fromIso round trip"""
    for d in [
        nanos(1),
        millis(0.5),
        minutes(90),
        days(400),
        millis(-1500),
        nanos(123_456_789_012_345_678),
    ]:
        text = d.format_iso()
        assert text is not None
        assert from_iso(text) == d, str(d)
    assert nanos(123_456_789_012_345_678).format_iso() == "P1428DT21H33M9.012345678S"


def test_parts() -> None:
    """parts"""
    inf = math.inf
    assert infinity.parts() == {
        "days": inf,
        "hours": inf,
        "minutes": inf,
        "seconds": inf,
        "millis": inf,
        "nanos": inf,
    }
    assert minutes(5.325).parts() == {
        "days": 0,
        "hours": 0,
        "minutes": 5,
        "seconds": 19,
        "millis": 500,
        "nanos": 0,
    }
    assert minutes(3.11125).parts() == {
        "days": 0,
        "hours": 0,
        "minutes": 3,
        "seconds": 6,
        "millis": 675,
        "nanos": 0,
    }


def test_to_json() -> None:
    """toJSON"""
    assert seconds(2).to_json() == {"_id": "Duration", "_tag": "Millis", "millis": 2000}
    assert nanos(5).to_json() == {"_id": "Duration", "_tag": "Nanos", "nanos": "5"}
    assert millis(1.5).to_json() == {"_id": "Duration", "_tag": "Nanos", "nanos": "1500000"}
    assert infinity.to_json() == {"_id": "Duration", "_tag": "Infinity"}


def test_pipe() -> None:
    """.pipe()"""
    same(seconds(1).pipe(lambda d: d.sum(seconds(1))), seconds(2))


def test_is_duration() -> None:
    """isDuration"""
    assert isinstance(millis(100), Duration)
    assert not isinstance(None, Duration)


def test_zero() -> None:
    """zero"""
    same(seconds(1).sum(zero), seconds(1))


def test_weeks() -> None:
    """weeks"""
    assert weeks(1) == days(7)
    assert weeks(1) != days(1)


def test_to_micros() -> None:
    """toMicros"""
    assert millis(1).to_micros() == 1000
    assert nanos(1).to_micros() == 0.001
    assert infinity.to_micros() == math.inf
    assert to_micros("1 milli") == 1000


def test_to_millis() -> None:
    """toMillis"""
    assert millis(1).to_millis() == 1
    assert nanos(1).to_millis() == 0.000001
    assert infinity.to_millis() == math.inf
    assert to_millis(1) == 1


def test_to_seconds() -> None:
    """toSeconds"""
    assert millis(1).to_seconds() == 0.001
    assert nanos(1).to_seconds() == 1e-9
    assert infinity.to_seconds() == math.inf
    assert to_seconds("1 milli") == 0.001


def test_to_nanos() -> None:
    """toNanos"""
    assert nanos(1).to_nanos() == 1
    assert infinity.to_nanos() is None
    assert negative_infinity.to_nanos() is None
    assert millis(1.0005).to_nanos() == 1_000_500
    assert millis(100).to_nanos() == 100_000_000
    assert to_nanos("invalid") is None


def test_to_nanos_unsafe() -> None:
    """toNanosUnsafe"""
    assert nanos(1).to_nanos_unsafe() == 1
    with pytest.raises(ValueError, match="Cannot convert infinite duration to nanos"):
        infinity.to_nanos_unsafe()
    assert millis(1.0005).to_nanos_unsafe() == 1_000_500
    assert millis(0.0000015).to_nanos_unsafe() == 2
    assert millis(-0.0000015).to_nanos_unsafe() == -2
    assert millis(100).to_nanos_unsafe() == 100_000_000
    assert millis(2**1023).to_nanos_unsafe() == 1_000_000 << 1023
    assert millis(1_760_450_000_123).to_nanos_unsafe() == 1_760_450_000_123_000_000


def test_to_hr_time() -> None:
    """toHrTime"""
    assert millis(1).to_hr_time() == (0, 1_000_000)
    assert nanos(1).to_hr_time() == (0, 1)
    assert nanos(1_000_000_001).to_hr_time() == (1, 1)
    assert millis(1001).to_hr_time() == (1, 1_000_000)
    assert infinity.to_hr_time() == (math.inf, 0)


def test_negative_values() -> None:  # noqa: PLR0915
    """negative values"""
    assert millis(-1).is_negative()
    assert nanos(-1).is_negative()
    assert millis(-1).to_millis() == -1
    assert nanos(-1).to_nanos_unsafe() == -1

    assert seconds(-5).is_negative()
    assert not zero.is_negative()
    assert not seconds(5).is_negative()
    assert not infinity.is_negative()
    assert negative_infinity.is_negative()

    assert seconds(5).is_positive()
    assert not zero.is_positive()
    assert not seconds(-5).is_positive()
    assert infinity.is_positive()
    assert not negative_infinity.is_positive()

    same(seconds(-5).abs(), seconds(5))
    same(seconds(5).abs(), seconds(5))
    same(zero.abs(), zero)
    same(negative_infinity.abs(), infinity)
    same(infinity.abs(), infinity)

    same(seconds(5).negate(), seconds(-5))
    same(seconds(-5).negate(), seconds(5))
    same(zero.negate(), zero)
    same(infinity.negate(), negative_infinity)
    same(negative_infinity.negate(), infinity)

    assert not negative_infinity.is_finite()
    assert not negative_infinity.is_zero()
    assert negative_infinity.to_millis() == -math.inf
    assert negative_infinity.to_seconds() == -math.inf
    assert negative_infinity.to_hr_time() == (-math.inf, 0)

    assert seconds(-5).format() == "-5s"
    assert negative_infinity.format() == "-Infinity"

    assert negative_infinity.compare(negative_infinity) == 0
    assert negative_infinity.compare(seconds(-5)) == -1
    assert seconds(-5).compare(negative_infinity) == 1
    assert negative_infinity.compare(infinity) == -1
    assert infinity.compare(negative_infinity) == 1
    assert seconds(-5).compare(seconds(-3)) == -1
    assert seconds(-3).compare(seconds(-5)) == 1

    assert negative_infinity == negative_infinity  # noqa: PLR0124
    assert negative_infinity != infinity

    same(infinity.sum(negative_infinity), zero)
    same(negative_infinity.sum(infinity), zero)
    same(negative_infinity.sum(negative_infinity), negative_infinity)
    same(negative_infinity.sum(seconds(5)), negative_infinity)

    same(infinity.times(-1), negative_infinity)
    same(negative_infinity.times(-1), infinity)
    same(infinity.times(0), zero)
    same(seconds(5).times(-2), seconds(-10))

    assert negative_infinity.parts() == dict.fromkeys(
        ("days", "hours", "minutes", "seconds", "millis", "nanos"), -math.inf
    )

    assert str(negative_infinity) == "-Infinity"
    assert str(millis(-5)) == "-5 millis"
    assert str(nanos(-10)) == "-10 nanos"

    assert negative_infinity.to_json() == {"_id": "Duration", "_tag": "NegativeInfinity"}


def test_match() -> None:
    """match"""

    def match(d: Duration) -> str:
        return d.match(
            on_millis=lambda m: f"millis: {duration.millis(m).to_millis():.0f}",
            on_nanos=lambda n: f"nanos: {n}",
            on_infinity=lambda: "infinity",
        )

    assert match(millis(100)) == "millis: 100"
    assert match(nanos(10)) == "nanos: 10"
    assert match(infinity) == "infinity"


def test_is_finite() -> None:
    """isFinite"""
    assert millis(100).is_finite()
    assert nanos(100).is_finite()
    assert not infinity.is_finite()


def test_is_zero() -> None:
    """isZero"""
    assert zero.is_zero()
    assert millis(0).is_zero()
    assert nanos(0).is_zero()
    assert not infinity.is_zero()
    assert not millis(1).is_zero()
    assert not nanos(1).is_zero()


def test_to_minutes() -> None:
    """toMinutes"""
    assert millis(60000).to_minutes() == 1
    assert nanos(60000000000).to_minutes() == 1
    assert infinity.to_minutes() == math.inf


def test_to_hours() -> None:
    """toHours"""
    assert millis(3_600_000).to_hours() == 1
    assert nanos(3_600_000_000_000).to_hours() == 1
    assert infinity.to_hours() == math.inf


def test_to_days() -> None:
    """toDays"""
    assert millis(86_400_000).to_days() == 1
    assert nanos(86_400_000_000_000).to_days() == 1
    assert infinity.to_days() == math.inf


def test_to_weeks() -> None:
    """toWeeks"""
    assert millis(604_800_000).to_weeks() == 1
    assert nanos(604_800_000_000_000).to_weeks() == 1
    assert infinity.to_weeks() == math.inf


def test_reducer_sum() -> None:
    """ReducerSum"""
    same(sum([millis(1), millis(2)], zero), millis(3))


def test_combiner_max() -> None:
    """CombinerMax"""
    same(max(millis(1), millis(2)), millis(2))


def test_combiner_min() -> None:
    """CombinerMin"""
    same(min(millis(1), millis(2)), millis(1))


def test_value_forms() -> None:
    """`value` is Effect's `DurationValue`, a class per `_tag`."""
    assert millis(5).value == Millis(5)
    assert nanos(5).value == Nanos(5)
    assert infinity.value == Infinity()
    assert negative_infinity.value == NegativeInfinity()
    assert zero.value == Millis(0)


def test_operators_follow_the_named_functions() -> None:
    """`+`, `-`, `*`, unary `-` and `abs` are `sum`, `subtract`, `times`, `negate` and `abs`;
    `bool` is `False` only for a zero length, as for `timedelta`."""
    same(seconds(1) + millis(500), millis(1500))
    same(seconds(1) - nanos(1), nanos(999_999_999))
    same(nanos(3) * 1.5, nanos(5))
    same(1.5 * nanos(3), nanos(5))
    same(-seconds(1), seconds(-1))
    same(abs(negative_infinity), infinity)
    assert not zero
    assert not nanos(0)
    assert seconds(1)
    assert negative_infinity


def test_immutable_and_picklable() -> None:
    import copy
    import pickle

    d = nanos(5)
    with pytest.raises(AttributeError):
        d._nanos = 6  # pyright: ignore[reportPrivateUsage]
    with pytest.raises(TypeError):
        Duration()  # pyright: ignore[reportCallIssue]
    for value in [millis(5), nanos(-7), infinity, negative_infinity, zero, millis(1e303)]:
        same(pickle.loads(pickle.dumps(value)), value)
        same(copy.deepcopy(value), value)


def test_to_timedelta() -> None:
    """A `timedelta` out, rounded to whole microseconds (ties to even)."""
    assert seconds(1.5).to_timedelta() == timedelta(seconds=1.5)
    assert nanos(1_500).to_timedelta() == timedelta(microseconds=2)
    assert nanos(2_500).to_timedelta() == timedelta(microseconds=2)
    assert nanos(-1_500).to_timedelta() == timedelta(microseconds=-2)
    with pytest.raises(ValueError, match="infinite"):
        infinity.to_timedelta()
    with pytest.raises(OverflowError):
        days(10**12).to_timedelta()


def test_duration_object_is_a_typed_dict() -> None:
    units: DurationObject = {"seconds": 1, "nanoseconds": 5}
    same(from_input_unsafe(units), nanos(1_000_000_005))
