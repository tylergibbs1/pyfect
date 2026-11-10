"""The race workflows of Effect's ``ClusterWorkflowEngine.test.ts``
(``RaceWorkflowLayers``)."""

from __future__ import annotations

import functools
from dataclasses import dataclass
from typing import Any

import pyfect as fx
from pyfect import schema as S
from pyfect.context import Tag
from pyfect.latch import Latch
from pyfect.workflow import activity, durable_clock, durable_deferred, workflow

from ._cluster_workflows import ID, Flags, IdPayload


def _make(tag: str, *, error: Any = S.Never) -> workflow.Workflow[Any, Any, Any]:
    return workflow.make(
        tag, payload=ID, success=S.String, error=error, idempotency_key=lambda p: p["id"]
    )


def _bump(flags: dict[str, Any], key: str) -> None:
    runs = flags.get(key)
    flags[key] = runs + 1 if isinstance(runs, int) else 1


def _slow(name: str, seconds: float, value: str = "slow") -> activity.Activity[str, Any, Any]:
    return activity.make(
        name=name, success=S.String, execute=fx.sleep(fx.duration.seconds(seconds)).as_(value)
    )


def _race(name: str, *effects: fx.Effect[Any, Any, Any]) -> fx.Effect[Any, Any, Any]:
    return durable_deferred.race_all(
        name=name, success=S.String, error=S.Never, effects=list(effects)
    )


def _durable_sleep(name: str, millis: int) -> fx.Effect[None, Any, Any]:
    return durable_clock.sleep(
        name=name, duration=fx.duration.seconds(millis / 1000), in_memory_threshold=0
    )


RaceWorkflow = _make("RaceWorkflow")


def _race_workflow(_: IdPayload, __: str):
    @fx.gen
    def body():
        flags = yield from Flags()
        yield from fx.add_finalizer(lambda _: fx.sync(lambda: flags.__setitem__("finalizer", True)))

        def racer(n: int, millis: int) -> activity.Activity[str, Any, Any]:
            return activity.make(
                name=f"Activity{n}",
                success=S.String,
                execute=fx.succeed(f"Activity{n}")
                .delay(fx.duration.seconds(millis / 1000))
                .on_interrupt(fx.sync(lambda: flags.__setitem__(f"interrupt{n}", True))),
            )

        return (
            yield from activity.race_all("race", [racer(1, 1000), racer(2, 500), racer(3, 100)])
        )

    return body


FailureRaceWorkflow = _make("FailureRaceWorkflow", error=S.String)


def _failure_race(_: IdPayload, __: str):
    return activity.race_all(
        "failure-race",
        [
            activity.make(
                name="failure-race-fast", success=S.String, error=S.String, execute=fx.fail("boom")
            ),
            activity.make(
                name="failure-race-slow",
                success=S.String,
                error=S.String,
                execute=fx.sleep("1 second").as_("slow"),
            ),
        ],
    )


DurableRaceWorkflow = _make("DurableRaceWorkflow")
DurableRaceGate = durable_deferred.make("DurableRaceGate")


def _durable_race(_: IdPayload, __: str):
    @fx.gen
    def body():
        flags = yield from Flags()
        yield from fx.add_finalizer(lambda _: fx.sync(lambda: flags.__setitem__("finalizer", True)))

        def racer(n: int, millis: int) -> activity.Activity[str, Any, Any]:
            return activity.make(
                name=f"Activity{n}",
                success=S.String,
                execute=_durable_sleep(f"Activity{n}", millis).as_(f"Activity{n}"),
            )

        result = yield from activity.race_all(
            "race", [racer(1, 50000), racer(2, 10000), racer(3, 1000)]
        )
        flags["durable-race-token"] = yield from DurableRaceGate.token()
        yield from DurableRaceGate.wait()
        return result

    return body


MixedRaceWorkflow = _make("MixedRaceWorkflow")
MixedRaceGate = durable_deferred.make("MixedRaceGate", success=S.String)


def _mixed_race(_: IdPayload, __: str):
    return _race("mixed-race", MixedRaceGate.wait(), _slow("mixed-race-activity", 1, "activity"))


LosingDeferredWorkflow = _make("LosingDeferredWorkflow")
LosingDeferredGate = durable_deferred.make("LosingDeferredGate", success=S.String)


def _losing_deferred(_: IdPayload, __: str):
    @fx.gen
    def body():
        flags = yield from Flags()
        winner = yield from _race(
            "losing-deferred",
            LosingDeferredGate.wait(),
            _slow("losing-deferred-activity", 1, "activity"),
        )

        def tail_body() -> fx.Effect[str]:
            _bump(flags, "losing-deferred-tail-runs")
            return fx.sleep("10 seconds").as_("tail")

        tail = yield from activity.make(
            name="losing-deferred-tail", success=S.String, execute=fx.suspend(tail_body)
        )
        return f"{winner}:{tail}"

    return body


InPlaceWakeWorkflow = _make("InPlaceWakeWorkflow")
InPlaceWakeGate = durable_deferred.make("InPlaceWakeGate", success=S.String)


def _in_place_wake(_: IdPayload, __: str):
    @fx.gen
    def body():
        flags = yield from Flags()
        _bump(flags, "in-place-wake-runs")
        return (
            yield from _race(
                "in-place-wake",
                InPlaceWakeGate.wait(),
                _slow("in-place-wake-activity", 5, "activity"),
            )
        )

    return body


IntoWrapWorkflow = _make("IntoWrapWorkflow")
IntoWrapGate = durable_deferred.make("IntoWrapGate", success=S.String)
IntoWrapAux = durable_deferred.make("IntoWrapAux", success=S.String)


def _into_wrap(_: IdPayload, __: str):
    return _race(
        "into-wrap",
        IntoWrapAux.into(IntoWrapGate.wait()),
        _slow("into-wrap-activity", 30, "activity"),
    )


ClockCaptureWorkflow = _make("ClockCaptureWorkflow")


def _clock_capture(_: IdPayload, __: str):
    return activity.race_all(
        "clock-capture",
        [
            activity.make(
                name="clock-capture-durable",
                success=S.String,
                execute=_durable_sleep("clock-capture-durable", 5000).as_("clock"),
            ),
            _slow("clock-capture-slow", 30),
        ],
    )


BareClockWorkflow = _make("BareClockWorkflow")


def _bare_clock(_: IdPayload, __: str):
    return _race(
        "bare-clock",
        _durable_sleep("bare-clock-timer", 5000).as_("clock"),
        _slow("bare-clock-slow", 30),
    )


MappedGateWorkflow = _make("MappedGateWorkflow")
MappedGate = durable_deferred.make("MappedGate", success=S.String)


def _mapped_gate(_: IdPayload, __: str):
    return _race(
        "mapped-gate", MappedGate.wait().map(lambda s: f"{s}!"), _slow("mapped-gate-slow", 30)
    )


PreGateWorkflow = _make("PreGateWorkflow")
PreGate = durable_deferred.make("PreGate", success=S.String)


def _pre_gate(_: IdPayload, __: str):
    @fx.gen
    def branch():
        a = yield from activity.make(
            name="pre-gate-activity", success=S.String, execute=fx.succeed("act")
        )
        s = yield from PreGate.wait()
        return f"{a}:{s}"

    return _race("pre-gate", branch, _slow("pre-gate-slow", 30))


TwoStepWorkflow = _make("TwoStepWorkflow")
TwoStepGateA = durable_deferred.make("TwoStepGateA", success=S.String)
TwoStepGateB = durable_deferred.make("TwoStepGateB", success=S.String)


@dataclass(frozen=True)
class BranchControl:
    entered: Latch
    release: Latch
    started: Latch


class TwoStepBranchControl(Tag[BranchControl], key="TwoStepBranchControl"):
    pass


two_step_branch_control_layer = fx.layer.sync(
    TwoStepBranchControl, lambda: BranchControl(Latch(), Latch(), Latch())
)


def _two_step(_: IdPayload, __: str):
    @fx.gen
    def branch():
        flags = yield from Flags()
        control = yield from TwoStepBranchControl()
        control.entered.open_unsafe()
        yield from control.release.wait()
        _bump(flags, "two-step-branch-runs")
        control.started.open_unsafe()
        a = yield from TwoStepGateA.wait()
        b = yield from TwoStepGateB.wait()
        return f"{a}:{b}"

    # A live branch that holds no activity slot, so wake re-runs are
    # processed while the race stays active.
    return _race("two-step", branch, fx.never)


SlowUnwindWorkflow = _make("SlowUnwindWorkflow")
SlowUnwindGateA = durable_deferred.make("SlowUnwindGateA", success=S.String)
SlowUnwindGateB = durable_deferred.make("SlowUnwindGateB", success=S.String)


def _slow_unwind(_: IdPayload, __: str):
    @fx.gen
    def body():
        flags = yield from Flags()
        _bump(flags, "slow-unwind-runs")
        return (
            yield from _race(
                "slow-unwind", SlowUnwindGateA.wait(), SlowUnwindGateB.wait()
            ).ensuring(
                # Slows the unwind so completions can land while a suspension commits.
                fx.sync(lambda: flags.__setitem__("slow-unwind-started", True)).and_then(
                    fx.sleep("10 seconds")
                )
            )
        )

    return body


TwoGateWorkflow = _make("TwoGateWorkflow")
TwoGateA = durable_deferred.make("TwoGateA", success=S.String)
TwoGateB = durable_deferred.make("TwoGateB", success=S.String)


def _two_gate(_: IdPayload, __: str):
    return _race("two-gates", TwoGateA.wait(), TwoGateB.wait())


race_workflow_layers: fx.Layer[Any, Any, Any] = functools.reduce(
    fx.layer.merge,
    [
        RaceWorkflow.to_layer(_race_workflow),
        FailureRaceWorkflow.to_layer(_failure_race),
        DurableRaceWorkflow.to_layer(_durable_race),
        MixedRaceWorkflow.to_layer(_mixed_race),
        LosingDeferredWorkflow.to_layer(_losing_deferred),
        InPlaceWakeWorkflow.to_layer(_in_place_wake),
        IntoWrapWorkflow.to_layer(_into_wrap),
        ClockCaptureWorkflow.to_layer(_clock_capture),
        BareClockWorkflow.to_layer(_bare_clock),
        MappedGateWorkflow.to_layer(_mapped_gate),
        TwoStepWorkflow.to_layer(_two_step),
        PreGateWorkflow.to_layer(_pre_gate),
        SlowUnwindWorkflow.to_layer(_slow_unwind),
        TwoGateWorkflow.to_layer(_two_gate),
    ],
)
