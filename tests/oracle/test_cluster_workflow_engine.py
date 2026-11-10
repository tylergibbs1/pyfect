"""Ports of Effect's ``test/cluster/ClusterWorkflowEngine.test.ts``.

Each test's docstring is the Effect test title. Durations are seconds
(``TestClock.adjust(1)`` is ``testing.adjust(0.001)``); the workflows and
helpers are in ``_cluster_workflows.py``."""
# pyright: reportPrivateUsage=false, reportUnknownVariableType=false
# pyright: reportUnknownArgumentType=false, reportUnknownMemberType=false
# pyright: reportUnknownLambdaType=false

from __future__ import annotations

import functools
from dataclasses import replace
from typing import Any, TypedDict, cast

import pytest

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schedule, testing
from pyfect import schema as S
from pyfect.clock import Clock, now_millis_unsafe
from pyfect.cluster import message_storage, runner_storage
from pyfect.cluster._entity_activation import CurrentActivationScope
from pyfect.cluster.cluster_error import PersistenceError
from pyfect.cluster.cluster_schema import Persisted
from pyfect.cluster.entity import Entity, EntityHandlers
from pyfect.cluster.entity_id import EntityId
from pyfect.cluster.envelope import Request as EnvelopeRequest
from pyfect.cluster.message_storage import MemoryDriver, MessageStorage
from pyfect.cluster.runner_storage import RunnerStorage
from pyfect.cluster.sharding import Sharding
from pyfect.cluster.sharding import layer as sharding_layer_of
from pyfect.cluster.snowflake import Snowflake
from pyfect.duration import Seconds
from pyfect.rpc import make as make_rpc
from pyfect.schema import ast
from pyfect.scope import CloseableScope, Scope
from pyfect.tracer import NativeSpan, SpanRequest, Tracer
from pyfect.workflow import Complete, Suspended, activity, durable_clock, durable_deferred, workflow
from pyfect.workflow.workflow import SuspendOnFailure
from pyfect.workflow.workflow_engine import (
    WorkflowEngine,
    WorkflowInstance,
    WorkflowInstanceService,
)

from . import _cluster_parallel_workflows as P
from . import _cluster_race_workflows as R
from . import _cluster_workflows as W
from ._cluster_workflows import (
    CatchWorkflow,
    ChildDeferred,
    EmailTrigger,
    EmailWorkflow,
    ErrorDefectWorkflow,
    Flags,
    ParentWorkflow,
    SendEmailError,
    SuspendOnFailureWorkflow,
    advance_until,
    poll_storage_until,
    poll_until,
    requests_of,
    wait_for_clock,
)

_workflow_layers: fx.Layer[Any, Any, Any] = functools.reduce(
    fx.layer.merge,
    [
        W.email_workflow_layer,
        W.parent_workflow_layer,
        W.child_workflow_layer,
        W.suspend_on_failure_workflow_layer,
        W.catch_workflow_layer,
        W.error_defect_workflow_layer,
        R.race_workflow_layers,
        P.parallel_workflow_layers,
    ],
)
test_workflow_layer = (
    _workflow_layers.pipe(fx.layer.provide_merge(W.flags_layer))
    .pipe(fx.layer.provide_merge(R.two_step_branch_control_layer))
    .pipe(fx.layer.provide_merge(P.sharded_clock_scheduled_layer))
    .pipe(fx.layer.provide_merge(W.test_workflow_engine))
)


@testing.effect
def test_executes_resumes_deduplicates_and_polls_a_suspended_workflow():
    """executes, resumes, deduplicates, and polls a suspended workflow"""

    @fx.gen
    def body():
        sharding = yield from Sharding()
        driver = yield from MemoryDriver()
        flags = yield from Flags()

        fiber = yield from EmailWorkflow.execute(
            {"id": "test-email-1", "to": "bob@example.com"}
        ).fork(start_immediately=True)

        # Do not advance the sleep until its durable wake-up has been persisted.
        yield from wait_for_clock(driver, "Some sleep")
        yield from testing.adjust("10 seconds")
        yield from poll_storage_until(
            lambda: flags.get("ensuring") is True, "suspended await must run ensuring"
        )

        # --- the workflow is suspended at this point

        # - 1 initial request
        # - 5 attempts to send email
        # - 1 sleep activity
        # - 1 durable clock run
        # - 1 durable clock deferred set
        assert len(driver.encoded.requests) == 9
        execution_id = driver.encoded.journal[0]["address"]["entityId"]

        # normal finalizer should run even after suspension
        assert flags.get("finalizer")
        # but not compensation
        assert not flags.get("compensation")
        # ensuring will run
        assert flags.get("ensuring")
        assert not flags.get("catchCause")

        # --- resume the workflow using DurableDeferred.done

        token = yield from EmailTrigger.token().pipe(
            fx.provide_service(
                WorkflowInstance, WorkflowInstanceService.initial(EmailWorkflow, execution_id)
            )
        )
        yield from EmailTrigger.done(token=token, exit=Exit.succeed("done"))
        yield from sharding.poll_storage

        # - 1 DurableDeferred set
        assert len(driver.encoded.requests) == 10

        # allow suspend polling to complete
        yield from testing.adjust("10 seconds")
        assert (yield from fiber.join()) is None

        # --- the workflow is complete

        assert flags.get("ensuring")
        assert not flags.get("catchCause")

        # test deduplication
        yield from EmailWorkflow.execute({"id": "test-email-1", "to": "bob@example.com"})
        assert len(driver.encoded.requests) == 10

        # test poll
        assert (yield from EmailWorkflow.poll(execution_id)) == Complete(Exit.succeed(None))

    yield from body.pipe(fx.provide(test_workflow_layer))


@testing.effect
def test_interrupts_a_suspended_workflow_and_runs_compensation():
    """interrupts a suspended workflow and runs compensation"""

    @fx.gen
    def body():
        sharding = yield from Sharding()
        driver = yield from MemoryDriver()
        yield from testing.adjust("1 millis")

        fiber = yield from EmailWorkflow.execute(
            {"id": "test-email-2", "to": "bob@example.com"}
        ).fork()

        yield from wait_for_clock(driver, "Some sleep")
        yield from testing.adjust("10 seconds")
        yield from sharding.poll_storage
        yield from testing.adjust("1 millis")

        envelope = driver.encoded.journal[0]
        execution_id = envelope["address"]["entityId"]

        def sleep_completed() -> bool:
            return any(
                entry.envelope["_tag"] == "Request"
                and entry.envelope["tag"] == "activity"
                and entry.envelope["address"]["entityId"] == execution_id
                and entry.envelope["payload"]["name"] == "Sleep"
                and any(
                    reply["_tag"] == "WithExit"
                    and reply["exit"]["_tag"] == "Success"
                    and reply["exit"]["value"]["_tag"] == "Complete"
                    for reply in entry.replies
                )
                for entry in requests_of(driver)
            )

        # Interrupt after the clock-backed activity completes, so the workflow
        # is suspended on EmailTrigger rather than racing the clock's completion.
        yield from poll_storage_until(sleep_completed, "sleep activity must complete")
        yield from poll_until(EmailWorkflow, execution_id, Suspended)
        yield from EmailWorkflow.interrupt(execution_id)

        def signal_persisted() -> bool:
            return any(
                entry.envelope["_tag"] == "Request"
                and entry.envelope["tag"] == "deferred"
                and entry.envelope["address"]["entityId"] == execution_id
                and entry.envelope["address"]["entityType"] == f"Workflow/{EmailWorkflow.tag}"
                and entry.envelope["payload"]["name"] == "Workflow/InterruptSignal"
                for entry in requests_of(driver)
            )

        yield from advance_until(signal_persisted, "interrupt signal request must be persisted")
        yield from poll_until(EmailWorkflow, execution_id, Complete)
        # - clock cleared
        assert len(driver.encoded.requests) == 9

        result = driver.encoded.requests[envelope["requestId"]]
        reply: Any = result.replies[0]
        assert reply["_tag"] == "WithExit" and reply["exit"]["_tag"] == "Success"
        value = reply["exit"]["value"]
        assert value["_tag"] == "Complete" and value["exit"]["_tag"] == "Failure"

        yield from advance_until(
            lambda: fiber.poll_unsafe() is not None,
            "execute waiter must observe interruption",
            0.01,
        )
        ex = yield from fiber.await_exit()
        assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts

        flags = yield from Flags()
        assert flags.get("compensation") is True

    yield from body.pipe(fx.provide(test_workflow_layer))


@testing.effect
def test_workflow_with_compensation_runs_compensation_when_the_workflow_fails():
    """Workflow.withCompensation runs compensation when the workflow fails"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        payload: W.EmailPayload = {"id": "test-email-3", "to": "compensation"}
        fiber = yield from EmailWorkflow.execute(payload).fork(start_immediately=True)
        yield from poll_until(
            EmailWorkflow, (yield from EmailWorkflow.execution_id(payload)), Complete
        )
        error = yield from fiber.join().flip()
        assert isinstance(error, SendEmailError)
        flags = yield from Flags()
        assert flags.get("compensation") is True

    yield from body.pipe(fx.provide(test_workflow_layer))


@testing.effect
def test_nested_workflows():
    """nested workflows"""

    @fx.gen
    def body():
        flags = yield from Flags()
        sharding = yield from Sharding()
        yield from testing.adjust("1 millis")

        yield from ParentWorkflow.execute({"id": "123"}).fork()
        yield from testing.adjust("1 second")
        while flags.get("parent-suspended") is None:
            yield from fx.yield_now()

        assert flags.get("parent-end") is None
        assert flags.get("child-end") is None
        assert flags.get("parent-suspended") is True
        token = flags.get("child-token")
        assert isinstance(token, str)

        yield from ChildDeferred.done(token=token, exit=Exit.succeed(None))
        yield from testing.adjust("5 seconds")
        yield from sharding.poll_storage
        assert flags.get("parent-end") is True
        assert flags.get("child-end") is True

    yield from body.pipe(fx.provide(test_workflow_layer))


@testing.effect
def test_wakes_the_parent_when_a_suspended_child_is_interrupted():
    """wakes the parent when a suspended child is interrupted"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        parent_id = yield from ParentWorkflow.execute({"id": "interrupted"}, discard=True)
        child_id = yield from W.ChildWorkflow.execution_id({"id": "interrupted"})
        yield from poll_until(ParentWorkflow, parent_id, Suspended)
        yield from poll_until(W.ChildWorkflow, child_id, Suspended)
        yield from W.ChildWorkflow.interrupt(child_id)
        child = yield from poll_until(W.ChildWorkflow, child_id, Complete)
        assert isinstance(child.exit, fx.Failure) and child.exit.cause.has_interrupts
        parent = yield from poll_until(ParentWorkflow, parent_id, Complete)
        assert isinstance(parent.exit, fx.Failure)
        assert parent.exit.cause.has_dies and not parent.exit.cause.has_interrupts

    yield from body.pipe(fx.provide(test_workflow_layer))


@testing.effect
def test_suspend_on_failure():
    """SuspendOnFailure"""

    @fx.gen
    def body():
        flags = yield from Flags()
        yield from testing.adjust("1 millis")
        yield from SuspendOnFailureWorkflow.execute({"id": ""}).fork(start_immediately=True)
        yield from testing.adjust("2 seconds")
        while "suspended" not in flags:
            yield from fx.yield_now()
        assert flags.get("suspended") is True
        assert "boom" in str(flags.get("cause"))

    yield from body.pipe(fx.provide(test_workflow_layer))


@testing.effect
def test_catch_cause_activity():
    """catchCause activity"""

    @fx.gen
    def body():
        flags = yield from Flags()
        yield from testing.adjust("1 millis")
        fiber = yield from CatchWorkflow.execute({"id": ""}).fork_scoped()
        yield from testing.adjust("1 millis")
        yield from fiber.join()
        assert flags.get("catch") is True

    yield from body.pipe(fx.provide(test_workflow_layer))


@testing.effect
def test_can_serialize_workflow_defects():
    """can serialize workflow defects"""

    @fx.gen
    def body():
        yield from testing.adjust("1 millis")
        ex = yield from ErrorDefectWorkflow.execute({"id": "raw-error-defect"}).exit()
        assert isinstance(ex, fx.Failure)
        defect = ex.cause.defects[0]
        assert isinstance(defect, Exception)
        assert str(defect) == "Batch request error: Request timed out"

    yield from body.pipe(fx.provide(test_workflow_layer))


# --- scopes, activities and shutdown -----------------------------------------------------


@pytest.mark.parametrize("complete", [True, False], ids=["completion", "teardown"])
@testing.effect
def test_releases_all_workflow_scopes_after_multiple_suspensions(complete: bool):
    """releases all workflow scopes after multiple suspensions on completion | teardown"""
    gates = [
        durable_deferred.make("WorkflowScopeCleanup/First"),
        durable_deferred.make("WorkflowScopeCleanup/Second"),
    ]
    wf = workflow.make("WorkflowScopeCleanup", payload=W.EMPTY, idempotency_key=lambda _: "one")
    acquired: list[int] = []
    released: list[int] = []
    finalized: list[int] = []

    def handler(_: Any, __: str):
        @fx.gen
        def body():
            run = len(acquired) + 1
            yield from workflow.add_finalizer(lambda _: fx.sync(lambda: finalized.append(run)))

            def acquire() -> int:
                acquired.append(run)
                return run

            yield from fx.acquire_release(
                fx.sync(acquire), lambda r, _: fx.sync(lambda: released.append(r))
            ).pipe(workflow.provide_scope)
            for gate in gates:
                yield from gate.wait()

        return body

    layer = wf.to_layer(handler).pipe(fx.layer.provide_merge(W.make_test_workflow_engine()))

    @fx.gen
    def run():
        execution_id = yield from wf.execute({}, discard=True)
        for index, gate in enumerate(gates):
            # The previous Suspended reply can remain visible until replay starts.
            sharding = yield from Sharding()
            for _ in range(2000):
                if len(acquired) > index:
                    break
                yield from testing.adjust("1 millis")
                yield from sharding.poll_storage
            yield from poll_until(wf, execution_id, Suspended)
            # Suspension retains every attempt's resources and durable finalizers.
            assert (acquired, released, finalized) == ([1] if index == 0 else [1, 2], [], [])
            if not complete and index == 1:
                return
            yield from gate.succeed(
                token=gate.token_from_execution_id(workflow=wf, execution_id=execution_id),
                value=None,
            )
        assert (yield from poll_until(wf, execution_id, Complete)) == Complete(Exit.succeed(None))
        assert (acquired, sorted(released), sorted(finalized)) == ([1, 2, 3], [1, 2, 3], [1, 2, 3])

    yield from run.pipe(fx.provide(layer))
    if not complete:
        assert (acquired, sorted(released), finalized) == ([1, 2], [1, 2], [])


@testing.effect
def test_wakes_an_activity_deferred_completed_before_a_parallel_sibling_lets_the_workflow_suspend():
    """wakes an activity deferred completed before a parallel sibling lets the workflow suspend"""
    gate = durable_deferred.make("EarlyActivityWake/Gate", success=S.String)
    wf = workflow.make(
        "EarlyActivityWake",
        payload=W.EMPTY,
        success=S.Array(S.String),
        idempotency_key=lambda _: "one",
    )
    sibling_started = yield from fx.Latch.make()
    release_sibling = yield from fx.Latch.make()
    activity_parked = yield from fx.Latch.make()
    await_gate = activity.make(
        name="await-gate",
        success=S.String,
        execute=sibling_started.wait().and_then(gate.wait()).on_interrupt(activity_parked.open()),
    )
    block = activity.make(
        name="block",
        success=S.String,
        execute=sibling_started.open().and_then(release_sibling.wait()).as_("blocked"),
    )
    activations = [0]

    def handler(_: Any, __: str):
        activations[0] += 1
        # Yield the activities themselves so both run through the workflow engine.
        return fx.all(await_gate, block, concurrency="unbounded")

    context = (
        yield from wf.to_layer(handler)
        .pipe(fx.layer.provide_merge(W.make_test_workflow_engine()))
        .build()
    )

    @fx.gen
    def run():
        sharding = yield from Sharding()
        execution_id = yield from wf.execute({}, discard=True)
        yield from activity_parked.wait()
        for _ in range(5):
            yield from testing.adjust("1 millis")
            yield from sharding.poll_storage
        assert (yield from wf.poll(execution_id)) is None
        completion = yield from gate.succeed(
            token=gate.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value="done",
        ).fork(start_immediately=True)
        # Deliver the callback while the sibling still prevents the parent from suspending.
        for _ in range(5):
            yield from testing.adjust("1 millis")
            yield from sharding.poll_storage
        assert (yield from wf.poll(execution_id)) is None
        yield from release_sibling.open()
        assert (yield from poll_until(wf, execution_id, Complete)) == Complete(
            Exit.succeed(("done", "blocked"))
        )
        yield from completion.join()
        assert activations[0] == 2

    yield from run.pipe(fx.provide(context))


@testing.effect
def test_answers_an_orphaned_activity_after_restart_even_when_replay_never_registers_it():
    """answers an orphaned activity after restart even when replay never registers it"""
    release = durable_deferred.make("OrphanActivity/Release")
    wf = workflow.make("OrphanActivity", payload=W.EMPTY, idempotency_key=lambda _: "one")
    storage = yield from W.make_shared_storage()

    def layer(crash: bool = False) -> fx.Layer[Any, Any, Any]:
        return wf.to_layer(lambda _, __: release.wait()).pipe(
            fx.layer.provide_merge(
                W.make_test_workflow_engine(
                    storage_layer=W.unanswered_activity_storage(storage)
                    if crash
                    else W.storage_layer_of(storage)
                )
            )
        )

    execution_id = yield from wf.execution_id({})

    @fx.gen
    def first():
        yield from wf.execute({}, discard=True)
        yield from poll_until(wf, execution_id, Suspended)
        # Crash residue: the losing request is durable, but its Interrupt is absent.
        return (yield from W.send_unregistered_activity(wf.tag, execution_id))

    request_id = yield from first.pipe(fx.provide(layer(True)))
    assert (yield from storage.replies_for_unfiltered([request_id])) == []

    @fx.gen
    def second():
        yield from (yield from Sharding()).poll_storage
        assert (yield from W.activity_reply(storage, request_id)) == Exit.succeed(Suspended())
        yield from release.succeed(
            token=release.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value=None,
        )
        assert (yield from poll_until(wf, execution_id, Complete)) == Complete(Exit.succeed(None))
        assert (yield from W.activity_reply(storage, request_id)) == Exit.succeed(Suspended())

    yield from second.pipe(fx.provide(layer()))


@testing.effect
def test_shuts_down_without_waiting_for_a_queued_activity_and_replays_it_after_restart():
    """shuts down without waiting for a queued activity and replays it after restart"""
    wf = workflow.make("QueuedActivityShutdown", payload=W.EMPTY, idempotency_key=lambda _: "one")
    executions = [0]

    def count() -> None:
        executions[0] += 1

    step = activity.make(name="step", execute=fx.sync(count))
    storage = yield from W.make_shared_storage()
    queued = yield from fx.Latch.make()

    def is_activity(message: Any) -> bool:
        return isinstance(message.envelope, EnvelopeRequest) and message.envelope.tag == "activity"

    def save_request(message: Any) -> fx.Effect[Any, Any]:
        return storage.save_request(message).tap(
            lambda _: queued.open() if message.rpc.tag == "activity" else fx.void
        )

    def unprocessed_messages(shard_ids: Any, **options: Any) -> fx.Effect[Any, Any]:
        return storage.unprocessed_messages(shard_ids, **options).map(
            lambda messages: [m for m in messages if not is_activity(m)]
        )

    def unprocessed_messages_by_id(ids: Any) -> fx.Effect[Any, Any]:
        return storage.unprocessed_messages_by_id(ids).map(
            lambda messages: [m for m in messages if not is_activity(m)]
        )

    # The activity request is persisted, but the runner never reads it back.
    queued_storage = W.storage_layer_of(
        W.override_storage(
            storage,
            save_request=save_request,
            unprocessed_messages=unprocessed_messages,
            unprocessed_messages_by_id=unprocessed_messages_by_id,
        )
    )

    def layer(storage_layer: fx.Layer[Any]) -> fx.Layer[Any, Any, Any]:
        return wf.to_layer(lambda _, __: step).pipe(
            fx.layer.provide_merge(
                W.make_test_workflow_engine(
                    storage_layer=storage_layer,
                    config_overrides={"entity_termination_timeout": Seconds(60)},
                )
            )
        )

    scope = CloseableScope()
    context = yield from layer(queued_storage).build_with_scope(scope)
    execution_id = yield from wf.execute({}, discard=True).pipe(fx.provide(context))
    yield from queued.wait()
    shutdown = yield from scope.close(Exit.succeed(None)).fork(start_immediately=True)
    for _ in range(100):
        if shutdown.poll_unsafe() is not None:
            break
        yield from testing.adjust("10 millis")
    closed_before_timeout = shutdown.poll_unsafe() is not None
    # Let a stalled shutdown finish, so the runner is released before asserting.
    yield from testing.adjust("1 minute")
    yield from shutdown.join()
    assert closed_before_timeout, "shutdown must not wait for entityTerminationTimeout"
    assert executions[0] == 0

    @fx.gen
    def after():
        assert (yield from poll_until(wf, execution_id, Complete)) == Complete(Exit.succeed(None))
        assert executions[0] == 1

    yield from after.pipe(fx.provide(layer(W.storage_layer_of(storage))))


@testing.effect
def test_shutdown_waits_for_a_running_activity_before_finalizing_its_workflow():
    """shutdown waits for a running activity before finalizing its workflow"""
    wf = workflow.make("RunningActivityShutdown", payload=W.EMPTY, idempotency_key=lambda _: "one")
    events: list[str] = []
    started = yield from fx.Latch.make()
    release = yield from fx.Latch.make()

    @fx.gen
    def step_body():
        events.append("activity:start")
        yield from started.open()
        yield from release.wait()
        events.append("activity:end")

    step = activity.make(name="step", execute=step_body)

    def handler(_: Any, __: str):
        @fx.gen
        def body():
            yield from fx.add_finalizer(lambda _: fx.sync(lambda: events.append("finalized"))).pipe(
                workflow.provide_scope
            )
            yield from step

        return body

    layer = wf.to_layer(handler).pipe(
        fx.layer.provide_merge(
            W.make_test_workflow_engine(
                config_overrides={"entity_termination_timeout": Seconds(60)}
            )
        )
    )
    scope = CloseableScope()
    context = yield from layer.build_with_scope(scope)
    yield from wf.execute({}, discard=True).pipe(fx.provide(context))
    yield from advance_until(started.is_open, "activity must start")
    shutdown = yield from scope.close(Exit.succeed(None)).fork(start_immediately=True)
    for _ in range(100):
        yield from testing.adjust("10 millis")
    pending_while_running = shutdown.poll_unsafe() is None
    yield from release.open()
    for _ in range(100):
        if shutdown.poll_unsafe() is not None:
            break
        yield from testing.adjust("10 millis")
    closed_before_timeout = shutdown.poll_unsafe() is not None
    # Let a stalled shutdown finish, so the runner is released before asserting.
    yield from testing.adjust("1 minute")
    yield from shutdown.join()
    assert pending_while_running, "shutdown must wait for the running activity"
    assert closed_before_timeout, "shutdown must finish once the activity completes"
    assert events == ["activity:start", "activity:end", "finalized"]


@testing.effect
def test_replays_a_raced_activity_that_starts_during_shutdown_on_the_next_owner():
    """replays a raced activity that starts during shutdown on the next owner"""
    wf = workflow.make(
        "ShutdownRacedActivity", payload=W.EMPTY, success=S.String, idempotency_key=lambda _: "one"
    )
    gate = durable_deferred.make("ShutdownRacedActivity/Gate")
    executions = [0]

    def execute() -> str:
        executions[0] += 1
        return "done"

    step = activity.make(name="step", success=S.String, execute=fx.sync(execute))
    storage = yield from W.make_shared_storage()
    held = yield from fx.Latch.make()

    def layer(hold_until_shutdown: bool) -> fx.Layer[Any, Any, Any]:
        @fx.gen
        def run():
            if hold_until_shutdown:
                # Start the activity only once the runner is shutting down.
                sharding = yield from Sharding()
                yield from held.open()
                while not (yield from sharding.is_shutdown):
                    yield from fx.yield_now()
            return (
                yield from durable_deferred.race_all(
                    name="steer",
                    success=S.String,
                    error=S.Never,
                    effects=[step, gate.wait().as_("steered")],
                )
            )

        return wf.to_layer(lambda _, __: run).pipe(
            fx.layer.provide_merge(
                W.make_test_workflow_engine(
                    storage_layer=W.storage_layer_of(storage),
                    config_overrides={"entity_termination_timeout": Seconds(2)},
                )
            )
        )

    scope = CloseableScope()
    context = yield from layer(True).build_with_scope(scope)
    execution_id = yield from wf.execute({}, discard=True).pipe(fx.provide(context))
    yield from advance_until(held.is_open, "run must start")
    shutdown = yield from scope.close(Exit.succeed(None)).fork(start_immediately=True)
    yield from advance_until(
        lambda: shutdown.poll_unsafe() is not None, "shutdown must finish", step=0.01
    )
    yield from shutdown.join()

    @fx.gen
    def after():
        assert (yield from poll_until(wf, execution_id, Complete)) == Complete(Exit.succeed("done"))
        assert executions[0] == 1

    yield from after.pipe(fx.provide(layer(False)))


@testing.effect
def test_retries_an_early_activity_registered_while_its_suspended_reply_is_still_being_persisted():
    """retries an early activity registered while its Suspended reply is still being persisted"""
    wf = workflow.make(
        "EarlyActivity", payload=W.EMPTY, success=S.Number, idempotency_key=lambda _: "one"
    )
    register = yield from fx.Latch.make()
    saving_reply = yield from fx.Latch.make()
    release_reply = yield from fx.Latch.make()
    registration_requested = yield from fx.Latch.make()
    executions = [0]
    activity_requests = [0]

    def execute() -> int:
        executions[0] += 1
        return executions[0]

    loser = activity.make(name="loser", success=S.Number, execute=fx.sync(execute))
    storage = yield from W.make_shared_storage()

    def save_reply(reply: Any) -> fx.Effect[None, Any]:
        if reply.rpc.tag == "activity" and not saving_reply.is_open():
            assert isinstance(reply.reply.exit, fx.Success)
            assert isinstance(reply.reply.exit.value, Suspended)
            return (
                saving_reply.open()
                .and_then(release_reply.wait())
                .and_then(storage.save_reply(reply))
            )
        return storage.save_reply(reply)

    def save_request(request: Any) -> fx.Effect[Any, Any]:
        def tap(_: Any) -> fx.Effect[Any]:
            if request.rpc.tag != "activity":
                return fx.void
            # Bound a broken reset/resend loop so this regression fails instead
            # of exhausting memory.
            activity_requests[0] += 1
            assert activity_requests[0] <= 20, "activity reset/resend must not livelock"
            return registration_requested.open()

        return storage.save_request(request).tap(tap)

    storage_layer = W.storage_layer_of(
        W.override_storage(storage, save_reply=save_reply, save_request=save_request)
    )
    execution_id = yield from wf.execution_id({})
    request_id = yield from fx.gen(lambda: W.send_unregistered_activity(wf.tag, execution_id)).pipe(
        fx.provide(
            wf.to_layer(lambda _, __: loser).pipe(
                fx.layer.provide_merge(
                    W.make_test_workflow_engine(
                        storage_layer=W.unanswered_activity_storage(storage)
                    )
                )
            )
        )
    )
    assert (yield from storage.replies_for_unfiltered([request_id])) == []

    @fx.gen
    def run():
        yield from wf.execute({}, discard=True)
        yield from (yield from Sharding()).poll_storage
        for _ in range(200):
            if saving_reply.is_open():
                break
            yield from testing.adjust("1 millis")
        assert saving_reply.is_open()
        assert (yield from storage.replies_for_unfiltered([request_id])) == []
        assert executions[0] == 0
        yield from register.open()
        # The replay has registered and requested the same activity before
        # the early reply commits.
        for _ in range(200):
            if registration_requested.is_open():
                break
            yield from testing.adjust("1 millis")
        assert registration_requested.is_open()
        assert (yield from storage.replies_for_unfiltered([request_id])) == []
        assert executions[0] == 0
        yield from release_reply.open()
        assert (yield from poll_until(wf, execution_id, Complete)) == Complete(Exit.succeed(1))
        assert executions[0] == 1
        # Registration must reset the stored Suspended reply, not allocate a new attempt.
        assert (yield from W.activity_reply(storage, request_id)) == Exit.succeed(
            Complete(Exit.succeed(1))
        )

    yield from run.pipe(
        fx.provide(
            wf.to_layer(lambda _, __: register.wait().and_then(loser)).pipe(
                fx.layer.provide_merge(W.make_test_workflow_engine(storage_layer=storage_layer))
            )
        )
    )


def test_engines_sharing_a_storage_never_reuse_a_request_id(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The flake behind the title above, 1 run in 1,024: a runner sends under its random machine
    id until it registers, the next engine's memory runner storage hands out id 0, and at one
    millisecond of the TestClock the second request repeats the first's id, so storage takes it
    as a duplicate and every fiber waits. Effect hangs the same way with ``Math.random`` at 0."""
    monkeypatch.setattr("random.randrange", lambda _: 0)
    test_retries_an_early_activity_registered_while_its_suspended_reply_is_still_being_persisted()


@testing.effect
def test_does_not_replay_for_an_unawaited_deferred_checkpoint():
    """does not replay for an unawaited deferred checkpoint"""
    checkpoint = durable_deferred.make("UnawaitedCheckpoint/Checkpoint")
    gate = durable_deferred.make("UnawaitedCheckpoint/Gate", success=S.String)
    wf = workflow.make(
        "UnawaitedCheckpoint", payload=W.EMPTY, success=S.String, idempotency_key=lambda _: "one"
    )
    activations = [0]

    def handler(_: Any, execution_id: str):
        @fx.gen
        def body():
            activations[0] += 1
            engine = yield from WorkflowEngine()
            if (yield from engine.deferred_result(checkpoint)) is None:
                yield from checkpoint.succeed(
                    token=checkpoint.token_from_execution_id(
                        workflow=wf, execution_id=execution_id
                    ),
                    value=None,
                )
            return (yield from gate.wait())

        return body

    context = (
        yield from wf.to_layer(handler)
        .pipe(fx.layer.provide_merge(W.make_test_workflow_engine()))
        .build()
    )

    @fx.gen
    def run():
        execution_id = yield from wf.execute({}, discard=True)
        yield from poll_until(wf, execution_id, Suspended)
        before_release = activations[0]
        yield from gate.succeed(
            token=gate.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value="done",
        )
        assert (yield from poll_until(wf, execution_id, Complete)) == Complete(Exit.succeed("done"))
        assert (before_release, activations[0]) == (1, 2)

    yield from run.pipe(fx.provide(context))


@testing.effect(timeout="20 seconds")
def test_advances_a_durable_race_continuation_while_a_sibling_is_parked():
    """advances a durable race continuation while a sibling is parked"""
    yield from W.expect_continues_beside_parked_sibling(
        "ParkedSiblingRace",
        durable_deferred.race_all(
            name="race",
            success=S.String,
            error=S.Never,
            effects=[
                workflow.wrap_activity_result(fx.sleep("1 second").as_("timer"), lambda _: False),
                durable_deferred.make("ParkedSiblingRace/Cancel").wait().as_("cancel"),
            ],
        ),
    )


@testing.effect(timeout="20 seconds")
def test_advances_a_durable_deferred_into_continuation_while_a_sibling_is_parked():
    """advances a DurableDeferred.into continuation while a sibling is parked"""
    # Not an activity: ``into`` itself keeps the run active until the exit is recorded.
    result = durable_deferred.make("ParkedSiblingInto/Result", success=S.String)
    yield from W.expect_continues_beside_parked_sibling(
        "ParkedSiblingInto", result.into(fx.sleep("1 second").as_("timer"))
    )


@testing.effect(timeout="20 seconds")
def test_lets_an_active_sibling_finish_before_a_durable_deferred_into_body_parks_the_run():
    """lets an active sibling finish before a DurableDeferred.into body parks the run"""
    gate = durable_deferred.make("ActiveSiblingInto/Gate", success=S.String)
    result = durable_deferred.make("ActiveSiblingInto/Result", success=S.String)
    wf = workflow.make(
        "ActiveSiblingInto", payload=W.EMPTY, success=S.String, idempotency_key=lambda _: "one"
    )
    next_step_runs: list[str] = []

    def handler(_: Any, __: str):
        return fx.all(
            workflow.wrap_activity_result(fx.sleep("100 millis"), lambda _: False).and_then(
                W.next_step_activity(next_step_runs, "sibling")
            ),
            result.into(gate.wait()),
            concurrency="unbounded",
        ).map(lambda pair: f"{pair[0]}:{pair[1]}")

    context = (
        yield from wf.to_layer(handler)
        .pipe(fx.layer.provide_merge(W.make_test_workflow_engine()))
        .build()
    )

    @fx.gen
    def run():
        execution_id = yield from wf.execute({}, discard=True)
        # The parked body must not suspend the run while the sibling is counted.
        yield from poll_until(wf, execution_id, Suspended)
        assert next_step_runs == ["sibling"]
        yield from gate.succeed(
            token=gate.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value="gate",
        )
        assert (yield from poll_until(wf, execution_id, Complete)) == Complete(
            Exit.succeed("sibling:next:gate")
        )
        assert next_step_runs == ["sibling"]

    yield from run.pipe(fx.provide(context))


@testing.effect(timeout="20 seconds")
def test_retries_a_deferred_wake_after_a_transient_run_reset_failure():
    """retries a deferred wake after a transient run reset failure"""
    gate = durable_deferred.make("ResetRetry/Gate", success=S.String)
    wf = workflow.make(
        "ResetRetry", payload=W.EMPTY, success=S.String, idempotency_key=lambda _: "one"
    )
    storage, driver = yield from W.make_shared_memory()
    run_request_id: list[str | None] = [None]
    reset_attempts = [0]

    def clear_replies(request_id: Any, **options: Any) -> fx.Effect[None, Any]:
        if str(request_id) != run_request_id[0]:
            return storage.clear_replies(request_id, **options)
        reset_attempts[0] += 1
        if reset_attempts[0] == 1:
            return fx.fail(PersistenceError(cause=RuntimeError("transient reset failure")))
        return storage.clear_replies(request_id, **options)

    storage_layer = W.storage_layer_of(W.override_storage(storage, clear_replies=clear_replies))
    context = (
        yield from wf.to_layer(lambda _, __: gate.wait())
        .pipe(fx.layer.provide_merge(W.make_test_workflow_engine(storage_layer=storage_layer)))
        .build()
    )

    @fx.gen
    def run():
        execution_id = yield from wf.execute({}, discard=True)
        yield from poll_until(wf, execution_id, Suspended)
        found = next(
            m for m in driver.encoded.journal if m["_tag"] == "Request" and m["tag"] == "run"
        )
        run_request_id[0] = found["requestId"]
        completion = yield from gate.succeed(
            token=gate.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value="signal",
        ).fork(start_immediately=True)
        yield from advance_until(
            lambda: reset_attempts[0] >= 2, "deferred wake must retry the failed reset", 0.2, 20
        )
        yield from completion.join()
        assert (yield from wf.poll(execution_id)) == Complete(Exit.succeed("signal"))

    yield from run.pipe(fx.provide(context))


@testing.effect(timeout="30 seconds")
def test_keeps_a_completed_reply_when_an_older_concurrent_wake_resets_it():
    """keeps a completed reply when an older concurrent wake resets it"""
    first_reset = yield from fx.Latch.make()
    allow_stale_reset = yield from fx.Latch.make()
    stale_reset_finished = yield from fx.Latch.make()
    allow_poll = yield from fx.Latch.make()
    first = durable_deferred.make("ConcurrentResume/First", success=S.String)
    second = durable_deferred.make("ConcurrentResume/Second", success=S.String)
    wf = workflow.make(
        "ConcurrentResume", payload=W.EMPTY, success=S.String, idempotency_key=lambda _: "one"
    )
    storage, driver = yield from W.make_shared_memory()
    run_request_id: list[Any] = [None]
    run_resets = [0]

    def clear_replies(request_id: Any, **options: Any) -> fx.Effect[None, Any]:
        if request_id == run_request_id[0] and options.get("expected_reply_id") is not None:
            run_resets[0] += 1
            if run_resets[0] == 1:
                return (
                    first_reset.open()
                    .and_then(allow_stale_reset.wait())
                    .and_then(storage.clear_replies(request_id, **options))
                    .and_then(stale_reset_finished.open())
                    # Do not let the stale wake poll storage and replay before
                    # inspecting the reply.
                    .and_then(allow_poll.wait())
                )
        return storage.clear_replies(request_id, **options)

    storage_layer = W.storage_layer_of(W.override_storage(storage, clear_replies=clear_replies))

    def handler(_: Any, __: str):
        return fx.all(first.wait(), second.wait(), concurrency="unbounded").map(
            lambda pair: f"{pair[0]}/{pair[1]}"
        )

    context = (
        yield from wf.to_layer(handler)
        .pipe(fx.layer.provide_merge(W.make_test_workflow_engine(storage_layer=storage_layer)))
        .build()
    )
    yield from fx.add_finalizer(
        lambda _: fx.all(allow_stale_reset.open(), allow_poll.open(), discard=True)
    )

    @fx.gen
    def run():
        execution_id = yield from wf.execute({}, discard=True)
        yield from poll_until(wf, execution_id, Suspended)
        found = next(
            m for m in driver.encoded.journal if m["_tag"] == "Request" and m["tag"] == "run"
        )
        run_request_id[0] = Snowflake(int(found["requestId"]))

        def complete(deferred: Any, value: str) -> fx.Effect[None, Any, Any]:
            return deferred.succeed(
                token=deferred.token_from_execution_id(workflow=wf, execution_id=execution_id),
                value=value,
            )

        first_fiber = yield from complete(first, "first").fork(start_immediately=True)
        yield from advance_until(first_reset.is_open, "first wake must reach reset")
        yield from complete(second, "second")
        assert (yield from poll_until(wf, execution_id, Complete)) == Complete(
            Exit.succeed("first/second")
        )
        yield from allow_stale_reset.open()
        yield from advance_until(stale_reset_finished.is_open, "stale reset must finish")
        assert (yield from wf.poll(execution_id)) == Complete(Exit.succeed("first/second"))
        yield from allow_poll.open()
        yield from first_fiber.join()

    yield from run.pipe(fx.provide(context))


@testing.effect
def test_keeps_a_newer_activity_reply_when_a_stale_suspended_reply_resets_the_attempt():
    """keeps a newer activity reply when a stale Suspended reply resets the attempt"""
    wf = workflow.make(
        "StaleActivityReset", payload=W.EMPTY, success=S.Number, idempotency_key=lambda _: "one"
    )
    register = yield from fx.Latch.make()
    stale_reset = yield from fx.Latch.make()
    allow_stale_reset = yield from fx.Latch.make()
    executions = [0]

    def execute() -> int:
        executions[0] += 1
        return executions[0]

    loser = activity.make(name="loser", success=S.Number, execute=fx.sync(execute))
    storage = yield from W.make_shared_storage()
    activity_request_id: list[Any] = [None]
    activity_resets = [0]

    # Freeze the first reset of the attempt, standing in for a stale runner
    # that read the Suspended reply before the new owner replaced it.
    def clear_replies(request_id: Any, **options: Any) -> fx.Effect[None, Any]:
        if request_id == activity_request_id[0]:
            activity_resets[0] += 1
            if activity_resets[0] == 1:
                return (
                    stale_reset.open()
                    .and_then(allow_stale_reset.wait())
                    .and_then(storage.clear_replies(request_id, **options))
                )
        return storage.clear_replies(request_id, **options)

    storage_layer = W.storage_layer_of(W.override_storage(storage, clear_replies=clear_replies))
    execution_id = yield from wf.execution_id({})
    request_id = yield from fx.gen(lambda: W.send_unregistered_activity(wf.tag, execution_id)).pipe(
        fx.provide(
            wf.to_layer(lambda _, __: loser).pipe(
                fx.layer.provide_merge(
                    W.make_test_workflow_engine(
                        storage_layer=W.unanswered_activity_storage(storage)
                    )
                )
            )
        )
    )
    activity_request_id[0] = request_id
    yield from fx.add_finalizer(lambda _: allow_stale_reset.open())

    @fx.gen
    def run():
        sharding = yield from Sharding()
        yield from wf.execute({}, discard=True)
        yield from sharding.poll_storage
        assert (yield from W.activity_reply(storage, request_id)) == Exit.succeed(Suspended())
        yield from register.open()
        yield from advance_until(stale_reset.is_open, "the replay must reset the Suspended attempt")
        # The new owner resets the same attempt and stores its result.
        assert (yield from sharding.reset(request_id)) is True
        yield from poll_storage_until(lambda: executions[0] == 1, "the owner must run the activity")
        assert (yield from W.activity_reply(storage, request_id)) == Exit.succeed(
            Complete(Exit.succeed(1))
        )
        yield from allow_stale_reset.open()
        assert (yield from poll_until(wf, execution_id, Complete)) == Complete(Exit.succeed(1))
        assert executions[0] == 1
        assert (yield from W.activity_reply(storage, request_id)) == Exit.succeed(
            Complete(Exit.succeed(1))
        )

    yield from run.pipe(
        fx.provide(
            wf.to_layer(lambda _, __: register.wait().and_then(loser)).pipe(
                fx.layer.provide_merge(W.make_test_workflow_engine(storage_layer=storage_layer))
            )
        )
    )


@pytest.mark.parametrize("mailbox_capacity", [2, 3])
@testing.effect(timeout="20 seconds")
def test_admits_a_required_completion_after_an_unrelated_completion(mailbox_capacity: int):
    """admits a required completion after an unrelated completion with mailbox capacity 2 | 3"""
    unrelated_read = yield from fx.Latch.make()
    required = durable_deferred.make("MailboxProgress/Required", success=S.String)
    unrelated = durable_deferred.make("MailboxProgress/Unrelated", success=S.String)
    wf = workflow.make(
        "MailboxProgress", payload=W.EMPTY, success=S.String, idempotency_key=lambda _: "one"
    )
    instance: list[Any] = [None]
    run_request_id: list[Any] = [None]
    storage, driver = yield from W.make_shared_memory()

    def replies_for_unfiltered(request_ids: Any) -> fx.Effect[Any, Any]:
        ids = list(request_ids)
        return storage.replies_for_unfiltered(ids).tap(
            lambda _: (
                unrelated_read.open()
                if run_request_id[0] is not None and run_request_id[0] in ids
                else fx.void
            )
        )

    storage_layer = W.storage_layer_of(
        W.override_storage(storage, replies_for_unfiltered=replies_for_unfiltered)
    )

    def handler(_: Any, __: str):
        @fx.gen
        def body():
            instance[0] = yield from WorkflowInstance()
            return (
                yield from durable_deferred.race_all(
                    name="mailbox-progress",
                    success=S.String,
                    error=S.Never,
                    # Keep the run active without allocating an activity RPC/mailbox slot.
                    effects=[required.wait(), fx.never],
                )
            )

        return body

    context = (
        yield from wf.to_layer(handler)
        .pipe(
            fx.layer.provide_merge(
                W.make_test_workflow_engine(
                    storage_layer=storage_layer,
                    config_overrides={"entity_mailbox_capacity": mailbox_capacity},
                )
            )
        )
        .build()
    )

    @fx.gen
    def run():
        sharding = yield from Sharding()
        execution_id = yield from wf.execute({}, discard=True)
        yield from advance_until(
            lambda: instance[0] is not None and required.name in instance[0].awaited_deferreds,
            "run must await the required deferred",
        )
        assert unrelated.name not in instance[0].awaited_deferreds
        found = next(
            m for m in driver.encoded.journal if m["_tag"] == "Request" and m["tag"] == "run"
        )
        run_request_id[0] = Snowflake(int(found["requestId"]))
        yield from unrelated.succeed(
            token=unrelated.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value="unrelated",
        )
        # Both implementations read the active run before replying or parking.
        # Wait for that read before admitting the completion needed for progress.
        yield from advance_until(
            unrelated_read.is_open, "unrelated completion must inspect the active run"
        )
        yield from required.succeed(
            token=required.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value="signal",
        )
        result = yield from wf.poll(execution_id)
        for _ in range(100):
            if isinstance(result, Complete):
                break
            yield from testing.adjust("100 millis")
            yield from sharding.poll_storage
            result = yield from wf.poll(execution_id)
        pending = [
            cast("Any", e.envelope)["payload"]["name"]
            for e in driver.encoded.requests.values()
            if e.envelope["_tag"] == "Request" and e.envelope["tag"] == "deferred" and not e.replies
        ]
        assert result == Complete(Exit.succeed("signal")), (
            f"required completion must progress; pending deferreds: {pending}"
        )

    yield from run.pipe(fx.provide(context))


@testing.effect(timeout="30 seconds")
def test_retains_a_handover_completion_before_its_deferred_reply_is_persisted():
    """retains a handover completion before its deferred reply is persisted"""
    gate = durable_deferred.make("DeferredHandover/Gate", success=S.String)
    wf = workflow.make(
        "DeferredHandover", payload=W.EMPTY, success=S.String, idempotency_key=lambda _: "one"
    )
    storage = yield from W.make_shared_storage()

    def save_reply(reply: Any) -> fx.Effect[None, Any]:
        if reply.rpc.tag == "deferred":
            return fx.sleep("100 millis").and_then(storage.save_reply(reply))
        return storage.save_reply(reply)

    layer = wf.to_layer(lambda _, __: gate.wait()).pipe(
        fx.layer.provide_merge(
            W.make_test_workflow_engine(
                storage_layer=W.storage_layer_of(W.override_storage(storage, save_reply=save_reply))
            )
        )
    )

    # Each owner has a fresh engine over the same durable storage.
    def with_owner(body: fx.Effect[Any, Any, Any]) -> fx.Effect[Any, Any, Any]:
        return fx.scoped(layer.build().flat_map(lambda ctx: body.pipe(fx.provide(ctx))))

    @fx.gen
    def first():
        execution_id = yield from wf.execute({}, discard=True)
        yield from poll_until(wf, execution_id, Suspended)
        return execution_id

    execution_id = yield from with_owner(first)

    @fx.gen
    def second():
        yield from gate.succeed(
            token=gate.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value="signal",
        )
        # Complete before the 5-second storage retry can hide a lost wake-up.
        result = yield from poll_until(wf, execution_id, Complete)
        yield from testing.adjust("1 second")
        return result

    result = yield from with_owner(second)
    assert result == Complete(Exit.succeed("signal"))


@testing.effect
def test_wakes_a_suspended_caller_when_its_workflow_completes():
    """wakes a suspended caller when its workflow completes"""
    retrying = yield from fx.Latch.make()
    gate = durable_deferred.make("CompletionWake/Gate", success=S.String)
    wf = workflow.make(
        "CompletionWake",
        payload=W.EMPTY,
        success=S.String,
        idempotency_key=lambda _: "one",
        # The retry stays the fallback, but is too slow to deliver within the test.
        suspended_retry_schedule=schedule.spaced("1 hour").tap(lambda _: retrying.open()),
    )
    context = (
        yield from wf.to_layer(lambda _, __: gate.wait())
        .pipe(fx.layer.provide_merge(W.make_test_workflow_engine()))
        .build()
    )

    @fx.gen
    def run():
        execution_id = yield from wf.execution_id({})
        fiber = yield from wf.execute({}).fork(start_immediately=True)
        yield from poll_until(wf, execution_id, Suspended)
        yield from advance_until(retrying.is_open, "caller must wait on its retry schedule")
        yield from gate.succeed(
            token=gate.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value="done",
        )
        yield from poll_until(wf, execution_id, Complete)
        yield from advance_until(
            lambda: fiber.poll_unsafe() is not None, "completion must wake the caller", 0.001, 1000
        )
        assert (yield from fiber.join()) == "done"

    yield from run.pipe(fx.provide(context))


@testing.effect
def test_delivers_a_completion_through_the_retry_schedule_when_the_wake_is_lost():
    """delivers a completion through the retry schedule when the wake is lost"""
    drop_wakes = [False]
    handlers = [0]
    gate = durable_deferred.make("LostWake/Gate", success=S.String)

    def drop() -> None:
        drop_wakes[0] = True

    wf = workflow.make(
        "LostWake",
        payload=W.EMPTY,
        success=S.String,
        idempotency_key=lambda _: "one",
        # Once the caller first waits, no reply notification reaches it.
        suspended_retry_schedule=schedule.spaced("10 seconds").tap(lambda _: fx.sync(drop)),
    )
    storage = yield from W.make_shared_storage()

    def register_reply_handler(message: Any) -> fx.Effect[None, Any]:
        def start() -> fx.Effect[None, Any]:
            handlers[0] += 1
            return fx.never if drop_wakes[0] else storage.register_reply_handler(message)

        def release() -> None:
            handlers[0] -= 1

        return fx.suspend(start).ensuring(fx.sync(release))

    storage_layer = W.storage_layer_of(
        W.override_storage(storage, register_reply_handler=register_reply_handler)
    )
    context = (
        yield from wf.to_layer(lambda _, __: gate.wait())
        .pipe(fx.layer.provide_merge(W.make_test_workflow_engine(storage_layer=storage_layer)))
        .build()
    )

    @fx.gen
    def run():
        execution_id = yield from wf.execution_id({})
        fiber = yield from wf.execute({}).fork(start_immediately=True)
        yield from poll_until(wf, execution_id, Suspended)
        yield from advance_until(lambda: drop_wakes[0], "caller must wait on its retry schedule")
        yield from gate.succeed(
            token=gate.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value="done",
        )
        yield from poll_until(wf, execution_id, Complete)
        assert fiber.poll_unsafe() is None, "a lost wake must leave the caller on its schedule"
        yield from advance_until(
            lambda: fiber.poll_unsafe() is not None,
            "the schedule must deliver the completion",
            1,
        )
        assert (yield from fiber.join()) == "done"
        assert handlers[0] == 0, "the caller must release its reply handlers"

    yield from run.pipe(fx.provide(context))


class _DelegatingSharding:
    """Effect's ``{ ...sharding, registerEntity }``."""

    def __init__(self, inner: Any, register_entity: Any) -> None:
        self._inner = inner
        self.register_entity = register_entity

    def __getattr__(self, name: str) -> Any:
        return getattr(self._inner, name)


@pytest.mark.parametrize("lifecycle", ["defect rebuild", "overlapping activations"])
@testing.effect(timeout="30 seconds")
def test_completes_before_deferred_persistence_across(lifecycle: str):  # noqa: PLR0915
    """completes before deferred persistence across defect rebuild | overlapping activations"""
    saving = yield from fx.Latch.make()
    allow_save = yield from fx.Latch.make()
    rebuilt = yield from fx.Latch.make()
    allow_run = yield from fx.Latch.make()
    allow_defect = yield from fx.Latch.make()
    closing = yield from fx.Latch.make()
    allow_close = yield from fx.Latch.make()
    closed = yield from fx.Latch.make()
    allow_redelivery = yield from fx.Latch.make()
    state = {"persisted": False, "builds": 0, "first_build_runs": 0, "deliveries": 0}
    activations: list[Any] = []
    gate = durable_deferred.make("BehaviouralLifecycle/Gate", success=S.String)
    wf = workflow.make(
        "BehaviouralLifecycle", payload=W.EMPTY, success=S.String, idempotency_key=lambda _: "one"
    )

    def wrap(inner: Any) -> Any:
        def register_entity(entity: Any, handlers: Any, options: Any) -> Any:
            @fx.gen
            def build():
                if entity.type != f"Workflow/{wf.tag}":
                    return (yield from handlers)
                state["builds"] += 1
                build_number = state["builds"]
                activation_option = yield from fx.service_option(CurrentActivationScope)
                assert activation_option is not None, (
                    "the entity manager must provide its activation"
                )
                activation = activation_option.value
                activations.append(activation)
                assert activation is not (yield from Scope()), (
                    "handler and activation scopes must differ"
                )
                # Registered before the production handlers, this marks the
                # end of activation cleanup.
                if build_number == 1:
                    yield from activation.add_finalizer(lambda _: closed.open())
                built = yield from handlers
                if build_number == 1 and lifecycle == "overlapping activations":
                    # Pause the retiring activation before its production
                    # cleanup. Its replacement records the completion first,
                    # then the old activation finishes closing.
                    yield from activation.add_finalizer(
                        lambda _: closing.open().and_then(allow_close.wait())
                    )
                if build_number == 2:
                    yield from rebuilt.open()
                run = built.by_tag["run"]
                deferred = built.by_tag["deferred"]

                def wrapped_run(request: Any) -> Any:
                    def go() -> Any:
                        if build_number == 1 and lifecycle == "defect rebuild":
                            state["first_build_runs"] += 1
                            if state["first_build_runs"] == 2:
                                # Defect outside Workflow.intoResult to
                                # rebuild the real RPC server.
                                return (
                                    saving.wait()
                                    .and_then(allow_defect.wait())
                                    .and_then(fx.die(RuntimeError("injected entity defect")))
                                )
                        if build_number == 2:
                            return allow_run.wait().and_then(fx.suspend(lambda: run(request)))
                        return run(request)

                    return fx.suspend(go)

                def wrapped_deferred(request: Any) -> Any:
                    def go() -> Any:
                        # A replayed completion must not repair a cache loss
                        # before the assertion.
                        state["deliveries"] += 1
                        if state["deliveries"] > 1:
                            return allow_redelivery.wait().and_then(
                                fx.suspend(lambda: deferred(request))
                            )
                        return deferred(request)

                    return fx.suspend(go)

                return EntityHandlers(
                    built.entity,
                    {**built.by_tag, "run": wrapped_run, "deferred": wrapped_deferred},
                )

            return inner.register_entity(entity, build, options)

        return _DelegatingSharding(inner, register_entity)

    sharding_layer = fx.layer.effect(Sharding, Sharding().map(wrap)).pipe(
        fx.layer.provide(sharding_layer_of)
    )

    def wrap_storage(storage: Any) -> Any:
        def save_reply(reply: Any) -> fx.Effect[None, Any]:
            if reply.rpc.tag != "deferred":
                return storage.save_reply(reply)

            def mark(_: Any) -> fx.Effect[None]:
                return fx.sync(lambda: state.__setitem__("persisted", True))

            return (
                saving.open()
                .and_then(allow_save.wait())
                .interruptible()
                .and_then(storage.save_reply(reply))
                .tap(mark)
            )

        return W.override_storage(storage, save_reply=save_reply)

    storage_layer = fx.layer.effect(MessageStorage, MessageStorage().map(wrap_storage)).pipe(
        fx.layer.provide(message_storage.layer_memory)
    )
    context = (
        yield from wf.to_layer(lambda _, __: gate.wait())
        .pipe(
            fx.layer.provide_merge(
                W.make_test_workflow_engine(
                    sharding_layer=sharding_layer, storage_layer=storage_layer
                )
            )
        )
        .build()
    )
    yield from fx.add_finalizer(
        lambda _: fx.all(
            allow_save.open(),
            allow_run.open(),
            allow_defect.open(),
            allow_close.open(),
            allow_redelivery.open(),
            discard=True,
        )
    )

    @fx.gen
    def run():
        execution_id = yield from wf.execute({}, discard=True)
        yield from poll_until(wf, execution_id, Suspended)
        if lifecycle == "overlapping activations":
            yield from advance_until(closing.is_open, "old activation must start closing", 5, 12)
            assert state["builds"] == 1
        yield from gate.succeed(
            token=gate.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value="signal",
        )
        yield from advance_until(saving.is_open, "deferred persistence must start")
        yield from allow_defect.open()
        yield from advance_until(rebuilt.is_open, "replacement handlers must be built")
        assert state["builds"] == 2
        if lifecycle == "defect rebuild":
            assert activations[0] is activations[1], "rebuild must retain activation identity"
            assert not closed.is_open(), "a handler rebuild must not close its activation"
        else:
            assert activations[0] is not activations[1], "replacement must have its own activation"
            yield from allow_close.open()
            yield from advance_until(closed.is_open, "old activation cleanup must finish")
        yield from allow_run.open()
        result = yield from poll_until(wf, execution_id, Complete)
        assert result == Complete(Exit.succeed("signal"))
        assert not allow_save.is_open(), "workflow must complete while persistence remains gated"
        assert not state["persisted"], "no deferred reply may be durable before workflow completion"
        assert not allow_redelivery.is_open(), "redelivery must not repair a lost completion"

    yield from run.pipe(fx.provide(context))


# --- transient save failures -----------------------------------------------------------------


def _transient_save(
    storage: Any, saves: Any, ack_lost: bool, on_save: Any = None
) -> tuple[fx.Layer[MessageStorage], dict[str, Any]]:
    """Storage whose first save of a matching request fails once with a
    ``PersistenceError``, after storing it when ``ack_lost``."""
    state: dict[str, Any] = {"failures": 0, "inserts": 0, "payloads": []}

    def save_request(envelope: Any) -> fx.Effect[Any, Any]:
        if not saves(envelope):
            return storage.save_request(envelope)
        state["payloads"].append(envelope.envelope.payload)

        def counted(result: Any) -> None:
            if isinstance(result, message_storage.SaveSuccess):
                state["inserts"] += 1

        save = storage.save_request(envelope).tap(lambda r: fx.sync(lambda: counted(r)))
        if state["failures"] > 0:
            return save
        state["failures"] += 1
        failure = fx.fail(PersistenceError(cause=RuntimeError("Connection closed")))
        return save.and_then(failure) if ack_lost else failure

    return W.storage_layer_of(W.override_storage(storage, save_request=save_request)), state


@pytest.mark.parametrize("ack_lost", [False, True])
@testing.effect
def test_runs_an_activity_once_after_a_transient_failure_saving_its_request(ack_lost: bool):
    """runs an activity once after a transient failure ${ackLost ? "acknowledging" : "saving"} its request"""  # noqa: E501
    wf = workflow.make(
        "ActivitySaveRetry", payload=W.EMPTY, success=S.Number, idempotency_key=lambda _: "one"
    )
    storage = yield from W.make_shared_storage()
    storage_layer, state = _transient_save(
        storage, lambda envelope: envelope.envelope.tag == "activity", ack_lost
    )
    runs = [0]

    def step() -> int:
        runs[0] += 1
        return 42

    @fx.gen
    def body():
        execution_id = yield from wf.execute({}, discard=True)
        result = yield from poll_until(wf, execution_id, Complete)
        assert result == Complete(Exit.succeed(42))
        assert runs[0] == 1
        assert state["failures"] == 1

    yield from body.pipe(
        fx.provide(
            wf.to_layer(
                lambda _, __: activity.make(name="Step", success=S.Number, execute=fx.sync(step))
            ).pipe(fx.layer.provide_merge(W.make_test_workflow_engine(storage_layer=storage_layer)))
        )
    )


_RetrySignal = durable_deferred.make("RetrySignal")


def _saves_deferred(envelope: Any) -> bool:
    return envelope.envelope.tag == "deferred"


def _durable_save_cases() -> list[Any]:
    return [
        pytest.param(
            lambda e: e.envelope.address.entity_type == "Workflow/-/DurableClock",
            lambda: durable_clock.sleep(
                name="Wait", duration="1 second", in_memory_threshold=0
            ).as_(42),
            None,
            id="a durable clock",
        ),
        pytest.param(
            _saves_deferred,
            lambda: durable_deferred.race_all(
                name="Race",
                success=S.Number,
                error=S.Never,
                effects=[fx.succeed(42.0), fx.never],
            ),
            None,
            id="a durable race winner",
        ),
        pytest.param(
            _saves_deferred,
            lambda: _RetrySignal.wait().as_(42),
            "registered",
            id="a token completion",
        ),
        pytest.param(
            _saves_deferred,
            lambda: _RetrySignal.wait().as_(42),
            "unregistered",
            id="a token completion from a runner without the workflow",
        ),
    ]


@pytest.mark.parametrize("ack_lost", [False, True])
@pytest.mark.parametrize(("saves", "make_body", "external"), _durable_save_cases())
@testing.effect
def test_completes_after_a_transient_failure_saving_it(
    saves: Any, make_body: Any, external: str | None, ack_lost: bool
):
    """completes ${name} after a transient failure ${ackLost ? "acknowledging" : "saving"} it"""
    wf = workflow.make(
        "DurableSaveRetry", payload=W.EMPTY, success=S.Number, idempotency_key=lambda _: "one"
    )
    storage = yield from W.make_shared_storage()
    storage_layer, state = _transient_save(storage, saves, ack_lost)

    @fx.gen
    def body():
        engine = yield from WorkflowEngine()
        execution_id = yield from wf.execution_id({})
        complete = _RetrySignal.done(
            token=_RetrySignal.token_from_execution_id(workflow=wf, execution_id=execution_id),
            exit=Exit.succeed(None),
        ).fork(start_immediately=True)
        caller = None
        if external == "unregistered":
            caller = yield from complete
        yield from engine.register(wf, lambda _, __: make_body())
        yield from wf.execute({}, discard=True)
        if external == "registered":
            yield from poll_until(wf, execution_id, Suspended)
            caller = yield from complete
        result = yield from poll_until(wf, execution_id, Complete)
        assert result == Complete(Exit.succeed(42))
        if caller is not None:
            # A stored completion can wake the workflow before the caller's retry runs.
            yield from testing.adjust("1 minute")
            yield from caller.join()
        assert state["failures"] == 1
        assert state["inserts"] == 1
        # A retry resends the original payload, including a clock's deadline.
        assert state["payloads"][1] == state["payloads"][0]

    yield from body.pipe(fx.provide(W.make_test_workflow_engine(storage_layer=storage_layer)))


# --- races ---------------------------------------------------------------------------------


def _with_test_layer(f: Any) -> Any:
    """Run the test body with Effect's ``TestWorkflowLayer``."""

    @functools.wraps(f)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        return fx.gen(lambda: f(*args, **kwargs)).pipe(fx.provide(test_workflow_layer))

    return wrapper


def _token(deferred: Any, wf: Any, execution_id: str) -> str:
    return deferred.token_from_execution_id(workflow=wf, execution_id=execution_id)


def _poll_and_adjust_until_done(fiber: Any, step: float, message: str) -> Any:
    sharding = yield from Sharding()
    for _ in range(2000):
        if fiber.poll_unsafe() is not None:
            break
        yield from sharding.poll_storage
        yield from testing.adjust(Seconds(step))
    assert fiber.poll_unsafe() is not None, message


@testing.effect
@_with_test_layer
def test_activity_race_all_returns_the_first_activity_and_interrupts_losers():
    """Activity.raceAll returns the first activity and interrupts losers"""
    flags = yield from Flags()
    yield from testing.adjust("1 millis")
    fiber = yield from R.RaceWorkflow.execute({"id": "race-1"}).fork(start_immediately=True)
    # Activity timers may be registered after the caller's first clock advance.
    yield from poll_until(
        R.RaceWorkflow, (yield from R.RaceWorkflow.execution_id({"id": "race-1"})), Complete
    )
    assert (yield from fiber.join()) == "Activity3"
    assert flags.get("interrupt1")
    assert flags.get("interrupt2")
    assert not flags.get("interrupt3")


@testing.effect
@_with_test_layer
def test_activity_race_all_ignores_a_failure_when_another_activity_can_succeed():
    """Activity.raceAll ignores a failure when another activity can succeed"""
    fiber = yield from R.FailureRaceWorkflow.execute({"id": "failure-race"}).fork(
        start_immediately=True
    )
    yield from _poll_and_adjust_until_done(
        fiber, 1, "failure race must complete when another activity can succeed"
    )
    yield from poll_until(
        R.FailureRaceWorkflow,
        (yield from R.FailureRaceWorkflow.execution_id({"id": "failure-race"})),
        Complete,
    )
    assert (yield from fiber.join()) == "slow"


@testing.effect
@_with_test_layer
def test_activity_race_all_replays_the_first_durable_activity():
    """Activity.raceAll replays the first durable activity"""
    flags = yield from Flags()
    sharding = yield from Sharding()
    driver = yield from MemoryDriver()
    yield from testing.adjust("1 millis")
    fiber = yield from R.DurableRaceWorkflow.execute({"id": "race-2"}).fork()
    yield from wait_for_clock(driver, "Activity3")
    yield from testing.adjust("1 second")
    yield from poll_storage_until(
        lambda: isinstance(flags.get("durable-race-token"), str),
        "durable race must reach its continuation",
    )
    token = flags["durable-race-token"]
    assert isinstance(token, str)
    yield from R.DurableRaceGate.done(token=token, exit=Exit.succeed(None))
    yield from sharding.poll_storage
    yield from testing.adjust("5 seconds")
    assert (yield from fiber.join()) == "Activity3"


def _race_with_gate(wf: Any, gate: Any, id_: str, value: str = "signal") -> Any:
    sharding = yield from Sharding()
    execution_id = yield from wf.execution_id({"id": id_})
    fiber = yield from wf.execute({"id": id_}).fork(start_immediately=True)
    yield from testing.adjust("1 millis")
    yield from gate.succeed(token=_token(gate, wf, execution_id), value=value)
    yield from sharding.poll_storage
    yield from testing.adjust("1 second")
    return (yield from fiber.join())


@testing.effect(timeout="20 seconds")
@_with_test_layer
def test_durable_deferred_race_all_lets_a_deferred_win_while_another_branch_is_active():
    """DurableDeferred.raceAll lets a deferred win while another branch is active"""
    assert (yield from _race_with_gate(R.MixedRaceWorkflow, R.MixedRaceGate, "mixed-race")) == (
        "signal"
    )


@testing.effect(timeout="20 seconds")
@_with_test_layer
def test_durable_deferred_race_all_lets_an_active_branch_win_while_the_deferred_stays_pending():
    """DurableDeferred.raceAll lets an active branch win while the deferred stays pending"""
    fiber = yield from R.MixedRaceWorkflow.execute({"id": "mixed-race-activity"}).fork(
        start_immediately=True
    )
    yield from _poll_and_adjust_until_done(
        fiber, 1, "active race branch must complete while the deferred stays pending"
    )
    assert (yield from fiber.join()) == "activity"


@testing.effect(timeout="20 seconds")
@_with_test_layer
def test_durable_deferred_race_all_does_not_replay_the_run_when_a_losing_deferred_completes_late():
    """DurableDeferred.raceAll does not replay the run when a losing deferred completes late"""
    flags = yield from Flags()
    sharding = yield from Sharding()
    wf = R.LosingDeferredWorkflow
    execution_id = yield from wf.execution_id({"id": "losing-deferred"})
    fiber = yield from wf.execute({"id": "losing-deferred"}).fork(start_immediately=True)
    yield from testing.adjust("1 millis")
    yield from testing.adjust("1 second")
    while flags.get("losing-deferred-tail-runs") != 1:
        yield from testing.adjust("1 second")
    yield from R.LosingDeferredGate.succeed(
        token=_token(R.LosingDeferredGate, wf, execution_id), value="signal"
    )
    for _ in range(4):
        yield from sharding.poll_storage
        yield from testing.adjust("10 seconds")
    assert (yield from fiber.join()) == "activity:tail"
    # The race already settled, so the late completion must not preempt the tail.
    assert flags.get("losing-deferred-tail-runs") == 1


@testing.effect(timeout="20 seconds")
@_with_test_layer
def test_durable_deferred_race_all_wakes_the_active_run_by_replaying_it():
    """DurableDeferred.raceAll wakes the active run by replaying it"""
    flags = yield from Flags()
    assert (
        yield from _race_with_gate(R.InPlaceWakeWorkflow, R.InPlaceWakeGate, "in-place-wake")
    ) == "signal"
    # Usually the completion preempts the parked run (2 runs); under load it
    # can land before the branch parks and is read directly (1 run).
    assert flags.get("in-place-wake-runs") in (1, 2)


@testing.effect(timeout="20 seconds")
@_with_test_layer
def test_durable_deferred_race_all_wakes_a_branch_wrapped_in_durable_deferred_into():
    """DurableDeferred.raceAll wakes a branch wrapped in DurableDeferred.into"""
    assert (yield from _race_with_gate(R.IntoWrapWorkflow, R.IntoWrapGate, "into-wrap")) == (
        "signal"
    )


@testing.effect(timeout="20 seconds")
@_with_test_layer
def test_durable_deferred_race_all_does_not_preempt_for_deferreds_awaited_inside_activity_bodies():
    """DurableDeferred.raceAll does not preempt for deferreds awaited inside activity bodies"""
    sharding = yield from Sharding()
    fiber = yield from R.ClockCaptureWorkflow.execute({"id": "clock-capture"}).fork(
        start_immediately=True
    )
    # Only workflow-level awaits preempt; the clock inside the activity does
    # not, so the other branch wins.
    yield from testing.adjust("1 millis")
    yield from testing.adjust("5 seconds")
    yield from sharding.poll_storage
    yield from testing.adjust("1 second")
    yield from testing.adjust("1 minute")
    assert (yield from fiber.join()) == "slow"


@testing.effect(timeout="20 seconds")
@_with_test_layer
def test_durable_deferred_race_all_lets_a_bare_durable_clock_branch_win_while_another_is_active():
    """DurableDeferred.raceAll lets a bare durable clock branch win while another branch is active"""  # noqa: E501
    sharding = yield from Sharding()
    fiber = yield from R.BareClockWorkflow.execute({"id": "bare-clock"}).fork(
        start_immediately=True
    )
    yield from testing.adjust("1 millis")
    for _ in range(8):
        yield from sharding.poll_storage
        yield from testing.adjust("5 seconds")
    assert (yield from fiber.join()) == "clock"


@testing.effect(timeout="20 seconds")
@_with_test_layer
def test_durable_deferred_race_all_runs_a_branchs_transformations_on_a_deferred_wake():
    """DurableDeferred.raceAll runs a branch's transformations on a deferred wake"""
    assert (yield from _race_with_gate(R.MappedGateWorkflow, R.MappedGate, "mapped-gate")) == (
        "signal!"
    )


@testing.effect(timeout="20 seconds")
@_with_test_layer
def test_durable_deferred_race_all_wakes_a_branch_that_ran_an_activity_before_its_await():
    """DurableDeferred.raceAll wakes a branch that ran an activity before its await"""
    sharding = yield from Sharding()
    wf = R.PreGateWorkflow
    execution_id = yield from wf.execution_id({"id": "pre-gate"})
    fiber = yield from wf.execute({"id": "pre-gate"}).fork(start_immediately=True)
    yield from testing.adjust("1 millis")
    yield from testing.adjust("1 millis")
    yield from R.PreGate.succeed(token=_token(R.PreGate, wf, execution_id), value="signal")
    yield from sharding.poll_storage
    yield from testing.adjust("1 second")
    assert (yield from fiber.join()) == "act:signal"


@testing.effect(timeout="20 seconds")
@_with_test_layer
def test_durable_deferred_race_all_re_runs_a_multi_await_branch_once_per_completion():
    """DurableDeferred.raceAll re-runs a multi-await branch once per completion"""
    flags = yield from Flags()
    control = yield from R.TwoStepBranchControl()
    sharding = yield from Sharding()
    wf = R.TwoStepWorkflow
    execution_id = yield from wf.execution_id({"id": "two-step"})
    fiber = yield from wf.execute({"id": "two-step"}).fork(start_immediately=True)
    yield from control.entered.wait()
    yield from R.TwoStepGateA.succeed(token=_token(R.TwoStepGateA, wf, execution_id), value="a")
    yield from sharding.poll_storage
    yield from testing.adjust("1 second")
    yield from control.release.open()
    yield from control.started.wait()
    # The run parks on the second gate after reading the first completion
    # directly or replaying once while the completion is committed.
    assert flags.get("two-step-branch-runs") in (1, 2)
    # A completion stored before the await is read directly, so let the run
    # park on the second gate first.
    yield from testing.adjust("1 second")
    yield from R.TwoStepGateB.succeed(token=_token(R.TwoStepGateB, wf, execution_id), value="b")
    yield from sharding.poll_storage
    yield from testing.adjust("1 second")
    assert (yield from fiber.join()) == "a:b"
    assert flags.get("two-step-branch-runs") in (2, 3)


@testing.effect(timeout="20 seconds")
def test_durable_deferred_resumes_a_discarded_execution_when_completion_precedes_the_commit():
    """DurableDeferred resumes a discarded execution when completion precedes the suspension commit"""  # noqa: E501
    saving_run = yield from fx.Latch.make()
    release_run = yield from fx.Latch.make()
    read_before_commit = yield from fx.Latch.make()
    saved_deferred = yield from fx.Latch.make()
    run_request_id: list[Any] = [None]
    gate = durable_deferred.make("DiscardedSuspension/Gate", success=S.String)
    wf = workflow.make(
        "DiscardedSuspension", payload=W.EMPTY, success=S.String, idempotency_key=lambda _: "one"
    )

    def wrap_storage(storage: Any) -> Any:
        def save_reply(reply: Any) -> fx.Effect[None, Any]:
            if reply.rpc.tag == "run" and not saving_run.is_open():
                run_request_id[0] = reply.reply.request_id
                assert isinstance(reply.reply.exit, fx.Success)
                assert isinstance(reply.reply.exit.value, Suspended)
                return (
                    saving_run.open()
                    .and_then(release_run.wait())
                    .and_then(storage.save_reply(reply))
                )
            return storage.save_reply(reply).tap(
                lambda _: saved_deferred.open() if reply.rpc.tag == "deferred" else fx.void
            )

        def replies_for_unfiltered(request_ids: Any) -> fx.Effect[Any, Any]:
            ids = list(request_ids)

            def tap(replies: Any) -> fx.Effect[Any]:
                if (
                    not release_run.is_open()
                    and run_request_id[0] is not None
                    and run_request_id[0] in ids
                ):
                    assert replies == []
                    return read_before_commit.open()
                return fx.void

            return storage.replies_for_unfiltered(ids).tap(tap)

        return W.override_storage(
            storage, save_reply=save_reply, replies_for_unfiltered=replies_for_unfiltered
        )

    storage_layer = fx.layer.effect(MessageStorage, MessageStorage().map(wrap_storage)).pipe(
        fx.layer.provide(message_storage.layer_memory)
    )
    context = (
        yield from wf.to_layer(lambda _, __: gate.wait())
        .pipe(fx.layer.provide_merge(W.make_test_workflow_engine(storage_layer=storage_layer)))
        .build()
    )
    yield from fx.add_finalizer(lambda _: release_run.open())

    @fx.gen
    def run():
        # No execute waiter may retry a Suspended reply and repair the lost wake-up.
        execution_id = yield from wf.execute({}, discard=True)
        yield from advance_until(saving_run.is_open, "run must reach suspension persistence")
        yield from gate.succeed(token=_token(gate, wf, execution_id), value="signal")
        # Both resume and waitForRunReply read storage. Hold the commit until
        # that read observes no reply, allowing a fixed handler to park on it.
        yield from advance_until(
            read_before_commit.is_open, "completion must read the uncommitted run"
        )
        yield from release_run.open()
        yield from advance_until(saved_deferred.is_open, "deferred completion must be persisted")
        result = yield from poll_until(wf, execution_id, Complete)
        assert result == Complete(Exit.succeed("signal"))

    yield from run.pipe(fx.provide(context))


@testing.effect(timeout="20 seconds")
@_with_test_layer
def test_durable_deferred_race_all_delivers_a_completion_that_lands_while_a_suspension_commits():
    """DurableDeferred.raceAll delivers a completion that lands while a suspension commits"""
    flags = yield from Flags()
    sharding = yield from Sharding()
    wf = R.SlowUnwindWorkflow
    execution_id = yield from wf.execution_id({"id": "slow-unwind"})
    fiber = yield from wf.execute({"id": "slow-unwind"}).fork(start_immediately=True)
    # Wait until both branches have parked and the ensuring sleep has started,
    # so the completion deterministically lands during unwind.
    while flags.get("slow-unwind-started") is not True:
        yield from fx.yield_now()
    yield from R.SlowUnwindGateB.succeed(
        token=_token(R.SlowUnwindGateB, wf, execution_id), value="signal-b"
    )
    # Finish the unwind, then the replay and its own ensuring sleep.
    for _ in range(4):
        yield from testing.adjust("10 seconds")
        yield from sharding.poll_storage
    assert (yield from fiber.join()) == "signal-b"
    assert flags.get("slow-unwind-runs") == 2


@testing.effect
def test_durable_deferred_race_all_replays_a_persisted_result_its_owner_has_not_processed_yet():
    """DurableDeferred.raceAll replays a persisted result its owner has not processed yet"""
    wf = workflow.make(
        "UnprocessedRaceResult", payload=W.EMPTY, success=S.String, idempotency_key=lambda _: "one"
    )
    idle = durable_deferred.make("UnprocessedRaceResult/Idle", success=S.String)
    text = durable_deferred.make("UnprocessedRaceResult/Text", success=S.String)
    result = durable_deferred.make("raceAll/pick", success=S.String)
    storage = yield from W.make_shared_storage()

    # The race result is durable, but the runner's mailbox poll has not read it yet.
    def is_result(message: Any) -> bool:
        envelope = message.envelope
        return (
            isinstance(envelope, EnvelopeRequest)
            and envelope.tag == "deferred"
            and envelope.payload["name"] == result.name
        )

    def unprocessed_messages(shard_ids: Any, **options: Any) -> fx.Effect[Any, Any]:
        return storage.unprocessed_messages(shard_ids, **options).map(
            lambda messages: [m for m in messages if not is_result(m)]
        )

    layer = wf.to_layer(
        lambda _, __: durable_deferred.race_all(
            name="pick",
            success=S.String,
            error=S.Never,
            effects=[idle.wait(), text.wait()],
        )
    ).pipe(
        fx.layer.provide_merge(
            W.make_test_workflow_engine(
                storage_layer=W.storage_layer_of(
                    W.override_storage(storage, unprocessed_messages=unprocessed_messages)
                )
            )
        )
    )
    execution_id = yield from wf.execution_id({})

    # The previous owner records `idle` as the winner, then stops.
    @fx.gen
    def previous():
        yield from wf.execute({}, discard=True)
        yield from poll_until(wf, execution_id, Suspended)
        yield from result.succeed(
            token=result.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value="idle",
        )

    yield from previous.pipe(fx.provide(layer))

    # Each owner registers with its own RunnerStorage as machine id 0, so on the
    # same TestClock millisecond its snowflakes would repeat the previous owner's.
    yield from testing.adjust("1 millis")

    # A later completion wakes the new owner, whose replay must keep `idle`.
    @fx.gen
    def next_owner():
        yield from text.succeed(
            token=text.token_from_execution_id(workflow=wf, execution_id=execution_id),
            value="text",
        )
        assert (yield from poll_until(wf, execution_id, Complete)) == Complete(Exit.succeed("idle"))

    yield from next_owner.pipe(fx.provide(layer))


@testing.effect(timeout="20 seconds")
@_with_test_layer
def test_durable_deferred_race_all_suspends_when_every_branch_is_pending_and_resumes():
    """DurableDeferred.raceAll suspends when every branch is pending and resumes with the winner"""
    sharding = yield from Sharding()
    wf = R.TwoGateWorkflow
    execution_id = yield from wf.execution_id({"id": "two-gates"})
    fiber = yield from wf.execute({"id": "two-gates"}).fork(start_immediately=True)
    # Wait for the race to suspend with both gates pending.
    yield from testing.adjust("1 millis")
    polled = yield from wf.poll(execution_id)
    while not isinstance(polled, Suspended):
        yield from fx.yield_now()
        polled = yield from wf.poll(execution_id)
    yield from R.TwoGateB.succeed(token=_token(R.TwoGateB, wf, execution_id), value="signal-b")
    yield from sharding.poll_storage
    yield from testing.adjust("5 seconds")
    assert (yield from fiber.join()) == "signal-b"


# --- clocks and child workflows ------------------------------------------------------------


@testing.effect
def test_bounds_a_durable_clock_notification_when_its_workflow_is_absent_after_restart():
    """bounds a durable clock notification when its workflow is absent after restart"""
    clock_duration = 3
    registration_timeout = 5
    removed = workflow.make("RemovedWorkflow", payload=W.EMPTY, idempotency_key=lambda _: "one")
    storage, driver = yield from W.make_shared_memory()
    storage_layer = W.storage_layer_of(storage)
    overrides = {"entity_registration_timeout": Seconds(registration_timeout)}
    clock = durable_clock.make(name="wait", duration=Seconds(clock_duration))

    @fx.gen
    def first():
        execution_id = yield from removed.execute({}, discard=True)
        yield from poll_until(removed, execution_id, Suspended)
        return execution_id

    execution_id = yield from first.pipe(
        fx.provide(
            removed.to_layer(
                lambda _, __: durable_clock.sleep(
                    name="wait", duration=Seconds(clock_duration), in_memory_threshold=0
                )
            ).pipe(
                fx.layer.provide_merge(
                    W.make_test_workflow_engine(
                        storage_layer=storage_layer, config_overrides=overrides
                    )
                )
            )
        )
    )
    clock_request = next(
        (
            m
            for m in driver.encoded.journal
            if m["_tag"] == "Request" and m["address"]["entityType"] == "Workflow/-/DurableClock"
        ),
        None,
    )
    assert clock_request is not None

    @fx.gen
    def second():
        # Fire the persisted timer before the registration-start deadline.
        yield from testing.adjust(Seconds(clock_duration))
        # The completion ClockEntity emits when the persisted timer fires.
        # Calling it directly isolates the registration wait from storage claims.
        fiber = yield from clock.deferred.done(
            token=_token(clock.deferred, removed, execution_id), exit=Exit.succeed(None)
        ).fork_daemon(start_immediately=True)
        yield from fx.yield_now()
        assert fiber.poll_unsafe() is None
        yield from testing.adjust(Seconds(registration_timeout - clock_duration))
        exit_ = fiber.poll_unsafe()
        assert exit_ is not None, "the notifyLocal registration wait must be bounded"
        defect = exit_.cause.defects[0] if isinstance(exit_, fx.Failure) else None
        assert isinstance(defect, Exception)
        assert str(defect) == f"Entity type 'Workflow/{removed.tag}' not registered"

    yield from second.pipe(
        fx.provide(
            W.make_test_workflow_engine(storage_layer=storage_layer, config_overrides=overrides)
        )
    )


@pytest.mark.parametrize("threshold", [0.0, 0], ids=["number", "bigint"])
@testing.effect
def test_durable_clock_sleep_preserves_an_explicit_zero_threshold(threshold: float):
    """DurableClock.sleep preserves an explicit number | bigint zero threshold"""
    yield from P.verify_zero_threshold(
        "number" if isinstance(threshold, float) else "bigint", threshold
    )


def _until_suspended(wf: Any, execution_id: str, extra: Any = None) -> Any:
    sharding = yield from Sharding()
    while True:
        yield from fx.yield_now()
        if extra is not None:
            yield from extra()
        yield from sharding.poll_storage
        result = yield from wf.poll(execution_id)
        if isinstance(result, Suspended):
            return


def _until_complete(wf: Any, execution_id: str) -> Any:
    sharding = yield from Sharding()
    result = yield from wf.poll(execution_id)
    while not isinstance(result, Complete):
        yield from fx.yield_now()
        yield from testing.adjust("1 millis")
        yield from sharding.poll_storage
        result = yield from wf.poll(execution_id)
    return result


@testing.effect
@_with_test_layer
def test_parallel_child_workflows_inside_an_activity_suspend_the_parent_durably():
    """parallel child workflows inside an activity suspend the parent durably"""
    sharding = yield from Sharding()
    flags = yield from Flags()
    yield from testing.adjust("1 millis")
    payload: P.ParallelParentPayload = {
        "id": "parallel-activity",
        "childCount": 3,
        "concurrency": 3,
        "sleep": 2000,
    }
    execution_id = yield from P.ParallelParentWorkflow.execution_id(payload)
    fiber = yield from P.ParallelParentWorkflow.execute(payload).fork(start_immediately=True)
    # The parent suspends durably once every child has been dispatched.
    yield from _until_suspended(P.ParallelParentWorkflow, execution_id)
    assert flags.get("parallel-runs-parallel-activity") == 1
    for index in range(3):
        assert flags.get(f"parallel-child-start-parallel-activity-child-{index}") is True
    assert flags.get("parallel-activity-runs-parallel-activity") == 1
    assert flags.get("parallel-activity-releases-parallel-activity") == 1
    # The children complete after a single sleep window and wake the parent.
    yield from testing.adjust("2 seconds")
    yield from sharding.poll_storage
    while fiber.poll_unsafe() is None:
        yield from fx.yield_now()
        yield from testing.adjust("1 millis")
        yield from sharding.poll_storage
    assert fiber.poll_unsafe() == Exit.succeed(("done-0", "done-1", "done-2"))
    # The parent replayed after suspending, and no run retried the activity body.
    parent_runs = int(flags["parallel-runs-parallel-activity"])
    activity_runs = int(flags["parallel-activity-runs-parallel-activity"])
    assert parent_runs >= 2
    assert activity_runs <= parent_runs


@testing.effect
@_with_test_layer
def test_bounded_child_concurrency_progresses_across_suspended_activity_replays():
    """bounded child concurrency progresses across suspended activity replays"""
    sharding = yield from Sharding()
    flags = yield from Flags()
    yield from testing.adjust("1 millis")
    payload: P.ParallelParentPayload = {
        "id": "parallel-bounded",
        "childCount": 5,
        "concurrency": 2,
        "sleep": 2000,
    }
    wf = P.ParallelParentWorkflow
    execution_id = yield from wf.execution_id(payload)
    yield from wf.execute(payload, discard=True)
    for started in (2, 4, 5):
        while True:
            yield from fx.yield_now()
            # Drive cluster retries between runs without advancing child
            # clocks while the activity is computing execution IDs.
            if flags.get("parallel-activity-runs-parallel-bounded") == flags.get(
                "parallel-activity-releases-parallel-bounded"
            ):
                yield from testing.adjust("1 millis")
            yield from sharding.poll_storage
            result = yield from wf.poll(execution_id)
            if (
                isinstance(result, Suspended)
                and flags.get(f"parallel-child-start-parallel-bounded-child-{started - 1}") is True
            ):
                break
        for index in range(5):
            assert flags.get(f"parallel-child-start-parallel-bounded-child-{index}") == (
                True if index < started else None
            )
        assert flags.get("parallel-activity-releases-parallel-bounded") == flags.get(
            "parallel-activity-runs-parallel-bounded"
        )
        yield from testing.adjust("2 seconds")
        yield from sharding.poll_storage
    result = yield from _until_complete(wf, execution_id)
    assert result == Complete(Exit.succeed(("done-0", "done-1", "done-2", "done-3", "done-4")))
    assert int(flags["parallel-activity-runs-parallel-bounded"]) <= int(
        flags["parallel-runs-parallel-bounded"]
    )


class _IndexPayload(TypedDict):
    index: int


@testing.effect
def test_resumes_when_children_complete_during_activity_cleanup():
    """resumes when children complete during activity cleanup"""
    cleaning_up = yield from fx.Latch.make()
    release = yield from fx.Latch.make()
    parent = workflow.make(
        "CleanupParent",
        payload=W.EMPTY,
        success=S.Array(S.Number),
        idempotency_key=lambda _: "parent",
    )
    child = workflow.make(
        "CleanupChild",
        payload=S.Struct(_IndexPayload),
        success=S.Number,
        idempotency_key=lambda p: str(p["index"]),
    )
    parent_layer = parent.to_layer(
        lambda _, __: activity.make(
            name="children",
            success=S.Array(S.Number),
            execute=fx.for_each(
                [0, 1], lambda index: child.execute({"index": index}), concurrency="unbounded"
            )
            .map(tuple)
            .ensuring(cleaning_up.open().and_then(release.wait())),
        )
    )
    child_layer = child.to_layer(
        lambda p, _: durable_clock.sleep(
            name="wait", duration="2 seconds", in_memory_threshold=0
        ).as_(p["index"])
    )

    @fx.gen
    def run():
        sharding = yield from Sharding()
        yield from testing.adjust("1 millis")
        execution_id = yield from parent.execute({}, discard=True)
        yield from cleaning_up.wait()
        yield from testing.adjust("2 seconds")
        yield from sharding.poll_storage
        for index in (0, 1):
            child_id = yield from child.execution_id({"index": index})
            child_result = yield from _until_complete(child, child_id)
            assert child_result == Complete(Exit.succeed(index))
        yield from release.open()
        result = yield from _until_complete(parent, execution_id)
        assert result == Complete(Exit.succeed((0, 1)))

    yield from run.pipe(
        fx.provide(
            fx.layer.merge(parent_layer, child_layer).pipe(
                fx.layer.provide_merge(test_workflow_layer)
            )
        )
    )


def _provide_with_test_layer(*layers: fx.Layer[Any, Any, Any]) -> Any:
    return fx.provide(
        functools.reduce(fx.layer.merge, layers).pipe(fx.layer.provide_merge(test_workflow_layer))
    )


def _request_entry(driver: Any, tag: str, entity_type: str) -> Any:
    return next(
        (
            e
            for e in driver.encoded.requests.values()
            if e.envelope["_tag"] == "Request"
            and e.envelope["tag"] == tag
            and e.envelope["address"]["entityType"] == entity_type
        ),
        None,
    )


@testing.effect
def test_keeps_a_failure_suspended_workflow_parked_when_a_discarded_child_completes():
    """keeps a failure-suspended workflow parked when a discarded child completes"""
    failures = [0]
    child_gate = durable_deferred.make("FailureParkedChildGate")
    parent = workflow.make(
        "FailureParked", payload=W.EMPTY, idempotency_key=lambda _: "parent"
    ).annotate(SuspendOnFailure, True)
    child = workflow.make("FailureParkedChild", payload=W.EMPTY, idempotency_key=lambda _: "child")

    def fail() -> fx.Effect[None]:
        failures[0] += 1
        return fx.die(RuntimeError("boom"))

    def parent_handler(_: Any, __: str):
        return child.execute({}, discard=True).and_then(
            activity.make(name="fail", execute=fx.suspend(fail))
        )

    @fx.gen
    def run():
        driver = yield from MemoryDriver()

        def parent_reply(tag: str) -> Any:
            entry = _request_entry(driver, tag, f"Workflow/{parent.tag}")
            if entry is None:
                return None
            return next((r for r in entry.replies if r["_tag"] == "WithExit"), None)

        yield from testing.adjust("1 millis")
        execution_id = yield from parent.execute({}, discard=True)
        child_id = yield from child.execution_id({})
        yield from poll_until(parent, execution_id, Suspended)
        suspended = parent_reply("run")
        assert suspended is not None
        yield from child_gate.succeed(token=_token(child_gate, child, child_id), value=None)
        yield from poll_until(child, child_id, Complete)
        # The completed child wakes the parent through its resume RPC. Once
        # that wake has replied, a reset of the failure suspension would
        # already have replaced the run reply.
        yield from poll_storage_until(
            lambda: parent_reply("resume") is not None, "the child must wake its parent"
        )
        assert parent_reply("run")["id"] == suspended["id"], (
            "only an explicit resume may reset the suspension"
        )
        assert failures[0] == 1
        # Resume resets the suspended reply, so the next Suspended reply
        # belongs to the replay.
        yield from parent.resume(execution_id)
        yield from poll_until(parent, execution_id, Suspended)
        assert failures[0] == 2

    yield from run.pipe(
        _provide_with_test_layer(
            parent.to_layer(parent_handler), child.to_layer(lambda _, __: child_gate.wait())
        )
    )


@testing.effect
def test_persists_a_detached_childs_parent_without_waking_it():
    """persists a detached child's parent without waking it"""
    parent_runs = [0]
    parent_gate = durable_deferred.make("DetachedParentGate")
    child_gate = durable_deferred.make("DetachedChildGate")
    parent = workflow.make("DetachedParent", payload=W.EMPTY, idempotency_key=lambda _: "parent")
    child = workflow.make("DetachedChild", payload=W.EMPTY, idempotency_key=lambda _: "child")

    def parent_handler(_: Any, __: str):
        @fx.gen
        def body():
            parent_runs[0] += 1
            yield from child.execute({}, discard=True, detached=True)
            yield from parent_gate.wait()

        return body

    @fx.gen
    def run():
        sharding = yield from Sharding()
        driver = yield from MemoryDriver()
        yield from testing.adjust("1 millis")
        execution_id = yield from parent.execute({}, discard=True)
        child_id = yield from child.execution_id({})
        yield from poll_until(parent, execution_id, Suspended)
        assert parent_runs[0] == 1
        # The parent stays recorded on the child for observability.
        child_run = _request_entry(driver, "run", f"Workflow/{child.tag}")
        assert child_run is not None
        assert child_run.envelope["payload"][
            "~effect/cluster/ClusterWorkflowEngine/payloadParentKey"
        ] == {"workflowName": parent.tag, "executionId": execution_id, "detached": True}
        yield from child_gate.succeed(token=_token(child_gate, child, child_id), value=None)
        yield from poll_until(child, child_id, Complete)
        for _ in range(20):
            yield from testing.adjust("1 millis")
            yield from sharding.poll_storage
        assert parent_runs[0] == 1, "a detached child must not wake its parent"

    yield from run.pipe(
        _provide_with_test_layer(
            parent.to_layer(parent_handler), child.to_layer(lambda _, __: child_gate.wait())
        )
    )


@testing.effect
def test_reacquires_shards_after_a_forced_release_abandons_a_parent_waking_from_its_child():
    """reacquires shards after a forced release abandons a parent waking from its child"""
    storage_down = [False]
    probe_runs = [0]
    child = workflow.make("AbandonedWakeChild", payload=W.EMPTY, idempotency_key=lambda _: "child")
    parent = workflow.make(
        "AbandonedWakeParent", payload=W.EMPTY, idempotency_key=lambda _: "parent"
    )
    probe = workflow.make("AbandonedWakeProbe", payload=W.EMPTY, idempotency_key=lambda _: "probe")

    def wrap(storage: Any) -> Any:
        def refresh(address: Any, shard_ids: Any) -> fx.Effect[Any, Any]:
            if storage_down[0]:
                return fx.fail(PersistenceError(cause=RuntimeError("runner storage outage")))
            return storage.refresh(address, shard_ids)

        return replace(storage, refresh=refresh)

    runner_storage_layer = fx.layer.effect(RunnerStorage, runner_storage.make_memory().map(wrap))

    def count_probe() -> None:
        probe_runs[0] += 1

    layer = functools.reduce(
        fx.layer.merge,
        [
            child.to_layer(lambda _, __: fx.void),
            # The child completes while the parent's run is still active, so
            # its wake waits for that run's reply until the forced release
            # retires it.
            parent.to_layer(lambda _, __: child.execute({}, discard=True).and_then(fx.never)),
            probe.to_layer(lambda _, __: fx.sync(count_probe)),
        ],
    ).pipe(
        fx.layer.provide_merge(
            W.make_test_workflow_engine(
                sharding_layer=sharding_layer_of.pipe(fx.layer.provide(runner_storage_layer)),
                config_overrides={
                    "shards_per_group": 1,
                    "shard_lock_refresh_interval": Seconds(0.5),
                    "shard_lock_expiration": Seconds(3),
                    "entity_termination_timeout": Seconds(0.5),
                    "entity_message_poll_interval": Seconds(0.02),
                    "entity_reply_poll_interval": Seconds(0.02),
                    "refresh_assignments_interval": Seconds(0.1),
                },
            )
        )
    )

    # Keep a regressed teardown bounded, so the assertions are reported.
    def close_scope(scope: CloseableScope) -> Any:
        closing = yield from scope.close(Exit.succeed(None)).fork_daemon()
        yield from advance_until(
            lambda: closing.poll_unsafe() is not None, "the runner must shut down", 0.1, 20
        )

    scope = yield from fx.acquire_release(
        fx.sync(CloseableScope), lambda scope, _: fx.gen(lambda: close_scope(scope))
    )
    context = yield from layer.build_with_scope(scope)

    @fx.gen
    def run():
        sharding = yield from Sharding()
        shard_id = sharding.get_shard_id(EntityId("parent"), "default")
        yield from parent.execute({}, discard=True)
        yield from poll_until(child, (yield from child.execution_id({})), Complete)
        yield from testing.adjust("1500 millis")
        assert sharding.has_shard_id(shard_id)
        storage_down[0] = True
        yield from advance_until(
            lambda: not sharding.has_shard_id(shard_id),
            "the outage must force the shard release",
            0.1,
            14,
        )
        storage_down[0] = False
        # Release must finish before the shard can be reacquired.
        yield from testing.adjust("4 seconds")
        assert sharding.has_shard_id(shard_id), "the shard must be reacquired after recovery"
        yield from probe.execute({}, discard=True)
        yield from testing.adjust("1 second")
        assert probe_runs[0] == 1, "an independent workflow must run after recovery"

    yield from run.pipe(fx.provide(context))


@testing.effect
def test_reacquires_shards_after_a_forced_release_interrupts_a_parent_resume_waiting_on_its_active_run():  # noqa: E501
    """reacquires shards after a forced release interrupts a parent resume waiting on its active run"""  # noqa: E501
    storage_down = [False]
    child = workflow.make("PendingResumeChild", payload=W.EMPTY, idempotency_key=lambda _: "child")
    parent = workflow.make(
        "PendingResumeParent", payload=W.EMPTY, success=S.Number, idempotency_key=lambda _: "parent"
    )

    def wrap(storage: Any) -> Any:
        def refresh(address: Any, shard_ids: Any) -> fx.Effect[Any, Any]:
            if storage_down[0]:
                return fx.fail(PersistenceError(cause=RuntimeError("runner storage outage")))
            return storage.refresh(address, shard_ids)

        return replace(storage, refresh=refresh)

    runner_storage_layer = fx.layer.effect(RunnerStorage, runner_storage.make_memory().map(wrap))

    # The child's resume waits for the parent's run reply while the activity
    # keeps that run active. The slow interrupt cleanup, like a storage round
    # trip, lets shutdown interrupt the uninterruptible resume before the run
    # exits and abandons its reply waiter.
    def parent_body(_: Any, __: str) -> fx.Effect[float, Any, Any]:
        slow = activity.make(name="slow", success=S.Number, execute=fx.sleep("5 seconds").as_(42.0))
        return (
            fx.all(child.execute({}), slow, concurrency=2)
            .map(lambda pair: pair[1])
            .on_interrupt(fx.sleep("100 millis"))
        )

    layer = fx.layer.merge(
        child.to_layer(lambda _, __: fx.void), parent.to_layer(parent_body)
    ).pipe(
        fx.layer.provide_merge(
            W.make_test_workflow_engine(
                sharding_layer=sharding_layer_of.pipe(fx.layer.provide(runner_storage_layer)),
                config_overrides={
                    "shards_per_group": 1,
                    "shard_lock_refresh_interval": Seconds(0.5),
                    "shard_lock_expiration": Seconds(3),
                    "entity_termination_timeout": Seconds(0.5),
                    "entity_message_poll_interval": Seconds(0.02),
                    "entity_reply_poll_interval": Seconds(0.02),
                    "refresh_assignments_interval": Seconds(0.1),
                },
            )
        )
    )

    def close_scope(scope: CloseableScope) -> Any:
        closing = yield from scope.close(Exit.succeed(None)).fork_daemon()
        yield from advance_until(
            lambda: closing.poll_unsafe() is not None, "the runner must shut down", 0.1, 20
        )

    scope = yield from fx.acquire_release(
        fx.sync(CloseableScope), lambda scope, _: fx.gen(lambda: close_scope(scope))
    )
    context = yield from layer.build_with_scope(scope)

    @fx.gen
    def run():
        sharding = yield from Sharding()
        shard_id = sharding.get_shard_id(EntityId("parent"), "default")
        yield from parent.execute({}, discard=True)
        yield from poll_until(child, (yield from child.execution_id({})), Complete)
        yield from testing.adjust("1500 millis")
        assert sharding.has_shard_id(shard_id)

        storage_down[0] = True
        yield from advance_until(
            lambda: not sharding.has_shard_id(shard_id),
            "the outage must force the shard release",
            0.1,
            14,
        )
        storage_down[0] = False

        # Release must finish before the shard can be reacquired, then the
        # durable resume replays the parent and its interrupted activity.
        yield from testing.adjust("10 seconds")
        assert sharding.has_shard_id(shard_id), "the shard must be reacquired after recovery"
        result = yield from poll_until(parent, (yield from parent.execution_id({})), Complete)
        assert result == Complete(Exit.succeed(42))

    yield from run.pipe(fx.provide(context))


@testing.effect
def test_interrupts_a_failure_suspended_workflow():
    """interrupts a failure-suspended workflow"""
    attempts = [0]
    failing = workflow.make(
        "FailureInterrupted", payload=W.EMPTY, idempotency_key=lambda _: "failing"
    ).annotate(SuspendOnFailure, True)

    def fail() -> fx.Effect[None]:
        attempts[0] += 1
        return fx.die(RuntimeError("boom"))

    @fx.gen
    def run():
        yield from testing.adjust("1 millis")
        execution_id = yield from failing.execute({}, discard=True)
        yield from poll_until(failing, execution_id, Suspended)
        yield from failing.interrupt(execution_id)
        result = yield from poll_until(failing, execution_id, Complete)
        assert isinstance(result.exit, fx.Failure) and result.exit.cause.has_interrupts
        assert attempts[0] == 1, "interrupt must not re-run the failed activity"

    yield from run.pipe(
        _provide_with_test_layer(
            failing.to_layer(lambda _, __: activity.make(name="fail", execute=fx.suspend(fail)))
        )
    )


# --- interrupts ----------------------------------------------------------------------------


def _is_suspended_reply(reply: Any) -> bool:
    exit_ = getattr(reply.reply, "exit", None)
    return (
        reply.rpc.tag == "run"
        and isinstance(exit_, fx.Success)
        and isinstance(exit_.value, Suspended)
    )


def _assert_interrupted(result: Any, message: str = "") -> None:
    assert isinstance(result, Complete), message
    assert isinstance(result.exit, fx.Failure) and result.exit.cause.has_interrupts, message


@testing.effect
def test_interrupts_a_replay_that_is_still_persisting_its_suspended_reply():
    """interrupts a replay that is still persisting its Suspended reply"""
    first = durable_deferred.make("SavingSuspendedFirst")
    second = durable_deferred.make("SavingSuspendedSecond")
    wf = workflow.make("SavingSuspendedInterrupt", payload=W.EMPTY, idempotency_key=lambda _: "one")
    saving_reply = yield from fx.Latch.make()
    release_reply = yield from fx.Latch.make()
    suspended_replies = [0]
    storage = yield from W.make_shared_storage()

    # Hold the replay's Suspended reply, after the first run's reply is saved.
    def save_reply(reply: Any) -> fx.Effect[None, Any]:
        if _is_suspended_reply(reply):
            suspended_replies[0] += 1
            if suspended_replies[0] == 2:
                return (
                    saving_reply.open()
                    .and_then(release_reply.wait())
                    .and_then(storage.save_reply(reply))
                )
        return storage.save_reply(reply)

    storage_layer = W.storage_layer_of(W.override_storage(storage, save_reply=save_reply))

    @fx.gen
    def run():
        execution_id = yield from wf.execute({}, discard=True)
        yield from poll_until(wf, execution_id, Suspended)
        yield from first.succeed(token=_token(first, wf, execution_id), value=None)
        yield from advance_until(
            saving_reply.is_open, "the replay must suspend on the second deferred"
        )
        yield from wf.interrupt(execution_id)
        # Let the interrupt signal be handled before the Suspended reply is saved.
        for _ in range(10):
            yield from testing.adjust("1 millis")
        yield from release_reply.open()
        result = yield from poll_until(wf, execution_id, Complete)
        _assert_interrupted(result, "the interrupt must not be lost")

    yield from run.pipe(
        fx.provide(
            wf.to_layer(lambda _, __: first.wait().and_then(second.wait())).pipe(
                fx.layer.provide_merge(W.make_test_workflow_engine(storage_layer=storage_layer))
            )
        )
    )


@testing.effect
def test_interrupts_a_failure_suspending_run_while_an_activity_wake_waits_for_its_reply():
    """interrupts a failure-suspending run while an activity wake waits for its reply"""
    wake = durable_deferred.make("FailureSavingWake")
    wf = workflow.make(
        "FailureSavingInterrupt", payload=W.EMPTY, idempotency_key=lambda _: "one"
    ).annotate(SuspendOnFailure, True)
    saving_reply = yield from fx.Latch.make()
    release_reply = yield from fx.Latch.make()
    awaiting_reply = yield from fx.Latch.make()
    storage = yield from W.make_shared_storage()

    # Hold the failed Suspended reply, and observe a wake waiting for it.
    def save_reply(reply: Any) -> fx.Effect[None, Any]:
        if _is_suspended_reply(reply) and reply.reply.exit.value.failed:
            return (
                saving_reply.open()
                .and_then(release_reply.wait())
                .and_then(storage.save_reply(reply))
            )
        return storage.save_reply(reply)

    def register_reply_handler(message: Any) -> fx.Effect[None, Any]:
        def start() -> fx.Effect[None, Any]:
            if saving_reply.is_open() and message.envelope.tag == "run":
                return awaiting_reply.open().and_then(storage.register_reply_handler(message))
            return storage.register_reply_handler(message)

        return fx.suspend(start)

    storage_layer = W.storage_layer_of(
        W.override_storage(
            storage, save_reply=save_reply, register_reply_handler=register_reply_handler
        )
    )

    @fx.gen
    def run():
        execution_id = yield from wf.execute({}, discard=True)
        yield from poll_storage_until(saving_reply.is_open, "the run must suspend on its failure")
        # The parked activity's wake holds the resume gate while it waits for the reply.
        yield from wake.succeed(token=_token(wake, wf, execution_id), value=None)
        yield from advance_until(
            awaiting_reply.is_open, "the activity wake must wait for the run reply"
        )
        yield from wf.interrupt(execution_id)
        # Let the interrupt signal be handled before the Suspended reply is saved.
        for _ in range(10):
            yield from testing.adjust("1 millis")
        yield from release_reply.open()
        result = yield from poll_until(wf, execution_id, Complete)
        _assert_interrupted(result, "the interrupt must not be lost")

    yield from run.pipe(
        fx.provide(
            wf.to_layer(
                lambda _, __: fx.all(
                    activity.make(name="await-wake", execute=wake.wait()),
                    activity.make(name="fail", execute=fx.die(RuntimeError("boom"))),
                    concurrency="unbounded",
                    discard=True,
                )
            ).pipe(fx.layer.provide_merge(W.make_test_workflow_engine(storage_layer=storage_layer)))
        )
    )


@testing.effect
def test_interrupts_a_workflow_parked_inside_an_activity():
    """interrupts a workflow parked inside an activity"""
    gate = durable_deferred.make("ActivityParkedGate")
    parent = workflow.make(
        "ActivityParkedParent", payload=W.EMPTY, idempotency_key=lambda _: "parent"
    )
    child = workflow.make("ActivityParkedChild", payload=W.EMPTY, idempotency_key=lambda _: "child")

    @fx.gen
    def run():
        yield from testing.adjust("1 millis")
        execution_id = yield from parent.execute({}, discard=True)
        yield from poll_until(parent, execution_id, Suspended)
        yield from parent.interrupt(execution_id)
        _assert_interrupted((yield from poll_until(parent, execution_id, Complete)))

    yield from run.pipe(
        _provide_with_test_layer(
            # The activity's stored reply is ``Suspended`` while it awaits the child.
            parent.to_layer(
                lambda _, __: activity.make(name="await-child", execute=child.execute({}))
            ),
            child.to_layer(lambda _, __: gate.wait()),
        )
    )


@testing.effect
def test_interrupt_unsafe_during_a_later_activity_closes_the_superseded_run_and_compensates_once():
    """interruptUnsafe during a later activity closes the superseded run and compensates once"""
    wf = workflow.make(
        "UnsafeInterruptCompensateOnce", payload=W.EMPTY, idempotency_key=lambda _: "one"
    )
    started = yield from fx.Latch.make()
    release = yield from fx.Latch.make()
    compensations: list[Any] = []
    finalizers: list[Any] = []
    attempts = [0]

    def handler(_: Any, __: str):
        @fx.gen
        def body():
            attempts[0] += 1
            yield from workflow.add_finalizer(
                lambda exit_: fx.sync(lambda: finalizers.append(exit_))
            )
            yield from activity.make(name="first", execute=fx.void).pipe(
                wf.with_compensation(lambda _, cause: fx.sync(lambda: compensations.append(cause)))
            )
            yield from activity.make(name="second", execute=started.open().and_then(release.wait()))
            yield from activity.make(name="third", execute=fx.void)

        return body

    layer = wf.to_layer(handler).pipe(fx.layer.provide_merge(W.make_test_workflow_engine()))

    @fx.gen
    def run():
        engine = yield from WorkflowEngine()
        yield from testing.adjust("1 millis")
        execution_id = yield from wf.execute({}, discard=True)
        yield from started.wait()
        yield from engine.interrupt_unsafe(wf, execution_id)
        yield from release.open()
        _assert_interrupted((yield from poll_until(wf, execution_id, Complete)))
        assert len(compensations) == 1, "the compensation must run only in the final run"
        assert compensations[0].has_interrupts
        # Every attempt's scope is closed; superseded attempts observe success.
        assert len(finalizers) == attempts[0], "every run scope must be closed"
        interrupted = [
            e for e in finalizers if isinstance(e, fx.Failure) and e.cause.has_interrupts
        ]
        assert len(interrupted) == 1, "only the final run observes the interrupt"
        assert len([e for e in finalizers if isinstance(e, fx.Success)]) == attempts[0] - 1

    yield from run.pipe(fx.provide(layer))


# Both the persisted interrupt and the replayed activity reply are read before a
# pending interrupt is applied.
@pytest.mark.parametrize(
    ("lookup_tag", "lookup_id"),
    [("deferred", "Workflow/InterruptSignal"), ("activity", "flaky/1")],
)
@testing.effect
def test_applies_a_persisted_interrupt_when_a_fresh_owner_replays_a_failure_suspended_workflow(
    lookup_tag: str, lookup_id: str
):
    """applies a persisted interrupt when a fresh owner replays a failure-suspended workflow after a transient ${lookup.tag} lookup failure"""  # noqa: E501
    attempts = [0]
    failing = workflow.make(
        "FailureInterruptedRecovery", payload=W.EMPTY, idempotency_key=lambda _: "failing"
    ).annotate(SuspendOnFailure, True)
    storage = yield from W.make_shared_storage()
    # The first owner records the interrupt and resets the run, but crashes
    # before the reset run is redelivered.
    crashed = [False]

    def unprocessed_messages(shard_ids: Any, **options: Any) -> fx.Effect[Any, Any]:
        return storage.unprocessed_messages(shard_ids, **options).map(
            lambda messages: (
                [
                    m
                    for m in messages
                    if not isinstance(m.envelope, EnvelopeRequest) or m.envelope.tag != "run"
                ]
                if crashed[0]
                else messages
            )
        )

    crashing_storage = W.storage_layer_of(
        W.override_storage(storage, unprocessed_messages=unprocessed_messages)
    )

    def flaky() -> fx.Effect[None]:
        attempts[0] += 1
        return fx.die(RuntimeError("boom")) if attempts[0] == 1 else fx.void

    def layer(storage_layer: fx.Layer[Any]) -> fx.Layer[Any, Any, Any]:
        return failing.to_layer(
            # A retry would succeed, so a replay that runs it completes normally.
            lambda _, __: activity.make(name="flaky", execute=fx.suspend(flaky))
        ).pipe(fx.layer.provide_merge(W.make_test_workflow_engine(storage_layer=storage_layer)))

    execution_id = yield from failing.execution_id({})

    @fx.gen
    def first():
        yield from testing.adjust("1 millis")
        yield from failing.execute({}, discard=True)
        yield from poll_until(failing, execution_id, Suspended)
        crashed[0] = True
        yield from failing.interrupt(execution_id)
        result = yield from failing.poll(execution_id)
        for _ in range(2000):
            if result is None:
                break
            yield from testing.adjust("1 millis")
            result = yield from failing.poll(execution_id)
        assert result is None, "the interrupt must reset the run"

    yield from first.pipe(fx.provide(layer(crashing_storage)))

    # The fresh owner's first lookup fails once.
    lookup_failed = [False]

    def request_id_for_primary_key(**options: Any) -> fx.Effect[Any, Any]:
        if not lookup_failed[0] and options["tag"] == lookup_tag and options["id"] == lookup_id:
            lookup_failed[0] = True
            return fx.fail(PersistenceError(cause=RuntimeError("transient lookup failure")))
        return storage.request_id_for_primary_key(**options)

    flaky_storage = W.storage_layer_of(
        W.override_storage(storage, request_id_for_primary_key=request_id_for_primary_key)
    )

    @fx.gen
    def second():
        result = yield from poll_until(failing, execution_id, Complete)
        assert lookup_failed[0], "the lookup must fail once"
        _assert_interrupted(result, "the replay must complete as interrupted")
        assert attempts[0] == 1, "a fresh owner must not re-run the failed activity"

    yield from second.pipe(fx.provide(layer(flaky_storage)))


# --- parents waking from children ----------------------------------------------------------


@testing.effect
def test_coalesces_parked_child_wakeups_while_parent_cleanup_is_pending():
    """coalesces parked child wakeups while parent cleanup is pending"""
    cleaning_up = yield from fx.Latch.make()
    release = yield from fx.Latch.make()
    indices = list(range(64))
    parked = [0]
    peak = [0]

    def wrap(storage: Any) -> Any:
        def register_reply_handler(message: Any) -> fx.Effect[None, Any]:
            if (
                message.envelope.address.entity_type != "Workflow/ManyChildrenParent"
                or message.envelope.tag != "run"
            ):
                return storage.register_reply_handler(message)

            def start() -> fx.Effect[None, Any]:
                parked[0] += 1
                peak[0] = max(peak[0], parked[0])
                return storage.register_reply_handler(message)

            def done() -> None:
                parked[0] -= 1

            return fx.suspend(start).ensuring(fx.sync(done))

        return W.override_storage(storage, register_reply_handler=register_reply_handler)

    storage_layer = fx.layer.effect(MessageStorage, MessageStorage().map(wrap)).pipe(
        fx.layer.provide_merge(message_storage.layer_memory)
    )
    parent = workflow.make(
        "ManyChildrenParent",
        payload=W.EMPTY,
        success=S.Array(S.Number),
        idempotency_key=lambda _: "parent",
    )
    child = workflow.make(
        "ManyChildrenChild",
        payload=S.Struct(_IndexPayload),
        success=S.Number,
        idempotency_key=lambda p: str(p["index"]),
    )
    parent_layer = parent.to_layer(
        lambda _, __: activity.make(
            name="children",
            success=S.Array(S.Number),
            execute=fx.for_each(
                indices, lambda index: child.execute({"index": index}), concurrency="unbounded"
            )
            .map(tuple)
            .ensuring(cleaning_up.open().and_then(release.wait())),
        )
    )
    child_layer = child.to_layer(
        lambda p, _: durable_clock.sleep(
            name="wait", duration="2 seconds", in_memory_threshold=0
        ).as_(p["index"])
    )

    @fx.gen
    def run():
        sharding = yield from Sharding()
        driver = yield from MemoryDriver()
        yield from testing.adjust("1 millis")
        execution_id = yield from parent.execute({}, discard=True)
        yield from cleaning_up.wait()
        yield from testing.adjust("2 seconds")

        def wake_requests() -> list[Any]:
            return [
                m
                for m in driver.encoded.journal
                if m["_tag"] == "Request"
                and m["address"]["entityType"] == "Workflow/ManyChildrenParent"
                and m["tag"] == "resume"
            ]

        def all_wakes_handled() -> bool:
            wakes = wake_requests()
            replied = sum(
                1
                for m in wakes
                if (entry := driver.encoded.requests.get(m["requestId"])) is not None
                and entry.replies
            )
            # Every wake must have replied or parked before releasing the parent.
            return len(wakes) == len(indices) and replied + parked[0] == len(indices)

        while not all_wakes_handled():
            yield from fx.yield_now()
            yield from testing.adjust("1 millis")
            yield from sharding.poll_storage
        wakes = wake_requests()
        parked_before_release = parked[0]
        yield from release.open()
        result = yield from parent.poll(execution_id)
        while not isinstance(result, Complete) or parked[0] != 0:
            yield from fx.yield_now()
            yield from testing.adjust("1 millis")
            yield from sharding.poll_storage
            result = yield from parent.poll(execution_id)
        assert result == Complete(Exit.succeed(tuple(indices)))
        assert parked[0] == 0
        assert len(wakes) == len(indices)
        # Each wake remains durable, but only one waits on this parent run.
        assert parked_before_release == 1, f"peak parked reply handlers: {peak[0]}"
        assert peak[0] == 1

    yield from run.pipe(
        fx.provide(
            fx.layer.merge(parent_layer, child_layer).pipe(
                fx.layer.provide_merge(
                    W.make_test_workflow_engine(
                        config_overrides={"entity_mailbox_capacity": 1000},
                        storage_layer=storage_layer,
                    )
                )
            )
        )
    )


class _LegacyResumePayload(S.Class):
    def primary_key(self) -> str:
        return ""


class _LegacyResume(Entity, type="Workflow/ColdParent"):
    resume = make_rpc("resume", payload=_LegacyResumePayload).annotate(Persisted, True)


@pytest.mark.parametrize("queued_replay", [False, True], ids=["false", "true"])
@testing.effect
def test_resumes_a_fresh_entity_from_a_legacy_envelope(queued_replay: bool):
    """resumes a fresh entity from a legacy envelope with queued replay false | true"""
    parent = workflow.make(
        "ColdParent", payload=W.EMPTY, success=S.Array(S.Number), idempotency_key=lambda _: "parent"
    )
    child = workflow.make(
        "ColdChild",
        payload=S.Struct(_IndexPayload),
        success=S.Number,
        idempotency_key=lambda p: str(p["index"]),
    )
    gate = durable_deferred.make("cold-child")
    parent_layer = parent.to_layer(
        lambda _, __: activity.make(
            name="children",
            success=S.Array(S.Number),
            execute=fx.for_each(
                [0, 1], lambda index: child.execute({"index": index}), concurrency="unbounded"
            ).map(tuple),
        )
    )
    child_layer = child.to_layer(lambda p, _: gate.wait().as_(p["index"]))

    @fx.gen
    def run():
        sharding = yield from Sharding()
        driver = yield from MemoryDriver()
        engine = yield from WorkflowEngine()
        yield from testing.adjust("1 millis")
        execution_id = yield from parent.execute({}, discard=True)
        result = yield from parent.poll(execution_id)
        while not isinstance(result, Suspended):
            yield from fx.yield_now()
            yield from testing.adjust("1 millis")
            yield from sharding.poll_storage
            result = yield from parent.poll(execution_id)
        for _ in range(12):
            if (yield from sharding.active_entity_count) == 0:
                break
            yield from testing.adjust("5 seconds")
        assert (yield from sharding.active_entity_count) == 0
        if queued_replay:
            found = next(
                m
                for m in driver.encoded.journal
                if m["_tag"] == "Request"
                and m["address"]["entityType"] == "Workflow/ColdParent"
                and m["tag"] == "run"
            )
            assert (yield from sharding.reset(Snowflake(int(found["requestId"]))))
            assert (yield from parent.poll(execution_id)) is None
        make_client = yield from _LegacyResume.client()
        # The empty payload is the format of resume messages persisted before this fix.
        legacy_resume = (
            yield from make_client(execution_id)
            .resume(_LegacyResumePayload())
            .fork(start_immediately=True)
        )
        for index in (0, 1):
            yield from engine.deferred_done(
                gate,
                workflow_name=child.tag,
                execution_id=(yield from child.execution_id({"index": index})),
                deferred_name=gate.name,
                exit=Exit.succeed(None),
            )
        result = yield from parent.poll(execution_id)
        while not isinstance(result, Complete) or legacy_resume.poll_unsafe() is None:
            yield from fx.yield_now()
            yield from testing.adjust("1 millis")
            yield from sharding.poll_storage
            result = yield from parent.poll(execution_id)
        assert result == Complete(Exit.succeed((0, 1)))
        assert legacy_resume.poll_unsafe() == Exit.succeed(None)

    yield from run.pipe(
        fx.provide(
            fx.layer.merge(parent_layer, child_layer).pipe(
                fx.layer.provide_merge(
                    W.make_test_workflow_engine(
                        config_overrides={"entity_message_poll_interval": Seconds(3600)}
                    )
                )
            )
        )
    )


def _until_fiber_done(fiber: Any) -> Any:
    sharding = yield from Sharding()
    while fiber.poll_unsafe() is None:
        yield from fx.yield_now()
        yield from testing.adjust("1 millis")
        yield from sharding.poll_storage


@testing.effect
@_with_test_layer
def test_a_parent_stays_suspended_past_the_activity_interrupt_retry_budget():
    """a parent stays suspended past the activity interrupt retry budget"""
    sharding = yield from Sharding()
    flags = yield from Flags()
    yield from testing.adjust("1 millis")
    payload: P.ParallelParentPayload = {
        "id": "parallel-long",
        "childCount": 2,
        "concurrency": 2,
        "sleep": 60_000,
    }
    wf = P.ParallelParentWorkflow
    execution_id = yield from wf.execution_id(payload)
    fiber = yield from wf.execute(payload).fork(start_immediately=True)
    yield from _until_suspended(wf, execution_id)
    # Well past the activity interrupt retry budget the run is still suspended
    # and the activity body has not been re-executed.
    yield from testing.adjust("50 seconds")
    yield from sharding.poll_storage
    assert isinstance((yield from wf.poll(execution_id)), Suspended)
    assert flags.get("parallel-activity-runs-parallel-long") == 1
    assert flags.get("parallel-activity-releases-parallel-long") == 1
    assert fiber.poll_unsafe() is None
    yield from testing.adjust("10 seconds")
    yield from sharding.poll_storage
    yield from _until_fiber_done(fiber)
    assert fiber.poll_unsafe() == Exit.succeed(("done-0", "done-1"))


@testing.effect
@_with_test_layer
def test_parallel_child_workflows_in_the_workflow_body_all_dispatch_before_suspending():
    """parallel child workflows in the workflow body all dispatch before suspending"""
    sharding = yield from Sharding()
    flags = yield from Flags()
    yield from testing.adjust("1 millis")
    payload: P.ParallelDirectPayload = {"id": "parallel-direct", "childCount": 3}
    wf = P.ParallelDirectWorkflow
    execution_id = yield from wf.execution_id(payload)
    fiber = yield from wf.execute(payload).fork(start_immediately=True)
    yield from _until_suspended(wf, execution_id)
    assert flags.get("parallel-runs-parallel-direct") == 1
    for index in range(3):
        assert flags.get(f"parallel-child-start-parallel-direct-child-{index}") is True
    yield from testing.adjust("2 seconds")
    yield from sharding.poll_storage
    yield from _until_fiber_done(fiber)
    assert fiber.poll_unsafe() == Exit.succeed(("done-0", "done-1", "done-2"))


# --- routing, registration and tracing -----------------------------------------------------


@testing.effect
@_with_test_layer
def test_routes_fractional_millisecond_durable_clock_wakeups_to_the_workflow_shard_group():
    """routes fractional millisecond durable clock wakeups to the workflow shard group"""
    driver = yield from MemoryDriver()
    sharding = yield from Sharding()
    scheduled = yield from P.ShardedClockScheduled()
    started_at = now_millis_unsafe((yield from Clock()))
    fiber = yield from P.ShardedClockWorkflow.execute({"id": "sharded-clock"}).fork(
        start_immediately=True
    )
    yield from scheduled.wait()
    envelope = next(
        m
        for m in driver.encoded.journal
        if m["_tag"] == "Request" and m["address"]["entityType"] == "Workflow/-/DurableClock"
    )
    assert envelope["address"]["shardId"]["group"] == "workflow"
    deliver_at = driver.encoded.requests[envelope["requestId"]].deliver_at
    assert deliver_at == started_at + 10001
    yield from testing.adjust("10001 millis")
    yield from sharding.poll_storage
    yield from testing.adjust("5 seconds")
    yield from fiber.join()


def _prime_partial_client(token: str) -> Any:
    # Prime the partial client cache without waiting for the unregistered
    # workflow entity.
    fiber = yield from P.ShardedDeferred.done(token=token, exit=Exit.succeed(None)).fork(
        start_immediately=True
    )
    yield from fx.yield_now()
    yield from fiber.interrupt()


def _new_journal_request(driver: Any, since: int, tag: str | None = None) -> Any:
    return next(
        (
            m
            for m in driver.encoded.journal[since:]
            if m["_tag"] == "Request"
            and m["address"]["entityType"] == "Workflow/ShardedDeferredWorkflow"
            and (tag is None or m["tag"] == tag)
        ),
        None,
    )


@testing.effect
def test_routes_durable_deferred_completions_to_the_workflow_shard_group_after_a_partial_client():
    """routes durable deferred completions to the workflow shard group after a partial client is cached"""  # noqa: E501

    @fx.gen
    def run():
        driver = yield from MemoryDriver()
        engine = yield from WorkflowEngine()
        wf = P.ShardedDeferredWorkflow
        before = yield from wf.execution_id({"id": "before-register"})
        yield from _prime_partial_client(_token(P.ShardedDeferred, wf, before))
        yield from engine.register(wf, lambda _, __: fx.void)
        after = yield from wf.execution_id({"id": "after-register"})
        journal_length = len(driver.encoded.journal)
        yield from P.ShardedDeferred.done(
            token=_token(P.ShardedDeferred, wf, after), exit=Exit.succeed(None)
        )
        envelope = _new_journal_request(driver, journal_length)
        assert envelope is not None
        assert envelope["address"]["shardId"]["group"] == "workflow"

    yield from run.pipe(fx.provide(W.test_workflow_engine))


class _WarningLog:
    def __init__(self) -> None:
        self.messages: list[str] = []

    def layer(self) -> fx.Layer[Any]:
        def record(options: Any) -> None:
            if options.log_level == fx.LogLevel.WARN:
                message = options.message
                self.messages.append(
                    " ".join(map(str, message))
                    if isinstance(message, (list, tuple))
                    else str(message)
                )

        return fx.logger.layer([fx.Logger.make(record)])

    def find(self, fragment: str) -> str | None:
        return next((m for m in self.messages if fragment in m), None)


class _FirstPayload(S.Class, identifier="DuplicateClassPayload"):
    organizationId: str


class _SecondPayload(S.Class, identifier="DuplicateClassPayload"):
    deploymentId: float


@testing.effect
def test_warns_for_conflicting_definitions_and_stays_silent_for_the_same_definition():
    """warns for conflicting definitions and stays silent for the same definition"""
    first = workflow.make(
        "DuplicateClassPayloadWorkflow",
        payload=_FirstPayload,
        idempotency_key=lambda p: p.organizationId,
    )
    second = workflow.make(
        "DuplicateClassPayloadWorkflow",
        payload=_SecondPayload,
        idempotency_key=lambda p: str(p.deploymentId),
    )
    log = _WarningLog()

    @fx.gen
    def run():
        engine = yield from WorkflowEngine()
        yield from engine.register(first, lambda _, __: fx.void)
        yield from engine.register(first, lambda _, __: fx.void)
        assert log.messages == []
        yield from engine.register(second, lambda _, __: fx.void)
        warning = log.find("DuplicateClassPayloadWorkflow")
        assert warning, "duplicate workflow registration must emit a warning containing its tag"
        normalized = warning.lower()
        for fragment in ("organizationid", "string", "deploymentid", "number"):
            assert fragment in normalized, (
                f"warning must identify both class payload shapes: {warning}"
            )

    yield from run.pipe(fx.provide(W.test_workflow_engine)).pipe(fx.provide(log.layer()))


def _unrenderable_struct(value: Any) -> Any:
    # Effect keys the struct by a symbol; a non-string key cannot be rendered
    # as JSON Schema either.
    return S.Bottom(ast.Objects((ast.PropertySignature(object(), value.ast),), ()))


@testing.effect
def test_does_not_fail_when_duplicate_workflow_payload_shapes_cannot_be_rendered():
    """does not fail when duplicate workflow payload shapes cannot be rendered"""
    first = workflow.make(
        "UnavailablePayloadShapeWorkflow",
        payload=_unrenderable_struct(S.String),
        idempotency_key=lambda _: "first",
    )
    second = workflow.make(
        "UnavailablePayloadShapeWorkflow",
        payload=_unrenderable_struct(S.Number),
        idempotency_key=lambda _: "second",
    )
    log = _WarningLog()

    @fx.gen
    def run():
        engine = yield from WorkflowEngine()
        yield from engine.register(first, lambda _, __: fx.void)
        yield from engine.register(second, lambda _, __: fx.void)
        assert log.find("UnavailablePayloadShapeWorkflow"), (
            "duplicate workflow registration must still warn when rendering a payload shape fails"
        )

    yield from run.pipe(fx.provide(W.test_workflow_engine)).pipe(fx.provide(log.layer()))


@testing.effect
def test_propagates_trace_context_to_persisted_workflow_requests():
    """propagates trace context to persisted workflow requests"""
    caller_span: list[NativeSpan] = []

    def make_span(request: SpanRequest) -> NativeSpan:
        span = NativeSpan(request)
        if request.name == "WorkflowEngine.deferredDone":
            caller_span.append(span)
        return span

    @fx.gen
    def run():
        driver = yield from MemoryDriver()
        engine = yield from WorkflowEngine()
        wf = P.ShardedDeferredWorkflow
        yield from engine.register(wf, lambda _, __: fx.void)
        execution_id = yield from wf.execution_id({"id": "trace-context"})
        journal_length = len(driver.encoded.journal)
        yield from P.ShardedDeferred.done(
            token=_token(P.ShardedDeferred, wf, execution_id), exit=Exit.succeed(None)
        )
        envelope = _new_journal_request(driver, journal_length, "deferred")
        assert envelope is not None
        assert caller_span
        span = caller_span[0]
        assert envelope["traceId"] == span.trace_id
        assert envelope["spanId"] == span.span_id
        assert envelope["sampled"] == span.sampled

    yield from run.with_tracer(Tracer(make_span)).pipe(fx.provide(W.test_workflow_engine))


@testing.effect
def test_routes_activities_to_the_workflow_shard_group_after_a_partial_client_is_cached():
    """routes activities to the workflow shard group after a partial client is cached"""

    @fx.gen
    def run():
        driver = yield from MemoryDriver()
        engine = yield from WorkflowEngine()
        wf = P.ShardedDeferredWorkflow
        payload: W.IdPayload = {"id": "partial-client-before-execute"}
        execution_id = yield from wf.execution_id(payload)
        yield from _prime_partial_client(_token(P.ShardedDeferred, wf, execution_id))
        yield from engine.register(
            wf, lambda _, __: activity.make(name="ShardedActivity", execute=fx.void)
        )
        journal_length = len(driver.encoded.journal)
        assert (yield from wf.execute(payload)) is None
        envelope = _new_journal_request(driver, journal_length, "activity")
        assert envelope is not None
        assert envelope["address"]["shardId"]["group"] == "workflow"

    yield from run.pipe(fx.provide(W.test_workflow_engine))
