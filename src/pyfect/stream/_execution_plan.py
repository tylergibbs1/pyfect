"""``stream.with_execution_plan``: run a stream under an ``ExecutionPlan``
(Effect's ``Stream.withExecutionPlan``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from typing import Any, Generic, Never, TypeVar, overload

from pyfect._core import Effect, _Succeed
from pyfect.effect import sync, yield_now
from pyfect.execution_plan._events import AttemptState, OnEvent
from pyfect.execution_plan._events import CurrentMetadata as PlanMetadata
from pyfect.execution_plan._model import ExecutionPlan, Step
from pyfect.execution_plan._run import PlanRun, fallback_schedule, first_schedule
from pyfect.exit import Exit
from pyfect.pull import catch_done
from pyfect.schedule import CurrentMetadata, Metadata, Schedule
from pyfect.schedule._model import to_step_with_metadata
from pyfect.stream._base import AnyStream, StreamBase
from pyfect.stream._constructors import fail, suspend, unwrap
from pyfect.stream._context import provide, provide_service_effect
from pyfect.stream._stream import Stream

P_contra = TypeVar("P_contra", contravariant=True)
In_contra = TypeVar("In_contra", contravariant=True)
PE_co = TypeVar("PE_co", covariant=True)
PR_co = TypeVar("PR_co", covariant=True)

type _AnyStream = Stream[Any, Any, Any]
_VOID: Effect[None] = _Succeed(None)


def _retry_without_reset(self: AnyStream, schedule: Schedule[Any, Any, Any, Any]) -> _AnyStream:
    """Rerun ``self`` after each failure while ``schedule`` recurs. Unlike
    ``Stream.retry``, items written before a failure do not reset the
    schedule, so a stream that always fails part-way still stops."""

    def build(step: Any) -> _AnyStream:
        meta: Metadata[Any, Any] = CurrentMetadata.default()

        def loop() -> _AnyStream:
            return self.pipe(provide_service_effect(CurrentMetadata, sync(lambda: meta))).catch_all(
                again
            )

        def again(error: Any) -> _AnyStream:
            def stepped(next_meta: Metadata[Any, Any]) -> _AnyStream:
                nonlocal meta
                meta = next_meta
                return unwrap(yield_now().as_(loop()))

            return unwrap(catch_done(step(error).map(stepped), lambda _: _Succeed(fail(error))))

        return loop()

    return unwrap(to_step_with_metadata(schedule).map(build))


class _StreamPlanRun(PlanRun):
    __slots__ = ("attempt", "last_error")

    def __init__(self, on_event: OnEvent[Any, Any] | None) -> None:
        super().__init__(on_event)
        self.attempt: AttemptState | None = None
        self.last_error: tuple[Any] | None = None

    def instrument(self, stream: _AnyStream) -> _AnyStream:
        emitter = self.emitter
        if emitter is None:
            return stream

        def started(state: AttemptState) -> None:
            self.attempt = state

        def ended(ex: Exit[Any, Any]) -> Effect[None, Never, Any]:
            state = self.attempt
            if state is None:
                return _VOID
            self.attempt = None
            return emitter.end(state, ex)

        return stream.on_start(emitter.begin().map(started)).on_exit(ended)


def _run_plan(
    self: AnyStream,
    plan: ExecutionPlan[Any, Any, Any, Any],
    prevent_fallback_on_partial_stream: bool,
    on_event: OnEvent[Any, Any] | None,
) -> _AnyStream:
    def start() -> _AnyStream:
        run = _StreamPlanRun(on_event)

        def step_stream(step: Step[Any, Any, Any, Any]) -> _AnyStream:
            provided = run.instrument(provide(step.provide)(self))
            attempt = provided.pipe(provide_service_effect(PlanMetadata, sync(run.next_meta)))
            if run.last_error is None:
                policy = first_schedule(step)
                return attempt if policy is None else _retry_without_reset(attempt, policy)
            (error,) = run.last_error
            replayed = False

            def next_run() -> AnyStream:
                nonlocal replayed
                if replayed:
                    return attempt
                replayed = True
                return fail(error)

            return _retry_without_reset(suspend(next_run), fallback_schedule(step))

        def loop() -> _AnyStream:
            received = False

            def first_item(_: Any) -> Effect[None]:
                nonlocal received
                received = True
                return _VOID

            def on_error(error: Any) -> _AnyStream:
                run.index += 1
                partial = prevent_fallback_on_partial_stream and received
                if partial or run.index >= len(plan.steps):
                    return fail(error)
                run.last_error = (error,)
                return suspend(loop)

            attempt = step_stream(plan.steps[run.index])
            if prevent_fallback_on_partial_stream:
                attempt = attempt.on_first(first_item)
            return attempt.catch_all(on_error)

        return suspend(loop)

    return suspend(start)


class _WithExecutionPlan(Generic[P_contra, In_contra, PE_co, PR_co]):
    """Runs a stream under a plan, removing ``P`` from its services. When
    the plan's predicates or schedules read the errors (``In`` is not
    ``object``), the stream's errors must be ``In`` and are typed as ``In``."""

    __slots__ = ("on_event", "plan", "prevent_fallback_on_partial_stream")

    def __init__(
        self,
        plan: ExecutionPlan[Any, Any, Any, Any],
        prevent_fallback_on_partial_stream: bool,
        on_event: OnEvent[Any, Any] | None,
    ) -> None:
        self.plan = plan
        self.prevent_fallback_on_partial_stream = prevent_fallback_on_partial_stream
        self.on_event = on_event

    @overload
    def __call__[A, E](
        self: _WithExecutionPlan[P_contra, object, PE_co, PR_co], stream: StreamBase[A, E, P_contra]
    ) -> Stream[A, E | PE_co, PR_co]: ...
    @overload
    def __call__[A, E, R](
        self: _WithExecutionPlan[P_contra, object, PE_co, PR_co],
        stream: StreamBase[A, E, P_contra | R],
    ) -> Stream[A, E | PE_co, R | PR_co]: ...
    @overload
    def __call__[A](
        self, stream: StreamBase[A, In_contra, P_contra]
    ) -> Stream[A, In_contra | PE_co, PR_co]: ...
    @overload
    def __call__[A, R](
        self, stream: StreamBase[A, In_contra, P_contra | R]
    ) -> Stream[A, In_contra | PE_co, R | PR_co]: ...
    def __call__(self, stream: AnyStream) -> _AnyStream:
        return _run_plan(stream, self.plan, self.prevent_fallback_on_partial_stream, self.on_event)


@overload
def with_execution_plan[P, In, PE, PR](
    plan: ExecutionPlan[P, In, PE, PR], *, prevent_fallback_on_partial_stream: bool = False
) -> _WithExecutionPlan[P, In, PE, PR]: ...
@overload
def with_execution_plan[P, In, PE, RR](
    plan: ExecutionPlan[P, In, PE, RR],
    *,
    prevent_fallback_on_partial_stream: bool = False,
    on_event: OnEvent[In | PE, RR],
) -> _WithExecutionPlan[P, In, PE, RR]: ...
def with_execution_plan(
    plan: ExecutionPlan[Any, Any, Any, Any],
    *,
    prevent_fallback_on_partial_stream: bool = False,
    on_event: OnEvent[Any, Any] | None = None,
) -> _WithExecutionPlan[Any, Any, Any, Any]:
    """Run a stream under ``plan``, as ``pyfect.with_execution_plan`` runs
    an effect: a failing step falls back to the next, even after writing
    items, unless ``prevent_fallback_on_partial_stream`` (then it fails).
    Use with ``.pipe``. A downstream consumer that stops early ends the
    attempt with ``AttemptSuccess``."""
    return _WithExecutionPlan(plan, prevent_fallback_on_partial_stream, on_event)
