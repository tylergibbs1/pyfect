"""Ports of Effect's ``Scheduler.test.ts``.

Omitted:

- ``runSyncExit does not create a dispatcher for synchronous effects``: pyfect
  schedulers have no dispatchers.
- ``runSyncExit does not schedule timers after yielding``: ``run_sync`` drives
  its own queue; there are no host timers to spy on.
- ``MixedScheduler orders by priority (sync)``: pyfect tasks have no priority.
- ``MixedScheduler falls back to a microtask when timers cannot be set``: a
  JavaScript host restriction.
"""

import pyfect as fx
from pyfect import testing
from pyfect.exit import Success
from pyfect.scheduler import SyncScheduler


def test_run_sync_exit_flushes_dispatcher_work_after_yielding():
    """Scheduler.test.ts "runSyncExit flushes dispatcher work after yielding"."""
    assert fx.run_sync_exit(fx.yield_now().as_(1)) == Success(1)


def test_mixed_scheduler_is_fifo_within_a_priority():
    """Scheduler.test.ts "MixedScheduler is FIFO within a priority", on the
    ``SyncScheduler`` (which has one priority)."""
    scheduler = SyncScheduler()
    order: list[int] = []
    for i in (1, 2, 3):
        scheduler.schedule(lambda i=i: order.append(i))
    assert order == []
    scheduler.run_until(lambda: len(order) == 3)
    assert order == [1, 2, 3]


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
    """Scheduler.test.ts "PreventSchedulerYield disables shouldYield checks".
    pyfect has no ``shouldYield``: the check it disables is the step budget,
    so two concurrent chains under a budget of 16 interleave without it and
    run one after the other with it (as in Effect 4.0.6 under Node)."""
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
def test_inlined_map_steps_count_against_max_ops_before_yield():
    """Scheduler.test.ts "inlined map steps count against MaxOpsBeforeYield"."""
    order: list[str] = []
    yield from fx.all(_chain("a", order), _chain("b", order), concurrency="unbounded").pipe(
        fx.provide_service(fx.MaxOpsBeforeYield, 16)
    )
    assert "".join(order) != "a" * 100 + "b" * 100
