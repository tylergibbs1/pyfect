"""Running an effect under a plan (Effect's ``Effect.withExecutionPlan``),
and the per-step retry schedules shared with ``Stream.with_execution_plan``."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, Generic, Never, TypeVar, overload

from pyfect._context_effects import provide_service_effect
from pyfect._core import Effect, _Gen, _Suspend, uninterruptible_mask
from pyfect._effect_args import require_effect
from pyfect.effect import from_result, sync
from pyfect.execution_plan._events import (
    CurrentMetadata,
    EventEmitter,
    Metadata,
    OnEvent,
)
from pyfect.execution_plan._model import ExecutionPlan, Step
from pyfect.layer import provide
from pyfect.result import Ok, Result
from pyfect.schedule import Schedule, recurs
from pyfect.schedule._drive import from_options, retry

P_contra = TypeVar("P_contra", contravariant=True)
In_contra = TypeVar("In_contra", contravariant=True)
PE_co = TypeVar("PE_co", covariant=True)
PR_co = TypeVar("PR_co", covariant=True)

_ONCE = recurs(1)


def first_schedule(step: Step[Any, Any, Any, Any]) -> Schedule[Any, Any, Any, Any] | None:
    """The retry schedule of the plan's first step: ``attempts - 1``
    retries on the step's schedule, or none when it runs once."""
    if step.attempts == 1 or not (step.schedule or step.attempts):
        return None
    times = None if step.attempts is None else step.attempts - 1
    return from_options(step.schedule, times, step.while_, None)


def fallback_schedule(step: Step[Any, Any, Any, Any]) -> Schedule[Any, Any, Any, Any]:
    """The retry schedule of a step after an earlier one failed: its first
    retry replays that failure, so the step's schedule (or a single retry)
    always applies at least once."""
    default = None if step.attempts else _ONCE
    return from_options(step.schedule or default, step.attempts, step.while_, None)


class PlanRun:
    """The state of one run of a plan: which step is running and the
    metadata of the latest attempt."""

    __slots__ = ("emitter", "index", "meta")

    def __init__(self, on_event: OnEvent[Any, Any] | None) -> None:
        self.index = 0
        self.meta = CurrentMetadata.default()
        self.emitter = None if on_event is None else EventEmitter(on_event, lambda: self.meta)

    def next_meta(self) -> Metadata:
        self.meta = Metadata(attempt=self.meta.attempt + 1, step_index=self.index)
        return self.meta


def _provide_meta[A, E, R](run: PlanRun, eff: Effect[A, E, R]) -> Effect[A, E, R]:
    return eff.pipe(provide_service_effect(CurrentMetadata, sync(run.next_meta)))


def _instrument[A, E, R](run: PlanRun, attempt: Effect[A, E, R]) -> Effect[A, E, R]:
    emitter = run.emitter
    if emitter is None:
        return attempt
    return uninterruptible_mask(
        lambda restore: emitter.begin().flat_map(
            lambda state: restore(attempt).on_exit(lambda ex: emitter.end(state, ex))
        )
    )


def _replaying_first(
    failed: Result[Any, Any], attempt: Effect[Any, Any, Any]
) -> Effect[Any, Any, Any]:
    replayed = False

    def next_run() -> Effect[Any, Any, Any]:
        nonlocal replayed
        if replayed:
            return attempt
        replayed = True
        return from_result(failed)

    return _Suspend(next_run)


def run_plan(
    eff: Effect[Any, Any, Any],
    plan: ExecutionPlan[Any, Any, Any, Any],
    on_event: OnEvent[Any, Any] | None,
) -> Effect[Any, Any, Any]:
    def attempt(run: PlanRun, step: Step[Any, Any, Any, Any]) -> Effect[Any, Any, Any]:
        return _provide_meta(run, _instrument(run, provide(step.provide)(eff)))

    def body() -> Any:
        run = PlanRun(on_event)
        first, *rest = plan.steps
        policy = first_schedule(first)
        tried = attempt(run, first)
        result = yield from (tried if policy is None else retry(tried, policy)).result()
        for step in rest:
            if isinstance(result, Ok):
                break
            run.index += 1
            replayed = _replaying_first(result, attempt(run, step))
            result = yield from retry(replayed, fallback_schedule(step)).result()
        return (yield from from_result(result))

    return _Gen(body)


class _WithExecutionPlan(Generic[P_contra, In_contra, PE_co, PR_co]):
    """Runs an effect under a plan, removing ``P`` from its services. When
    the plan's predicates or schedules read the errors (``In`` is not
    ``object``), the effect's errors must be ``In`` and are typed as ``In``."""

    __slots__ = ("on_event", "plan")

    def __init__(
        self, plan: ExecutionPlan[Any, Any, Any, Any], on_event: OnEvent[Any, Any] | None
    ) -> None:
        self.plan = plan
        self.on_event = on_event

    @overload
    def __call__[A, E, R = Never](
        self: _WithExecutionPlan[P_contra, object, PE_co, PR_co], eff: Effect[A, E, P_contra]
    ) -> Effect[A, E | PE_co, PR_co]: ...
    @overload
    def __call__[A, E, R = Never](
        self: _WithExecutionPlan[P_contra, object, PE_co, PR_co], eff: Effect[A, E, P_contra | R]
    ) -> Effect[A, E | PE_co, R | PR_co]: ...
    @overload
    def __call__[A, R = Never](
        self, eff: Effect[A, In_contra, P_contra]
    ) -> Effect[A, In_contra | PE_co, PR_co]: ...
    @overload
    def __call__[A, R = Never](
        self, eff: Effect[A, In_contra, P_contra | R]
    ) -> Effect[A, In_contra | PE_co, R | PR_co]: ...
    def __call__(self, eff: Effect[Any, Any, Any]) -> Effect[Any, Any, Any]:
        require_effect(eff, "eff")
        return run_plan(eff, self.plan, self.on_event)


@overload
def with_execution_plan[P, In, PE, PR](
    plan: ExecutionPlan[P, In, PE, PR],
) -> _WithExecutionPlan[P, In, PE, PR]: ...
@overload
def with_execution_plan[P, In, PE, RR](
    plan: ExecutionPlan[P, In, PE, RR], *, on_event: OnEvent[In | PE, RR]
) -> _WithExecutionPlan[P, In, PE, RR]: ...
def with_execution_plan(
    plan: ExecutionPlan[Any, Any, Any, Any], *, on_event: OnEvent[Any, Any] | None = None
) -> _WithExecutionPlan[Any, Any, Any, Any]:
    """Run an effect under ``plan``: each step in turn, with the services
    it provides, retried as the step says, until an attempt succeeds or
    the plan runs out (then fail with the last error). Defects and
    interruptions are not retried. Use with ``.pipe``::

        fetch.pipe(fx.with_execution_plan(plan))

    Each attempt sees its ``CurrentMetadata``. ``on_event`` observes every
    attempt's start and end, in order; its failures are ignored, and the
    end is reported even when the attempt is interrupted."""
    return _WithExecutionPlan(plan, on_event)
