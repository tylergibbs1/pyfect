"""Schedules run Effect's step protocol, and until 0.7.0 the public step functions
still speak 0.6's: ``from_step`` takes either kind of step, ``to_step`` and its
variants hand back ``Continue``/``Stop``, and only code that makes those
classes itself is warned."""
# pyright: reportDeprecated=false

from __future__ import annotations

import itertools
import warnings

import pytest

import pyfect as fx
from pyfect import schedule
from pyfect.cause import done
from pyfect.duration import Duration, zero
from pyfect.errors import Done
from pyfect.schedule import Continue, Decision, Metadata, Stop


def test_from_step_takes_a_step_in_effects_protocol() -> None:
    def step(_now: float, n: int) -> fx.Effect[tuple[int, Duration], Done[str]]:
        return fx.succeed((n, zero)) if n < 3 else done(f"stopped at {n}")

    counter = itertools.count(1)
    bump = fx.sync(lambda: next(counter))
    assert fx.run_sync(bump.repeat(schedule.from_step(fx.succeed(step)))) == "stopped at 3"


def test_from_step_with_metadata_takes_a_step_in_effects_protocol() -> None:
    def step(m: schedule.InputMetadata[object]) -> fx.Effect[tuple[int, Duration], Done[int]]:
        return fx.succeed((m.attempt, zero)) if m.attempt < 3 else done(m.attempt)

    assert fx.run_sync(fx.void.repeat(schedule.from_step_with_metadata(fx.succeed(step)))) == 3


def test_from_step_still_takes_a_step_deciding_continue_or_stop() -> None:
    def step(_now: float, n: int) -> fx.Effect[Decision[int]]:
        return fx.succeed(Continue(n, zero) if n < 3 else Stop(-n))

    counter = itertools.count(1)
    bump = fx.sync(lambda: next(counter))
    with pytest.warns(DeprecationWarning):
        assert fx.run_sync(bump.repeat(schedule.from_step(fx.succeed(step)))) == -3


def test_making_continue_or_stop_warns_that_they_go_in_0_7_0() -> None:
    with pytest.warns(DeprecationWarning, match=r"Continue is removed in 0\.7\.0"):
        Continue(1, zero)
    with pytest.warns(DeprecationWarning, match=r"Stop is removed in 0\.7\.0"):
        Stop(1)


def test_the_step_functions_hand_back_decisions_without_warning() -> None:
    once = schedule.recurs(1)

    @fx.gen
    def steps():
        step = yield from schedule.to_step(once)
        with_metadata = yield from schedule.to_step_with_metadata(once)
        with_sleep = yield from schedule.to_step_with_sleep(once)
        return (
            [(yield from step(0.0, None)), (yield from step(0.0, None))],
            [(yield from with_metadata(None)), (yield from with_metadata(None))],
            [(yield from with_sleep(None)), (yield from with_sleep(None))],
        )

    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        decided, metadata, slept = fx.testing.run_test(steps)
    assert decided == [Continue(0, zero), Stop(1)]
    assert isinstance(metadata[0], Metadata) and metadata[0].output == 0
    assert metadata[1] == Stop(1)
    assert slept == [Continue(0, zero), Stop(1)]
