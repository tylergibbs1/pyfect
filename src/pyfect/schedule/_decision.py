"""The step protocol of pyfect 0.6's public step functions, kept until 0.7.0.

There a step succeeds with ``Continue(output, delay)`` or ``Stop(output)``.
Schedules now run Effect's protocol (``_model``): a step is a ``Pull`` that
succeeds with ``(output, delay)`` or fails with ``Done(output)``. These
functions translate at the boundary, so code written against 0.6 runs
unchanged; ``from_step`` and ``from_step_with_metadata`` also take Effect's
steps. ``Continue`` and ``Stop`` warn, and go in 0.7.0 with this module.
"""
# pyright: reportPrivateUsage=false, reportDeprecated=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Never, TypeVar, cast, final, overload
from warnings import deprecated

from pyfect._core import Effect, _FailCause, _Succeed
from pyfect._effect_args import require_effect
from pyfect.cause import done
from pyfect.duration import Duration
from pyfect.errors import Done
from pyfect.pull import Pull, match_effect
from pyfect.schedule import _model
from pyfect.schedule._model import InputMetadata, Metadata, Schedule

O_co = TypeVar("O_co", covariant=True)

_REMOVED = (
    "is removed in 0.7.0, where a schedule step is Effect's Pull: it succeeds with "
    "(output, delay) and fails with pyfect.cause.done(output) to finish"
)


@deprecated(f"schedule.Continue {_REMOVED}")
@final
@dataclass(frozen=True, slots=True)
class Continue(Generic[O_co]):
    """A step's decision to recur after ``delay``, producing ``output``."""

    output: O_co
    delay: Duration


@deprecated(f"schedule.Stop {_REMOVED}")
@final
@dataclass(frozen=True, slots=True)
class Stop(Generic[O_co]):
    """A step's decision to finish, producing ``output`` (Effect's
    ``Cause.done(output)``)."""

    output: O_co


type Decision[Out] = Continue[Out] | Stop[Out]

type StepFn[Out, In, E, R] = Callable[[float, In], Effect[Decision[Out], E, R]]
"""``(now, input) -> decision``; ``now`` is wall-clock milliseconds since the epoch."""


def _continue(output: object, delay: Duration) -> Continue[Any]:
    """A ``Continue`` made for the caller of a 0.6 step function, who chose
    that protocol: the warning is for code that names the class."""
    made = cast("Continue[Any]", object.__new__(Continue))
    object.__setattr__(made, "output", output)
    object.__setattr__(made, "delay", delay)
    return made


def _stop(output: object) -> Stop[Any]:
    made = cast("Stop[Any]", object.__new__(Stop))
    object.__setattr__(made, "output", output)
    return made


def _from_decision(decided: object) -> Effect[Any, Any, Any]:
    if isinstance(decided, Continue):
        kept = cast("Continue[Any]", decided)
        return _Succeed((kept.output, kept.delay))
    if isinstance(decided, Stop):
        return done(cast("Stop[Any]", decided).output)
    return _Succeed(decided)


def _as_pull_step(
    step: Callable[[float, Any], Effect[Any, Any, Any]],
) -> _model.StepFn[Any, Any, Any, Any]:
    return lambda now, input: step(now, input).flat_map(_from_decision)


@overload
def from_step[Out, In, E = Never, R = Never](
    make_step: Effect[Callable[[float, In], Effect[tuple[Out, Duration], Done[Out], R]], E, R],
) -> Schedule[Out, In, E, R]: ...
@overload
def from_step[Out, In, E = Never, R = Never](
    make_step: Effect[_model.StepFn[Out, In, E, R], E, R],
) -> Schedule[Out, In, E, R]: ...
@overload
def from_step[Out, In, E = Never, R = Never](
    make_step: Effect[StepFn[Out, In, E, R], E, R],
) -> Schedule[Out, In, E, R]: ...
def from_step(make_step: Effect[Any, Any, Any]) -> Schedule[Any, Any, Any, Any]:
    """A schedule from an effect that makes its step function. The effect
    runs once per run of the schedule, so the step can keep state. A step
    succeeds with ``(output, delay)`` and fails with ``done(output)`` to
    finish, or (until 0.7.0) succeeds with ``Continue`` or ``Stop``."""
    require_effect(make_step, "make_step")
    return _model.from_step(make_step.map(_as_pull_step))


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
@overload
def from_step_with_metadata[Out, In, E = Never, R = Never](
    make_step: Effect[Callable[[InputMetadata[In]], Effect[Decision[Out], E, R]], E, R],
) -> Schedule[Out, In, E, R]: ...
def from_step_with_metadata(make_step: Effect[Any, Any, Any]) -> Schedule[Any, Any, Any, Any]:
    """``from_step``, but the step gets ``InputMetadata`` (attempt, start,
    elapsed time) in place of ``(now, input)``."""
    require_effect(make_step, "make_step")

    def as_pull(
        f: Callable[[InputMetadata[Any]], Effect[Any, Any, Any]],
    ) -> Callable[[InputMetadata[Any]], Effect[Any, Any, Any]]:
        return lambda meta: f(meta).flat_map(_from_decision)

    return _model.from_step_with_metadata(make_step.map(as_pull))


def _on_done_stop(output: object) -> Effect[Any]:
    return _Succeed(_stop(output))


def _continue_with(result: tuple[Any, Duration]) -> Effect[Any]:
    return _Succeed(_continue(result[0], result[1]))


def _continue_after(meta: Metadata[Any, Any]) -> Effect[Any]:
    return _Succeed(_continue(meta.output, meta.duration))


type _TimedStep = Callable[[float, Any], Effect[Any, Any, Any]]
type _InputStep = Callable[[Any], Effect[Any, Any, Any]]


def _as_decision_step(step: _TimedStep) -> _TimedStep:
    return lambda now, input: match_effect(
        step(now, input), on_success=_continue_with, on_failure=_FailCause, on_done=_on_done_stop
    )


def _metadata_or_stop(step: _InputStep) -> _InputStep:
    return lambda input: match_effect(
        step(input), on_success=_Succeed, on_failure=_FailCause, on_done=_on_done_stop
    )


def _decision_after_sleep(step: _InputStep) -> _InputStep:
    return lambda input: match_effect(
        step(input), on_success=_continue_after, on_failure=_FailCause, on_done=_on_done_stop
    )


def to_step[Out, In, E, R](
    schedule: Schedule[Out, In, E, R],
) -> Effect[StepFn[Out, In, E, R], Never, R]:
    """Make a fresh step function. If making it fails, every call of the
    step fails with that cause."""
    return cast(
        "Effect[StepFn[Out, In, E, R], Never, R]", _model.to_step(schedule).map(_as_decision_step)
    )


def to_step_with_metadata[Out, In, E, R](
    schedule: Schedule[Out, In, E, R],
) -> Effect[Callable[[In], Effect[Metadata[Out, In] | Stop[Out], E, R]], Never, R]:
    """A step that reads the clock, decides, and sleeps the delay before
    returning the step's ``Metadata``; or returns ``Stop`` without sleeping."""
    made = _model.to_step_with_metadata(schedule).map(_metadata_or_stop)
    return cast(
        "Effect[Callable[[In], Effect[Metadata[Out, In] | Stop[Out], E, R]], Never, R]", made
    )


def to_step_with_sleep[Out, In, E, R](
    schedule: Schedule[Out, In, E, R],
) -> Effect[Callable[[In], Effect[Decision[Out], E, R]], Never, R]:
    """``to_step_with_metadata``, returning ``Continue(output, delay)``
    after the sleep in place of the metadata."""
    made = _model.to_step_with_metadata(schedule).map(_decision_after_sleep)
    return cast("Effect[Callable[[In], Effect[Decision[Out], E, R]], Never, R]", made)
