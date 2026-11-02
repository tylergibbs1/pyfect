"""``CurrentScheduler``, ``MaxOpsBeforeYield`` and ``PreventSchedulerYield``
are References (Effect ``Scheduler.ts`` / ``References.ts``): a fiber reads
them from its context, so each can be provided to one effect."""

from collections.abc import Callable

import pyfect as fx
from pyfect import testing
from pyfect._wake_tracking import WakeTracker
from pyfect.duration import Seconds
from pyfect.exit import Success
from pyfect.scheduler import Cancel, Scheduler, SyncScheduler, Task
from pyfect.scope import CloseableScope


class CountingScheduler:
    """Counts the tasks scheduled on it and runs them on ``inner``."""

    def __init__(self, inner: Scheduler) -> None:
        self.inner = inner
        self.scheduled = 0

    def schedule(self, task: Task) -> None:
        self.scheduled += 1
        self.inner.schedule(task)

    def call_later(self, delay: Seconds, task: Task, *, daemon: bool = False) -> Cancel:
        return self.inner.call_later(delay, task, daemon=daemon)

    def track(self, tracker: WakeTracker, f: Callable[[], None]) -> None:
        self.inner.track(tracker, f)

    def outside_work(self) -> WakeTracker:
        return self.inner.outside_work()


def _two_workers(log: list[str]) -> fx.Effect[None]:
    def worker(name: str) -> fx.Effect[None]:
        return fx.for_each(range(3), lambda i: fx.sync(lambda: log.append(f"{name}{i}"))).as_void()

    @fx.gen
    def program():
        a = yield from worker("a").fork()
        b = yield from worker("b").fork()
        yield from a.join()
        yield from b.join()

    return program


_SEQUENTIAL = ["a0", "a1", "a2", "b0", "b1", "b2"]


def test_the_run_functions_provide_the_scheduler_they_run_on():
    assert isinstance(fx.run_sync(fx.CurrentScheduler()), SyncScheduler)


@testing.effect
def test_a_provided_scheduler_runs_the_tasks_of_that_effect_and_its_children():
    outer = yield from fx.CurrentScheduler()
    counting = CountingScheduler(outer)

    @fx.gen
    def on_counting():
        child = yield from fx.yield_now().fork()  # start + yield: two tasks
        yield from child.join()

    yield from on_counting.pipe(fx.provide_service(fx.CurrentScheduler, counting))
    during = counting.scheduled
    yield from fx.yield_now()
    assert during >= 2
    assert counting.scheduled == during


@testing.effect
def test_a_provided_budget_makes_fibers_yield_to_each_other():
    log: list[str] = []
    yield from _two_workers(log).pipe(fx.provide_service(fx.MaxOpsBeforeYield, 1))
    assert sorted(log) == _SEQUENTIAL
    assert log != _SEQUENTIAL


@testing.effect
def test_the_default_budget_lets_short_fibers_run_to_completion():
    log: list[str] = []
    yield from _two_workers(log)
    assert log == _SEQUENTIAL


@testing.effect
def test_the_budget_returns_to_the_outer_one_after_the_effect():
    inner: list[str] = []
    outer: list[str] = []
    yield from _two_workers(inner).pipe(fx.provide_service(fx.MaxOpsBeforeYield, 1))
    yield from _two_workers(outer)
    assert inner != _SEQUENTIAL
    assert outer == _SEQUENTIAL


@testing.effect
def test_prevent_scheduler_yield_ignores_the_budget():
    log: list[str] = []
    yield from (
        _two_workers(log)
        .pipe(fx.provide_service(fx.PreventSchedulerYield, True))
        .pipe(fx.provide_service(fx.MaxOpsBeforeYield, 1))
    )
    assert log == _SEQUENTIAL


def test_a_budget_below_one_still_makes_progress():
    """Effect 4.0.6 never finishes with a budget of 2 or less (each resume
    spends its budget yielding again); pyfect counts it as 1."""
    for budget in (0, -5):
        program = fx.for_each(range(10), fx.succeed).pipe(
            fx.provide_service(fx.MaxOpsBeforeYield, budget)
        )
        assert fx.run_sync(program) == list(range(10))


def test_the_references_read_their_defaults_and_provided_values():
    @fx.gen
    def program():
        default = yield from fx.MaxOpsBeforeYield()
        provided = yield from fx.MaxOpsBeforeYield().pipe(
            fx.provide_service(fx.MaxOpsBeforeYield, 16)
        )
        return default, provided, (yield from fx.PreventSchedulerYield())

    assert fx.run_sync(program) == (2048, 16, False)


@testing.effect
def test_an_interrupt_from_under_a_provided_scheduler_lands_at_once():
    """As in Effect 4.0.6 (checked under Node): interrupting a fiber that has
    not started yet stops it before it runs, even when the interrupter runs
    on a provided scheduler wrapping the one the fiber runs on."""
    log: list[str] = []
    on_counting = fx.provide_service(
        fx.CurrentScheduler, CountingScheduler((yield from fx.CurrentScheduler()))
    )
    child = yield from fx.sync(lambda: log.append("outer child ran")).fork()
    yield from child.interrupt().pipe(on_counting)
    child = yield from fx.sync(lambda: log.append("counting child ran")).fork().pipe(on_counting)
    yield from child.interrupt()
    assert log == []


def test_a_context_from_an_earlier_run_runs_on_the_current_runtime():
    """A finalizer keeps the context it was added under, as Effect's
    ``addFinalizer`` does. Closing its scope in a later run must not move the
    fiber onto the earlier run's scheduler, which nothing drives any more:
    a finalizer that yielded there would hang (Effect 4.0.6 runs it,
    checked under Node)."""
    scope = CloseableScope()
    ran_on: list[Scheduler] = []
    finalizer = fx.CurrentScheduler().flat_map(lambda s: fx.sync(lambda: ran_on.append(s)))
    fx.run_sync(scope.add_finalizer(lambda _: finalizer))

    @fx.gen
    def close():
        yield from scope.close(Success(None))
        return (yield from fx.CurrentScheduler())

    closed_on = fx.run_sync(close)
    assert ran_on == [closed_on]


def test_a_scheduler_provided_in_an_earlier_run_is_kept():
    scope = CloseableScope()
    ran_on: list[Scheduler] = []
    finalizer = fx.CurrentScheduler().flat_map(lambda s: fx.sync(lambda: ran_on.append(s)))

    @fx.gen
    def add():
        counting = CountingScheduler((yield from fx.CurrentScheduler()))
        yield from scope.add_finalizer(lambda _: finalizer).pipe(
            fx.provide_service(fx.CurrentScheduler, counting)
        )
        return counting

    counting = fx.run_sync(add)
    fx.run_sync(scope.close(Success(None)))
    assert ran_on == [counting]


class ImmediateScheduler(CountingScheduler):
    """Runs each task the moment it is scheduled."""

    def schedule(self, task: Task) -> None:
        task()


@testing.effect
def test_a_scheduler_that_runs_tasks_at_once_does_not_nest_fibers():
    """A task scheduled from inside a fiber's run waits for that run to end,
    so a scheduled child still starts after its parent's step and a fiber's
    own ``yield_now`` does not re-enter it."""
    outer = yield from fx.CurrentScheduler()
    log: list[str] = []

    @fx.gen
    def program():
        child = yield from fx.sync(lambda: log.append("child")).fork()
        log.append("parent")
        yield from fx.yield_now()
        log.append("after yield")
        yield from child.join()

    yield from program.pipe(fx.provide_service(fx.CurrentScheduler, ImmediateScheduler(outer)))
    assert log == ["parent", "child", "after yield"]
