"""Schedule constructors, and ``max`` / ``min`` to combine schedules."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any

from pyfect._concurrency import for_each
from pyfect._core import Effect, _Gen, _Succeed, _Sync
from pyfect._js import power, remainder
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
from pyfect.schedule._model import (
    Continue,
    Decision,
    InputMetadata,
    Schedule,
    StepFn,
    Stop,
    from_step,
    from_step_with_metadata,
    to_step,
)


def _stateless[Out](
    step: Callable[[InputMetadata[object]], Decision[Out]],
) -> Schedule[Out]:
    return from_step_with_metadata(_Succeed(lambda m: _Sync(lambda: step(m))))


def spaced(duration: DurationInput) -> Schedule[int]:
    """Recur forever, waiting ``duration`` each time. Outputs the count of
    recurrences so far, from 0."""
    delay = from_input_unsafe(duration)
    return _stateless(lambda m: Continue(m.attempt - 1, delay))


forever: Schedule[int] = spaced(zero)
"""Recur forever without waiting. Outputs the count, from 0."""


def recurs(times: int) -> Schedule[int]:
    """Recur ``times`` times without waiting (never, if not positive).
    Outputs the count, from 0."""
    return forever.while_(lambda m: m.attempt <= times)


once: Schedule[None] = recurs(1).map(lambda _: None)
"""Recur once, without waiting."""


def identity[A]() -> Schedule[A, A]:
    """Recur forever without waiting, outputting each input. Name the input
    type with an annotation: ``s: Schedule[str, str] = identity()``."""
    return _IDENTITY


_IDENTITY: Schedule[Any, Any] = from_step(
    _Succeed(lambda _now, input: _Succeed(Continue(input, zero)))
)


def exponential(base: DurationInput, factor: float = 2.0) -> Schedule[Duration]:
    """Recur forever, waiting ``base``, ``base*factor``, ``base*factor**2``,
    ... Outputs the delay, which becomes infinite once it passes float
    range (cap it with ``min(..., spaced(d))``)."""
    first = to_millis(base)

    def step(m: InputMetadata[object]) -> Decision[Duration]:
        delay = millis(first * power(factor, m.attempt - 1))
        return Continue(delay, delay)

    return _stateless(step)


def fibonacci(one: DurationInput) -> Schedule[Duration]:
    """Recur forever, waiting ``one``, ``one``, ``2*one``, ``3*one``,
    ``5*one``, ...: each delay the sum of the two before. Outputs the delay,
    which becomes infinite once it passes float range."""
    unit = to_millis(one)

    def make() -> StepFn[Duration, object, Any, Any]:
        # Effect's float milliseconds, which saturate to infinity.
        a, b = 0.0, unit

        def step() -> Decision[Duration]:
            nonlocal a, b
            delay = millis(b)
            a, b = b, a + b
            return Continue(delay, delay)

        return lambda _now, _input: _Sync(step)

    return from_step(_Sync(make))


def fixed(interval: DurationInput) -> Schedule[int]:
    """Recur on a fixed beat of ``interval``, counted from the first step.
    A run that overruns the beat is followed at once; missed beats are not
    replayed. Outputs the count, from 0."""
    window = to_millis(from_input_unsafe(interval))

    def make() -> Callable[[InputMetadata[object]], Effect[Decision[int]]]:
        # Effect's float milliseconds, ``%`` included.
        start = 0.0
        last_run = 0.0

        def step(m: InputMetadata[object]) -> Decision[int]:
            nonlocal start, last_run
            if window == 0:
                return Continue(m.attempt - 1, zero)
            if m.attempt == 1:
                start = m.now
                last_run = m.now + window
                return Continue(0, millis(window))
            running_behind = m.now > last_run + window
            boundary = window - remainder(m.now - start, window)
            on_beat = window if millis(boundary).is_zero() else boundary
            delay = 0.0 if running_behind else on_beat
            last_run = m.now if running_behind else m.now + delay
            return Continue(m.attempt - 1, millis(delay))

        return lambda m: _Sync(lambda: step(m))

    return from_step_with_metadata(_Sync(make))


def windowed(interval: DurationInput) -> Schedule[int]:
    """Recur at the end of each ``interval``-long window, counted from the
    first step. Outputs the count, from 0."""
    window = to_millis(from_input_unsafe(interval))

    def step(m: InputMetadata[object]) -> Decision[int]:
        if window == 0:
            return Continue(m.attempt - 1, zero)
        delay = millis(window - remainder(m.elapsed, window))
        return Continue(m.attempt - 1, millis(window) if delay.is_zero() else delay)

    return _stateless(step)


def duration(duration: DurationInput) -> Schedule[Duration]:
    """Recur once, after ``duration``. Outputs the duration, then 0."""
    delay = from_input_unsafe(duration)
    return _stateless(lambda m: Continue(delay, delay) if m.attempt == 1 else Stop(zero))


def during(duration: DurationInput) -> Schedule[Duration]:
    """Recur without waiting until more than ``duration`` has passed since
    the first step. Outputs the time elapsed."""
    limit = to_millis(duration)

    def step(m: InputMetadata[object]) -> Decision[Duration]:
        elapsed = millis(m.elapsed)
        return Stop(elapsed) if m.elapsed > limit else Continue(elapsed, zero)

    return _stateless(step)


# --- combining ------------------------------------------------------------------------


def _combine[I, E, R](
    schedules: tuple[Schedule[object, I, E, R], ...],
    pick: Callable[[list[Duration | None]], Duration | None],
) -> Schedule[Duration, I, E, R]:
    def make() -> Any:
        steps = yield from for_each(schedules, to_step)

        def step(now: float, input: I) -> Effect[Decision[Duration], E, R]:
            def body() -> Any:
                delays: list[Duration | None] = []
                for s in steps:
                    decision = yield from s(now, input)
                    delays.append(None if isinstance(decision, Stop) else decision.delay)
                chosen = pick(delays)
                return Stop(zero) if chosen is None else Continue(chosen, chosen)

            return _Gen(body)

        return step

    return from_step(_Gen(make))


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
