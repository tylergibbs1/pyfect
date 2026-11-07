"""Ports of Effect's ``test/workflow/DurableQueue.test.ts``.

Each test's docstring is the Effect test title. ``Schema.Void`` is
``S.Null``; ``Effect.sleep("10 millis").pipe(TestClock.withLive)`` is
``testing.with_live(fx.sleep(0.01))``.
"""

from __future__ import annotations

import functools
from collections.abc import Generator
from typing import Any, Never, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cause import Fail
from pyfect.persistence import persisted_queue as pq
from pyfect.workflow import (
    Complete,
    Result,
    WorkflowEngine,
    durable_queue,
    workflow,
    workflow_engine,
)

PERSISTED_QUEUE_LAYER = pq.layer.pipe(fx.layer.provide_merge(pq.layer_store_memory))


def _merge_build_nothing(
    *layers: fx.Layer[Never, Never, WorkflowEngine | pq.PersistedQueueFactory],
) -> fx.Layer[Never, Never, WorkflowEngine | pq.PersistedQueueFactory]:
    """``layer.merge`` of layers that all build nothing infers ``Unknown``."""
    return functools.reduce(fx.layer.merge, layers)


def _poll_until_complete[A, E](
    poll: fx.Effect[Result[A, E] | None, Any, Any],
) -> Generator[Any, Any, Result[A, E] | None]:
    polled = yield from poll
    for _ in range(10):
        if isinstance(polled, Complete):
            break
        yield from fx.yield_now()
        yield from testing.with_live(fx.sleep("10 millis"))
        polled = yield from poll
    return polled


class IdValue(TypedDict):
    id: str
    value: float


class Id(TypedDict):
    id: str


SuccessQueue = durable_queue.make(
    name="DurableQueueTest/SuccessQueue",
    payload=S.Struct(IdValue),
    success=S.Number,
    error=S.String,
    idempotency_key=lambda p: p["id"],
)
SuccessWorkflow = workflow.make(
    "DurableQueueTest/SuccessWorkflow",
    payload=S.Struct(IdValue),
    success=S.Number,
    error=S.String,
    idempotency_key=lambda p: p["id"],
)
_SuccessWorkers = _merge_build_nothing(
    SuccessWorkflow.to_layer(lambda p, _id: SuccessQueue.process(p)),
    SuccessQueue.worker(lambda p: fx.succeed(p["value"] + 1)),
)
SuccessLayer = _SuccessWorkers.pipe(fx.layer.provide_merge(workflow_engine.layer_memory)).pipe(
    fx.layer.provide_merge(PERSISTED_QUEUE_LAYER)
)


@testing.effect
def test_processes_queued_items_and_resumes_the_workflow():
    """DurableQueue / processes queued items and resumes the workflow"""

    def program():
        execution_id = yield from SuccessWorkflow.execute(
            {"id": "success", "value": 41}, discard=True
        )
        polled = yield from _poll_until_complete(SuccessWorkflow.poll(execution_id))
        assert polled == Complete(fx.Success(42))

    yield from fx.gen(program).pipe(fx.provide(SuccessLayer))


FailureQueue = durable_queue.make(
    name="DurableQueueTest/FailureQueue",
    payload=S.Struct(Id),
    success=S.Null,
    error=S.String,
    idempotency_key=lambda p: p["id"],
)
FailureWorkflow = workflow.make(
    "DurableQueueTest/FailureWorkflow",
    payload=S.Struct(Id),
    success=S.Null,
    error=S.String,
    idempotency_key=lambda p: p["id"],
)
_FailureWorkers = _merge_build_nothing(
    FailureWorkflow.to_layer(lambda p, _id: FailureQueue.process(p)),
    FailureQueue.worker(lambda _p: fx.fail("boom")),
)
FailureLayer = _FailureWorkers.pipe(fx.layer.provide_merge(workflow_engine.layer_memory)).pipe(
    fx.layer.provide_merge(PERSISTED_QUEUE_LAYER)
)


@testing.effect
def test_propagates_worker_failures_to_the_workflow():
    """DurableQueue / propagates worker failures to the workflow"""

    def program():
        execution_id = yield from FailureWorkflow.execute({"id": "failure"}, discard=True)
        polled = yield from _poll_until_complete(FailureWorkflow.poll(execution_id))
        assert isinstance(polled, Complete) and isinstance(polled.exit, fx.Failure)
        errors = [r.error for r in polled.exit.cause.reasons if isinstance(r, Fail)]
        assert errors[:1] == ["boom"]

    yield from fx.gen(program).pipe(fx.provide(FailureLayer))
