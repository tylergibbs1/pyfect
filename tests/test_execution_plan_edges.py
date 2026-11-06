"""ExecutionPlan edge cases beyond ``ExecutionPlan.test.ts``, each result
printed by Effect under Node first: how a fallback step counts the failure
it takes over, a partial-stream guard that writes nothing, and a captured
layer step."""

from collections.abc import Callable
from dataclasses import dataclass

import pytest

import pyfect as fx
from pyfect import cause, execution_plan, layer, schedule, stream, testing
from pyfect.context import Context
from pyfect.execution_plan import Step

EMPTY = Context.empty()


def _always_failing() -> tuple[list[int], fx.Effect[int, str]]:
    runs: list[int] = []

    def run() -> fx.Effect[int, str]:
        runs.append(len(runs) + 1)
        return fx.fail("x")

    return runs, fx.suspend(run)


@pytest.mark.parametrize(
    ("plan", "expected_runs"),
    [
        # The fallback step's first retry replays the earlier failure, so
        # one attempt is spent on it: attempts=1 runs once, recurs(0) never.
        (execution_plan.make(Step(EMPTY), Step(EMPTY, attempts=1)), 2),
        (execution_plan.make(Step(EMPTY), Step(EMPTY, schedule=schedule.recurs(0))), 1),
        (execution_plan.make(Step(EMPTY, attempts=2), Step(EMPTY, attempts=3)), 5),
        (execution_plan.make(Step(EMPTY), Step(EMPTY)), 2),
    ],
)
def test_a_fallback_step_counts_the_failure_it_takes_over(
    plan: execution_plan.ExecutionPlan[object], expected_runs: int
) -> None:
    runs, eff = _always_failing()
    ex = fx.run_blocking(eff.pipe(fx.with_execution_plan(plan)).exit())
    testing.assert_exit_failure(ex, cause.fail("x"))
    assert len(runs) == expected_runs


def _counted_stream(make: Callable[[int], stream.Stream[int, str]]) -> stream.Stream[int, str]:
    runs = 0

    def build() -> stream.Stream[int, str]:
        nonlocal runs
        runs += 1
        return make(runs)

    return stream.suspend(build)


def test_a_stream_fallback_step_counts_the_failure_it_takes_over() -> None:
    items: list[int] = []
    source = _counted_stream(lambda n: stream.make(n).concat(stream.fail(f"e{n}")))
    plan = execution_plan.make(Step(EMPTY), Step(EMPTY, attempts=1))
    ex = fx.run_blocking(
        source.pipe(stream.with_execution_plan(plan))
        .run_for_each(lambda i: fx.sync(lambda: items.append(i)))
        .exit()
    )
    testing.assert_exit_failure(ex, cause.fail("e2"))
    assert items == [1, 2]


def test_preventing_fallback_on_partial_streams_still_falls_back_before_any_item() -> None:
    items: list[int] = []
    source = _counted_stream(lambda n: stream.fail("e") if n == 1 else stream.make(7))
    plan = execution_plan.make(Step(EMPTY), Step(EMPTY))
    ex = fx.run_blocking(
        source.pipe(stream.with_execution_plan(plan, prevent_fallback_on_partial_stream=True))
        .run_for_each(lambda i: fx.sync(lambda: items.append(i)))
        .exit()
    )
    assert isinstance(ex, fx.Success)
    assert items == [7]


@dataclass(frozen=True)
class Named:
    name: str


class Policy(fx.Tag[Named]):
    pass


class Svc(fx.Tag[Named]):
    pass


@testing.effect
def test_capture_requirements_bakes_the_services_into_a_layer_step():
    svc_live = layer.effect(Svc, Policy().map(lambda p: Named(f"svc-{p.name}")))
    plan = execution_plan.make(Step(svc_live))
    captured = yield from plan.capture_requirements.pipe(
        fx.provide_service(Policy, Named("captured"))
    )
    read = Svc().map(lambda s: s.name)
    assert (yield from read.pipe(fx.with_execution_plan(captured))) == "svc-captured"
    ambient = read.pipe(fx.with_execution_plan(captured)).pipe(
        fx.provide_service(Policy, Named("ambient"))
    )
    assert (yield from ambient) == "svc-captured"
