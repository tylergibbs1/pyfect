"""Ports of Effect's ``test/workflow/Workflow.test.ts``.

Each test's docstring is the Effect test title. Effect's test pauses the
fiber with a custom ``Scheduler.shouldYield`` once the activity is
registered, then interrupts it. The port
sweeps ``MaxOpsBeforeYield`` budgets, interrupting the paused fiber each
time, and checks that some budget lands the pause between the acquisition
and the body.
"""

from __future__ import annotations

import functools
from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.workflow import workflow
from pyfect.workflow.workflow_engine import WorkflowInstance, WorkflowInstanceService

BUDGETS = range(1, 40)


class Empty(TypedDict):
    pass


@testing.effect
def test_releases_acquisition_interrupted_before_the_body_starts():
    """Workflow.wrapActivityResult / releases acquisition interrupted before the body starts"""
    wf = workflow.make(
        "ActivityInterruption",
        payload=S.Struct(Empty),
        idempotency_key=lambda _: "activity-interruption",
    )
    interrupted_before_body = 0
    for budget in BUDGETS:
        instance = WorkflowInstanceService.initial(wf, "acquisition")
        entered: list[bool] = []
        fiber = (
            yield from workflow.wrap_activity_result(
                fx.sync(functools.partial(entered.append, True)), lambda _: False
            )
            .pipe(fx.provide_service(WorkflowInstance, instance))
            .pipe(fx.provide_service(fx.MaxOpsBeforeYield, budget))
            .fork(start_immediately=True)
        )
        paused_registered = instance.activity_state.count == 1
        yield from fiber.interrupt()
        ex = yield from fiber.await_exit()
        if paused_registered and not entered:
            interrupted_before_body += 1
            assert isinstance(ex, fx.Failure) and ex.cause.has_interrupts
            # The acquisition was released: the latch it closed is open again.
            yield from instance.activity_state.latch.wait()
        assert instance.activity_state.count == 0
    assert interrupted_before_body > 0, "no budget paused between acquisition and body"
