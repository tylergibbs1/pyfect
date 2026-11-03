"""The in-memory engine (Effect's ``WorkflowEngine.layerMemory``): every
execution, activity result and deferred completion lives in this process.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Generator
from dataclasses import dataclass
from typing import Any, Literal, Never, cast

from pyfect._core import Effect, _WithFiber
from pyfect._fiber import Fiber
from pyfect.deferred import Deferred
from pyfect.effect import die, from_exit, gen, never, provide_service, service_option, succeed
from pyfect.effect import suspend as suspend_effect
from pyfect.exit import Exit, Failure, Success
from pyfect.fiber_map import FiberMap
from pyfect.scope import CloseableScope, Scope
from pyfect.workflow._encoded import (
    AnyWorkflow,
    DeferredState,
    Encoded,
    Handler,
    make_deferred_state,
    make_unsafe,
)
from pyfect.workflow._result import Complete, Result, Suspended
from pyfect.workflow._services import (
    WorkflowEngine,
    WorkflowEngineService,
    WorkflowInstance,
    WorkflowInstanceService,
)
from pyfect.workflow.activity import Activity
from pyfect.workflow.durable_clock import DurableClock
from pyfect.workflow.durable_deferred import DurableDeferred
from pyfect.workflow.workflow import SuspendOnFailure, into_result

type WakeMode = Literal["explicit", "automatic"]


def _is_unwakeable(result: Result[Any, Any], mode: WakeMode) -> bool:
    return isinstance(result, Complete) or (mode == "automatic" and result.failed)


def _read_run_exit(
    ex: Exit[Result[Any, Any], Any], instance: WorkflowInstanceService
) -> Exit[Result[Any, Any], Any]:
    if isinstance(ex, Failure) and ex.cause.has_interrupts_only and instance.suspended:
        return Success(Suspended())
    return ex


@dataclass(frozen=True, slots=True)
class _Run:
    """One run of an execution: its fiber and the instance it runs with.
    Its exit is read only through ``poll`` / ``await_exit``, which read a run
    that a deferred completion preempted (``DeferredState.deferred_done``:
    interrupted, its instance suspended) as ``Suspended``, so no reader can
    take a preemption for the end of the execution and close its scope (and
    skip its compensations)."""

    instance: WorkflowInstanceService
    _fiber: Fiber[Result[Any, Any], Any]

    def poll(self) -> Exit[Result[Any, Any], Any] | None:
        ex = self._fiber.poll_unsafe()
        return None if ex is None else _read_run_exit(ex, self.instance)

    def await_exit(self) -> Effect[Exit[Result[Any, Any], Any]]:
        return self._fiber.await_exit().map(lambda ex: _read_run_exit(ex, self.instance))

    def interrupt(self) -> Effect[None]:
        return self._fiber.interrupt()


@dataclass(slots=True)
class _Registered:
    workflow: AnyWorkflow
    execute: Handler
    scope: CloseableScope


@dataclass(slots=True)
class _Execution:
    payload: object
    execute: Handler
    parent: str | None
    instance: WorkflowInstanceService
    # Completed once a run is ``Complete``; then the execution cannot resume.
    done: Deferred[None]
    # The parent of every run's scope. The scopes of runs that suspended
    # stay open under it, so their finalizers last until the execution ends.
    scope: CloseableScope
    interrupted: bool = False
    interrupted_unsafe: bool = False
    # The strongest wake asked for while a run was still finishing.
    resume_requested: WakeMode | None = None
    run: _Run | None = None


@dataclass(slots=True)
class _ActivityRecord:
    exit: Exit[Result[Any, Any], Any] | None = None


class _MemoryEngine:
    """The state of one in-memory engine and its ``Encoded`` operations."""

    def __init__(self, engine_scope: CloseableScope, clocks: FiberMap[str, Any, Any]) -> None:
        self.engine_scope = engine_scope
        self.clocks = clocks
        self.workflows: dict[str, _Registered] = {}
        self.executions: dict[str, _Execution] = {}
        self.activities: dict[str, _ActivityRecord] = {}
        self.deferred_results: dict[str, Exit[Any, Any]] = {}
        self.deferred_state: DeferredState = make_deferred_state()
        self.service = make_unsafe(
            Encoded(
                register=self.register,
                execute=self.execute,
                poll=self.poll,
                interrupt=self.interrupt,
                interrupt_unsafe=self.interrupt_unsafe,
                resume=self.resume_explicit,
                activity_execute=self.activity_execute,
                deferred_result=self.deferred_result,
                deferred_done=self.deferred_done,
                schedule_clock=self.schedule_clock,
                await_complete=self.await_complete,
            )
        )

    # --- waking runs ---------------------------------------------------------------------

    def resume(self, execution_id: str, mode: WakeMode) -> Effect[None]:
        """Start a run of ``execution_id``, or queue the wake behind the run
        still finishing."""

        def run() -> Generator[Effect[Any, Never, Any], Any]:
            state = self.executions.get(execution_id)
            if state is None:
                return
            ex = None if state.run is None else state.run.poll()
            if isinstance(ex, Success) and _is_unwakeable(ex.value, mode):
                return
            if state.run is not None and ex is None:
                yield from self._queue_wake(state, execution_id, mode)
                return
            state.run = yield from self._start_run(state)

        return gen(run)

    def _queue_wake(self, state: _Execution, execution_id: str, mode: WakeMode) -> Effect[None]:
        # Queue wakes until the run finishes cleanup; explicit wakes take priority.
        requested = state.resume_requested
        state.resume_requested = mode if mode == "explicit" else (requested or mode)
        if requested is not None or state.run is None:
            return succeed(None)

        def again(_: object) -> Effect[None]:
            queued = state.resume_requested
            state.resume_requested = None
            return succeed(None) if queued is None else self.resume(execution_id, queued)

        return state.run.await_exit().flat_map(again).fork_in(self.engine_scope).as_void()

    def _start_run(self, state: _Execution) -> Effect[_Run]:
        entry = self.workflows[state.instance.workflow.tag]
        # Each run gets a fresh scope, so a replay rebuilds its compensations
        # instead of registering them again.
        instance = WorkflowInstanceService.initial(
            state.instance.workflow, state.instance.execution_id, scope=state.scope.fork_unsafe()
        )
        state.instance = instance
        suspend_on_failure = instance.workflow.annotations.get_unsafe(SuspendOnFailure)

        def on_run_exit(ex: Exit[Any, Any]) -> Effect[None]:
            # A safe interrupt takes effect only when the run would suspend;
            # an unsafe one also survives a replay that completes normally.
            if not state.interrupted or (
                not state.interrupted_unsafe
                and not instance.suspended
                and not instance.abandoned
                and not (suspend_on_failure and isinstance(ex, Failure))
            ):
                return succeed(None)
            instance.interrupted = True
            instance.suspended = False
            return _WithFiber(lambda fiber: fiber.interrupt().interruptible())

        def wake_parent(result: Result[Any, Any]) -> Effect[None]:
            if state.parent is None or not isinstance(result, Complete):
                return succeed(None)
            return self.resume(state.parent, "automatic").fork_in(self.engine_scope).as_void()

        def finish(ex: Exit[Result[Any, Any], Any]) -> Effect[None]:
            if isinstance(ex, Success) and isinstance(ex.value, Suspended):
                return succeed(None)
            # The final run's scope closed with the real exit; closing the
            # parent now closes the earlier ones, last first, with success, so
            # their superseded compensations are skipped.
            closed = state.scope.close(Success(None))
            if isinstance(ex, Success) and isinstance(ex.value, Complete):
                return closed.and_then(state.done.succeed(None)).as_void()
            return closed

        tracked: Effect[Result[Any, Any], Never, Any] = self.deferred_state.track_run(
            instance,
            into_result(
                state.execute(state.payload, instance.execution_id).on_exit(on_run_exit)
            ).pipe(provide_service(WorkflowEngine, self.service)),
        )
        return (
            tracked.tap(wake_parent)
            .on_exit(lambda ex: finish(_read_run_exit(ex, instance)))
            .fork_in(entry.scope)
            .map(lambda fiber: _Run(instance, fiber))
        )

    # --- the Encoded operations ----------------------------------------------------------

    def register(self, workflow: AnyWorkflow, execute: Handler, /) -> Effect[None, Never, Scope]:
        return Scope().map(
            lambda scope: self.workflows.__setitem__(
                workflow.tag, _Registered(workflow, execute, scope)
            )
        )

    def execute(
        self,
        workflow: AnyWorkflow,
        /,
        *,
        execution_id: str,
        payload: object,
        discard: bool,
        parent: WorkflowInstanceService | None,
        detached: bool,
    ) -> Effect[Result[Any, Any] | None]:
        def run() -> Generator[Effect[Any, Any, Any], Any, Result[Any, Any] | None]:
            entry = self.workflows.get(workflow.tag)
            if entry is None:
                return (yield from die(RuntimeError(f"Workflow {workflow.tag} is not registered")))
            state = self.executions.get(execution_id)
            if state is None:
                state = _Execution(
                    payload=payload,
                    execute=entry.execute,
                    parent=None if detached or parent is None else parent.execution_id,
                    instance=WorkflowInstanceService.initial(workflow, execution_id),
                    done=Deferred[None](),
                    scope=CloseableScope(),
                )
                self.executions[execution_id] = state
                yield from self.resume(execution_id, "explicit")
            if discard:
                return None
            # Read the run now, so a wake swapping in a replay cannot desync it.
            current = state.run
            assert current is not None, "resume starts the first run"
            # A preempted run gives ``Suspended``; the caller retries into the replay.
            return (yield from from_exit((yield from current.await_exit())))

        return cast("Effect[Result[Any, Any] | None]", gen(run))

    def _owned(self, workflow: AnyWorkflow, execution_id: str) -> _Execution | None:
        """The execution ``execution_id`` when it is one of ``workflow``: an
        operation called through one workflow never reaches another's."""
        state = self.executions.get(execution_id)
        if state is None or state.instance.workflow.tag != workflow.tag:
            return None
        return state

    def await_complete(self, workflow: AnyWorkflow, execution_id: str) -> Effect[None]:
        def run() -> Effect[None]:
            state = self._owned(workflow, execution_id)
            return never if state is None else state.done.wait()

        return suspend_effect(run)

    def interrupt(self, workflow: AnyWorkflow, execution_id: str) -> Effect[None]:
        def run() -> Effect[None]:
            state = self._owned(workflow, execution_id)
            if state is None:
                return succeed(None)
            state.interrupted = True
            return self.resume(execution_id, "explicit")

        return suspend_effect(run)

    def interrupt_unsafe(self, workflow: AnyWorkflow, execution_id: str) -> Effect[None]:
        def run() -> Generator[Effect[Any, Never, Any], Any]:
            state = self._owned(workflow, execution_id)
            if state is None:
                return
            state.interrupted = True
            state.interrupted_unsafe = True
            if state.run is not None:
                yield from state.run.interrupt()
            # Replay after a hard interrupt to record a terminal result.
            yield from self.resume(execution_id, "explicit")

        return gen(run)

    def resume_explicit(self, workflow: AnyWorkflow, execution_id: str) -> Effect[None]:
        return suspend_effect(
            lambda: (
                succeed(None)
                if self._owned(workflow, execution_id) is None
                else self.resume(execution_id, "explicit")
            )
        )

    def activity_execute(
        self, activity: Activity[Any, Any, Any], attempt: int
    ) -> Effect[Result[Any, Any], Never, WorkflowInstance]:
        def run() -> Generator[Effect[Any, Any, Any], Any, Result[Any, Any]]:
            instance = yield from WorkflowInstance()
            activity_id = f"{instance.execution_id}/{activity.name}/{attempt}"
            record = self.activities.get(activity_id)
            if record is not None:
                ex = record.exit
                if isinstance(ex, Success) and isinstance(ex.value, Suspended):
                    record.exit = None
                elif ex is not None:
                    return (yield from from_exit(ex))
            else:
                record = _ActivityRecord()
                self.activities[activity_id] = record
            # A pending interrupt replays only to rebuild compensations, so it
            # runs no new activity. Finalizers run once ``interrupted`` is set.
            execution = self.executions.get(instance.execution_id)
            if execution is not None and execution.interrupted and not instance.interrupted:
                return Suspended()
            activity_instance = WorkflowInstanceService.initial(
                instance.workflow, instance.execution_id
            )
            activity_instance.interrupted = instance.interrupted
            held = record

            def store(ex: Exit[Result[Any, Any], Any]) -> Effect[None]:
                # A preempted activity runs again on the next replay.
                interrupted = isinstance(ex, Failure) and ex.cause.has_interrupts_only
                held.exit = None if interrupted else ex
                return succeed(None)

            return (
                yield from into_result(activity.execute_encoded)
                .pipe(provide_service(WorkflowInstance, activity_instance))
                .on_exit(store)
            )

        return cast("Effect[Result[Any, Any], Never, WorkflowInstance]", gen(run))

    def poll(self, workflow: AnyWorkflow, execution_id: str) -> Effect[Result[Any, Any] | None]:
        def run() -> Effect[Result[Any, Any] | None]:
            state = self._owned(workflow, execution_id)
            ex = None if state is None or state.run is None else state.run.poll()
            if ex is None:
                return succeed(None)
            if isinstance(ex, Success):
                return succeed(ex.value)
            return die(ex.cause.squash())

        return suspend_effect(run)

    def deferred_result(
        self, deferred: DurableDeferred[Any, Any]
    ) -> Effect[Exit[Any, Any] | None, Never, WorkflowInstance]:
        return WorkflowInstance().map(
            lambda instance: self.deferred_results.get(f"{instance.execution_id}/{deferred.name}")
        )

    def deferred_done(
        self, *, workflow_name: str, execution_id: str, deferred_name: str, exit: Exit[Any, Any]
    ) -> Effect[None]:
        def run() -> Effect[None]:
            key = f"{execution_id}/{deferred_name}"
            if key in self.deferred_results:
                return succeed(None)
            self.deferred_results[key] = exit
            wake = self.deferred_state.deferred_done(execution_id, deferred_name).and_then(
                self.resume(execution_id, "automatic")
            )

            def by_caller(found: Any) -> Effect[None]:
                # A workflow finalizer cannot wait for its own run's cleanup:
                # the engine scope owns that wake, so cleanup still precedes
                # the replay.
                if found is not None and found.value.execution_id == execution_id:
                    return wake.fork_in(self.engine_scope).as_void()
                return wake

            return service_option(WorkflowInstance).flat_map(by_caller)

        return suspend_effect(run)

    def schedule_clock(
        self, workflow: AnyWorkflow, execution_id: str, clock: DurableClock
    ) -> Effect[None]:
        wake = self.service.deferred_done(
            clock.deferred,
            workflow_name=workflow.tag,
            execution_id=execution_id,
            deferred_name=clock.deferred.name,
            exit=Success(None),
        ).delay(clock.duration)
        return self.clocks.run(f"{execution_id}/{clock.name}", wake, only_if_missing=True).as_void()


def make_memory() -> Effect[WorkflowEngineService, Never, Scope]:
    """A new in-memory engine; its runs and clocks end with the scope."""

    def body() -> Generator[Effect[Any, Never, Any], Any, WorkflowEngineService]:
        engine_scope = yield from Scope()
        clocks: FiberMap[str, Any, Any] = yield from FiberMap[str, Any, Any].make()
        return _MemoryEngine(engine_scope, clocks).service

    return gen(body)


__all__ = ["make_memory"]
