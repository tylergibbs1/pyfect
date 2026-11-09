"""Workflow edges Effect's tests leave open: each case below was run under
Node against Effect's ``layerMemory`` and pins the counts it printed."""

from __future__ import annotations

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
from pyfect.workflow.workflow_engine import WorkflowInstance, WorkflowInstanceService


class Empty(TypedDict):
    pass


class Detached(TypedDict):
    detached: bool


EMPTY = S.Struct(Empty)


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


def _with_engine(*layers: fx.Layer[Never, Never, Any]) -> Any:
    """Provide the workflows' layers on ``layer_memory`` (merged untyped:
    ``layer.merge`` of layers that all build nothing infers ``Unknown``)."""
    merged: fx.Layer[Any, Any, Any] = functools.reduce(fx.layer.merge, layers)
    return fx.provide(merged.pipe(fx.layer.provide_merge(workflow_engine.layer_memory)))


@testing.effect
def test_an_activity_that_suspended_runs_again_on_replay():
    """An activity whose body waits on a deferred stores no result, so the
    replay runs its body again (Effect: runs=2, bodyRuns=2)."""
    gate = durable_deferred.make("gate", success=S.String)
    counts = {"runs": 0, "body": 0}
    wf = workflow.make("Inner", payload=EMPTY, success=S.String, idempotency_key=lambda _: "a")

    def inner():
        counts["body"] += 1
        return (yield from gate.wait())

    def handler(_p: Empty, _id: str):
        counts["runs"] += 1
        return activity.make(name="inner", success=S.String, execute=fx.gen(inner))

    def program():
        execution_id = yield from wf.execute({}, discard=True)
        yield from _poll_until_suspended(wf, execution_id)
        token = gate.token_from_execution_id(workflow=wf, execution_id=execution_id)
        yield from gate.succeed(token=token, value="v")
        result = yield from _poll_until_complete(wf, execution_id)
        assert result.exit == fx.Success("v")
        assert counts == {"runs": 2, "body": 2}

    yield from fx.gen(program).pipe(_with_engine(wf.to_layer(handler)))


@testing.effect
def test_a_detached_child_completing_does_not_wake_its_parent():
    """A linked child's completion replays its suspended parent; a
    detached one's does not (Effect: parentRuns 1 detached, 2 linked)."""
    gate = durable_deferred.make("gate")
    child_gate = durable_deferred.make("childGate")
    runs = {"parent": 0}
    Child = workflow.make("Child", payload=EMPTY, idempotency_key=lambda _: "c")
    Parent = workflow.make(
        "Parent",
        payload=S.Struct(Detached),
        idempotency_key=lambda p: str(p["detached"]),
    )

    def parent(p: Detached, _id: str):
        def body():
            runs["parent"] += 1
            yield from Child.execute({}, discard=True, detached=p["detached"])
            yield from gate.wait()

        return fx.gen(body)

    layers = (Child.to_layer(lambda _p, _id: child_gate.wait()), Parent.to_layer(parent))

    def run(detached: bool):
        def program():
            runs["parent"] = 0
            execution_id = yield from Parent.execute({"detached": detached}, discard=True)
            yield from _poll_until_suspended(Parent, execution_id)
            child_id = yield from Child.execution_id({})
            token = child_gate.token_from_execution_id(workflow=Child, execution_id=child_id)
            yield from child_gate.succeed(token=token, value=None)
            yield from _poll_until_complete(Child, child_id)
            for _ in range(200):
                yield from fx.yield_now()
            return runs["parent"]

        return fx.gen(program).pipe(_with_engine(*layers))

    assert (yield from run(True)) == 1
    assert (yield from run(False)) == 2


@testing.effect
def test_a_safe_interrupt_ends_a_failure_suspended_workflow():
    """With ``SuspendOnFailure``, a failing run suspends; a safe interrupt
    then replays it and the failure completes the execution (Effect:
    runs=2, Complete(Fail "boom"), no interrupt in the cause)."""
    runs = {"n": 0}
    wf = workflow.make(
        "FailureSuspends", payload=EMPTY, error=S.String, idempotency_key=lambda _: "c"
    ).annotate(workflow.SuspendOnFailure, True)

    def handler(_p: Empty, _id: str):
        def run():
            runs["n"] += 1
            return fx.fail("boom")

        return fx.suspend(run)

    def program():
        execution_id = yield from wf.execute({}, discard=True)
        suspended = yield from _poll_until_suspended(wf, execution_id)
        assert suspended.failed
        yield from wf.interrupt(execution_id)
        result = yield from _poll_until_complete(wf, execution_id)
        assert isinstance(result.exit, fx.Failure)
        reasons = result.exit.cause.reasons
        assert len(reasons) == 1 and isinstance(reasons[0], Fail) and reasons[0].error == "boom"
        assert runs["n"] == 2

    yield from fx.gen(program).pipe(_with_engine(wf.to_layer(handler)))


@testing.effect
def test_a_suspension_waits_for_an_activity_already_running():
    """A durable wait that suspends lets a sibling activity already in
    flight finish and store its result, so the replay does not run it again
    (Effect: slowRuns 1 before and after the resume)."""
    gate = durable_deferred.make("gate")
    counts = {"runs": 0, "slow": 0}
    wf = workflow.make("Siblings", payload=EMPTY, idempotency_key=lambda _: "d")

    def slow():
        counts["slow"] += 1
        return fx.sleep("30 seconds")

    def handler(_p: Empty, _id: str):
        counts["runs"] += 1
        return fx.all(
            activity.make(name="slow", execute=fx.suspend(slow)),
            gate.wait(),
            concurrency="unbounded",
        ).as_void()

    def program():
        execution_id = yield from wf.execute({}, discard=True)
        yield from testing.adjust("30 seconds")
        yield from _poll_until_suspended(wf, execution_id)
        assert counts["slow"] == 1
        token = gate.token_from_execution_id(workflow=wf, execution_id=execution_id)
        yield from gate.succeed(token=token, value=None)
        yield from _poll_until_complete(wf, execution_id)
        assert counts == {"runs": 2, "slow": 1}

    yield from fx.gen(program).pipe(_with_engine(wf.to_layer(handler)))


@testing.effect
def test_completing_a_race_loser_later_does_not_preempt_the_run():
    """Once a durable race settles, its losing wait no longer counts as
    awaited, so completing it later does not replay the run (Effect:
    runs=1, Complete("fast"))."""
    loser = durable_deferred.make("loser", success=S.String)
    runs = {"n": 0}
    wf = workflow.make("RaceLoser", payload=EMPTY, success=S.String, idempotency_key=lambda _: "e")

    def handler(_p: Empty, _id: str):
        def body():
            runs["n"] += 1
            won = yield from durable_deferred.race_all(
                name="race",
                success=S.String,
                error=S.Never,
                effects=[loser.wait(), fx.succeed("fast")],
            )
            yield from activity.make(name="later", execute=fx.sleep("30 seconds"))
            return won

        return fx.gen(body)

    def program():
        execution_id = yield from wf.execute({}, discard=True)
        for _ in range(20):
            yield from fx.yield_now()
        token = loser.token_from_execution_id(workflow=wf, execution_id=execution_id)
        yield from loser.succeed(token=token, value="late")
        yield from testing.adjust("30 seconds")
        result = yield from _poll_until_complete(wf, execution_id)
        assert result.exit == fx.Success("fast")
        assert runs["n"] == 1

    yield from fx.gen(program).pipe(_with_engine(wf.to_layer(handler)))


@testing.effect
def test_a_sleep_as_long_as_the_threshold_runs_in_memory():
    """``durable_clock.sleep`` of exactly ``in_memory_threshold`` sleeps in
    an activity, without suspending the execution (Effect: poll None
    mid-sleep)."""
    wf = workflow.make("Sleeps", payload=EMPTY, idempotency_key=lambda _: "f")
    layer = wf.to_layer(
        lambda _p, _id: durable_clock.sleep(
            name="nap", duration="50 seconds", in_memory_threshold="50 seconds"
        )
    )

    def program():
        execution_id = yield from wf.execute({}, discard=True)
        yield from testing.adjust("10 seconds")
        assert (yield from wf.poll(execution_id)) is None
        yield from testing.adjust("40 seconds")
        result = yield from _poll_until_complete(wf, execution_id)
        assert result.exit == fx.Success(None)

    yield from fx.gen(program).pipe(_with_engine(layer))


@testing.effect
def test_a_suspension_waits_for_a_child_still_computing_its_id():
    """A child execution counts as in flight before its execution id is
    computed, so a sibling wait that suspends first lets the child start
    (Effect: childRuns=1 once the parent is suspended)."""
    gate = durable_deferred.make("gate")
    runs = {"child": 0}
    Child = workflow.make("Child", payload=EMPTY, success=S.String, idempotency_key=lambda _: "c")
    Parent = workflow.make("Parent", payload=EMPTY, idempotency_key=lambda _: "p")

    def child(_p: Empty, _id: str):
        def run() -> str:
            runs["child"] += 1
            return "child"

        return fx.sync(run)

    def parent(_p: Empty, _id: str):
        return fx.all(Child.execute({}), gate.wait(), concurrency="unbounded").as_void()

    layers = (Child.to_layer(child), Parent.to_layer(parent))

    def program():
        execution_id = yield from Parent.execute({}, discard=True)
        yield from _poll_until_suspended(Parent, execution_id)
        assert runs["child"] == 1

    yield from fx.gen(program).pipe(_with_engine(*layers))


@pytest.mark.parametrize(
    ("interrupted", "abandoned_after", "events"),
    [
        (False, True, ["body finalizer"]),
        (True, False, ["body finalizer", "workflow finalizer"]),
    ],
    ids=["abandoned", "abandoned-and-interrupted"],
)
@testing.effect
def test_an_abandoned_run_skips_workflow_finalizers(
    interrupted: bool, abandoned_after: bool, events: list[str]
):
    """A run the engine marked abandoned, then interrupted from outside,
    keeps its workflow finalizers for the replay elsewhere; a workflow
    interrupt overrides the mark (both checked under Node)."""
    wf = workflow.make("Abandoned", payload=EMPTY, idempotency_key=lambda _: "h")
    instance = WorkflowInstanceService.initial(wf, "h")
    seen: list[str] = []
    body = (
        workflow.add_finalizer(lambda _: fx.sync(lambda: seen.append("workflow finalizer")))
        .and_then(fx.never)
        .ensuring(fx.sync(lambda: seen.append("body finalizer")))
    )
    fiber = (
        yield from workflow.into_result(body)
        .pipe(fx.provide_service(WorkflowInstance, instance))
        .fork(start_immediately=True)
    )
    yield from fx.yield_now()
    instance.abandoned = True
    instance.interrupted = interrupted
    yield from fiber.interrupt()
    ex = yield from fiber.await_exit()
    assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts_only
    assert instance.abandoned is abandoned_after
    assert seen == events


@testing.effect
def test_a_deferred_refuses_a_token_naming_another_deferred():
    """A token minted for one deferred cannot complete another through it
    (Effect writes the value into whatever deferred the token names)."""
    gate = durable_deferred.make("gate", success=S.String)
    other = durable_deferred.make("other", success=S.String)
    wf = workflow.make("Gated", payload=EMPTY, success=S.String, idempotency_key=lambda _: "g")

    def handler(_p: Empty, _id: str):
        return gate.wait()

    def program():
        execution_id = yield from wf.execute({}, discard=True)
        yield from _poll_until_suspended(wf, execution_id)
        token = gate.token_from_execution_id(workflow=wf, execution_id=execution_id)
        exit = yield from other.succeed(token=token, value="forged").exit()
        assert isinstance(exit, fx.Failure)
        assert isinstance((yield from wf.poll(execution_id)), Suspended)

    yield from fx.gen(program).pipe(_with_engine(wf.to_layer(handler)))


@testing.live(timeout="10 seconds")
def test_poll_gives_none_for_an_unknown_and_for_a_running_execution():
    """As Effect's ``poll`` (``Option.none()`` for both, printed under Node):
    a run inside a short (in-memory) durable sleep is running, not suspended
    (DOGFOOD outlay #9)."""
    gate = durable_deferred.make("poll-gate")
    wf = workflow.make("Polled", payload=EMPTY, success=S.String, idempotency_key=lambda _: "a")

    def handler(_p: Empty, _id: str):
        def body():
            yield from durable_clock.sleep(name="short", duration="50 millis")
            yield from gate.wait()
            return "done"

        return fx.gen(body)

    def program():
        assert (yield from wf.poll("unknown")) is None
        execution_id = yield from wf.execute({}, discard=True)
        assert (yield from wf.poll(execution_id)) is None
        assert (yield from _poll_until_suspended(wf, execution_id)) == Suspended()

    yield from fx.gen(program).pipe(_with_engine(wf.to_layer(handler)))


@pytest.mark.parametrize(
    "payload", [S.String, S.Int, S.Union(S.Struct(Empty), S.String)], ids=["String", "Int", "Union"]
)
def test_make_refuses_a_payload_that_is_not_a_struct_or_a_schema_class(payload: Any):
    """Effect types ``Workflow.make``'s payload as ``Schema.Struct.Fields |
    AnyStructSchema``; pyfect refuses any other schema at definition, where
    the cluster engine used to die at run time (dogfood apps #9)."""
    with pytest.raises(TypeError, match="must be a struct or a schema class"):
        workflow.make("Plain", payload=payload, idempotency_key=str)


def test_make_takes_a_checked_struct_and_a_schema_class():
    class Order(S.Class):
        id: str

    workflow.make(
        "Checked", payload=EMPTY.check(S.make_filter(lambda _: True)), idempotency_key=str
    )
    workflow.make("Cls", payload=Order, idempotency_key=lambda o: o.id)
