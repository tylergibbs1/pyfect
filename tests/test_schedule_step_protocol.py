"""``from_step`` and ``from_step_with_metadata`` take Effect's steps: a ``Pull``
that succeeds with ``(output, delay)`` to recur and fails with
``cause.done(output)`` to stop."""

from __future__ import annotations

import itertools

import pyfect as fx
from pyfect import schedule
from pyfect.cause import done
from pyfect.duration import Duration, zero
from pyfect.errors import Done


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
