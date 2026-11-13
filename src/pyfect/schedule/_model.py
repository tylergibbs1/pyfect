"""The ``Schedule`` value, its step protocol and metadata.

A schedule is an effect that makes a step function. Each run of a schedule
(each ``retry``, ``repeat``, ...) runs that effect once, so the step can keep
state in its closure while the schedule itself stays an immutable value.

A step is Effect's: a ``Pull`` taking the current wall-clock time
(milliseconds since the epoch, as ``currentTimeMillis``) and an input. It
succeeds with ``(output, delay)`` to go again after ``delay``, or fails with
``Done(output)`` to finish. It may also fail with ``E`` and need ``R``.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Generic, Never, Self, TypeVar, final, overload

from pyfect._core import Effect, _FailCause, _Succeed, _Suspend
from pyfect._effect_args import require_effect
from pyfect.clock import clock_with, sleep
from pyfect.context import Reference
from pyfect.duration import Duration, from_input_unsafe, millis, zero
from pyfect.duration import Input as DurationInput
from pyfect.errors import Done
from pyfect.pull import Pull

if TYPE_CHECKING:
    from pyfect.result import Result

Out_co = TypeVar("Out_co", covariant=True)
In_contra = TypeVar("In_contra", contravariant=True, default=object)
E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)
# Metadata records are immutable, covariant in what they hold.
O_co = TypeVar("O_co", covariant=True)
I_co = TypeVar("I_co", covariant=True)


type StepFn[Out, In, E, R] = Callable[[float, In], Pull[tuple[Out, Duration], E, Out, R]]
"""``(now, input) -> (output, delay)``, or ``Done(output)`` to finish; ``now``
is wall-clock milliseconds since the epoch."""


@dataclass(frozen=True, slots=True, kw_only=True)
class InputMetadata(Generic[I_co]):
    """What a step knows before it decides. ``start`` and ``now`` are
    wall-clock milliseconds since the epoch, and ``elapsed`` and ``elapsed_since_previous``
    milliseconds too (``now - start``, as Effect's); ``attempt`` counts this step's
    decisions to recur, from 1."""

    input: I_co
    attempt: int
    start: float
    now: float
    elapsed: float
    elapsed_since_previous: float


@final
@dataclass(frozen=True, slots=True, kw_only=True)
class Metadata(InputMetadata[I_co], Generic[O_co, I_co]):
    """``InputMetadata`` plus the step's decision: its output and delay."""

    output: O_co
    duration: Duration


class CurrentMetadata(Reference[Metadata[object, object]]):
    """The metadata of the schedule step that started the current run of a
    repeated, retried or scheduled effect. Before the first step it is the
    default: ``attempt`` 0 and every time 0."""

    @classmethod
    def default(cls) -> Metadata[object, object]:
        return Metadata(
            input=None,
            output=None,
            duration=zero,
            attempt=0,
            start=0.0,
            now=0.0,
            elapsed=0,
            elapsed_since_previous=0,
        )


class _MetadataCounter:
    """Effect's ``metadataFn``: counts attempts and tracks times for one
    run of one step function."""

    __slots__ = ("attempt", "previous", "start")

    def __init__(self) -> None:
        self.attempt = 0
        self.previous: float | None = None
        self.start: float | None = None

    def __call__[In](self, now: float, input: In) -> InputMetadata[In]:
        if self.start is None:
            self.start = now
        since_previous = 0 if self.previous is None else now - self.previous
        self.previous = now
        self.attempt += 1
        return InputMetadata(
            input=input,
            attempt=self.attempt,
            start=self.start,
            now=now,
            elapsed=now - self.start,
            elapsed_since_previous=since_previous,
        )

    def full[Out, In](
        self, now: float, input: In, output: Out, duration: Duration
    ) -> Metadata[Out, In]:
        m = self(now, input)
        return Metadata(
            input=m.input,
            attempt=m.attempt,
            start=m.start,
            now=m.now,
            elapsed=m.elapsed,
            elapsed_since_previous=m.elapsed_since_previous,
            output=output,
            duration=duration,
        )


class Schedule(Generic[Out_co, In_contra, E_co, R_co]):
    """``Schedule[Out, In, E, R]``: decides, from each input, whether to
    recur and after how long, producing an ``Out`` each time. Its steps may
    fail with ``E`` and need ``R``.

    Build schedules with the constructors in ``pyfect.schedule`` and refine
    them with these methods. Each method keeps the schedule's own steps
    and adds what it describes."""

    __slots__ = ("_make_step",)

    def __init__(
        self, make_step: Effect[StepFn[Out_co, In_contra, E_co, R_co], E_co, R_co]
    ) -> None:
        self._make_step = make_step

    @overload
    def map[B, I, E2, R2](
        self: Schedule[Out_co, I, E_co, R_co], f: Callable[[Metadata[Out_co, I]], Effect[B, E2, R2]]
    ) -> Schedule[B, I, E_co | E2, R_co | R2]: ...
    @overload
    def map[B, I](
        self: Schedule[Out_co, I, E_co, R_co], f: Callable[[Metadata[Out_co, I]], B]
    ) -> Schedule[B, I, E_co, R_co]: ...
    def map(self, f: Callable[[Any], Any]) -> Schedule[Any, Any, Any, Any]:
        """Replace each output (including the final one) with ``f(metadata)``,
        or with what it succeeds with when it is an effect."""
        from pyfect.schedule._combinators import map_

        return map_(self, f)

    def map_effect[B, I, E2 = Never, R2 = Never](
        self: Schedule[Out_co, I, E_co, R_co], f: Callable[[Metadata[Out_co, I]], Effect[B, E2, R2]]
    ) -> Schedule[B, I, E_co | E2, R_co | R2]:
        """``map`` with an effectful ``f``."""
        from pyfect.schedule._combinators import map_

        return map_(self, f)

    def tap[I, E2 = Never, R2 = Never](
        self: Schedule[Out_co, I, E_co, R_co],
        f: Callable[[Metadata[Out_co, I]], Effect[object, E2, R2]],
    ) -> Schedule[Out_co, I, E_co | E2, R_co | R2]:
        """Run ``f(metadata)`` after each decision to recur."""
        from pyfect.schedule._combinators import tap

        return tap(self, f)

    @overload
    def while_[I, E2, R2](
        self: Schedule[Out_co, I, E_co, R_co],
        predicate: Callable[[Metadata[Out_co, I]], Effect[bool, E2, R2]],
    ) -> Schedule[Out_co, I, E_co | E2, R_co | R2]: ...
    @overload
    def while_[I](
        self: Schedule[Out_co, I, E_co, R_co], predicate: Callable[[Metadata[Out_co, I]], bool]
    ) -> Schedule[Out_co, I, E_co, R_co]: ...
    def while_(self, predicate: Callable[[Any], Any]) -> Schedule[Any, Any, Any, Any]:
        """Recur only while ``predicate(metadata)``, a value or an effect,
        holds (Effect's ``Schedule.while``); stop with the step's output once
        it fails."""
        from pyfect.schedule._combinators import while_

        return while_(self, predicate)

    def while_effect[I, E2 = Never, R2 = Never](
        self: Schedule[Out_co, I, E_co, R_co],
        predicate: Callable[[Metadata[Out_co, I]], Effect[bool, E2, R2]],
    ) -> Schedule[Out_co, I, E_co | E2, R_co | R2]:
        """``while_`` with an effectful predicate."""
        from pyfect.schedule._combinators import while_

        return while_(self, predicate)

    def modify_delay[I, E2 = Never, R2 = Never](
        self: Schedule[Out_co, I, E_co, R_co],
        f: Callable[[Metadata[Out_co, I]], Effect[DurationInput, E2, R2]],
    ) -> Schedule[Out_co, I, E_co | E2, R_co | R2]:
        """Replace each delay with the one ``f(metadata)`` gives."""
        from pyfect.schedule._combinators import modify_delay

        return modify_delay(self, f)

    def add_delay[I, E2 = Never, R2 = Never](
        self: Schedule[Out_co, I, E_co, R_co],
        f: Callable[[Metadata[Out_co, I]], Effect[DurationInput, E2, R2]],
    ) -> Schedule[Out_co, I, E_co | E2, R_co | R2]:
        """Add the delay ``f(metadata)`` gives to each delay."""
        from pyfect.schedule._combinators import modify_delay

        return modify_delay(
            self, lambda m: f(m).map(lambda extra: from_input_unsafe(extra) + m.duration)
        )

    def jittered(self) -> Schedule[Out_co, In_contra, E_co, R_co]:
        """Scale each delay by a random factor between 0.8 and 1.2."""
        from pyfect.schedule._combinators import jittered

        return jittered(self)

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        """Apply ``f`` to this schedule (one step per call, as ``Effect.pipe``)."""
        return f(self)

    def passthrough[I](self: Schedule[Out_co, I, E_co, R_co]) -> Schedule[I, I, E_co, R_co]:
        """Keep the decisions, but output each input instead."""
        from pyfect.schedule._combinators import passthrough

        return passthrough(self)

    def up_to(
        self, *, times: int | None = None, duration: DurationInput | None = None
    ) -> Schedule[Out_co, In_contra, E_co, R_co]:
        """Stop after ``times`` recurrences, or once more than ``duration``
        has passed since the first step, whichever comes first."""
        limit = None if duration is None else from_input_unsafe(duration)

        def within(m: Metadata[Any, Any]) -> bool:
            return (times is None or m.attempt <= times) and (
                limit is None or millis(m.elapsed) <= limit
            )

        return self.while_(within)

    def concat_result[O2, I, EE, RR](
        self: Schedule[Out_co, I, EE, RR], other: Schedule[O2, I, EE, RR]
    ) -> Schedule[Result[O2, Out_co], I, EE, RR]:
        """Run this schedule until it stops, then ``other``. Outputs are
        ``Err(output)`` from this schedule and ``Ok(output)`` from ``other``."""
        from pyfect.schedule._combinators import concat_result

        return concat_result(self, other)

    def concat[O2, I, EE, RR](
        self: Schedule[Out_co, I, EE, RR], other: Schedule[O2, I, EE, RR]
    ) -> Schedule[Out_co | O2, I, EE, RR]:
        """Run this schedule until it stops, then ``other``."""
        from pyfect.result import Ok

        # Effect's ``concat`` maps with ``succeed(Result.merge(output))``.
        return self.concat_result(other).map_effect(
            lambda m: _Succeed(m.output.value if isinstance(m.output, Ok) else m.output.error)
        )


# --- steps ----------------------------------------------------------------------------


@overload
def from_step[Out, In, E = Never, R = Never](
    make_step: Effect[Callable[[float, In], Effect[tuple[Out, Duration], Done[Out], R]], E, R],
) -> Schedule[Out, In, E, R]: ...
@overload
def from_step[Out, In, E = Never, R = Never](
    make_step: Effect[StepFn[Out, In, E, R], E, R],
) -> Schedule[Out, In, E, R]: ...
def from_step(make_step: Effect[Any, Any, Any]) -> Schedule[Any, Any, Any, Any]:
    """A schedule from an effect that makes its step function. The effect
    runs once per run of the schedule, so the step can keep state."""
    require_effect(make_step, "make_step")
    return Schedule(make_step)


@overload
def from_step_with_metadata[Out, In, E = Never, R = Never](
    make_step: Effect[
        Callable[[InputMetadata[In]], Effect[tuple[Out, Duration], Done[Out], R]], E, R
    ],
) -> Schedule[Out, In, E, R]: ...
@overload
def from_step_with_metadata[Out, In, E = Never, R = Never](
    make_step: Effect[Callable[[InputMetadata[In]], Pull[tuple[Out, Duration], E, Out, R]], E, R],
) -> Schedule[Out, In, E, R]: ...
def from_step_with_metadata(make_step: Effect[Any, Any, Any]) -> Schedule[Any, Any, Any, Any]:
    """``from_step``, but the step gets ``InputMetadata`` (attempt, start,
    elapsed time) in place of ``(now, input)``."""
    require_effect(make_step, "make_step")

    def with_counter(
        f: Callable[[InputMetadata[Any]], Effect[Any, Any, Any]],
    ) -> StepFn[Any, Any, Any, Any]:
        meta = _MetadataCounter()
        return lambda now, input: f(meta(now, input))

    return Schedule(make_step.map(with_counter))


def to_step[Out, In, E, R](
    schedule: Schedule[Out, In, E, R],
) -> Effect[StepFn[Out, In, E, R], Never, R]:
    """Make a fresh step function. If making it fails, every call of the
    step fails with that cause."""

    def failing(cause: Any) -> Effect[StepFn[Out, In, E, R]]:
        return _Succeed(lambda _now, _input: _FailCause(cause))

    return schedule._make_step.catch_cause(failing)


type MetadataStep[Out, In, E, R] = Callable[[In], Pull[Metadata[Out, In], E, Out, R]]
"""A step reading the clock itself and sleeping the delay: Effect's
``toStepWithMetadata`` step."""


def to_step_with_metadata[Out, In, E, R](
    schedule: Schedule[Out, In, E, R],
) -> Effect[MetadataStep[Out, In, E, R], Never, R]:
    """A step that reads the clock, decides, and sleeps the delay before
    succeeding with the step's ``Metadata``; or fails with ``Done(output)``
    without sleeping."""

    def with_clock(clock: Any) -> Effect[MetadataStep[Out, In, E, R], Never, R]:
        def make(step: StepFn[Out, In, E, R]) -> MetadataStep[Out, In, E, R]:
            meta = _MetadataCounter()

            def run(input: In) -> Pull[Metadata[Out, In], E, Out, R]:
                def go() -> Pull[Metadata[Out, In], E, Out, R]:
                    now: float = clock.current_time_millis_unsafe()

                    def decided(result: tuple[Out, Duration]) -> Effect[Metadata[Out, In]]:
                        output, delay = result
                        return sleep(delay).as_(meta.full(now, input, output, delay))

                    return step(now, input).flat_map(decided)

                return _Suspend(go)

            return run

        return to_step(schedule).map(make)

    return clock_with(with_clock)


def to_step_with_sleep[Out, In, E, R](
    schedule: Schedule[Out, In, E, R],
) -> Effect[Callable[[In], Pull[Out, E, Out, R]], Never, R]:
    """``to_step_with_metadata``, succeeding with the output after the sleep
    in place of the metadata."""

    def make(step: MetadataStep[Out, In, E, R]) -> Callable[[In], Pull[Out, E, Out, R]]:
        return lambda input: step(input).map(lambda m: m.output)

    return to_step_with_metadata(schedule).map(make)


@final
class SetInputType[I]:
    """Fixes a schedule's input type to ``I``: what ``set_input_type`` returns
    and what the builder forms of ``Effect.retry`` and ``repeat`` receive."""

    __slots__ = ()

    def __call__[O, E, R](self, schedule: Schedule[O, I, E, R]) -> Schedule[O, I, E, R]:
        return schedule


def set_input_type[I](input_type: type[I], /) -> SetInputType[I]:
    """Type a schedule to take ``input_type`` inputs, so the metadata its
    combinators see carries that type::

        schedule.recurs(3).pipe(set_input_type(int)).passthrough()  # Schedule[int, int]

    Curried for ``.pipe``: as a method, pyright would fix the input type
    from the schedule before seeing ``input_type``."""
    return SetInputType()
