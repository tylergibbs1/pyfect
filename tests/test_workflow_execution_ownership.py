"""An operation by execution id acts only on an execution of the workflow
it is called through: ``A.resume(id_of_B)`` (what ``<A>Resume`` on the
workflow proxy runs) and the other by-id operations leave ``B`` alone.
Effect's engines ignore the workflow; pyfect does not."""

from __future__ import annotations

import functools
from collections.abc import Callable
from typing import Any, Never, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.workflow import Suspended, workflow, workflow_engine
from pyfect.workflow.workflow_engine import WorkflowEngine


class Empty(TypedDict):
    pass


EMPTY = S.Struct(Empty)

A = workflow.make("Exposed", payload=EMPTY, idempotency_key=lambda _: "k")


def _a(_p: Empty, _id: str) -> fx.Effect[None]:
    return fx.void


# Every ``WorkflowEngineService`` member taking ``(workflow, execution_id)``.
type ById = Callable[[Any, Any, str], fx.Effect[Any, Any, Any]]
BY_ID: dict[str, ById] = {
    "resume": lambda engine, wf, id: engine.resume(wf, id),
    "interrupt": lambda engine, wf, id: engine.interrupt(wf, id),
    "interrupt_unsafe": lambda engine, wf, id: engine.interrupt_unsafe(wf, id),
    "poll": lambda engine, wf, id: engine.poll(wf, id),
}


def test_every_by_id_member_is_covered() -> None:
    from pyfect.workflow._services import WorkflowEngineService

    hints = WorkflowEngineService.__annotations__
    assert {name for name, hint in hints.items() if "ByExecutionId" in str(hint)} | {"poll"} == set(
        BY_ID
    )


@pytest.mark.parametrize("operation", sorted(BY_ID))
@testing.effect
def test_an_operation_through_another_workflow_leaves_the_execution_alone(operation: str):
    runs = {"n": 0}
    b = workflow.make(
        "Hidden", payload=EMPTY, error=S.String, idempotency_key=lambda _: "k"
    ).annotate(workflow.SuspendOnFailure, True)

    def handler(_p: Empty, _id: str) -> fx.Effect[Never, str]:
        def run() -> fx.Effect[Never, str]:
            runs["n"] += 1
            return fx.fail("boom")

        return fx.suspend(run)

    def program():
        execution_id = yield from b.execute({}, discard=True)
        result = yield from b.poll(execution_id)
        while not isinstance(result, Suspended):
            yield from fx.yield_now()
            result = yield from b.poll(execution_id)
        engine = yield from WorkflowEngine()
        seen = yield from BY_ID[operation](engine, A, execution_id)
        for _ in range(20):
            yield from fx.yield_now()
        assert runs["n"] == 1
        assert seen is None
        assert isinstance((yield from b.poll(execution_id)), Suspended)

    layers: fx.Layer[Any, Any, Any] = functools.reduce(
        fx.layer.merge, [A.to_layer(_a), b.to_layer(handler)]
    )
    yield from fx.gen(program).pipe(
        fx.provide(layers.pipe(fx.layer.provide_merge(workflow_engine.layer_memory)))
    )
