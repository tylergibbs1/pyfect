"""Schedule constructors, and ``max`` / ``min`` to combine schedules."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any, Never

from pyfect._concurrency import for_each
from pyfect._core import Effect, _FailCause, _Succeed, _Sync
from pyfect._js import power, remainder
from pyfect.cause import Cause, done
from pyfect.duration import (
    Duration,
    from_input_unsafe,
    millis,
    to_millis,
    zero,
)
from pyfect.duration import (
    Input as DurationInput,
)
from pyfect.pull import Pull, match_effect
from pyfect.schedule._model import (
    InputMetadata,
    Schedule,
    StepFn,
    from_step,
    from_step_with_metadata,
    to_step,
)

type _Decided[Out] = Pull[tuple[Out, Duration], Never, Out]


def spaced(duration: DurationInput) -> Schedule[int]:
    """Recur forever, waiting ``duration`` each time. Outputs the count of
    recurrences so far, from 0."""
    delay = from_input_unsafe(duration)
    return from_step_with_metadata(_Succeed(lambda m: _Succeed((m.attempt - 1, delay))))


forever: Schedule[int] = spaced(zero)
"""Recur forever without waiting. Outputs the count, from 0."""


def recurs(times: int) -> Schedule[int]:
    """Recur ``times`` times without waiting (never, if not positive).
    Outputs the count, from 0."""
    return forever.while_(lambda m: _Succeed(m.attempt <= times))


once: Schedule[None] = recurs(1).map(lambda _: None)
"""Recur once, without waiting."""


def identity[A]() -> Schedule[A, A]:
    """Recur forever without waiting, outputting each input. Name the input
    type with an annotation: ``s: Schedule[str, str] = identity()``."""
    return _IDENTITY


_IDENTITY: Schedule[Any, Any] = from_step(_Succeed(lambda _now, input: _Succeed((input, zero))))


def exponential(base: DurationInput, factor: float = 2.0) -> Schedule[Duration]:
    """Recur forever, waiting ``base``, ``base*factor``, ``base*factor**2``,
    ... Outputs the delay, which becomes infinite once it passes float
    range (cap it with ``min(..., spaced(d))``)."""
    first = to_millis(base)

    def step(m: InputMetadata[object]) -> _Decided[Duration]:
        delay = millis(first * power(factor, m.attempt - 1))
        return _Succeed((delay, delay))

    return from_step_with_metadata(_Succeed(step))


def fibonacci(one: DurationInput) -> Schedule[Duration]:
    """Recur forever, waiting ``one``, ``one``, ``2*one``, ``3*one``,
    ``5*one``, ...: each delay the sum of the two before. Outputs the delay,
    which becomes infinite once it passes float range."""
    unit = to_millis(one)

    def make() -> StepFn[Duration, object, Never, Never]:
        # Effect's float milliseconds, which saturate to infinity.
        a, b = 0.0, unit

        def step() -> tuple[Duration, Duration]:
            nonlocal a, b
            delay = millis(b)
            a, b = b, a + b
            return (delay, delay)

        # As Effect's ``constant(sync(...))``: one effect, run at each step.
        each = _Sync(step)
        return lambda _now, _input: each

    return from_step(_Sync(make))


def fixed(interval: DurationInput) -> Schedule[int]:
    """Recur on a fixed beat of ``interval``, counted from the first step.
    A run that overruns the beat is followed at once; missed beats are not
    replayed. Outputs the count, from 0."""
    window = to_millis(from_input_unsafe(interval))

    def make() -> Callable[[InputMetadata[object]], _Decided[int]]:
        # Effect's float milliseconds, ``%`` included.
        start = 0.0
        last_run = 0.0

        def step(m: InputMetadata[object]) -> tuple[int, Duration]:
            nonlocal start, last_run
            if window == 0:
                return (m.attempt - 1, zero)
            if m.attempt == 1:
                start = m.now
                last_run = m.now + window
                return (0, millis(window))
            running_behind = m.now > last_run + window
            boundary = window - remainder(m.now - start, window)
            on_beat = window if millis(boundary).is_zero() else boundary
            delay = 0.0 if running_behind else on_beat
            last_run = m.now if running_behind else m.now + delay
            return (m.attempt - 1, millis(delay))

        return lambda m: _Sync(lambda: step(m))

    return from_step_with_metadata(_Sync(make))


def windowed(interval: DurationInput) -> Schedule[int]:
    """Recur at the end of each ``interval``-long window, counted from the
    first step. Outputs the count, from 0."""
    window = to_millis(from_input_unsafe(interval))

    def step(m: InputMetadata[object]) -> tuple[int, Duration]:
        if window == 0:
            return (m.attempt - 1, zero)
        delay = millis(window - remainder(m.elapsed, window))
        return (m.attempt - 1, millis(window) if delay.is_zero() else delay)

    return from_step_with_metadata(_Succeed(lambda m: _Sync(lambda: step(m))))


def duration(duration: DurationInput) -> Schedule[Duration]:
    """Recur once, after ``duration``. Outputs the duration, then 0."""
    delay = from_input_unsafe(duration)

    def step(m: InputMetadata[object]) -> _Decided[Duration]:
        return _Succeed((delay, delay)) if m.attempt == 1 else done(zero)

    return from_step_with_metadata(_Succeed(step))


def during(duration: DurationInput) -> Schedule[Duration]:
    """Recur without waiting until more than ``duration`` has passed since
    the first step. Outputs the time elapsed."""
    limit = to_millis(duration)

    def step(m: InputMetadata[object]) -> _Decided[Duration]:
        elapsed = millis(m.elapsed)
        return done(elapsed) if m.elapsed > limit else _Succeed((elapsed, zero))

    return from_step_with_metadata(_Succeed(step))


# --- combining ------------------------------------------------------------------------


def _combine[I, E, R](
    schedules: tuple[Schedule[object, I, E, R], ...],
    pick: Callable[[list[Duration | None]], Duration | None],
) -> Schedule[Duration, I, E, R]:
    # Effect's ``max`` / ``min``: every step's delay (``None`` once it is
    # done), then the picked one, or ``Done(zero)`` when there is none.
    def make(steps: list[StepFn[object, I, E, R]]) -> StepFn[Duration, I, E, R]:
        def step(now: float, input: I) -> Pull[tuple[Duration, Duration], E, Duration, R]:
            def delay_of(s: StepFn[object, I, E, R]) -> Effect[Duration | None, E, R]:
                def delay(result: tuple[object, Duration]) -> Effect[Duration | None]:
                    return _Succeed(result[1])

                def ended(_: object) -> Effect[Duration | None]:
                    return _Succeed(None)

                def failed(cause: Cause[Any]) -> Effect[Duration | None, Any]:
                    return _FailCause(cause)

                pull: Effect[tuple[object, Duration], Any, R] = s(now, input)
                return match_effect(pull, on_success=delay, on_failure=failed, on_done=ended)

            def chosen(delays: list[Duration | None]) -> _Decided[Duration]:
                picked = pick(delays)
                return done(zero) if picked is None else _Succeed((picked, picked))

            return for_each(steps, delay_of).flat_map(chosen)

        return step

    return from_step(for_each(schedules, to_step).map(make))


def max[I, E, R](
    first: Schedule[object, I, E, R], *rest: Schedule[object, I, E, R]
) -> Schedule[Duration, I, E, R]:
    """Recur while every schedule recurs, waiting the longest of their
    delays. Outputs the delay."""

    def longest(delays: list[Duration | None]) -> Duration | None:
        return None if None in delays else builtins.max(d for d in delays if d is not None)

    return _combine((first, *rest), longest)


def min[I, E, R](
    first: Schedule[object, I, E, R], *rest: Schedule[object, I, E, R]
) -> Schedule[Duration, I, E, R]:
    """Recur while any schedule recurs, waiting the shortest delay of those
    that recur. Outputs the delay."""

    def shortest(delays: list[Duration | None]) -> Duration | None:
        live = [d for d in delays if d is not None]
        return builtins.min(live) if live else None

    return _combine((first, *rest), shortest)
