"""``ExecutionPlan`` values: steps, ``make``, ``merge`` and
``capture_requirements``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Generic, Never, TypeVar

from pyfect._core import Effect, _Succeed, _WithFiber
from pyfect.context import Context
from pyfect.layer import Layer, provide, succeed_context
from pyfect.schedule import Schedule
from pyfect.schedule._model import StepFn

# Variance is declared, not inferred: a step providing more services is a
# step providing fewer (``Layer`` and ``Context`` are contravariant in what
# they provide), so ``make`` over steps solves ``P`` to what *every* step
# provides, Effect's intersection of the steps' services.
P_contra = TypeVar("P_contra", contravariant=True)
In_contra = TypeVar("In_contra", contravariant=True, default=object)
E_co = TypeVar("E_co", covariant=True, default=Never)
R_co = TypeVar("R_co", covariant=True, default=Never)

type Predicate[In, E, R] = Callable[[In], bool | Effect[bool, E, R]]


@dataclass(frozen=True, slots=True)
class Step(Generic[P_contra, In_contra, E_co, R_co]):
    """One step of a plan (Effect's ``ExecutionPlan.make.Step``): run with
    ``provide`` (a layer or a context) up to ``attempts`` times, retrying
    on ``schedule``'s delays while ``while_(error)`` holds.

    Without ``attempts`` or ``schedule`` the step runs once. ``attempts``
    must be at least 1 (``make`` checks it)."""

    provide: Context[P_contra] | Layer[P_contra, E_co, R_co]
    attempts: int | None = None
    while_: Predicate[In_contra, E_co, R_co] | None = None
    schedule: Schedule[Any, In_contra, E_co, R_co] | None = None


@dataclass(frozen=True, slots=True)
class ExecutionPlan(Generic[P_contra, In_contra, E_co, R_co]):
    """``ExecutionPlan[P, In, E, R]``: steps to try in order until one
    succeeds. ``P`` is what every step provides, ``In`` the errors the
    steps' predicates and schedules accept, ``E`` and ``R`` what building
    the steps' layers and running their predicates and schedules may fail
    with and need. Build one with ``make`` or ``merge``."""

    steps: tuple[Step[P_contra, In_contra, E_co, R_co], ...]

    @property
    def capture_requirements(self) -> Effect[ExecutionPlan[P_contra, In_contra, E_co], Never, R_co]:
        """The plan with the current services baked into every step's
        layer, predicate and schedule, so it no longer needs ``R``. The
        captured services win over those where the plan later runs."""
        steps = self.steps
        return _WithFiber(
            lambda fiber: _Succeed(ExecutionPlan(tuple(_capture(s, fiber._context) for s in steps)))
        )


def make[P, In = object, EE = Never, RR = Never](
    first: Step[P, In, EE, RR], /, *rest: Step[P, In, EE, RR]
) -> ExecutionPlan[P, In, EE, RR]:
    """A plan of one or more steps (Effect's ``ExecutionPlan.make``)."""
    steps = (first, *rest)
    for i, step in enumerate(steps):
        if step.attempts is not None and step.attempts < 1:
            raise ValueError(f"ExecutionPlan.make: step[{i}].attempts must be greater than 0")
    return ExecutionPlan(steps)


def merge[P, In = object, EE = Never, RR = Never](
    first: ExecutionPlan[P, In, EE, RR], /, *rest: ExecutionPlan[P, In, EE, RR]
) -> ExecutionPlan[P, In, EE, RR]:
    """One plan running the steps of each plan in turn."""
    return ExecutionPlan(tuple(step for plan in (first, *rest) for step in plan.steps))


def _capture(step: Step[Any, Any, Any, Any], ctx: Context[Any]) -> Step[Any, Any, Any, Never]:
    with_ctx = provide(ctx)
    predicate = step.while_
    schedule = step.schedule
    source = step.provide
    return Step(
        provide=source if isinstance(source, Context) else provide(succeed_context(ctx))(source),
        attempts=step.attempts,
        while_=None if predicate is None else lambda error: with_ctx(_as_effect(predicate(error))),
        schedule=None if schedule is None else _capture_schedule(schedule, ctx),
    )


def _as_effect(verdict: bool | Effect[bool, Any, Any]) -> Effect[bool, Any, Any]:
    return verdict if isinstance(verdict, Effect) else _Succeed(verdict)


def _capture_schedule(
    schedule: Schedule[Any, Any, Any, Any], ctx: Context[Any]
) -> Schedule[Any, Any, Any, Never]:
    with_ctx = provide(ctx)

    def wrap(step: StepFn[Any, Any, Any, Any]) -> StepFn[Any, Any, Any, Never]:
        return lambda now, input: with_ctx(step(now, input))

    return Schedule(with_ctx(schedule._make_step.map(wrap)))
