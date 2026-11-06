"""Ports of Effect's ``Scheduler.test.ts``.

Omitted:

- ``runSyncExit does not schedule timers after yielding``: spies on the
  JavaScript host's ``setImmediate``; ``run_sync`` never fires a timer here.
- ``MixedScheduler falls back to a microtask when timers cannot be set``: a
  JavaScript host restriction.
"""

from collections.abc import Callable
from typing import Any, Never

import pyfect as fx
from pyfect import testing
from pyfect.errors import AsyncFiberError
from pyfect.exit import Success
from pyfect.scheduler import (
    EffectScheduler,
    MixedScheduler,
    SchedulerDispatcher,
)


class _Hooked(EffectScheduler):
    """Effect's ``{ executionMode, makeDispatcher, shouldYield }``."""

    def __init__(self, should_yield: Callable[[fx.Fiber[Any, Any]], bool]) -> None:
        self._should_yield = should_yield
        self._mixed = MixedScheduler()

    def should_yield(self, fiber: fx.Fiber[Any, Any]) -> bool:
        return self._should_yield(fiber)

    def make_dispatcher(self) -> SchedulerDispatcher:
        return self._mixed.make_dispatcher()


def test_run_sync_exit_does_not_create_a_dispatcher_for_synchronous_effects():
    """runSyncExit does not create a dispatcher for synchronous effects"""
    made: list[int] = []

    class Counting(MixedScheduler):
        def make_dispatcher(self) -> SchedulerDispatcher:
            made.append(1)
            return super().make_dispatcher()

    ex = fx.run_sync_exit(
        fx.sync(lambda: 1).pipe(fx.provide_service(fx.CurrentScheduler, Counting()))
    )
    assert ex == Success(1)
    assert made == []


def test_run_sync_exit_flushes_dispatcher_work_after_yielding():
    """runSyncExit flushes dispatcher work after yielding"""
    assert fx.run_sync_exit(fx.yield_now().as_(1)) == Success(1)


def test_run_sync_exit_of_a_sleep_dies_with_async_fiber_error():
    """Effect.runSyncExit(Effect.sleep(...)), under Node: a Die with
    AsyncFiberError."""
    ex = fx.run_sync_exit(fx.sleep(0.01))
    assert isinstance(ex, fx.Failure)
    error = ex.cause.squash()
    assert isinstance(error, AsyncFiberError)
    assert error.message == "An asynchronous Effect was executed with Effect.runSync"


def test_run_sync_raises_the_async_fiber_error():
    """Effect.runSync throws the squashed cause."""
    try:
        fx.run_sync(fx.sleep(0.01))
    except AsyncFiberError:
        return
    raise AssertionError("expected AsyncFiberError")


def test_run_sync_of_from_async_dies_with_async_fiber_error():
    """Effect.runSyncExit(Effect.promise(...)), under Node."""

    async def go() -> int:
        return 1

    ex = fx.run_sync_exit(fx.from_async(go))
    assert isinstance(ex, fx.Failure)
    assert isinstance(ex.cause.squash(), AsyncFiberError)


def test_mixed_scheduler_orders_by_priority_sync():
    """MixedScheduler orders by priority (sync)"""
    dispatcher = MixedScheduler("sync").make_dispatcher()
    order: list[str] = []
    for label, priority in (("p0-1", 0), ("p10-1", 10), ("p-1-1", -1), ("p10-2", 10), ("p0-2", 0)):
        dispatcher.schedule_task(lambda label=label: order.append(label), priority)
    assert order == []
    dispatcher.flush()
    assert order == ["p-1-1", "p0-1", "p0-2", "p10-1", "p10-2"]


def test_mixed_scheduler_is_fifo_within_a_priority():
    """MixedScheduler is FIFO within a priority"""
    dispatcher = MixedScheduler("sync").make_dispatcher()
    order: list[int] = []
    for i in (1, 2, 3):
        dispatcher.schedule_task(lambda i=i: order.append(i), 5)
    dispatcher.flush()
    assert order == [1, 2, 3]


@testing.effect
def test_yield_now_with_resumes_lowest_priority_first():
    """Effect.ts yieldNowWith: lower numbers resume first within a tick."""
    order: list[str] = []

    def task(label: str, priority: int) -> fx.Effect[None]:
        return fx.yield_now_with(priority).flat_map(lambda _: fx.sync(lambda: order.append(label)))

    fibers: list[fx.Fiber[None, Never]] = []
    for label, priority in (("high", 10), ("first", -1), ("zero", 0)):
        fibers.append((yield from task(label, priority).fork(start_immediately=True)))
    for fiber in fibers:
        yield from fiber.join()
    assert order == ["first", "zero", "high"]


def _chain(label: str, order: list[str]) -> fx.Effect[int]:
    def step(n: int) -> int:
        order.append(label)
        return n + 1

    effect = fx.succeed(0)
    for _ in range(100):
        effect = effect.map(step)
    return effect


@testing.effect
def test_prevent_scheduler_yield_disables_should_yield_checks():
    """PreventSchedulerYield disables shouldYield checks"""
    calls: list[int] = []

    def should_yield(_fiber: fx.Fiber[Any, Any]) -> bool:
        calls.append(1)
        return False

    scheduler = _Hooked(should_yield)
    yield from (
        fx.sync(lambda: None)
        .map(lambda _: None)
        .pipe(fx.provide_service(fx.CurrentScheduler, scheduler))
    )
    assert len(calls) > 0

    calls.clear()
    yield from (
        fx.sync(lambda: None)
        .map(lambda _: None)
        .pipe(fx.provide_service(fx.CurrentScheduler, scheduler))
        .pipe(fx.provide_service(fx.PreventSchedulerYield, True))
    )
    assert calls == []


@testing.effect
def test_prevent_scheduler_yield_disables_the_step_budget():
    # Without a hook the check is the step budget: two concurrent chains
    # under a budget of 16 interleave, and run one after the other with
    # PreventSchedulerYield (as in Effect 4.0.6 under Node).
    checked: list[str] = []
    yield from fx.all(_chain("a", checked), _chain("b", checked), concurrency="unbounded").pipe(
        fx.provide_service(fx.MaxOpsBeforeYield, 16)
    )
    assert "".join(checked) != "a" * 100 + "b" * 100

    prevented: list[str] = []
    yield from (
        fx.all(_chain("a", prevented), _chain("b", prevented), concurrency="unbounded")
        .pipe(fx.provide_service(fx.MaxOpsBeforeYield, 16))
        .pipe(fx.provide_service(fx.PreventSchedulerYield, True))
    )
    assert "".join(prevented) == "a" * 100 + "b" * 100


@testing.effect
def test_a_custom_should_yield_replaces_the_step_budget():
    # A scheduler saying yes every 4 steps interleaves the chains under the
    # default budget of 2048; one that never says yes keeps them apart
    # under a budget of 1.
    every_four = _Hooked(lambda fiber: fiber.current_op_count >= 4)
    order: list[str] = []
    yield from fx.all(_chain("a", order), _chain("b", order), concurrency="unbounded").pipe(
        fx.provide_service(fx.CurrentScheduler, every_four)
    )
    assert "".join(order) != "a" * 100 + "b" * 100

    kept: list[str] = []
    yield from (
        fx.all(_chain("a", kept), _chain("b", kept), concurrency="unbounded")
        .pipe(fx.provide_service(fx.CurrentScheduler, _Hooked(lambda _f: False)))
        .pipe(fx.provide_service(fx.MaxOpsBeforeYield, 1))
    )
    assert "".join(kept) == "a" * 100 + "b" * 100


@testing.effect
def test_a_raising_should_yield_is_a_defect():
    def broken(_fiber: fx.Fiber[Any, Any]) -> bool:
        raise ValueError("hook")

    ex = (
        yield from fx.sync(lambda: 1)
        .map(lambda n: n + 1)
        .pipe(fx.provide_service(fx.CurrentScheduler, _Hooked(broken)))
        .exit()
    )
    assert isinstance(ex, fx.Failure)
    assert isinstance(ex.cause.squash(), ValueError)


@testing.effect
def test_inlined_map_steps_count_against_max_ops_before_yield():
    """Scheduler.test.ts "inlined map steps count against MaxOpsBeforeYield"."""
    order: list[str] = []
    yield from fx.all(_chain("a", order), _chain("b", order), concurrency="unbounded").pipe(
        fx.provide_service(fx.MaxOpsBeforeYield, 16)
    )
    assert "".join(order) != "a" * 100 + "b" * 100
