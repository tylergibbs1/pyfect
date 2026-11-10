"""Parallel child, sharded clock and zero-threshold workflows of Effect's
``ClusterWorkflowEngine.test.ts``."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, TypedDict

import pyfect as fx
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect.cluster.cluster_schema import ShardGroup
from pyfect.context import Tag
from pyfect.latch import Latch
from pyfect.workflow import Complete, activity, durable_clock, durable_deferred, workflow
from pyfect.workflow.workflow_engine import (
    Encoded,
    WorkflowEngine,
    WorkflowInstance,
    WorkflowInstanceService,
    make_unsafe,
)

from ._cluster_workflows import ID, Flags, IdPayload


class ParallelParentPayload(TypedDict):
    id: str
    childCount: int
    concurrency: int
    sleep: int


class ParallelDirectPayload(TypedDict):
    id: str
    childCount: int


class ParallelChildPayload(TypedDict):
    id: str
    index: int
    sleep: int


ParallelParentWorkflow = workflow.make(
    "ParallelParentWorkflow",
    payload=S.Struct(ParallelParentPayload),
    success=S.Array(S.String),
    idempotency_key=lambda p: p["id"],
)
ParallelDirectWorkflow = workflow.make(
    "ParallelDirectWorkflow",
    payload=S.Struct(ParallelDirectPayload),
    success=S.Array(S.String),
    idempotency_key=lambda p: p["id"],
)
ParallelChildWorkflow = workflow.make(
    "ParallelChildWorkflow",
    payload=S.Struct(ParallelChildPayload),
    success=S.String,
    idempotency_key=lambda p: p["id"],
)


def increment(flags: dict[str, Any], key: str) -> None:
    flags[key] = int(flags.get(key, 0)) + 1


def _child(payload: ParallelParentPayload | ParallelDirectPayload, index: int, sleep: int) -> Any:
    return ParallelChildWorkflow.execute(
        {"id": f"{payload['id']}-child-{index}", "index": index, "sleep": sleep}
    )


def _parallel_parent(payload: ParallelParentPayload, _: str):
    @fx.gen
    def body():
        flags = yield from Flags()
        increment(flags, f"parallel-runs-{payload['id']}")
        indices = range(payload["childCount"])

        def children() -> fx.Effect[Any, Any, Any]:
            increment(flags, f"parallel-activity-runs-{payload['id']}")
            return fx.for_each(
                indices,
                lambda index: _child(payload, index, payload["sleep"]),
                concurrency=payload["concurrency"],
            ).map(tuple)

        return (
            yield from activity.make(
                name="parallel-children",
                success=S.Array(S.String),
                execute=fx.suspend(children).ensuring(
                    fx.sync(lambda: increment(flags, f"parallel-activity-releases-{payload['id']}"))
                ),
            )
        )

    return body


def _parallel_direct(payload: ParallelDirectPayload, _: str):
    @fx.gen
    def body():
        flags = yield from Flags()
        increment(flags, f"parallel-runs-{payload['id']}")
        return (
            yield from fx.for_each(
                range(payload["childCount"]),
                lambda index: _child(payload, index, 2000),
                concurrency="unbounded",
            ).map(tuple)
        )

    return body


def _parallel_child(payload: ParallelChildPayload, _: str):
    @fx.gen
    def body():
        flags = yield from Flags()
        flags[f"parallel-child-start-{payload['id']}"] = True
        yield from durable_clock.sleep(
            name="parallel-child",
            duration=fx.duration.seconds(payload["sleep"] / 1000),
            in_memory_threshold=0,
        )
        return f"done-{payload['index']}"

    return body


ShardedClockWorkflow = workflow.make(
    "ShardedClockWorkflow", payload=ID, idempotency_key=lambda p: p["id"]
).annotate(ShardGroup, lambda _: "workflow")


class ShardedClockScheduled(Tag[Latch], key="ShardedClockScheduled"):
    pass


sharded_clock_scheduled_layer = fx.layer.sync(ShardedClockScheduled, Latch)


def _sharded_clock(_: IdPayload, __: str):
    @fx.gen
    def body():
        engine = yield from WorkflowEngine()
        instance = yield from WorkflowInstance()
        scheduled = yield from ShardedClockScheduled()
        clock = durable_clock.make(name="ShardedClock", duration="10000500 micros")
        yield from engine.schedule_clock(
            instance.workflow, execution_id=instance.execution_id, clock=clock
        )
        yield from scheduled.open()
        yield from clock.deferred.wait()

    return body


ShardedDeferred = durable_deferred.make("ShardedDeferred")
ShardedDeferredWorkflow = workflow.make(
    "ShardedDeferredWorkflow", payload=ID, idempotency_key=lambda p: p["id"]
).annotate(ShardGroup, lambda _: "workflow")


parallel_workflow_layers: fx.Layer[Any, Any, Any] = functools.reduce(
    fx.layer.merge,
    [
        ParallelParentWorkflow.to_layer(_parallel_parent),
        ParallelDirectWorkflow.to_layer(_parallel_direct),
        ParallelChildWorkflow.to_layer(_parallel_child),
        ShardedClockWorkflow.to_layer(_sharded_clock),
    ],
)


ZeroThresholdWorkflow = workflow.make(
    "DurableClock/ZeroThreshold", payload=ID, idempotency_key=lambda p: p["id"]
)


def verify_zero_threshold(id_: str, in_memory_threshold: float) -> Any:
    instance = WorkflowInstanceService.initial(ZeroThresholdWorkflow, f"execution/{id_}")
    calls: list[str] = []

    def unexpected(*_: Any, **__: Any) -> fx.Effect[Any]:
        return fx.die(RuntimeError("unexpected engine operation"))

    def record(name: str, value: Any) -> Callable[..., fx.Effect[Any]]:
        def run() -> Any:
            calls.append(name)
            return value

        def call(*_: object) -> fx.Effect[Any]:
            return fx.sync(run)

        return call

    engine = make_unsafe(
        Encoded(
            register=unexpected,
            execute=unexpected,
            poll=unexpected,
            interrupt=unexpected,
            interrupt_unsafe=unexpected,
            resume=unexpected,
            deferred_done=unexpected,
            activity_execute=record("activityExecute", Complete(Exit.succeed(None))),
            schedule_clock=record("scheduleClock", None),
            deferred_result=record("deferredResult", Exit.succeed(None)),
        )
    )
    yield from (
        durable_clock.sleep(
            name=f"clock/{id_}",
            duration="10 millis",
            in_memory_threshold=fx.duration.seconds(in_memory_threshold),
        )
        .pipe(fx.provide_service(WorkflowEngine, engine))
        .pipe(fx.provide_service(WorkflowInstance, instance))
    )
    assert calls == ["scheduleClock", "deferredResult"]
