"""The work behind ``Schedule``'s methods, op for op as Effect's: each
combinator maps the inner step function made by ``to_step`` and keeps its
own ``_MetadataCounter``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, cast

from pyfect._core import Effect, _FailCause, _Succeed, _Sync
from pyfect.cause import done
from pyfect.duration import Duration, from_input_unsafe, millis, zero
from pyfect.duration import Input as DurationInput
from pyfect.pull import Pull, catch_done, match_effect
from pyfect.random import next as next_double
from pyfect.result import Err, Ok, Result
from pyfect.schedule._model import (
    Metadata,
    Schedule,
    StepFn,
    _MetadataCounter,
    from_step,
    to_step,
)


def _as_effect(result: object) -> Effect[Any, Any, Any] | None:
    return cast("Effect[Any, Any, Any]", result) if isinstance(result, Effect) else None


def map_[O, I, E, R](
    schedule: Schedule[O, I, E, R], f: Callable[[Metadata[O, I]], Any]
) -> Schedule[Any, I, Any, Any]:
    """Effect's ``Schedule.map``: ``f`` returns the new output, or an effect
    of it."""

    def make(step: StepFn[O, I, E, R]) -> StepFn[Any, I, Any, Any]:
        meta = _MetadataCounter()

        def mapped(now: float, input: I) -> Pull[tuple[Any, Duration], Any, Any, Any]:
            def on_success(result: tuple[O, Duration]) -> Effect[tuple[Any, Duration], Any, Any]:
                output, delay = result
                value = f(meta.full(now, input, output, delay))
                eff = _as_effect(value)
                if eff is None:
                    return _Succeed((value, delay))
                return eff.map(lambda o: (o, delay))

            def on_done(output: O) -> Effect[Never, Any, Any]:
                value = f(meta.full(now, input, output, zero))
                eff = _as_effect(value)
                return done(value) if eff is None else eff.flat_map(done)

            return match_effect(
                step(now, input), on_success=on_success, on_failure=_fail_cause, on_done=on_done
            )

        return mapped

    return from_step(to_step(schedule).map(make))


def tap[O, I, E, R, E2, R2](
    schedule: Schedule[O, I, E, R], f: Callable[[Metadata[O, I]], Effect[object, E2, R2]]
) -> Schedule[O, I, E | E2, R | R2]:
    def make(step: StepFn[O, I, E, R]) -> StepFn[O, I, E | E2, R | R2]:
        meta = _MetadataCounter()

        def tapped(now: float, input: I) -> Pull[tuple[O, Duration], E | E2, O, R | R2]:
            def run(result: tuple[O, Duration]) -> Effect[object, E2, R2]:
                output, delay = result
                return f(meta.full(now, input, output, delay))

            return step(now, input).tap(run)

        return tapped

    return from_step(to_step(schedule).map(make))


def while_[O, I, E, R](
    schedule: Schedule[O, I, E, R], predicate: Callable[[Metadata[O, I]], Any]
) -> Schedule[O, I, Any, Any]:
    """Effect's ``Schedule.while``: ``predicate`` returns a bool, or an
    effect of one."""

    def make(step: StepFn[O, I, E, R]) -> StepFn[O, I, Any, Any]:
        meta = _MetadataCounter()

        def checked(now: float, input: I) -> Pull[tuple[O, Duration], Any, O, Any]:
            def decide(result: tuple[O, Duration]) -> Pull[tuple[O, Duration], Any, O, Any]:
                output, delay = result
                value = predicate(meta.full(now, input, output, delay))
                eff = _as_effect(value)
                check = _Succeed(value) if eff is None else eff
                return check.flat_map(lambda ok: _Succeed(result) if ok else done(output))

            return step(now, input).flat_map(decide)

        return checked

    return from_step(to_step(schedule).map(make))


def modify_delay[O, I, E, R, E2, R2](
    schedule: Schedule[O, I, E, R], f: Callable[[Metadata[O, I]], Effect[DurationInput, E2, R2]]
) -> Schedule[O, I, E | E2, R | R2]:
    def make(step: StepFn[O, I, E, R]) -> StepFn[O, I, E | E2, R | R2]:
        meta = _MetadataCounter()

        def modified(now: float, input: I) -> Pull[tuple[O, Duration], E | E2, O, R | R2]:
            def replace(result: tuple[O, Duration]) -> Effect[tuple[O, Duration], E2, R2]:
                output, delay = result
                return f(meta.full(now, input, output, delay)).map(
                    lambda replacement: (output, from_input_unsafe(replacement))
                )

            return step(now, input).flat_map(replace)

        return modified

    return from_step(to_step(schedule).map(make))


def jittered[O, I, E, R](schedule: Schedule[O, I, E, R]) -> Schedule[O, I, E, R]:
    def jitter(m: Metadata[O, I]) -> Effect[DurationInput]:
        d = m.duration.to_millis()
        return next_double().map(lambda r: millis(d * 0.8 * (1 - r) + d * 1.2 * r))

    return modify_delay(schedule, jitter)


def passthrough[O, I, E, R](schedule: Schedule[O, I, E, R]) -> Schedule[I, I, E, R]:
    def make(step: StepFn[O, I, E, R]) -> StepFn[I, I, E, R]:
        def echo(now: float, input: I) -> Pull[tuple[I, Duration], E, I, R]:
            return match_effect(
                step(now, input),
                on_success=lambda result: _Succeed((input, result[1])),
                on_failure=_fail_cause,
                on_done=lambda _: done(input),
            )

        return echo

    return from_step(to_step(schedule).map(make))


def concat_result[O, O2, I, E, R](
    first: Schedule[O, I, E, R], second: Schedule[O2, I, E, R]
) -> Schedule[Result[O2, O], I, E, R]:
    left: Schedule[Result[O2, O], I, E, R] = first.map(lambda m: Err(m.output))
    right: Schedule[Result[O2, O], I, E, R] = second.map(lambda m: Ok(m.output))

    def make() -> StepFn[Result[O2, O], I, E, R]:
        side = 0
        current: StepFn[Result[O2, O], I, E, R] | None = None

        def recur(
            now: float, input: I
        ) -> Pull[tuple[Result[O2, O], Duration], E, Result[O2, O], R]:
            if current is not None:
                return current(now, input)

            def started(
                step: StepFn[Result[O2, O], I, E, R],
            ) -> Pull[tuple[Result[O2, O], Duration], E, Result[O2, O], R]:
                nonlocal side, current
                side += 1
                if side == 1:

                    def until_done(
                        now: float, input: I
                    ) -> Pull[tuple[Result[O2, O], Duration], E, Result[O2, O], R]:
                        def next_side(_: object) -> Any:
                            nonlocal current
                            current = None
                            return recur(now, input)

                        return catch_done(step(now, input), next_side)

                    current = until_done
                    return current(now, input)
                current = step
                return current(now, input)

            return to_step(left if side == 0 else right).flat_map(started)

        return recur

    return from_step(_Sync(make))


def _fail_cause(cause: Any) -> Effect[Any, Any, Any]:
    return _FailCause(cause)
