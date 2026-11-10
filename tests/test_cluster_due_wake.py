"""A message due later (a durable clock's wake-up) is read when it falls due,
not at the next storage poll (DOGFOOD outlay #3).

Effect finds such a message only by the storage poll
(``entityMessagePollInterval``, 10 s), so under the test clock a wake-up
fired up to 10 s late and a test adjusting just past it stalled. The runner
that stores the message also wakes its storage read at the message's due
time, on the ``Clock`` service; the poll remains the fallback for messages
another runner stored (PARITY.md §4).
"""

from __future__ import annotations

from dataclasses import replace
from typing import TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import (
    cluster_workflow_engine,
    message_storage,
    runner_health,
    runner_storage,
    runners,
    sharding,
    sharding_config,
)
from pyfect.duration import Duration
from pyfect.workflow import WorkflowEngine, durable_clock, workflow


class Payload(TypedDict):
    id: str


W = workflow.make(
    "DueWake", payload=S.Struct(Payload), success=S.String, idempotency_key=lambda p: p["id"]
)


def _app(*, poll_interval: float, sleep: float) -> fx.Layer[WorkflowEngine]:
    def handler(_p: Payload, _id: str):
        def body():
            yield from durable_clock.sleep(name="deadline", duration=Duration(sleep))
            return "woke"

        return fx.gen(body)

    config = replace(sharding_config.DEFAULTS, entity_message_poll_interval=Duration(poll_interval))
    runner = (
        sharding.layer.pipe(fx.layer.provide_merge(runners.layer_noop))
        .pipe(fx.layer.provide_merge(message_storage.layer_memory))
        .pipe(
            fx.layer.provide(fx.layer.merge(runner_storage.layer_memory, runner_health.layer_noop))
        )
        .pipe(fx.layer.provide(sharding_config.layer(config)))
    )
    return W.to_layer(handler).pipe(
        fx.layer.provide_merge(cluster_workflow_engine.layer.pipe(fx.layer.provide_merge(runner)))
    )


def _run_past_the_deadline(app: fx.Layer[WorkflowEngine], after: float) -> fx.Effect[str]:
    def scenario():
        running = yield from W.execute({"id": "a"}).fork()
        yield from testing.adjust("1 second")
        yield from testing.adjust(Duration(after - 1))
        return (yield from running.join())

    return fx.gen(scenario).pipe(fx.provide(app))


@testing.effect
def test_a_durable_clock_wakes_when_due_not_at_the_next_poll():
    # Polls at 10 s, 20 s, ... 60 s, then 70 s: 62 s is between two polls.
    assert (yield from _run_past_the_deadline(_app(poll_interval=10, sleep=61), 62)) == "woke"
