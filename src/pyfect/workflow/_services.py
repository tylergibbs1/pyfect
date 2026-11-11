"""The two services every workflow runs with: ``WorkflowEngine`` (Effect's
``WorkflowEngine.WorkflowEngine``) and ``WorkflowInstance``, the state of
one workflow run."""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Never, Protocol, Self

from pyfect._core import Effect
from pyfect._service_copy import replaced
from pyfect.cause import Cause
from pyfect.context import Tag
from pyfect.exit import Exit
from pyfect.latch import Latch
from pyfect.scope import CloseableScope, Scope

if TYPE_CHECKING:
    from pyfect.schedule import Schedule
    from pyfect.workflow._result import Result
    from pyfect.workflow.activity import Activity
    from pyfect.workflow.durable_clock import DurableClock
    from pyfect.workflow.durable_deferred import DurableDeferred
    from pyfect.workflow.workflow import Workflow


class ActivityState:
    """How many activities of a run are in flight; ``latch`` is open when
    none are."""

    __slots__ = ("count", "latch")

    def __init__(self) -> None:
        self.count = 0
        self.latch = Latch()


class WorkflowInstanceService:
    """The state of one workflow run (Effect's ``WorkflowInstance``
    service): its execution id and workflow, a scope closed only when the
    execution completes, and the flags the engine and the run set.

    ``awaited_deferreds`` counts the durable waits of the run per deferred
    name (a completion of one of them preempts the run);
    ``completed_deferreds`` names those the run completed itself."""

    __slots__ = (
        "__weakref__",
        "abandoned",
        "activity_state",
        "awaited_deferreds",
        "cause",
        "completed_deferreds",
        "execution_id",
        "failed",
        "interrupted",
        "scope",
        "suspended",
        "workflow",
    )

    def __init__(
        self,
        workflow: Workflow[Any, Any, Any],
        execution_id: str,
        *,
        scope: CloseableScope,
        awaited_deferreds: dict[str, int],
        completed_deferreds: set[str],
        activity_state: ActivityState,
    ) -> None:
        self.execution_id = execution_id
        self.workflow = workflow
        self.scope = scope
        self.suspended = False
        self.interrupted = False
        self.abandoned = False
        self.cause: Cause[Never] | None = None
        self.failed = False
        self.awaited_deferreds = awaited_deferreds
        self.completed_deferreds = completed_deferreds
        self.activity_state = activity_state

    @staticmethod
    def initial(
        workflow: Workflow[Any, Any, Any],
        execution_id: str,
        *,
        scope: CloseableScope | None = None,
        awaited_deferreds: dict[str, int] | None = None,
    ) -> WorkflowInstanceService:
        """A fresh run: not suspended, interrupted, abandoned or failed.
        ``awaited_deferreds`` shares the waits of the run an activity
        instance belongs to."""
        return WorkflowInstanceService(
            workflow,
            execution_id,
            scope=CloseableScope() if scope is None else scope,
            awaited_deferreds={} if awaited_deferreds is None else awaited_deferreds,
            completed_deferreds=set(),
            activity_state=ActivityState(),
        )

    def copy(self) -> WorkflowInstanceService:
        """A copy sharing the scope and the deferred bookkeeping, with its
        own activity state and not suspended (Effect's ``{ ...instance,
        suspended: false, activityState: ... }``)."""
        copied = WorkflowInstanceService(
            self.workflow,
            self.execution_id,
            scope=self.scope,
            awaited_deferreds=self.awaited_deferreds,
            completed_deferreds=self.completed_deferreds,
            activity_state=ActivityState(),
        )
        copied.interrupted = self.interrupted
        copied.abandoned = self.abandoned
        copied.cause = self.cause
        copied.failed = self.failed
        return copied


class WorkflowInstance(
    Tag[WorkflowInstanceService], key="effect/workflow/WorkflowEngine/WorkflowInstance"
):
    """The workflow run the current effect belongs to."""


# --- the engine ------------------------------------------------------------------------


class Register(Protocol):
    def __call__(
        self,
        workflow: Workflow[Any, Any, Any],
        execute: Callable[[Any, str], Effect[Any, Any, Any]],
        /,
    ) -> Effect[None, Never, Scope]: ...


class Execute(Protocol):
    def __call__(
        self,
        workflow: Workflow[Any, Any, Any],
        /,
        *,
        execution_id: str,
        payload: object,
        discard: bool = False,
        detached: bool = False,
        suspended_retry_schedule: Schedule[Any, Any, Any, Any] | None = None,
    ) -> Effect[Any, Any]: ...


class Poll(Protocol):
    def __call__[P, A, E](
        self, workflow: Workflow[P, A, E], execution_id: str, /
    ) -> Effect[Result[A, E] | None]: ...


class ByExecutionId(Protocol):
    def __call__(self, workflow: Workflow[Any, Any, Any], execution_id: str, /) -> Effect[None]: ...


class ActivityExecute(Protocol):
    def __call__[A, E](
        self, activity: Activity[A, E, Any], attempt: int, /
    ) -> Effect[Result[A, E], Never, WorkflowInstance]: ...


class DeferredResult(Protocol):
    def __call__[A, E](
        self, deferred: DurableDeferred[A, E], /
    ) -> Effect[Exit[A, E] | None, Never, WorkflowInstance]: ...


class DeferredDone(Protocol):
    def __call__[A, E](
        self,
        deferred: DurableDeferred[A, E],
        /,
        *,
        workflow_name: str,
        execution_id: str,
        deferred_name: str,
        exit: Exit[A, E],
    ) -> Effect[None]: ...


class ScheduleClock(Protocol):
    def __call__(
        self, workflow: Workflow[Any, Any, Any], /, *, execution_id: str, clock: DurableClock
    ) -> Effect[None]: ...


class WorkflowEngineService:
    """Registers and runs workflows and coordinates their activities,
    durable deferreds, interrupts, resumes and clocks (Effect's
    ``WorkflowEngine``). Build one with ``workflow_engine.make_unsafe``
    (or use ``layer_memory``); ``copy.replace(engine, poll=...)`` swaps an
    operation."""

    __slots__ = (
        "_activity_execute",
        "_deferred_done",
        "_deferred_result",
        "_execute",
        "_interrupt",
        "_interrupt_unsafe",
        "_poll",
        "_register",
        "_resume",
        "_schedule_clock",
    )

    def __replace__(self, **changes: Any) -> Self:
        """A copy with ``changes`` to the constructor's arguments (``copy.replace``)."""
        return replaced(self, changes)

    def __init__(  # noqa: PLR0917
        self,
        register: Register,
        execute: Execute,
        poll: Poll,
        interrupt: ByExecutionId,
        interrupt_unsafe: ByExecutionId,
        resume: ByExecutionId,
        activity_execute: ActivityExecute,
        deferred_result: DeferredResult,
        deferred_done: DeferredDone,
        schedule_clock: ScheduleClock,
    ) -> None:
        self._register = register
        self._execute = execute
        self._poll = poll
        self._interrupt = interrupt
        self._interrupt_unsafe = interrupt_unsafe
        self._resume = resume
        self._activity_execute = activity_execute
        self._deferred_result = deferred_result
        self._deferred_done = deferred_done
        self._schedule_clock = schedule_clock

    def register(
        self,
        workflow: Workflow[Any, Any, Any],
        execute: Callable[[Any, str], Effect[Any, Any, Any]],
        /,
    ) -> Effect[None, Never, Scope]:
        """Registers ``execute(payload, execution_id)`` as the handler of
        ``workflow``, with the services of the caller, until the ``Scope``
        closes. Never fails."""
        return self._register(workflow, execute)

    def execute(
        self,
        workflow: Workflow[Any, Any, Any],
        /,
        *,
        execution_id: str,
        payload: object,
        discard: bool = False,
        detached: bool = False,
        suspended_retry_schedule: Schedule[Any, Any, Any, Any] | None = None,
    ) -> Effect[Any, Any]:
        """Runs ``workflow`` (it must be registered, else a defect) with
        ``payload`` as ``execution_id``. With ``discard`` it gives the
        execution id without waiting for the result; otherwise it gives the
        workflow's success or fails with its error.
        A caller outside any workflow waits for the result, retrying a
        suspended execution on ``suspended_retry_schedule`` (by default
        exponential from 200 ms, at most 30 s apart), woken sooner when the
        engine sees the result. Inside a workflow the child is interrupted
        with its parent, and a child suspension suspends the parent; a child
        that was interrupted is a defect for the parent. ``detached`` skips
        that link and needs ``discard`` (else a defect)."""
        return self._execute(
            workflow,
            execution_id=execution_id,
            payload=payload,
            discard=discard,
            detached=detached,
            suspended_retry_schedule=suspended_retry_schedule,
        )

    def poll[P, A, E](
        self, workflow: Workflow[P, A, E], execution_id: str, /
    ) -> Effect[Result[A, E] | None]:
        """The result of the execution so far (``Complete`` or
        ``Suspended``), ``None`` when it has none. Never fails."""
        return self._poll(workflow, execution_id)

    def interrupt(self, workflow: Workflow[Any, Any, Any], execution_id: str, /) -> Effect[None]:
        """Interrupts the execution: its run is replayed to run its
        compensations and interrupt its child workflows. Never fails."""
        return self._interrupt(workflow, execution_id)

    def interrupt_unsafe(
        self, workflow: Workflow[Any, Any, Any], execution_id: str, /
    ) -> Effect[None]:
        """Interrupts the execution at once, possibly skipping its
        compensations and orphaning its child workflows. Never fails."""
        return self._interrupt_unsafe(workflow, execution_id)

    def resume(self, workflow: Workflow[Any, Any, Any], execution_id: str, /) -> Effect[None]:
        """Replays a suspended execution. Never fails."""
        return self._resume(workflow, execution_id)

    def activity_execute[A, E](
        self, activity: Activity[A, E, Any], attempt: int, /
    ) -> Effect[Result[A, E], Never, WorkflowInstance]:
        """Runs ``activity`` (its ``attempt``-th try) for the workflow run
        in the context, or gives its stored result when it already ran.
        Its failure is in the ``Result``; the effect never fails."""
        return self._activity_execute(activity, attempt)

    def deferred_result[A, E](
        self, deferred: DurableDeferred[A, E], /
    ) -> Effect[Exit[A, E] | None, Never, WorkflowInstance]:
        """The stored exit of ``deferred`` for the workflow run in the
        context, ``None`` while it is not done. Never fails."""
        return self._deferred_result(deferred)

    def deferred_done[A, E](
        self,
        deferred: DurableDeferred[A, E],
        /,
        *,
        workflow_name: str,
        execution_id: str,
        deferred_name: str,
        exit: Exit[A, E],
    ) -> Effect[None]:
        """Stores ``exit`` as the result of the deferred ``deferred_name``
        of ``execution_id`` (of ``workflow_name``), then resumes the run
        waiting on it. Never fails."""
        return self._deferred_done(
            deferred,
            workflow_name=workflow_name,
            execution_id=execution_id,
            deferred_name=deferred_name,
            exit=exit,
        )

    def schedule_clock(
        self, workflow: Workflow[Any, Any, Any], /, *, execution_id: str, clock: DurableClock
    ) -> Effect[None]:
        """Schedules the wake-up of ``clock`` for ``execution_id``: when it
        is due, the clock's deferred is done and the execution resumes.
        Never fails."""
        return self._schedule_clock(workflow, execution_id=execution_id, clock=clock)


class WorkflowEngine(Tag[WorkflowEngineService], key="effect/workflow/WorkflowEngine"):
    """The engine running workflows (``workflow_engine.layer_memory``)."""


__all__ = [
    "ActivityState",
    "WorkflowEngine",
    "WorkflowEngineService",
    "WorkflowInstance",
    "WorkflowInstanceService",
]
