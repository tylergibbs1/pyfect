"""The work behind ``Schedule``'s methods. Each combinator wraps the inner
step function and keeps its own ``_MetadataCounter``, as Effect does."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect._core import Effect, _Gen, _Sync
from pyfect.duration import Input as DurationInput
from pyfect.duration import from_input_unsafe, millis, zero
from pyfect.random import next as next_double
from pyfect.result import Err, Ok, Result
from pyfect.schedule._model import (
    Continue,
    Decision,
    Metadata,
    Schedule,
    StepFn,
    Stop,
    _MetadataCounter,
    from_step,
    to_step,
)


def _wrap[O, I, E, R, O2, E2, R2](
    schedule: Schedule[O, I, E, R],
    wrap: Callable[[StepFn[O, I, E, R], _MetadataCounter], StepFn[O2, I, E2, R2]],
) -> Schedule[O2, I, E2, R | R2]:
    return from_step(to_step(schedule).map(lambda step: wrap(step, _MetadataCounter())))


def map_effect[O, I, E, R, B, E2, R2](
    schedule: Schedule[O, I, E, R], f: Callable[[Metadata[O, I]], Effect[B, E2, R2]]
) -> Schedule[B, I, E | E2, R | R2]:
    def wrap(step: StepFn[O, I, E, R], meta: _MetadataCounter) -> StepFn[B, I, E | E2, R | R2]:
        def mapped(now: float, input: I) -> Effect[Decision[B], E | E2, R | R2]:
            def body() -> Any:
                decision = yield from step(now, input)
                if isinstance(decision, Stop):
                    m = meta.full(now, input, decision.output, zero)
                    return Stop((yield from f(m)))
                m = meta.full(now, input, decision.output, decision.delay)
                return Continue((yield from f(m)), decision.delay)

            return _Gen(body)

        return mapped

    return _wrap(schedule, wrap)


def tap[O, I, E, R, E2, R2](
    schedule: Schedule[O, I, E, R], f: Callable[[Metadata[O, I]], Effect[object, E2, R2]]
) -> Schedule[O, I, E | E2, R | R2]:
    def wrap(step: StepFn[O, I, E, R], meta: _MetadataCounter) -> StepFn[O, I, E | E2, R | R2]:
        def tapped(now: float, input: I) -> Effect[Decision[O], E | E2, R | R2]:
            def body() -> Any:
                decision = yield from step(now, input)
                if isinstance(decision, Continue):
                    yield from f(meta.full(now, input, decision.output, decision.delay))
                return decision

            return _Gen(body)

        return tapped

    return _wrap(schedule, wrap)


def while_effect[O, I, E, R, E2, R2](
    schedule: Schedule[O, I, E, R], predicate: Callable[[Metadata[O, I]], Effect[bool, E2, R2]]
) -> Schedule[O, I, E | E2, R | R2]:
    def wrap(step: StepFn[O, I, E, R], meta: _MetadataCounter) -> StepFn[O, I, E | E2, R | R2]:
        def checked(now: float, input: I) -> Effect[Decision[O], E | E2, R | R2]:
            def body() -> Any:
                decision = yield from step(now, input)
                if isinstance(decision, Stop):
                    return decision
                m = meta.full(now, input, decision.output, decision.delay)
                return decision if (yield from predicate(m)) else Stop(decision.output)

            return _Gen(body)

        return checked

    return _wrap(schedule, wrap)


def modify_delay[O, I, E, R, E2, R2](
    schedule: Schedule[O, I, E, R], f: Callable[[Metadata[O, I]], Effect[DurationInput, E2, R2]]
) -> Schedule[O, I, E | E2, R | R2]:
    def wrap(step: StepFn[O, I, E, R], meta: _MetadataCounter) -> StepFn[O, I, E | E2, R | R2]:
        def modified(now: float, input: I) -> Effect[Decision[O], E | E2, R | R2]:
            def body() -> Any:
                decision = yield from step(now, input)
                if isinstance(decision, Stop):
                    return decision
                m = meta.full(now, input, decision.output, decision.delay)
                return Continue(decision.output, from_input_unsafe((yield from f(m))))

            return _Gen(body)

        return modified

    return _wrap(schedule, wrap)


def jittered[O, I, E, R](schedule: Schedule[O, I, E, R]) -> Schedule[O, I, E, R]:
    def jitter(m: Metadata[O, I]) -> Effect[DurationInput]:
        d = m.duration.to_millis()
        return next_double().map(lambda r: millis(d * 0.8 * (1 - r) + d * 1.2 * r))

    return modify_delay(schedule, jitter)


def passthrough[O, I, E, R](schedule: Schedule[O, I, E, R]) -> Schedule[I, I, E, R]:
    def wrap(step: StepFn[O, I, E, R], _meta: _MetadataCounter) -> StepFn[I, I, E, R]:
        def echo(decision: Decision[O], input: I) -> Decision[I]:
            return Stop(input) if isinstance(decision, Stop) else Continue(input, decision.delay)

        return lambda now, input: step(now, input).map(lambda d: echo(d, input))

    return _wrap(schedule, wrap)


def concat_result[O, O2, I, E, R](
    first: Schedule[O, I, E, R], second: Schedule[O2, I, E, R]
) -> Schedule[Result[O2, O], I, E, R]:
    left: Schedule[Result[O2, O], I, E, R] = first.map(lambda m: Err(m.output))
    right: Schedule[Result[O2, O], I, E, R] = second.map(lambda m: Ok(m.output))

    def make() -> StepFn[Result[O2, O], I, E, R]:
        return _ConcatResult(left, right).recur

    return from_step(_Sync(make))


class _ConcatResult[O, I, E, R]:
    """One run of ``concat_result``: steps through ``left``, then ``right``.
    The current step lives on this object, not in closures that reach each
    other (that cycle would keep both schedules alive after the run)."""

    __slots__ = ("left", "left_step", "on_left", "right", "right_step")

    def __init__(self, left: Schedule[O, I, E, R], right: Schedule[O, I, E, R]) -> None:
        self.left = left
        self.right = right
        self.on_left = True
        self.left_step: StepFn[O, I, E, R] | None = None
        self.right_step: StepFn[O, I, E, R] | None = None

    def recur(self, now: float, input: I) -> Effect[Decision[O], E, R]:
        left_step = self.left_step
        if left_step is not None:
            return _Gen(lambda: self.until_done(left_step, now, input))
        right_step = self.right_step
        if right_step is not None:
            return right_step(now, input)
        return _Gen(lambda: self.start(now, input))

    def start(self, now: float, input: I) -> Any:
        step = yield from to_step(self.left if self.on_left else self.right)
        if self.on_left:
            self.on_left = False
            self.left_step = step
        else:
            self.right_step = step
        return (yield from self.recur(now, input))

    def until_done(self, step: StepFn[O, I, E, R], now: float, input: I) -> Any:
        decision = yield from step(now, input)
        if isinstance(decision, Stop):
            self.left_step = None
            return (yield from self.recur(now, input))
        return decision
