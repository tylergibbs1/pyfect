"""Engines over encoded values: ``Encoded`` and ``make_unsafe`` building a
``WorkflowEngineService`` from one, and ``DeferredState``, the live runs a
deferred completion wakes (Effect's ``WorkflowEngine.makeUnsafe``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any, Never, Protocol, cast, overload

from pyfect._core import Effect, _Locally, _WithFiber
from pyfect._effect_args import require_effect
from pyfect._fiber import Fiber
from pyfect.effect import (
    context,
    die,
    from_exit,
    gen,
    provide_service,
    service_option,
    succeed,
    suspend,
    sync,
)
from pyfect.exit import Exit
from pyfect.schedule import Schedule, Stop, exponential, min, spaced, to_step_with_sleep
from pyfect.schema import decode_unknown_effect, encode_unknown_effect
from pyfect.scope import Scope, add_finalizer
from pyfect.tracer import annotate_current_span
from pyfect.workflow._result import Complete, Result, Suspended
from pyfect.workflow._services import (
    WorkflowEngineService,
    WorkflowInstance,
    WorkflowInstanceService,
)
from pyfect.workflow._suspension import suspend as suspend_run
from pyfect.workflow._suspension import wrap_activity_result
from pyfect.workflow.activity import Activity
from pyfect.workflow.durable_clock import DurableClock
from pyfect.workflow.durable_deferred import DurableDeferred
from pyfect.workflow.workflow import Workflow

type AnyWorkflow = Workflow[Any, Any, Any]
type Handler = Callable[[Any, str], Effect[Any, Any, Any]]

DEFAULT_SUSPENDED_RETRY_SCHEDULE: Schedule[Any, Any, Any, Any] = min(
    exponential("200 millis", 1.5), spaced("30 seconds")
)
"""How a caller outside any workflow polls a suspended execution:
exponential from 200 ms, at most 30 s apart."""


# --- the deferred bookkeeping shared by engines ---------------------------------------


class DeferredState:
    """The live runs of an engine, so a deferred completion can wake the run
    waiting on it (Effect's ``DeferredState``)."""

    __slots__ = ("_running",)

    def __init__(self) -> None:
        self._running: dict[str, tuple[WorkflowInstanceService, Fiber[Any, Any]]] = {}

    # The first overload solves an effect needing only the instance; the
    # second alone would leave ``R`` Unknown.
    @overload
    def track_run[A, E](
        self, instance: WorkflowInstanceService, effect: Effect[A, E, WorkflowInstance]
    ) -> Effect[A, E]: ...
    @overload
    def track_run[A, E, R](
        self, instance: WorkflowInstanceService, effect: Effect[A, E, R | WorkflowInstance]
    ) -> Effect[A, E, R]: ...
    def track_run[A, E, R](
        self, instance: WorkflowInstanceService, effect: Effect[A, E, R | WorkflowInstance]
    ) -> Effect[A, E, R]:
        """Run ``effect`` with ``instance``, tracked until it completes or
        suspends."""
        require_effect(effect, "effect")

        def body(fiber: Fiber[Any, Any]) -> Effect[A, E, R]:
            run = (instance, fiber)
            self._running[instance.execution_id] = run

            def untrack() -> None:
                if self._running.get(instance.execution_id) is run:
                    del self._running[instance.execution_id]

            return effect.pipe(provide_service(WorkflowInstance, instance)).ensuring(sync(untrack))

        return _WithFiber(body)

    def deferred_done(self, execution_id: str, name: str) -> Effect[None]:
        """Preempt the run of ``execution_id`` if it waits on ``name``."""

        def body(current: Fiber[Any, Any]) -> Effect[None]:
            run = self._running.get(execution_id)
            if run is None:
                return succeed(None)
            instance, fiber = run
            if (
                fiber is current
                or fiber.poll_unsafe() is not None
                or name not in instance.awaited_deferreds
            ):
                return succeed(None)
            # The engine stores the completion before waking the run; its
            # replay reads it after the interrupted run reports suspension.
            instance.suspended = True
            return fiber.interrupt()

        return _WithFiber(body)


def make_deferred_state() -> DeferredState:
    return DeferredState()


# --- engines over encoded values --------------------------------------------------------


class EncodedRegister(Protocol):
    def __call__(
        self, workflow: AnyWorkflow, execute: Handler, /
    ) -> Effect[None, Never, Scope]: ...


class EncodedExecute(Protocol):
    def __call__(
        self,
        workflow: AnyWorkflow,
        /,
        *,
        execution_id: str,
        payload: object,
        discard: bool,
        parent: WorkflowInstanceService | None,
        detached: bool,
    ) -> Effect[Result[Any, Any] | None]: ...


class EncodedDeferredDone(Protocol):
    def __call__(
        self, *, workflow_name: str, execution_id: str, deferred_name: str, exit: Exit[Any, Any]
    ) -> Effect[None]: ...


@dataclass(frozen=True, slots=True)
class Encoded:
    """An engine working on encoded values; ``make_unsafe`` adds the schema
    decoding and encoding. ``execute`` gives ``None`` with ``discard``.

    ``await_complete(workflow, execution_id)``, if given, waits until a
    suspended execution has a result other than ``Suspended``. A caller
    races it with its ``suspended_retry_schedule``, so it may never
    complete; completing while the execution is still suspended spends a
    step of that schedule."""

    register: EncodedRegister
    execute: EncodedExecute
    poll: Callable[[AnyWorkflow, str], Effect[Result[Any, Any] | None]]
    interrupt: Callable[[AnyWorkflow, str], Effect[None]]
    interrupt_unsafe: Callable[[AnyWorkflow, str], Effect[None]]
    resume: Callable[[AnyWorkflow, str], Effect[None]]
    activity_execute: Callable[
        [Activity[Any, Any, Any], int], Effect[Result[Any, Any], Never, WorkflowInstance]
    ]
    deferred_result: Callable[
        [DurableDeferred[Any, Any]], Effect[Exit[Any, Any] | None, Never, WorkflowInstance]
    ]
    deferred_done: EncodedDeferredDone
    schedule_clock: Callable[[AnyWorkflow, str, DurableClock], Effect[None]]
    await_complete: Callable[[AnyWorkflow, str], Effect[None]] | None = None


def make_unsafe(options: Encoded) -> WorkflowEngineService:
    """A ``WorkflowEngineService`` over ``options``, which must persist,
    resume and encode workflow state correctly."""

    def register(workflow: AnyWorkflow, execute: Handler) -> Effect[None, Never, Scope]:
        def body() -> Generator[Effect[Any, Never, Any], Any]:
            services = yield from context()

            def handler(payload: Any, execution_id: str) -> Effect[Any, Any, Any]:
                return _Locally(
                    suspend(lambda: execute(payload, execution_id)),
                    services.merge,
                )

            yield from options.register(workflow, handler)

        return gen(body)

    def execute(
        workflow: AnyWorkflow,
        /,
        *,
        execution_id: str,
        payload: object,
        discard: bool = False,
        detached: bool = False,
        suspended_retry_schedule: Schedule[Any, Any, Any, Any] | None = None,
    ) -> Effect[Any, Any]:
        def body() -> Generator[Effect[Any, Any, Any], Any, Any]:
            if detached and not discard:
                return (
                    yield from die(
                        RuntimeError(f"{workflow.tag}.execute: detached requires discard")
                    )
                )
            schedule = (
                DEFAULT_SUSPENDED_RETRY_SCHEDULE
                if suspended_retry_schedule is None
                else suspended_retry_schedule
            )
            yield from annotate_current_span({"executionId": execution_id})
            result: list[Result[Any, Any]] = []

            # Link interruption with the parent workflow.
            parent = yield from service_option(WorkflowInstance)
            parent_instance = None if parent is None else parent.value
            if parent_instance is not None and not detached:
                linked = parent_instance

                def interrupt_child(_: Exit[Any, Any]) -> Effect[None]:
                    if not linked.interrupted or (result and isinstance(result[0], Complete)):
                        return succeed(None)
                    return options.interrupt(workflow, execution_id)

                yield from add_finalizer(interrupt_child)

            run = options.execute(
                workflow,
                execution_id=execution_id,
                payload=payload,
                discard=discard,
                parent=parent_instance,
                detached=detached,
            )
            if discard:
                yield from run
                return execution_id

            if parent_instance is not None:
                wrapped = yield from wrap_activity_result(
                    cast("Effect[Result[Any, Any], Never, Never]", run),
                    lambda r: isinstance(r, Suspended),
                )
                result[:] = [wrapped]
                if isinstance(wrapped, Suspended):
                    return (yield from suspend_run(parent_instance))
                return (yield from from_exit(wrapped.exit))

            step: Callable[[Any], Effect[Any, Any, Any]] | None = None
            while True:
                wrapped = cast("Result[Any, Any]", (yield from run))
                result[:] = [wrapped]
                if isinstance(wrapped, Complete):
                    return (yield from from_exit(wrapped.exit))
                if step is None:
                    step = yield from to_step_with_sleep(schedule)
                sleep = _sleep_step(step, workflow)
                # Completion wakes the caller early; the schedule is the fallback.
                yield from (
                    sleep
                    if options.await_complete is None
                    else sleep.race_first(options.await_complete(workflow, execution_id))
                )

        return cast("Effect[Any, Any]", gen(body))

    def activity_execute(
        activity: Activity[Any, Any, Any], attempt: int, /
    ) -> Effect[Result[Any, Any], Never, WorkflowInstance]:
        def decoded(result: Result[Any, Any]) -> Effect[Result[Any, Any]]:
            if isinstance(result, Suspended):
                return succeed(result)
            return (
                decode_unknown_effect(activity.exit_schema_partial)(result.exit)
                .or_die()
                .map(Complete)
            )

        return options.activity_execute(activity, attempt).flat_map(decoded)

    def deferred_result(
        deferred: DurableDeferred[Any, Any], /
    ) -> Effect[Exit[Any, Any] | None, Never, WorkflowInstance]:
        def body() -> Generator[Effect[Any, Never, Any], Any, Exit[Any, Any] | None]:
            instance = yield from WorkflowInstance()
            yield from annotate_current_span({"executionId": instance.execution_id})
            found = yield from options.deferred_result(deferred)
            if found is None:
                return None
            return (yield from decode_unknown_effect(deferred.exit_schema)(found).or_die())

        return gen(body).with_span(
            "WorkflowEngine.deferredResult",
            attributes={"name": deferred.name},
            capture_stack_trace=False,
        )

    def deferred_done(
        deferred: DurableDeferred[Any, Any],
        /,
        *,
        workflow_name: str,
        execution_id: str,
        deferred_name: str,
        exit: Exit[Any, Any],
    ) -> Effect[None]:
        return (
            encode_unknown_effect(deferred.exit_schema)(exit)
            .or_die()
            .flat_map(
                lambda encoded: options.deferred_done(
                    workflow_name=workflow_name,
                    execution_id=execution_id,
                    deferred_name=deferred_name,
                    exit=encoded,
                )
            )
            .with_span(
                "WorkflowEngine.deferredDone",
                attributes={"name": deferred_name, "executionId": execution_id},
                capture_stack_trace=False,
            )
        )

    def schedule_clock(
        workflow: AnyWorkflow, /, *, execution_id: str, clock: DurableClock
    ) -> Effect[None]:
        return options.schedule_clock(workflow, execution_id, clock).with_span(
            "WorkflowEngine.scheduleClock",
            attributes={"executionId": execution_id, "name": clock.name},
            capture_stack_trace=False,
        )

    return WorkflowEngineService(
        register=register,
        execute=execute,
        poll=options.poll,
        interrupt=options.interrupt,
        interrupt_unsafe=options.interrupt_unsafe,
        resume=options.resume,
        activity_execute=activity_execute,
        deferred_result=deferred_result,
        deferred_done=deferred_done,
        schedule_clock=schedule_clock,
    )


def _sleep_step(
    step: Callable[[Any], Effect[Any, Any, Any]], workflow: AnyWorkflow
) -> Effect[None]:
    def exhausted(decision: Any) -> Effect[None]:
        if isinstance(decision, Stop):
            return die(RuntimeError(f"{workflow.tag}.execute: suspendedRetrySchedule exhausted"))
        return succeed(None)

    return cast(
        "Effect[None]",
        step(None)
        .catch_all(
            lambda _: die(RuntimeError(f"{workflow.tag}.execute: suspendedRetrySchedule exhausted"))
        )
        .flat_map(exhausted),
    )


__all__ = [
    "DEFAULT_SUSPENDED_RETRY_SCHEDULE",
    "AnyWorkflow",
    "DeferredState",
    "Encoded",
    "Handler",
    "make_deferred_state",
    "make_unsafe",
]
