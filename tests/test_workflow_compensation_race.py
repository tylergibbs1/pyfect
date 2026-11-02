"""A compensation survives a run preempted by a deferred completion.

A ``race_all`` over a deferred and a short (in-memory) durable sleep keeps the
run live while it waits; completing the deferred then interrupts that run to
replay it. The preempted run is a suspension, not the end of the execution, so
the compensation registered before the race still runs when the replay fails.

Effect's ``layerMemory`` loses it (its ``onExit`` closes the execution's scope
for any exit but ``Success(Suspended)``, printed under Node: ``['step']``), so
these cases pin pyfect's fix rather than an Effect result (PARITY.md §4).
"""

from __future__ import annotations

from typing import Any, Never, TypedDict

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.cluster import cluster_workflow_engine, test_runner
from pyfect.workflow import activity, durable_clock, durable_deferred, workflow, workflow_engine


class Payload(TypedDict):
    id: str


W = workflow.make(
    "CompensatedRace",
    payload=S.Struct(Payload),
    success=S.String,
    error=S.String,
    idempotency_key=lambda p: p["id"],
)
Decision = durable_deferred.make("decision", success=S.Boolean)

ENGINES: dict[str, fx.Layer[Any, Never, Never]] = {
    "memory": workflow_engine.layer_memory,
    "cluster": cluster_workflow_engine.layer.pipe(fx.layer.provide_merge(test_runner.layer)),
}


def _app(log: list[str], engine: str) -> fx.Layer[Any, Never, Never]:
    def handler(_p: Payload, _id: str):
        def body():
            yield from activity.make(
                name="step", success=S.String, execute=fx.sync(lambda: log.append("step") or "v")
            ).pipe(W.with_compensation(lambda v, _c: fx.sync(lambda: log.append(f"undo {v}"))))
            ok = yield from durable_deferred.race_all(
                name="decision-or-deadline",
                success=S.Boolean,
                error=S.Never,
                effects=[
                    Decision.wait(),
                    durable_clock.sleep(name="deadline", duration=30).as_(False),
                ],
            )
            if not ok:
                return (yield from fx.fail("rejected"))
            return "done"

        return fx.gen(body)

    return W.to_layer(handler).pipe(fx.layer.provide_merge(ENGINES[engine]))


@pytest.mark.parametrize("engine", ENGINES)
@testing.effect
def test_a_deferred_completed_during_a_race_with_a_short_sleep_keeps_the_compensation(
    engine: str,
):
    log: list[str] = []

    def scenario():
        payload: Payload = {"id": "x"}
        token = yield from Decision.token_from_payload(workflow=W, payload=payload)
        running = yield from W.execute(payload).exit().fork()
        # The run is inside the race: its deferred arm parked, the sleep running.
        while log != ["step"]:
            yield from fx.yield_now()
        yield from testing.adjust(1)
        yield from Decision.succeed(token=token, value=False)
        yield from testing.adjust(1)
        return (yield from running.join())

    exit_ = yield from fx.gen(scenario).pipe(fx.provide(_app(log, engine)))
    assert exit_.cause.find_fail().error == "rejected"  # pyright: ignore
    assert log == ["step", "undo v"]
