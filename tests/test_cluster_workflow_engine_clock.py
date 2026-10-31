"""A durable clock wakes at its exact millisecond (Effect adds the
duration's milliseconds to now, then rounds up): a duration of whole
milliseconds must not gain one from a float product."""

from __future__ import annotations

from datetime import timedelta

from oracle._cluster_workflows import EmailWorkflow, test_workflow_engine

import pyfect as fx
from pyfect import testing
from pyfect.clock import Clock, now_millis_unsafe
from pyfect.cluster.message_storage import MemoryDriver
from pyfect.workflow import durable_clock
from pyfect.workflow.workflow_engine import WorkflowEngine


@testing.effect
def test_a_whole_millisecond_clock_wakes_at_that_millisecond():
    @fx.gen
    def body():
        driver = yield from MemoryDriver()
        engine = yield from WorkflowEngine()
        started_at = now_millis_unsafe((yield from Clock()))
        # 2.007 * 1000 is 2006.9999999999998 in floating point.
        clock = durable_clock.make(name="exact", duration=timedelta(milliseconds=2007))
        yield from engine.schedule_clock(EmailWorkflow, execution_id="exact", clock=clock)
        (envelope,) = (
            m
            for m in driver.encoded.journal
            if m["_tag"] == "Request" and m["address"]["entityType"] == "Workflow/-/DurableClock"
        )
        assert driver.encoded.requests[envelope["requestId"]].deliver_at == started_at + 2007

    yield from body.pipe(fx.provide(test_workflow_engine))
