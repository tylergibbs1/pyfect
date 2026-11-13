"""Stream operators let go of what they handled once the run ends, without
the cycle collector (see ``tests/test_closure_cycles.py``)."""

from __future__ import annotations

from _closure_release import Handled, assert_freed_after_run

import pyfect as fx
from pyfect import execution_plan, stream
from pyfect.context import Context
from pyfect.execution_plan import Step

EMPTY = Context.empty()


def test_map_array_frees_its_upstream() -> None:
    assert_freed_after_run(lambda v: stream.make(v, Handled()).map_array(lambda c: c).run_drain())


def test_map_array_effect_frees_its_upstream() -> None:
    assert_freed_after_run(lambda v: stream.make(v).map_array_effect(fx.succeed).run_drain())


def test_rechunk_frees_its_upstream() -> None:
    assert_freed_after_run(lambda v: stream.make(v, Handled(), Handled()).rechunk(2).run_drain())


def test_paginate_frees_its_last_state() -> None:
    assert_freed_after_run(
        lambda v: stream.paginate(v, lambda _s: fx.succeed(((1,), None))).run_drain()
    )


def test_with_execution_plan_frees_the_last_error() -> None:
    plan = execution_plan.make(Step(EMPTY), Step(EMPTY, attempts=1))
    assert_freed_after_run(
        lambda v: stream.fail(v).pipe(stream.with_execution_plan(plan)).run_drain()
    )


def test_debounce_frees_the_upstream_failure() -> None:
    assert_freed_after_run(lambda v: stream.fail(v).debounce("1 millis").run_drain())


def test_throttle_enforce_frees_its_upstream() -> None:
    assert_freed_after_run(
        lambda v: (
            stream.make(v)
            .throttle(cost=len, units=1, duration="1 second", strategy="enforce")
            .run_drain()
        )
    )


def test_while_loop_frees_its_body() -> None:
    def build(v: Handled) -> fx.Effect[None]:
        left = [1]
        return fx.while_loop(
            while_=lambda: bool(left), body=lambda: fx.succeed(v), step=lambda _a: left.clear()
        )

    assert_freed_after_run(build)


def test_fiber_await_all_frees_the_exits() -> None:
    def build(v: Handled) -> fx.Effect[object]:
        return fx.yield_now().as_(v).fork().flat_map(lambda f: fx.Fiber.await_all([f]))

    assert_freed_after_run(build)


def test_tx_frees_its_body() -> None:
    assert_freed_after_run(lambda v: fx.tx(fx.succeed(v)))
