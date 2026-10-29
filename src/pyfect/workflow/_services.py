"""The two services every workflow runs with: ``WorkflowEngine`` (Effect's
``WorkflowEngine.WorkflowEngine``) and ``WorkflowInstance``, the state of
one workflow run."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Never, Protocol

from pyfect._core import Effect
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


@dataclass(frozen=True, slots=True)
class WorkflowEngineService:
    """Registers and runs workflows and coordinates their activities,
    durable deferreds, interrupts, resumes and clocks. Build one with
    ``workflow_engine.make_unsafe`` (or use ``layer_memory``); replace a
    member with ``dataclasses.replace``.

    - ``register(workflow, execute)``: the handler of ``workflow``
    - ``execute(workflow, execution_id=, payload=, discard=, detached=,
      suspended_retry_schedule=)``: run it; unless ``discard``, a caller
      outside any workflow waits for the result, retrying a suspended
      execution on ``suspended_retry_schedule`` (woken sooner when the
      engine sees the result). ``detached`` needs ``discard`` (else a
      defect) and skips the parent's completion wakes and interruption.
    - ``poll``: the result so far, ``None`` while there is none
    - ``interrupt`` / ``interrupt_unsafe``: interrupt an execution; the
      unsafe one may skip compensations and orphan child workflows
    - ``resume``: replay a suspended execution
    - ``activity_execute``, ``deferred_result``, ``deferred_done``,
      ``schedule_clock``: what activities, durable deferreds and clocks
      call
    """

    register: Register
    execute: Execute
    poll: Poll
    interrupt: ByExecutionId
    interrupt_unsafe: ByExecutionId
    resume: ByExecutionId
    activity_execute: ActivityExecute
    deferred_result: DeferredResult
    deferred_done: DeferredDone
    schedule_clock: ScheduleClock


class WorkflowEngine(Tag[WorkflowEngineService], key="effect/workflow/WorkflowEngine"):
    """The engine running workflows (``workflow_engine.layer_memory``)."""


__all__ = [
    "ActivityState",
    "WorkflowEngine",
    "WorkflowEngineService",
    "WorkflowInstance",
    "WorkflowInstanceService",
]
