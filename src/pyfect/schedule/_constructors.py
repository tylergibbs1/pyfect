"""Schedule constructors, and ``max`` / ``min`` to combine schedules."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import builtins
from collections.abc import Callable
from typing import Any

from pyfect._concurrency import for_each
from pyfect._core import Effect, _Gen, _Succeed, _Sync
from pyfect._js import power
from pyfect.duration import (
    ZERO,
    Duration,
    Seconds,
    from_millis,
    nanos_or_infinite,
    to_millis,
    to_seconds,
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


def spaced(duration: Duration) -> Schedule[int]:
    """Recur forever, waiting ``duration`` each time. Outputs the count of
    recurrences so far, from 0."""
    delay = to_seconds(duration)
    return _stateless(lambda m: Continue(m.attempt - 1, delay))


forever: Schedule[int] = spaced(ZERO)
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
    _Succeed(lambda _now, input: _Succeed(Continue(input, ZERO)))
)


def exponential(base: Duration, factor: float = 2.0) -> Schedule[Seconds]:
    """Recur forever, waiting ``base``, ``base*factor``, ``base*factor**2``,
    ... Outputs the delay, which becomes infinite once it passes float
    range (cap it with ``min(..., spaced(d))``)."""
    first = to_millis(base)

    def step(m: InputMetadata[object]) -> Decision[Seconds]:
        delay = from_millis(first * power(factor, m.attempt - 1))
        return Continue(delay, delay)

    return _stateless(step)


def fibonacci(one: Duration) -> Schedule[Seconds]:
    """Recur forever, waiting ``one``, ``one``, ``2*one``, ``3*one``,
    ``5*one``, ...: each delay the sum of the two before. Outputs the delay,
    which becomes infinite once it passes float range."""
    unit = to_millis(one)

    def make() -> StepFn[Seconds, object, Any, Any]:
        # Effect's float milliseconds, which saturate to infinity.
        a, b = 0.0, unit

        def step() -> Decision[Seconds]:
            nonlocal a, b
            delay = from_millis(b)
            a, b = b, a + b
            return Continue(delay, delay)

        return lambda _now, _input: _Sync(step)

    return from_step(_Sync(make))


def fixed(interval: Duration) -> Schedule[int]:
    """Recur on a fixed beat of ``interval``, counted from the first step.
    A run that overruns the beat is followed at once; missed beats are not
    replayed. Outputs the count, from 0."""
    window = nanos_or_infinite(to_seconds(interval))

    def make() -> Callable[[InputMetadata[object]], Effect[Decision[int]]]:
        # Effect's arithmetic, in whole nanoseconds since the first step.
        last_run: float = 0

        def step(m: InputMetadata[object]) -> Decision[int]:
            nonlocal last_run
            if window == 0:
                return Continue(m.attempt - 1, ZERO)
            if m.attempt == 1:
                last_run = window
                return Continue(0, _seconds(window))
            now = nanos_or_infinite(m.elapsed)
            running_behind = now > last_run + window
            delay = 0 if running_behind else _to_boundary(now, window)
            last_run = now + delay
            return Continue(m.attempt - 1, _seconds(delay))

        return lambda m: _Sync(lambda: step(m))

    return from_step_with_metadata(_Sync(make))


def windowed(interval: Duration) -> Schedule[int]:
    """Recur at the end of each ``interval``-long window, counted from the
    first step. Outputs the count, from 0."""
    window = nanos_or_infinite(to_seconds(interval))

    def step(m: InputMetadata[object]) -> Decision[int]:
        delay = 0 if window == 0 else _to_boundary(nanos_or_infinite(m.elapsed), window)
        return Continue(m.attempt - 1, _seconds(delay))

    return _stateless(step)


def _to_boundary(elapsed: float, window: float) -> float:
    """Nanoseconds to the next window boundary, with JavaScript's ``%``
    (the remainder takes the sign of ``elapsed``) as Effect computes it."""
    rest = abs(elapsed) % abs(window)
    return window - (rest if elapsed >= 0 else -rest)


def _seconds(nanos: float) -> Seconds:
    return Seconds(nanos / 1_000_000_000)


def duration(duration: Duration) -> Schedule[Seconds]:
    """Recur once, after ``duration``. Outputs the duration, then 0."""
    delay = to_seconds(duration)
    return _stateless(lambda m: Continue(delay, delay) if m.attempt == 1 else Stop(ZERO))


def during(duration: Duration) -> Schedule[Seconds]:
    """Recur without waiting until more than ``duration`` has passed since
    the first step. Outputs the time elapsed."""
    limit = to_seconds(duration)

    def step(m: InputMetadata[object]) -> Decision[Seconds]:
        elapsed = Seconds(m.elapsed)
        return Stop(elapsed) if m.elapsed > limit else Continue(elapsed, ZERO)

    return _stateless(step)


# --- combining ------------------------------------------------------------------------


def _combine[I, E, R](
    schedules: tuple[Schedule[object, I, E, R], ...],
    pick: Callable[[list[Seconds | None]], Seconds | None],
) -> Schedule[Seconds, I, E, R]:
    def make() -> Any:
        steps = yield from for_each(schedules, to_step)

        def step(now: float, input: I) -> Effect[Decision[Seconds], E, R]:
            def body() -> Any:
                delays: list[Seconds | None] = []
                for s in steps:
                    decision = yield from s(now, input)
                    delays.append(None if isinstance(decision, Stop) else decision.delay)
                chosen = pick(delays)
                return Stop(ZERO) if chosen is None else Continue(chosen, chosen)

            return _Gen(body)

        return step

    return from_step(_Gen(make))


def max[I, E, R](
    first: Schedule[object, I, E, R], *rest: Schedule[object, I, E, R]
) -> Schedule[Seconds, I, E, R]:
    """Recur while every schedule recurs, waiting the longest of their
    delays. Outputs the delay."""

    def longest(delays: list[Seconds | None]) -> Seconds | None:
        return None if None in delays else builtins.max(d for d in delays if d is not None)

    return _combine((first, *rest), longest)


def min[I, E, R](
    first: Schedule[object, I, E, R], *rest: Schedule[object, I, E, R]
) -> Schedule[Seconds, I, E, R]:
    """Recur while any schedule recurs, waiting the shortest delay of those
    that recur. Outputs the delay."""

    def shortest(delays: list[Seconds | None]) -> Seconds | None:
        live = [d for d in delays if d is not None]
        return builtins.min(live) if live else None

    return _combine((first, *rest), shortest)
