"""Ports of Effect's ``test/workflow/WorkflowEngine.test.ts``
(``workflow/Workflow.test.ts`` is in ``test_workflow.py``).

Each test's docstring is the Effect test title. Durations are seconds;
``Schema.Void`` is ``S.Null`` (``None``); ``{ ...engine, deferredResult }``
is ``copy.replace(engine, deferred_result=...)``; ``Layer.build``
into a scope is ``layer.build_with_scope(scope)``.

Omitted:

- ``supports class extension``: a Python class cannot extend a workflow
  value; a module-level workflow is the definition.
"""

from __future__ import annotations

import copy
import functools
from collections.abc import Generator
from typing import Any, Never, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cause import Fail
from pyfect.workflow import (
    Complete,
    Suspended,
    activity,
    durable_clock,
    durable_deferred,
    workflow,
    workflow_engine,
)
from pyfect.workflow.workflow_engine import WorkflowEngine, WorkflowInstance


class Empty(TypedDict):
    pass


class Value(TypedDict):
    value: float


class Index(TypedDict):
    index: float


class Id(TypedDict):
    id: str


class KeyValue(TypedDict):
    key: str
    value: float


EMPTY = S.Struct(Empty)


def _with_engine(*workflows: fx.Layer[Never, Never, Any]) -> Any:
    """Provide the workflows' layers (merged; ``layer.merge`` of layers
    that all build nothing infers ``Unknown``) on ``layer_memory``."""
    merged: fx.Layer[Any, Any, Any] = functools.reduce(fx.layer.merge, workflows)
    return fx.provide(merged.pipe(fx.layer.provide_merge(workflow_engine.layer_memory)))


def _poll_until_complete[A, E](
    wf: workflow.Workflow[Any, A, E], execution_id: str
) -> Generator[Any, Any, Complete[A, E]]:
    result = yield from wf.poll(execution_id)
    while not isinstance(result, Complete):
        yield from fx.yield_now()
        result = yield from wf.poll(execution_id)
    return result


def _poll_until_suspended(
    wf: workflow.Workflow[Any, Any, Any], execution_id: str
) -> Generator[Any, Any, Suspended]:
    result = yield from wf.poll(execution_id)
    while not isinstance(result, Suspended):
        yield from fx.yield_now()
        result = yield from wf.poll(execution_id)
    return result


def _num(value: float) -> str:
    """``String(value)`` in JavaScript for the integral floats used here."""
    return str(int(value)) if value == int(value) else str(value)


# --- deferred self-completion ------------------------------------------------------------


@pytest.mark.parametrize("failure", [False, True], ids=["success", "failure"])
@testing.live(timeout="5 seconds")
def test_deferred_self_completion(failure: bool):
    """deferred self-completion / success | failure"""
    signal = durable_deferred.make("signal", success=S.String, error=S.String)
    read = yield from fx.Latch.make()
    cleanup = yield from fx.Latch.make()
    release = yield from fx.Latch.make()
    events: list[str] = []
    runs = 0
    wf = workflow.make(
        "SelfCompletion",
        payload=EMPTY,
        success=S.String,
        error=S.String,
        idempotency_key=lambda _: "one",
    )

    def handler(_p: Empty, _id: str):
        def body():
            nonlocal runs
            runs += 1
            run = runs
            events.append(f"start-{run}")
            engine = yield from WorkflowEngine()

            def on_cleanup():
                events.append("cleanup-start")
                yield from cleanup.open()
                yield from release.wait()
                events.append("cleanup-end")

            producer = (
                read.wait()
                .and_then(fx.yield_now())
                .and_then(fx.fail("boom") if failure else fx.succeed("ok"))
                .pipe(signal.into)
                # Successful completion must preempt this producer and replay the run.
                .and_then(fx.never)
                .on_interrupt(fx.gen(on_cleanup) if run == 1 else fx.void)
            )

            def deferred_result(deferred: Any) -> Any:
                return engine.deferred_result(deferred).tap(
                    lambda _: read.open() if deferred.name == signal.name else fx.void
                )

            return (
                yield from durable_deferred.race_all(
                    name="race",
                    success=S.String,
                    error=S.String,
                    effects=[signal.wait(), producer],
                )
                .pipe(
                    fx.provide_service(
                        WorkflowEngine, copy.replace(engine, deferred_result=deferred_result)
                    )
                )
                .ensuring(fx.sync(lambda: events.append(f"end-{run}")))
            )

        return fx.gen(body)

    layer = wf.to_layer(handler)

    def program():
        execution = yield from wf.execute({}).exit().fork(start_immediately=True)
        if not failure:
            yield from cleanup.wait()
            for _ in range(20):
                yield from fx.yield_now()
            assert events == ["start-1", "cleanup-start"], "replay must wait for cleanup"
            yield from release.open()
        result = yield from execution.join()
        if failure:
            assert isinstance(result, fx.Failure)
            assert len(result.cause.reasons) == 1
            reason = result.cause.reasons[0]
            assert isinstance(reason, Fail)
            assert reason.error == "boom"
        else:
            assert result == fx.Success("ok")
            assert events == [
                "start-1",
                "cleanup-start",
                "cleanup-end",
                "end-1",
                "start-2",
                "end-2",
            ]

    yield from fx.gen(program).pipe(_with_engine(layer))


# --- WorkflowEngine ----------------------------------------------------------------------

IncrementWorkflow = workflow.make(
    "WorkflowEngine/IncrementWorkflow",
    payload=S.Struct(Value),
    success=S.Number,
    idempotency_key=lambda p: _num(p["value"]),
)
IncrementWorkflowLayer = IncrementWorkflow.to_layer(lambda p, _id: fx.succeed(p["value"] + 1))

DeferredRaceWorkflow = workflow.make(
    "WorkflowEngine/DeferredRaceWorkflow",
    payload=S.Struct(Id),
    success=S.String,
    idempotency_key=lambda p: p["id"],
)
DeferredRaceGate = durable_deferred.make("WorkflowEngine/DeferredRaceGate", success=S.String)
deferred_race = {"runs": 0}


def _deferred_race(_p: Id, _id: str) -> fx.Effect[str, Any, Any]:
    def run() -> fx.Effect[str, Any, Any]:
        deferred_race["runs"] += 1
        return durable_deferred.race_all(
            name="memory-deferred-race",
            success=S.String,
            error=S.Never,
            effects=[DeferredRaceGate.wait(), fx.sleep("10 seconds").as_("activity")],
        )

    return fx.suspend(run)


DeferredRaceWorkflowLayer = DeferredRaceWorkflow.to_layer(_deferred_race)


@testing.effect
def test_layer_executes_and_polls_workflows():
    """WorkflowEngine / layer executes and polls workflows"""

    def program():
        execution_id = yield from IncrementWorkflow.execute({"value": 1}, discard=True)
        result = yield from IncrementWorkflow.execute({"value": 1})
        polled = yield from IncrementWorkflow.poll(execution_id)
        assert result == 2
        assert isinstance(polled, Complete) and polled.exit == fx.Success(2)

    yield from fx.gen(program).pipe(_with_engine(IncrementWorkflowLayer))


@pytest.mark.parametrize(
    ("child_count", "concurrency", "waves"),
    [(3, "unbounded", [3]), (5, 2, [2, 4, 5])],
    ids=["unbounded", "2"],
)
@testing.effect
def test_layer_memory_replays_suspended_activity_fan_out(
    child_count: int, concurrency: Any, waves: list[int]
):
    """WorkflowEngine / layerMemory replays suspended activity fan-out with concurrency ${concurrency}"""  # noqa: E501
    Parent = workflow.make(
        "WorkflowEngine/FanOutParent",
        payload=EMPTY,
        success=S.Array(S.Number),
        idempotency_key=lambda _: "parent",
    )
    Child = workflow.make(
        "WorkflowEngine/FanOutChild",
        payload=S.Struct(Index),
        success=S.Number,
        idempotency_key=lambda p: _num(p["index"]),
    )
    started: set[float] = set()
    counts = {"parent": 0, "activity": 0, "released": 0}

    def parent(_p: Empty, _id: str):
        def run():
            counts["parent"] += 1

            def body():
                counts["activity"] += 1
                return fx.for_each(
                    list(range(child_count)),
                    lambda index: Child.execute({"index": index}),
                    concurrency=concurrency,
                )

            def release():
                counts["released"] += 1

            return activity.make(
                name="fan-out",
                success=S.Array(S.Number),
                execute=fx.suspend(body).map(tuple).ensuring(fx.sync(release)),
            )

        return fx.suspend(run)

    def child(p: Index, _id: str):
        def body():
            started.add(p["index"])
            yield from durable_clock.sleep(
                name="child", duration="2 seconds", in_memory_threshold=0
            )
            return p["index"]

        return fx.gen(body)

    def program():
        execution_id = yield from Parent.execute({}, discard=True)
        for expected in waves:
            result = yield from Parent.poll(execution_id)
            while not isinstance(result, Suspended) or len(started) != expected:
                yield from fx.yield_now()
                result = yield from Parent.poll(execution_id)
            assert sorted(started) == list(range(expected))
            assert counts["released"] == counts["activity"]
            assert counts["activity"] <= counts["parent"]
            if expected == waves[0]:
                assert counts["parent"] == 1
            yield from testing.adjust("2 seconds")
        result = yield from _poll_until_complete(Parent, execution_id)
        assert result == Complete(fx.Success(tuple(range(child_count))))
        assert counts["parent"] >= len(waves) + 1
        assert counts["activity"] <= counts["parent"]

    yield from fx.gen(program).pipe(_with_engine(Parent.to_layer(parent), Child.to_layer(child)))


@testing.effect
def test_layer_memory_reruns_an_activity_interrupted_by_replay_preemption():
    """WorkflowEngine / layerMemory reruns an activity interrupted by replay preemption"""
    Probe = workflow.make(
        "WorkflowEngine/PreemptedActivity",
        payload=S.Struct(Id),
        success=S.String,
        idempotency_key=lambda p: p["id"],
    )
    counts = {"executions": 0, "writes": 0}
    writing = yield from fx.Deferred[None].make()
    written = yield from fx.Deferred[None].make()

    def handler(_p: Id, _id: str):
        def body():
            counts["executions"] += 1
            if counts["executions"] == 2:
                # Advance once the clock result is stored, but before its
                # wake-up preempts this replay.
                engine = yield from WorkflowEngine()
                room = durable_deferred.make("DurableClock/room")
                while (yield from engine.deferred_result(room)) is None:
                    yield from fx.yield_now()
            yield from durable_clock.sleep(name="room", duration="5 seconds", in_memory_threshold=0)

            def write():
                counts["writes"] += 1
                yield from writing.succeed(None)
                yield from written.wait()

            yield from activity.make(name="write", execute=fx.gen(write))
            return "ended"

        return fx.gen(body)

    def program():
        execution_id = yield from Probe.execute({"id": "probe"}, discard=True)
        yield from _poll_until_suspended(Probe, execution_id)
        # Start a replay as the clock comes due; its delayed wake-up
        # interrupts the activity.
        yield from Probe.resume(execution_id)
        yield from testing.adjust("5 seconds")
        yield from writing.wait()
        while counts["executions"] < 3:
            yield from fx.yield_now()
        yield from written.succeed(None)
        polled = yield from _poll_until_complete(Probe, execution_id)
        assert polled.exit == fx.Success("ended")
        assert counts["executions"] == 3
        assert counts["writes"] == 2

    yield from fx.gen(program).pipe(_with_engine(Probe.to_layer(handler)))


def _cleanup_parent_child():
    Parent = workflow.make(
        "WorkflowEngine/CleanupParent",
        payload=EMPTY,
        success=S.Array(S.Number),
        idempotency_key=lambda _: "parent",
    )
    Child = workflow.make(
        "WorkflowEngine/CleanupChild",
        payload=S.Struct(Index),
        success=S.Number,
        idempotency_key=lambda p: _num(p["index"]),
    )
    return Parent, Child


@testing.effect
def test_layer_memory_resumes_when_children_complete_during_activity_cleanup():
    """WorkflowEngine / layerMemory resumes when children complete during activity cleanup"""
    cleaning_up = yield from fx.Latch.make()
    release = yield from fx.Latch.make()
    Parent, Child = _cleanup_parent_child()
    parent_layer = Parent.to_layer(
        lambda _p, _id: activity.make(
            name="children",
            success=S.Array(S.Number),
            execute=fx.for_each(
                [0, 1], lambda index: Child.execute({"index": index}), concurrency="unbounded"
            )
            .map(tuple)
            .ensuring(cleaning_up.open().and_then(release.wait())),
        )
    )
    child_layer = Child.to_layer(
        lambda p, _id: durable_clock.sleep(
            name="wait", duration="2 seconds", in_memory_threshold=0
        ).as_(p["index"])
    )

    def program():
        execution_id = yield from Parent.execute({}, discard=True)
        yield from cleaning_up.wait()
        yield from testing.adjust("2 seconds")
        yield from release.open()
        result = yield from _poll_until_complete(Parent, execution_id)
        assert result == Complete(fx.Success((0, 1)))

    yield from fx.gen(program).pipe(_with_engine(parent_layer, child_layer))


@testing.effect
def test_layer_memory_keeps_a_failure_suspended_workflow_parked_when_a_discarded_child_completes():
    """WorkflowEngine / layerMemory keeps a failure-suspended workflow parked when a discarded child completes"""  # noqa: E501
    failures = 0
    ChildGate = durable_deferred.make("WorkflowEngine/FailureParkedChildGate")
    Parent = workflow.make(
        "WorkflowEngine/FailureParked", payload=EMPTY, idempotency_key=lambda _: "parent"
    ).annotate(workflow.SuspendOnFailure, True)
    Child = workflow.make(
        "WorkflowEngine/FailureParkedChild", payload=EMPTY, idempotency_key=lambda _: "child"
    )

    def fail_once():
        nonlocal failures
        failures += 1
        return fx.die(RuntimeError("boom"))

    def parent(_p: Empty, _id: str):
        def body():
            yield from Child.execute({}, discard=True)
            yield from activity.make(name="fail", execute=fx.suspend(fail_once))

        return fx.gen(body)

    def program():
        execution_id = yield from Parent.execute({}, discard=True)
        child_id = yield from Child.execution_id({})
        yield from _poll_until_suspended(Parent, execution_id)

        yield from ChildGate.succeed(
            token=ChildGate.token_from_execution_id(workflow=Child, execution_id=child_id),
            value=None,
        )
        child = yield from _poll_until_complete(Child, child_id)
        assert child == Complete(fx.Success(None))
        for _ in range(100):
            yield from fx.yield_now()
        assert failures == 1, "only an explicit resume may replay the failed activity"

        yield from Parent.resume(execution_id)
        while failures < 2:
            yield from fx.yield_now()
        assert failures == 2

    yield from fx.gen(program).pipe(
        _with_engine(Parent.to_layer(parent), Child.to_layer(lambda _p, _id: ChildGate.wait()))
    )


@testing.effect
def test_layer_memory_wakes_a_parent_when_its_failure_suspended_child_is_resumed():
    """WorkflowEngine / layerMemory wakes a parent when its failure-suspended child is resumed"""
    attempts = 0
    Parent = workflow.make(
        "WorkflowEngine/InheritedCauseParent",
        payload=EMPTY,
        success=S.Number,
        idempotency_key=lambda _: "parent",
    )
    Child = workflow.make(
        "WorkflowEngine/InheritedCauseChild",
        payload=EMPTY,
        success=S.Number,
        idempotency_key=lambda _: "child",
    ).annotate(workflow.SuspendOnFailure, True)

    def flaky():
        nonlocal attempts
        attempts += 1
        return fx.die(RuntimeError("boom")) if attempts == 1 else fx.succeed(float(attempts))

    # Await from an activity, so its own result must not inherit the failure.
    parent_layer = Parent.to_layer(
        lambda _p, _id: activity.make(name="child", success=S.Number, execute=Child.execute({}))
    )
    child_layer = Child.to_layer(
        lambda _p, _id: activity.make(name="flaky", success=S.Number, execute=fx.suspend(flaky))
    )

    def program():
        execution_id = yield from Parent.execute({}, discard=True)
        yield from _poll_until_suspended(Parent, execution_id)
        # The parent carries the child's cause but did not fail itself.
        yield from Child.resume((yield from Child.execution_id({})))
        result = yield from _poll_until_complete(Parent, execution_id)
        assert result == Complete(fx.Success(2.0))

    yield from fx.gen(program).pipe(_with_engine(parent_layer, child_layer))


@testing.effect
def test_layer_memory_keeps_an_explicit_resume_queued_behind_an_automatic_wake():
    """WorkflowEngine / layerMemory keeps an explicit resume queued behind an automatic wake"""
    failures = 0
    cleaning_up = yield from fx.Latch.make()
    release = yield from fx.Latch.make()
    Gate = durable_deferred.make("WorkflowEngine/QueuedWakeGate")
    Failing = workflow.make(
        "WorkflowEngine/QueuedWake", payload=EMPTY, idempotency_key=lambda _: "failing"
    ).annotate(workflow.SuspendOnFailure, True)

    def fail_once():
        nonlocal failures
        failures += 1
        return fx.die(RuntimeError("boom"))

    layer = Failing.to_layer(
        lambda _p, _id: activity.make(name="fail", execute=fx.suspend(fail_once)).ensuring(
            cleaning_up.open().and_then(release.wait())
        )
    )

    def program():
        execution_id = yield from Failing.execute({}, discard=True)
        yield from cleaning_up.wait()
        # The run is still cleaning up, so both wakes wait for it to finish.
        yield from Gate.succeed(
            token=Gate.token_from_execution_id(workflow=Failing, execution_id=execution_id),
            value=None,
        )
        yield from Failing.resume(execution_id)
        yield from release.open()
        while failures < 2:
            yield from fx.yield_now()
        assert failures == 2, "the explicit resume must replay the failed activity"

    yield from fx.gen(program).pipe(_with_engine(layer))


@testing.effect
def test_layer_memory_does_not_interrupt_a_detached_child_with_its_parent():
    """WorkflowEngine / layerMemory does not interrupt a detached child with its parent"""
    ParentGate = durable_deferred.make("WorkflowEngine/DetachedParentGate")
    ChildGate = durable_deferred.make("WorkflowEngine/DetachedChildGate")
    Parent = workflow.make(
        "WorkflowEngine/DetachedParent", payload=EMPTY, idempotency_key=lambda _: "parent"
    )
    Child = workflow.make(
        "WorkflowEngine/DetachedChild", payload=EMPTY, idempotency_key=lambda _: "child"
    )

    def parent(_p: Empty, _id: str):
        def body():
            yield from Child.execute({}, discard=True, detached=True)
            yield from ParentGate.wait()

        return fx.gen(body)

    def program():
        execution_id = yield from Parent.execute({}, discard=True)
        yield from _poll_until_suspended(Parent, execution_id)
        yield from Parent.interrupt(execution_id)
        yield from _poll_until_complete(Parent, execution_id)

        child_id = yield from Child.execution_id({})
        yield from ChildGate.succeed(
            token=ChildGate.token_from_execution_id(workflow=Child, execution_id=child_id),
            value=None,
        )
        child = yield from _poll_until_complete(Child, child_id)
        assert child == Complete(fx.Success(None))

    yield from fx.gen(program).pipe(
        _with_engine(Parent.to_layer(parent), Child.to_layer(lambda _p, _id: ChildGate.wait()))
    )


@pytest.mark.parametrize("mode", ["failure", "interruption"])
@testing.effect
def test_layer_memory_releases_a_pending_child_registration(mode: str):
    """WorkflowEngine / layerMemory releases a pending child registration on ${mode}"""
    computing_id = yield from fx.Latch.make()
    started: list[float] = []
    Parent = workflow.make(
        f"WorkflowEngine/PendingParent/{mode}",
        payload=EMPTY,
        success=S.Array(S.Number),
        idempotency_key=lambda _: "parent",
    )

    def key(p: Index) -> str:
        if p["index"] == 1:
            if mode == "failure":
                raise RuntimeError("cannot compute the execution id")
            computing_id.open_unsafe()
        return _num(p["index"])

    Child = workflow.make(
        f"WorkflowEngine/PendingChild/{mode}",
        payload=S.Struct(Index),
        success=S.Number,
        idempotency_key=key,
    )

    def run_child(index: int) -> fx.Effect[float, Any, Any]:
        execute = Child.execute({"index": index})
        if index == 0:
            return execute
        if mode == "failure":
            return execute.catch_defect(lambda _: fx.succeed(-1.0))
        return execute.race_first(computing_id.wait().as_(-1.0))

    parent_layer = Parent.to_layer(
        lambda _p, _id: activity.make(
            name="children",
            success=S.Array(S.Number),
            execute=fx.for_each([0, 1], run_child, concurrency="unbounded").map(tuple),
        )
    )

    def child(p: Index, _id: str):
        def body():
            started.append(p["index"])
            yield from durable_clock.sleep(name="wait", duration="2 seconds", in_memory_threshold=0)
            return p["index"]

        return fx.gen(body)

    def program():
        execution_id = yield from Parent.execute({}, discard=True)
        yield from _poll_until_suspended(Parent, execution_id)
        assert started == [0]
        yield from testing.adjust("2 seconds")
        result = yield from _poll_until_complete(Parent, execution_id)
        assert result == Complete(fx.Success((0, -1)))

    yield from fx.gen(program).pipe(_with_engine(parent_layer, Child.to_layer(child)))


@testing.effect
def test_discard_returns_the_deterministic_execution_id():
    """WorkflowEngine / discard returns the deterministic execution ID"""

    def program():
        execution_id = yield from IncrementWorkflow.execution_id({"value": 1})
        discarded = yield from IncrementWorkflow.execute({"value": 1}, discard=True)
        assert discarded == execution_id

    yield from fx.gen(program).pipe(_with_engine(IncrementWorkflowLayer))


@testing.effect
def test_distinguishes_workflow_tags_and_idempotency_keys_at_string_boundaries():
    """WorkflowEngine / distinguishes workflow tags and idempotency keys at string boundaries"""

    def make_workflow(tag: str) -> workflow.Workflow[KeyValue, None, Any]:
        return workflow.make(tag, payload=S.Struct(KeyValue), idempotency_key=lambda p: p["key"])

    for left_tag, left_key, right_tag, right_key in [
        ("Order", "Pay-42", "Order-Pay", "42"),
        ("Order", "Pay:42", "Order:Pay", "42"),
        ("", "-", "-", ""),
        ('A"', "B\\", 'A"-B', "\\"),
    ]:
        left = make_workflow(left_tag)
        right = make_workflow(right_tag)
        left_id = yield from left.execution_id({"key": left_key, "value": 1})
        right_id = yield from right.execution_id({"key": right_key, "value": 1})
        assert left_id != right_id
        assert (yield from left.execution_id({"key": left_key, "value": 1})) == left_id
        assert (yield from left.execution_id({"key": left_key, "value": 2})) == left_id


@testing.effect
def test_layer_memory_wakes_an_active_workflow_when_a_durable_deferred_completes():
    """WorkflowEngine / layerMemory wakes an active workflow when a durable deferred completes"""
    deferred_race["runs"] = 0

    def program():
        payload: Id = {"id": "memory-deferred-race"}
        execution_id = yield from DeferredRaceWorkflow.execution_id(payload)
        fiber = yield from DeferredRaceWorkflow.execute(payload).fork(start_immediately=True)

        # Park the deferred branch before completing it.
        yield from testing.adjust("1 millis")
        yield from testing.adjust("1 millis")
        token = DeferredRaceGate.token_from_execution_id(
            workflow=DeferredRaceWorkflow, execution_id=execution_id
        )
        yield from DeferredRaceGate.succeed(token=token, value="signal")
        # Require the wake to settle before the sleeper.
        yield from _poll_until_complete(DeferredRaceWorkflow, execution_id)

        # Let the caller's suspended-retry loop pick up a replayed result.
        yield from testing.adjust("1 second")
        assert (yield from fiber.join()) == "signal"
        assert deferred_race["runs"] in (1, 2)

    yield from fx.gen(program).pipe(_with_engine(DeferredRaceWorkflowLayer))


@testing.effect
def test_layer_memory_wakes_a_suspended_caller_when_its_workflow_completes():
    """WorkflowEngine / layerMemory wakes a suspended caller when its workflow completes"""
    retrying = yield from fx.Latch.make()
    gate = durable_deferred.make("WorkflowEngine/CompletionWakeGate", success=S.String)
    wf = workflow.make(
        "WorkflowEngine/CompletionWake",
        payload=EMPTY,
        success=S.String,
        idempotency_key=lambda _: "one",
        # The retry stays the fallback, but is too slow to deliver within the test.
        suspended_retry_schedule=fx.schedule.spaced("1 hour").tap(lambda _: retrying.open()),
    )

    def program():
        execution_id = yield from wf.execution_id({})
        fiber = yield from wf.execute({}).fork(start_immediately=True)
        for _ in range(1000):
            if retrying.is_open():
                break
            yield from testing.adjust("1 millis")
        assert retrying.is_open(), "caller must wait on its retry schedule"
        yield from gate.succeed(
            token=gate.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value="done",
        )
        polled = yield from wf.poll(execution_id)
        for _ in range(1000):
            if isinstance(polled, Complete):
                break
            yield from fx.yield_now()
            polled = yield from wf.poll(execution_id)
        assert isinstance(polled, Complete), "workflow must complete"
        for _ in range(1000):
            if fiber.poll_unsafe() is not None:
                break
            yield from testing.adjust("1 millis")
        assert fiber.poll_unsafe() is not None, "completion must wake the caller"
        assert (yield from fiber.join()) == "done"

    yield from fx.gen(program).pipe(_with_engine(wf.to_layer(lambda _p, _id: gate.wait())))


@testing.effect
def test_layer_memory_does_not_spend_a_retry_when_a_replay_suspends_again():
    """WorkflowEngine / layerMemory does not spend a retry when a replay suspends again"""
    retrying = yield from fx.Latch.make()
    runs = 0
    first = durable_deferred.make("WorkflowEngine/ResuspendFirst", success=S.String)
    second = durable_deferred.make("WorkflowEngine/ResuspendSecond", success=S.String)
    wf = workflow.make(
        "WorkflowEngine/Resuspend",
        payload=EMPTY,
        success=S.String,
        idempotency_key=lambda _: "one",
        # A single retry: only completion can deliver the result.
        suspended_retry_schedule=fx.schedule.spaced("1 hour")
        .up_to(times=1)
        .tap(lambda _: retrying.open()),
    )

    def complete(deferred: Any, execution_id: str, value: str) -> Any:
        return deferred.succeed(
            token=deferred.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value=value,
        )

    def handler(_p: Empty, _id: str):
        def body():
            nonlocal runs
            runs += 1
            a = yield from first.wait()
            b = yield from second.wait()
            return f"{a}/{b}"

        return fx.gen(body)

    def program():
        execution_id = yield from wf.execution_id({})
        fiber = yield from wf.execute({}).fork(start_immediately=True)
        for _ in range(1000):
            if retrying.is_open():
                break
            yield from testing.adjust("1 millis")
        assert retrying.is_open(), "caller must wait on its retry schedule"
        yield from complete(first, execution_id, "first")
        polled = yield from wf.poll(execution_id)
        for _ in range(1000):
            if runs == 2 and polled is not None:
                break
            yield from fx.yield_now()
            polled = yield from wf.poll(execution_id)
        assert runs == 2 and isinstance(polled, Suspended), "replay must suspend again"
        yield from complete(second, execution_id, "second")
        for _ in range(1000):
            if fiber.poll_unsafe() is not None:
                break
            yield from testing.adjust("1 millis")
        assert fiber.poll_unsafe() is not None, "completion must wake the caller"
        assert (yield from fiber.join()) == "first/second"

    yield from fx.gen(program).pipe(_with_engine(wf.to_layer(handler)))


@testing.effect
def test_layer_memory_does_not_wake_a_caller_from_a_run_that_died_before_a_resume():
    """WorkflowEngine / layerMemory does not wake a caller from a run that died before a resume"""
    retrying = yield from fx.Latch.make()
    runs = 0
    gate = durable_deferred.make("WorkflowEngine/DiedGate", success=S.String)
    wf = workflow.make(
        "WorkflowEngine/Died",
        payload=EMPTY,
        success=S.String,
        idempotency_key=lambda _: "one",
        # A single retry: only completion can deliver the result.
        suspended_retry_schedule=fx.schedule.spaced("1 hour")
        .up_to(times=1)
        .tap(lambda _: retrying.open()),
    ).annotate(workflow.CaptureDefects, False)

    def handler(_p: Empty, _id: str):
        def run():
            nonlocal runs
            runs += 1
            return fx.die(RuntimeError("boom")) if runs == 1 else gate.wait()

        return fx.suspend(run)

    def program():
        execution_id = yield from wf.execution_id({})
        assert isinstance((yield from wf.execute({}).exit()), fx.Failure), "first run must die"
        yield from wf.resume(execution_id)
        fiber = yield from wf.execute({}).fork(start_immediately=True)
        for _ in range(1000):
            if retrying.is_open():
                break
            yield from testing.adjust("1 millis")
        assert retrying.is_open(), "caller must wait on its retry schedule"
        assert fiber.poll_unsafe() is None, "the died run must not wake the caller"
        yield from gate.succeed(
            token=gate.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value="done",
        )
        for _ in range(1000):
            if fiber.poll_unsafe() is not None:
                break
            yield from testing.adjust("1 millis")
        assert fiber.poll_unsafe() is not None, "completion must wake the caller"
        assert (yield from fiber.join()) == "done"

    yield from fx.gen(program).pipe(_with_engine(wf.to_layer(handler)))


@testing.effect
def test_layer_memory_propagates_interruption_when_the_engine_is_shut_down():
    """WorkflowEngine / layerMemory propagates interruption when the engine is shut down"""
    Stuck = workflow.make(
        "WorkflowEngine/ShutdownWorkflow", payload=S.Struct(Id), idempotency_key=lambda p: p["id"]
    )
    layer = Stuck.to_layer(lambda _p, _id: fx.never).pipe(
        fx.layer.provide_merge(workflow_engine.layer_memory)
    )
    scope = fx.CloseableScope()
    services = yield from layer.build_with_scope(scope)
    fiber = (
        yield from Stuck.execute({"id": "one"})
        .pipe(fx.provide_context(services))
        .fork(start_immediately=True)
    )
    yield from fx.yield_now()
    yield from fx.yield_now()

    # Shutting down must interrupt the caller, not report a suspension.
    yield from scope.close(fx.Success(None))
    ex = yield from fiber.await_exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts


@testing.effect
def test_layer_memory_runs_compensations_when_the_engine_is_shut_down():
    """WorkflowEngine / layerMemory runs compensations when the engine is shut down"""
    ready = fx.Latch()
    compensated: list[str] = []
    Stuck = workflow.make(
        "WorkflowEngine/ShutdownCompensation",
        payload=S.Struct(Id),
        idempotency_key=lambda p: p["id"],
    )

    def handler(_p: Id, _id: str):
        def body():
            yield from Stuck.with_compensation(
                fx.succeed("a"), lambda value, _cause: fx.sync(lambda: compensated.append(value))
            )
            ready.open_unsafe()
            return (yield from fx.never)

        return fx.gen(body)

    layer = Stuck.to_layer(handler).pipe(fx.layer.provide_merge(workflow_engine.layer_memory))
    scope = fx.CloseableScope()
    services = yield from layer.build_with_scope(scope)
    fiber = (
        yield from Stuck.execute({"id": "one"})
        .pipe(fx.provide_context(services))
        .fork(start_immediately=True)
    )
    yield from ready.wait()

    yield from scope.close(fx.Success(None))
    ex = yield from fiber.await_exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts
    assert compensated == ["a"]


@testing.effect
def test_layer_memory_compensates_a_completed_activity_only_once_after_replay():
    """WorkflowEngine / layerMemory compensates a completed activity only once after replay"""
    gate = durable_deferred.make("WorkflowEngine/CompensationReplay/Gate", error=S.String)
    events: list[str] = []
    runs = 0
    Order = workflow.make(
        "WorkflowEngine/CompensationReplay",
        payload=S.Struct(Id),
        error=S.String,
        idempotency_key=lambda p: p["id"],
    )

    def charge() -> str:
        events.append("charge")
        return "ch_1"

    def handler(_p: Id, _id: str):
        def body():
            nonlocal runs
            runs += 1
            yield from activity.make(name="charge", success=S.String, execute=fx.sync(charge)).pipe(
                Order.with_compensation(
                    lambda id, _cause: fx.sync(lambda: events.append(f"refund {id}"))
                )
            )
            yield from gate.wait()

        return fx.gen(body)

    def program():
        execution_id = yield from Order.execute({"id": "one"}, discard=True)
        yield from _poll_until_suspended(Order, execution_id)
        assert events == ["charge"]

        yield from Order.resume(execution_id)
        result = yield from Order.poll(execution_id)
        while not isinstance(result, Suspended):
            yield from fx.yield_now()
            result = yield from Order.poll(execution_id)
        assert runs == 2
        assert events == ["charge"]

        token = gate.token_from_execution_id(workflow=Order, execution_id=execution_id)
        yield from gate.fail(token=token, error="rejected")
        result = yield from _poll_until_complete(Order, execution_id)

        assert isinstance(result.exit, fx.Failure)
        assert len(result.exit.cause.reasons) == 1
        reason = result.exit.cause.reasons[0]
        assert isinstance(reason, Fail)
        assert reason.error == "rejected"
        assert runs == 3
        assert events == ["charge", "refund ch_1"]

    yield from fx.gen(program).pipe(_with_engine(Order.to_layer(handler)))


@testing.effect
def test_layer_memory_closes_finalizers_registered_before_suspension():
    """WorkflowEngine / layerMemory closes finalizers registered before suspension"""
    gate = durable_deferred.make("WorkflowEngine/SuspendedScope/Gate")
    finalized: list[int] = []
    runs = 0
    Suspends = workflow.make(
        "WorkflowEngine/SuspendedScope", payload=S.Struct(Id), idempotency_key=lambda p: p["id"]
    )

    def handler(_p: Id, _id: str):
        def body():
            nonlocal runs
            runs += 1
            run = runs
            yield from workflow.add_finalizer(lambda _: fx.sync(lambda: finalized.append(run)))
            yield from gate.wait()

        return fx.gen(body)

    def program():
        payload: Id = {"id": "one"}
        execution_id = yield from Suspends.execute(payload, discard=True)
        yield from _poll_until_suspended(Suspends, execution_id)

        token = gate.token_from_execution_id(workflow=Suspends, execution_id=execution_id)
        yield from gate.succeed(token=token, value=None)
        yield from Suspends.execute(payload)

        assert finalized == [2, 1]

    yield from fx.gen(program).pipe(_with_engine(Suspends.to_layer(handler)))


@testing.effect
def test_layer_memory_closes_every_suspended_run_scope_when_a_finalizer_dies():
    """WorkflowEngine / layerMemory closes every suspended run scope when a finalizer dies"""
    gate = durable_deferred.make("WorkflowEngine/SuspendedScopeDefect/Gate")
    finalized: list[int] = []
    runs = 0
    Suspends = workflow.make(
        "WorkflowEngine/SuspendedScopeDefect", payload=EMPTY, idempotency_key=lambda _: "one"
    )

    def handler(_p: Empty, _id: str):
        def body():
            nonlocal runs
            runs += 1
            run = runs

            def finalizer(_ex: Any):
                finalized.append(run)
                if run == 2:
                    return fx.die(RuntimeError("finalizer defect"))
                return fx.void

            yield from workflow.add_finalizer(lambda ex: fx.suspend(lambda: finalizer(ex)))
            yield from gate.wait()

        return fx.gen(body)

    def program():
        execution_id = yield from Suspends.execute({}, discard=True)
        yield from _poll_until_suspended(Suspends, execution_id)

        yield from Suspends.resume(execution_id)
        result = yield from Suspends.poll(execution_id)
        while not isinstance(result, Suspended):
            yield from fx.yield_now()
            result = yield from Suspends.poll(execution_id)
        assert runs == 2

        token = gate.token_from_execution_id(workflow=Suspends, execution_id=execution_id)
        yield from gate.succeed(token=token, value=None)
        ex = yield from Suspends.poll(execution_id).exit()
        while isinstance(ex, fx.Success) and not isinstance(ex.value, Complete):
            yield from fx.yield_now()
            ex = yield from Suspends.poll(execution_id).exit()

        assert runs == 3
        assert isinstance(ex, fx.Failure) and ex.cause.has_dies
        assert finalized == [3, 2, 1]

    yield from fx.gen(program).pipe(_with_engine(Suspends.to_layer(handler)))


@testing.effect
def test_layer_memory_hides_deposited_interrupts_from_body_finalizers():
    """WorkflowEngine / layerMemory hides deposited interrupts from body finalizers"""
    gate = durable_deferred.make("WorkflowEngine/InterruptBodyFinalizer/Gate")
    observed: list[bool] = []
    Suspends = workflow.make(
        "WorkflowEngine/InterruptBodyFinalizer",
        payload=S.Struct(Id),
        idempotency_key=lambda p: p["id"],
    )

    def handler(_p: Id, _id: str):
        def body():
            instance = yield from WorkflowInstance()
            return (
                yield from gate.wait().on_exit(
                    lambda _: fx.sync(lambda: observed.append(instance.interrupted))
                )
            )

        return fx.gen(body)

    def program():
        execution_id = yield from Suspends.execute({"id": "one"}, discard=True)
        yield from _poll_until_suspended(Suspends, execution_id)
        yield from Suspends.interrupt(execution_id)
        yield from _poll_until_complete(Suspends, execution_id)
        assert observed == [False, False]

    yield from fx.gen(program).pipe(_with_engine(Suspends.to_layer(handler)))


@testing.effect
def test_layer_memory_exposes_deposited_interrupts_to_workflow_finalizers():
    """WorkflowEngine / layerMemory exposes deposited interrupts to workflow finalizers"""
    gate = durable_deferred.make("WorkflowEngine/InterruptWorkflowFinalizer/Gate")
    observed: list[bool] = []
    runs = 0
    Suspends = workflow.make(
        "WorkflowEngine/InterruptWorkflowFinalizer",
        payload=S.Struct(Id),
        idempotency_key=lambda p: p["id"],
    )

    def handler(_p: Id, _id: str):
        def body():
            nonlocal runs
            run = runs
            runs += 1
            instance = yield from WorkflowInstance()
            if run == 1:
                yield from workflow.add_finalizer(
                    lambda _: fx.sync(lambda: observed.append(instance.interrupted))
                )
            return (yield from gate.wait())

        return fx.gen(body)

    def program():
        execution_id = yield from Suspends.execute({"id": "one"}, discard=True)
        yield from _poll_until_suspended(Suspends, execution_id)
        yield from Suspends.interrupt(execution_id)
        yield from _poll_until_complete(Suspends, execution_id)
        assert observed == [True]

    yield from fx.gen(program).pipe(_with_engine(Suspends.to_layer(handler)))


@pytest.mark.parametrize(
    "last_step", [True, False], ids=["the last activity", "an activity before another step"]
)
@testing.effect
def test_layer_memory_applies_safe_interruption_only_on_suspension(last_step: bool):
    """WorkflowEngine / layerMemory applies safe interruption during ${the last activity | an activity before another step} only on suspension"""  # noqa: E501
    started = yield from fx.Latch.make()
    release = yield from fx.Latch.make()
    events: list[str] = []
    Running = workflow.make(
        f"WorkflowEngine/InterruptRunningActivity/{str(last_step).lower()}",
        payload=EMPTY,
        success=S.String,
        idempotency_key=lambda _: "one",
    )

    def handler(_p: Empty, _id: str):
        def body():
            yield from Running.with_compensation(
                activity.make(name="running", execute=started.open().and_then(release.wait())),
                lambda _v, _c: fx.sync(lambda: events.append("compensated")),
            )
            if not last_step:
                yield from activity.make(
                    name="next", execute=fx.sync(lambda: events.append("next")).as_void()
                )
            return "done"

        return fx.gen(body)

    def program():
        execution_id = yield from Running.execute({}, discard=True)
        yield from started.wait()
        yield from Running.interrupt(execution_id)
        yield from release.open()
        result = yield from _poll_until_complete(Running, execution_id)

        # Safe interruption takes effect at the next suspension, not at normal completion.
        interrupted = isinstance(result.exit, fx.Failure) and result.exit.cause.has_interrupts
        if last_step:
            assert (interrupted, events) == (False, [])
            assert result.exit == fx.Success("done")
        else:
            assert (interrupted, events) == (True, ["compensated"])

    yield from fx.gen(program).pipe(_with_engine(Running.to_layer(handler)))


@pytest.mark.parametrize("state", ["running", "suspended"])
@testing.effect
def test_layer_memory_interrupt_unsafe_completes_a_workflow_without_an_external_wake(state: str):
    """WorkflowEngine / layerMemory interruptUnsafe completes a ${state} workflow without an external wake"""  # noqa: E501
    started = yield from fx.Deferred[None].make()
    gate = durable_deferred.make("WorkflowEngine/InterruptUnsafeNoWake/Gate")
    wf = workflow.make(
        "WorkflowEngine/InterruptUnsafeNoWake", payload=EMPTY, idempotency_key=lambda _: "one"
    )

    def handler(_p: Empty, _id: str) -> fx.Effect[None, Any, Any]:
        if state == "running":
            return activity.make(name="blocked", execute=started.succeed(None).and_then(fx.never))
        return gate.wait()

    def program():
        engine = yield from WorkflowEngine()
        execution_id = yield from wf.execute({}, discard=True)
        if state == "running":
            yield from started.wait()
        else:
            result = yield from wf.poll(execution_id)
            for _ in range(1000):
                if isinstance(result, Suspended):
                    break
                yield from fx.yield_now()
                result = yield from wf.poll(execution_id)
            assert isinstance(result, Suspended), "workflow must suspend first"

        yield from engine.interrupt_unsafe(wf, execution_id)
        # Do not complete the gate or resume: interruption supplies its own wake.
        result = yield from wf.poll(execution_id)
        for _ in range(1000):
            if isinstance(result, Complete):
                break
            yield from fx.yield_now()
            result = yield from wf.poll(execution_id)
        assert isinstance(result, Complete), "interruption must complete the workflow"
        assert isinstance(result.exit, fx.Failure) and result.exit.cause.has_interrupts

    yield from fx.gen(program).pipe(_with_engine(wf.to_layer(handler)))


@testing.effect
def test_layer_memory_preserves_interrupt_unsafe_across_a_suspended_replay():
    """WorkflowEngine / layerMemory preserves interruptUnsafe across a suspended replay"""
    gate = durable_deferred.make("WorkflowEngine/InterruptUnsafeReplay/Gate")
    Suspends = workflow.make(
        "WorkflowEngine/InterruptUnsafeReplay",
        payload=S.Struct(Id),
        idempotency_key=lambda p: p["id"],
    )

    def program():
        engine = yield from WorkflowEngine()
        execution_id = yield from Suspends.execute({"id": "one"}, discard=True)
        yield from _poll_until_suspended(Suspends, execution_id)

        yield from engine.interrupt_unsafe(Suspends, execution_id)
        token = gate.token_from_execution_id(workflow=Suspends, execution_id=execution_id)
        yield from gate.succeed(token=token, value=None)
        result = yield from _poll_until_complete(Suspends, execution_id)
        assert isinstance(result.exit, fx.Failure) and result.exit.cause.has_interrupts

    yield from fx.gen(program).pipe(_with_engine(Suspends.to_layer(lambda _p, _id: gate.wait())))


@pytest.mark.parametrize("recover", [False, True])
@testing.effect
def test_layer_memory_interrupted_child_without_interrupting_its_sibling(recover: bool):
    """WorkflowEngine / layerMemory ${recover ? "lets a parent recover from" : "fails a parent with a defect for"} an interrupted child without interrupting its sibling"""  # noqa: E501
    gate = durable_deferred.make("WorkflowEngine/InterruptedChildGate")
    Parent = workflow.make(
        f"WorkflowEngine/InterruptedChildParent/{_js_bool(recover)}",
        payload=EMPTY,
        idempotency_key=lambda _: "parent",
    )
    Child = workflow.make(
        f"WorkflowEngine/InterruptedChild/{_js_bool(recover)}",
        payload=S.Struct(Id),
        idempotency_key=lambda p: p["id"],
    )

    def parent(_p: Empty, _id: str):
        def body():
            yield from Child.execute({"id": "sibling"}, discard=True)
            child = Child.execute({"id": "child"})
            yield from (child.exit() if recover else child)

        return fx.gen(body)

    def program():
        parent_id = yield from Parent.execute({}, discard=True)
        child_id = yield from Child.execution_id({"id": "child"})
        sibling_id = yield from Child.execution_id({"id": "sibling"})
        yield from _poll_until_suspended(Parent, parent_id)
        yield from Child.interrupt(child_id)
        result = yield from _poll_until_complete(Parent, parent_id)
        if recover:
            assert result.exit == fx.Success(None)
        else:
            assert isinstance(result.exit, fx.Failure)
            assert result.exit.cause.has_dies and not result.exit.cause.has_interrupts
        yield from _poll_until_suspended(Child, sibling_id)

    yield from fx.gen(program).pipe(
        _with_engine(Parent.to_layer(parent), Child.to_layer(lambda _p, _id: gate.wait()))
    )


def _js_bool(value: bool) -> str:
    return "true" if value else "false"
