"""Durations: parsed once at the boundary, so every consumer agrees."""

import asyncio
import math
import time
from datetime import timedelta

import pytest

import pyfect as fx
from pyfect import schedule
from pyfect.duration import Seconds, format_duration, to_seconds


@pytest.mark.parametrize(
    ("given", "expected"),
    [(float("nan"), 0.0), (-0.0, 0.0), (1.5, 1.5), (timedelta(milliseconds=1500), 1.5)],
)
def test_to_seconds_normalises_like_effect_duration_make(given: float, expected: float):
    """Effect's ``Duration.make`` maps NaN (and -0) to zero."""
    parsed = to_seconds(given)
    assert isinstance(parsed, Seconds)
    assert parsed == expected and math.copysign(1.0, parsed) == math.copysign(1.0, expected)


def test_seconds_cannot_hold_nan():
    assert Seconds(float("nan")) == 0.0


def test_sleep_nan_completes_at_once_on_the_sync_scheduler():
    assert fx.run_sync_exit(fx.sleep(float("nan")).as_("woke").timeout(5)) == fx.Success("woke")


def test_sleep_nan_completes_at_once_on_asyncio():
    ex = asyncio.run(fx.run_async_exit(fx.sleep(float("nan")).as_("woke").timeout(5)))
    assert ex == fx.Success("woke")


def test_nan_timeout_fires_at_once():
    assert isinstance(fx.run_sync_exit(fx.never.timeout(float("nan"))), fx.Failure)


def test_schedules_treat_nan_as_zero():
    @fx.gen
    def first_decision():
        step = yield from schedule.to_step(schedule.spaced(float("nan")))
        return (yield from step(0.0, None))

    assert fx.run_sync(first_decision) == schedule.Continue(0, Seconds(0.0))


@pytest.mark.parametrize(
    ("seconds", "text"),
    [
        (1.0, "1s"),
        (1.001, "1s 1ms"),
        (1.5, "1s 500ms"),
        (300.0, "5m"),
        (5.325 * 60, "5m 19s 500ms"),
        (3 * 3600.0, "3h"),
        (3.11125 * 3600, "3h 6m 40s 500ms"),
        (2 * 86400.0, "2d"),
        (2.25 * 86400, "2d 6h"),
        (7 * 86400.0, "7d"),
        (0.0, "0"),
        (0.000_001_5, "1500ns"),
        (-5.0, "-5s"),
        (1_000_000_000.001, "11574d 1h 46m 40s 1ms"),
        # Half-nanosecond ties round away from zero, from the milliseconds
        # ``seconds * 1000`` (checked under Node).
        (2.5e-9, "3ns"),
        (-2.5e-9, "-3ns"),
        (7.0000000005, "7s 1ns"),
        (1.0000000005, "1s 1ns"),
        (0.5e-9 * 3, "2ns"),
        (math.inf, "Infinity"),
        (-math.inf, "-Infinity"),
    ],
)
def test_format_duration_matches_effect(seconds: float, text: str):
    """Effect's ``Duration.format`` (Duration.test.ts "format" and the
    negative-duration format checks)."""
    assert format_duration(Seconds(seconds)) == text


def test_an_infinite_sleep_never_wakes_and_does_not_crash_the_sync_scheduler():
    """An infinite duration is kept (Effect's ``Duration.infinity``): the
    sleep never wakes, and waiting on its timer must not overflow."""
    other_thread = fx.blocking(lambda: time.sleep(0.05)).as_("other")
    assert fx.run_sync(fx.sleep(math.inf).as_("slept").race(other_thread)) == "other"


@pytest.mark.parametrize("seconds", [1e-12, -1e-12])
def test_format_duration_of_a_sub_nanosecond_value_is_zero(seconds: float):
    """Effect rounds to whole nanoseconds, then ``Duration.format`` of zero is ``"0"``."""
    assert format_duration(Seconds(seconds)) == "0"
