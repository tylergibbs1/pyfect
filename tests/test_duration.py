"""Durations: parsed once at the boundary, so every consumer agrees."""

import asyncio
import math
import time
from datetime import timedelta

import pytest

import pyfect as fx
from pyfect import schedule
from pyfect.duration import (
    Duration,
    from_input_unsafe,
    infinity,
    millis,
    nanos,
    negative_infinity,
    seconds,
    zero,
)
from pyfect.duration import Input as DurationInput


@pytest.mark.parametrize(
    ("given", "expected"),
    [
        (float("nan"), zero),
        (-0.0, zero),
        (1500, millis(1500)),
        (1.5, nanos(1_500_000)),
        (timedelta(milliseconds=1500), millis(1500)),
        (millis(1500), millis(1500)),
    ],
)
def test_parsing_normalises_like_effect_duration_make(given: DurationInput, expected: Duration):
    """A bare number is milliseconds (Effect's ``Duration.millis``), and
    ``Duration.make`` maps NaN (and -0) to zero."""
    parsed = from_input_unsafe(given)
    assert isinstance(parsed, Duration)
    assert parsed.value == expected.value


def test_a_parsed_duration_passes_through_unchanged():
    """A ``Duration`` input is returned as it is (Effect's ``fromInputUnsafe``): it is not
    read again as milliseconds."""
    parsed = from_input_unsafe("2 seconds")
    assert from_input_unsafe(parsed) is parsed


def test_arithmetic_keeps_the_type_and_is_exact():
    """Durations computed from durations stay durations; ``Nanos`` add exactly past
    2**53 ns, where a float would round (checked under Node)."""
    two = seconds(2)
    for kept in (two + two, two - two, two * 1.5, 3 * two, -two, abs(-two), +two):
        assert type(kept) is Duration
    assert (nanos(2**53) + nanos(1)).to_nanos_unsafe() == 9_007_199_254_740_993
    assert (millis(2**53) + nanos(1)).to_nanos_unsafe() == 9_007_199_254_740_992_000_001
    assert (nanos(2**70) - millis(1)).to_nanos_unsafe() == 1_180_591_620_717_410_303_424
    assert infinity * 0 == zero
    assert infinity + negative_infinity == zero


def test_two_millis_add_as_javascript_numbers():
    """``Millis`` plus ``Millis`` is a float sum, as in Effect: it rounds past 2**53 ms
    and saturates past float range (checked under Node)."""
    assert (millis(2**53) + millis(1)).value == millis(2**53).value
    assert millis(1e308) + millis(1e308) == infinity
    assert millis(1e308) * 10 == infinity


def test_sleep_nan_completes_at_once_on_the_sync_scheduler():
    assert fx.run_blocking_exit(fx.sleep(float("nan")).as_("woke").timeout("5 seconds")) == (
        fx.Success("woke")
    )


def test_sleep_nan_completes_at_once_on_asyncio():
    ex = asyncio.run(fx.run_async_exit(fx.sleep(float("nan")).as_("woke").timeout("5 seconds")))
    assert ex == fx.Success("woke")


def test_nan_timeout_fires_at_once():
    assert isinstance(fx.run_blocking_exit(fx.never.timeout(float("nan"))), fx.Failure)


def test_schedules_treat_nan_as_zero():
    @fx.gen
    def first_decision():
        step = yield from schedule.to_step(schedule.spaced(float("nan")))
        return (yield from step(0.0, None))

    assert fx.run_blocking(first_decision) == schedule.Continue(0, zero)


@pytest.mark.parametrize(
    ("given", "text"),
    [
        (seconds(1), "1s"),
        (seconds(1.001), "1s 1ms"),
        (seconds(1.5), "1s 500ms"),
        (millis(0.0015), "1500ns"),
        (seconds(-5), "-5s"),
        (seconds(1_000_000_000.001), "11574d 1h 46m 40s 1ms"),
        # Half-nanosecond ties round away from zero, from the milliseconds
        # ``seconds * 1000`` (checked under Node).
        (seconds(2.5e-9), "3ns"),
        (seconds(-2.5e-9), "-3ns"),
        (seconds(7.0000000005), "7s 1ns"),
        (seconds(1.0000000005), "1s 1ns"),
        (seconds(0.5e-9 * 3), "2ns"),
        (seconds(1e-12), "0"),
        (seconds(-1e-12), "0"),
        (nanos(10**25 + 5), "115740740740d 17h 46m 40s 5ns"),
        (nanos(-1_500_000_001), "-1s 500ms 1ns"),
        (infinity, "Infinity"),
        (negative_infinity, "-Infinity"),
    ],
)
def test_format_matches_effect(given: Duration, text: str):
    """Effect's ``Duration.format``; the long one prints its days as a JavaScript number
    (checked under Node)."""
    assert given.format() == text


def test_an_infinite_sleep_never_wakes_and_does_not_crash_the_sync_scheduler():
    """An infinite duration is kept (Effect's ``Duration.infinity``): the
    sleep never wakes, and waiting on its timer must not overflow."""
    other_thread = fx.blocking(lambda: time.sleep(0.05)).as_("other")
    assert fx.run_blocking(fx.sleep(math.inf).as_("slept").race(other_thread)) == "other"


def test_a_sleep_past_float_range_never_wakes():
    """A finite sleep longer than any timer can wait is handed to the loop as an infinity."""
    other_thread = fx.blocking(lambda: time.sleep(0.05)).as_("other")
    sleep = fx.sleep(nanos(10**400)).as_("slept")
    assert fx.run_blocking(sleep.race(other_thread)) == "other"


def test_iso_text_of_big_nanosecond_counts():
    """``formatIso`` stays exact past 2**53 ns (checked under Node)."""
    assert nanos(10**30 + 1).format_iso() == "P11574074074074074DT1H46M40.000000001S"
    assert nanos(-(10**30) - 7).format_iso() == "-P11574074074074074DT1H46M40.000000007S"
    assert millis(2**60).format_iso() == "P13343998895DT21H54M6.976S"


def test_a_format_spec_names_the_conversion_to_use():
    """`f"{d:g}"` worked while durations were floats; pyright can't see format specs."""
    d = fx.duration.seconds(2)
    assert f"{d}" == str(d) == "2000 millis"
    with pytest.raises(TypeError, match=r"d\.to_seconds\(\)"):
        f"{d:g}"
