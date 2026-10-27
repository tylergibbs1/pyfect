"""The work behind ``Schedule``'s methods. Each combinator wraps the inner
step function and keeps its own ``_MetadataCounter``, as Effect does."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from pyfect._core import Effect, _Gen, _Sync
from pyfect.duration import Duration, Seconds, to_seconds
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
                    m = meta.full(now, input, decision.output, Seconds(0.0))
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
    schedule: Schedule[O, I, E, R], f: Callable[[Metadata[O, I]], Effect[Duration, E2, R2]]
) -> Schedule[O, I, E | E2, R | R2]:
    def wrap(step: StepFn[O, I, E, R], meta: _MetadataCounter) -> StepFn[O, I, E | E2, R | R2]:
        def modified(now: float, input: I) -> Effect[Decision[O], E | E2, R | R2]:
            def body() -> Any:
                decision = yield from step(now, input)
                if isinstance(decision, Stop):
                    return decision
                m = meta.full(now, input, decision.output, decision.delay)
                return Continue(decision.output, to_seconds((yield from f(m))))

            return _Gen(body)

        return modified

    return _wrap(schedule, wrap)


def jittered[O, I, E, R](schedule: Schedule[O, I, E, R]) -> Schedule[O, I, E, R]:
    def jitter(m: Metadata[O, I]) -> Effect[Duration]:
        d = m.duration
        return next_double().map(lambda r: d * 0.8 * (1 - r) + d * 1.2 * r)

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
        current: StepFn[Result[O2, O], I, E, R] | None = None
        on_left = True

        def recur(now: float, input: I) -> Effect[Decision[Result[O2, O]], E, R]:
            if current is not None:
                return current(now, input)

            def body() -> Any:
                nonlocal current, on_left
                step = yield from to_step(left if on_left else right)
                if on_left:
                    on_left = False

                    def until_done(now: float, input: I) -> Effect[Decision[Result[O2, O]], E, R]:
                        def go() -> Any:
                            nonlocal current
                            decision = yield from step(now, input)
                            if isinstance(decision, Stop):
                                current = None
                                return (yield from recur(now, input))
                            return decision

                        return _Gen(go)

                    current = until_done
                else:
                    current = step
                return (yield from current(now, input))

            return _Gen(body)

        return recur

    return from_step(_Sync(make))
