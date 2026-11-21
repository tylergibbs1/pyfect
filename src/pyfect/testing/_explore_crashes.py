"""``explore.activity_crashes``: a workflow stopped at each activity
boundary, resumed, and checked.

A crash stops the run as a suspension does: nothing after the boundary
runs, the run's finalizers do not run, and what the engine stored stays.
Resuming replays the run from the start, as a restarted runner does: the
activities whose results were stored give them back, the rest run.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Generator
from dataclasses import dataclass
from typing import Any, Never, cast

from pyfect._core import Effect
from pyfect._layer_core import require_layer
from pyfect.deferred import Deferred
from pyfect.effect import fail, gen, provide_service, yield_now
from pyfect.errors import TaggedError
from pyfect.exit import Exit
from pyfect.layer import Layer, provide
from pyfect.workflow._activity_hook import ActivityHook, ActivityRun
from pyfect.workflow._result import Result, Suspended
from pyfect.workflow._services import WorkflowEngine, WorkflowInstance, WorkflowInstanceService
from pyfect.workflow.activity import Activity
from pyfect.workflow.workflow import Workflow, into_result


@dataclass(frozen=True)
class CrashPoint:
    """The ``index``-th activity the run executed (from 1), named
    ``activity``: the crash came after it ran and, when ``stored``, after
    the engine stored its result."""

    index: int
    activity: str
    stored: bool

    def __str__(self) -> str:
        when = "after its result was stored" if self.stored else "before its result was stored"
        return f"crash after activity {self.index} ({self.activity!r}) ran, {when}"


@dataclass(frozen=True)
class CrashReport:
    """Every crash point tried, in order; each passed the check, as did
    the run with no crash."""

    points: tuple[CrashPoint, ...]


@dataclass
class CrashFailure(TaggedError):
    """The check failed after a crash at ``point`` (``None``: in the run
    with no crash)."""

    point: CrashPoint | None
    problem: str

    @property
    def message(self) -> str:
        where = "with no crash" if self.point is None else str(self.point)
        return f"explore.activity_crashes: {where}: {self.problem}"


class _Crash:
    """The hook of one run: counts the activities it executes and stops the
    run at ``at`` (``None``: never), once."""

    def __init__(self, at: int | None, stored: bool) -> None:
        self.at = at
        self.stored = stored
        self.executed: list[str] = []
        self.fired: CrashPoint | None = None
        self.stopped = Deferred[None]()

    def hook(self, activity: Activity[Any, Any, Any], run: ActivityRun) -> ActivityRun:
        if self.fired is not None:
            return run
        self.executed.append(activity.name)
        if len(self.executed) != self.at:
            return run
        point = CrashPoint(len(self.executed), activity.name, self.stored)
        ran = run if self.stored else _run_unstored(activity)
        return ran.and_then(self._fire(point))

    def _fire(self, point: CrashPoint) -> Effect[Result[Any, Any]]:
        def body() -> Generator[Effect[Any, Never, Any], Any, Result[Any, Any]]:
            self.fired = point
            yield from self.stopped.succeed(None)
            return Suspended()

        return gen(body)


def _run_unstored(activity: Activity[Any, Any, Any]) -> ActivityRun:
    """The activity's effect, run as the engines run it, its result thrown
    away: a crash before the engine stores it."""

    def body() -> Generator[Effect[Any, Never, Any], Any, Result[Any, Any]]:
        instance = yield from WorkflowInstance()
        own = WorkflowInstanceService.initial(instance.workflow, instance.execution_id)
        yield from into_result(activity.execute_encoded).pipe(
            provide_service(WorkflowInstance, own)
        )
        return Suspended()

    return gen(body)


def _until_suspended[P](workflow: Workflow[P, Any, Any], execution_id: str) -> Effect[None]:
    """Wait until the stopped run has published its suspension: an engine
    resumes only an execution it sees suspended."""

    def body() -> Generator[Effect[Any, Never, Any], Any]:
        while not isinstance((yield from workflow.poll(execution_id)), Suspended):
            yield from yield_now()

    return cast("Effect[None]", gen(body))


def _attempt[P, A, E, R, ER, RL](
    workflow: Workflow[P, A, E],
    payload: P,
    layer: Layer[R | WorkflowEngine, ER, RL],
    check: Callable[[Exit[A, E]], Effect[str | None, Never, R]],
    crash: _Crash,
) -> Effect[str | None, ER, RL]:
    def body() -> Generator[Effect[Any, Any, Any], Any, str | None]:
        execution_id = yield from workflow.execution_id(payload)
        waiter = yield from workflow.execute(payload).exit().fork()
        yield from crash.stopped.wait().race_first(waiter.await_exit().as_void())
        if crash.fired is not None:
            yield from _until_suspended(workflow, execution_id)
            yield from workflow.resume(execution_id)
        ex = yield from waiter.join()
        return (yield from check(ex))

    # The hook is in the context the layer is built in, which the workflow's
    # registration (and so every run of it) takes.
    run = gen(body).pipe(provide(cast("Layer[Any, ER, RL]", layer)))
    return cast("Effect[str | None, ER, RL]", run.pipe(provide_service(ActivityHook, crash.hook)))


def activity_crashes[P, A, E, R, ER = Never, RL = Never](
    workflow: Workflow[P, A, E],
    payload: P,
    *,
    layer: Layer[R | WorkflowEngine, ER, RL],
    check: Callable[[Exit[A, E]], Effect[str | None, Never, R]],
) -> Effect[CrashReport, CrashFailure | ER, RL]:
    """Run ``workflow`` with ``payload`` once without a crash, then once per
    crash point: after each activity it executes ran (before the engine
    stored its result, and after), the run stops and is resumed. After each,
    ``check`` gets the workflow's exit and returns what went wrong, or
    ``None``; the first problem fails with ``CrashFailure``.

    ``layer`` provides the engine with the workflow registered (memory, or
    a cluster engine such as ``single_runner.layer`` on SQLite) and what
    ``check`` reads; it is built afresh for every run."""
    require_layer(layer, "layer")

    def body() -> Generator[Effect[Any, Any, Any], Any, CrashReport]:
        dry = _Crash(None, stored=False)
        problem = yield from _attempt(workflow, payload, layer, check, dry)
        if problem is not None:
            return (yield from fail(CrashFailure(None, problem)))
        points: list[CrashPoint] = []
        for index in range(1, len(dry.executed) + 1):
            for stored in (False, True):
                crash = _Crash(index, stored)
                problem = yield from _attempt(workflow, payload, layer, check, crash)
                point = crash.fired
                if point is None:
                    point = CrashPoint(index, dry.executed[index - 1], stored)
                    problem = f"the run executed fewer than {index} activities this time"
                points.append(point)
                if problem is not None:
                    return (yield from fail(CrashFailure(point, problem)))
        return CrashReport(tuple(points))

    return cast("Effect[CrashReport, CrashFailure | ER, RL]", gen(body))


__all__ = ["CrashFailure", "CrashPoint", "CrashReport", "activity_crashes"]
