"""Ports of the fork and interruption cases of Effect's ``Effect.test.ts``
that exercise a forked fiber being interrupted: races, ``forEach``
interruption, ``acquireRelease`` and the "interruption" block.

Each test's docstring is the Effect test title. ``Effect.forkChild`` is
``fork``; ``Scope.provide(scope)`` is ``fx.scope.provide(scope)``.
A resume in Effect runs the woken fiber at once; in pyfect it goes through
the scheduler, so a port yields where Effect's fiber would already have run.
"""

from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect import metric, testing
from pyfect._fiber import Fiber
from pyfect._stack_frame import CurrentStackFrame, InterruptorStackTrace, StackFrame
from pyfect.scope import CloseableScope

from ._custom_scheduler import Custom, drain, on


def _interrupted(ex: fx.Exit[Any, Any] | None) -> bool:
    return isinstance(ex, fx.Failure) and ex.cause.has_interrupts


def _on_interrupt[A, E](eff: fx.Effect[A, E], log: list[str], label: str) -> fx.Effect[A, E]:
    return eff.on_interrupt(fx.sync(lambda: log.append(label)))


@testing.effect
def test_race_interrupts_the_loser_when_the_other_side_succeeds():
    """race interrupts the loser when the other side succeeds"""
    interrupted: list[str] = []
    fast = _on_interrupt(fx.succeed("fast").delay("100 millis"), interrupted, "fast")
    slow = _on_interrupt(fx.succeed("slow").delay("500 millis"), interrupted, "slow")
    fiber = yield from fast.race(slow).fork()
    yield from testing.adjust("500 millis")
    assert (yield from fiber.join()) == "fast"
    assert interrupted == ["slow"]


@testing.effect
def test_race_first_interrupts_the_loser_when_the_other_side_succeeds():
    """raceFirst interrupts the loser when the other side succeeds"""
    interrupted: list[str] = []
    fast = _on_interrupt(fx.succeed("fast").delay("100 millis"), interrupted, "fast")
    slow = _on_interrupt(fx.succeed("slow").delay("500 millis"), interrupted, "slow")
    fiber = yield from fast.race_first(slow).fork()
    yield from testing.adjust("500 millis")
    assert (yield from fiber.join()) == "fast"
    assert interrupted == ["slow"]


@testing.effect
def test_race_first_interrupts_the_loser_when_the_other_side_fails():
    """raceFirst interrupts the loser when the other side fails"""
    interrupted: list[str] = []
    slow = _on_interrupt(fx.succeed("slow").delay("500 millis"), interrupted, "slow")
    fiber = yield from fx.fail("boom").delay("100 millis").race_first(slow).exit().fork()
    yield from testing.adjust("500 millis")
    assert (yield from fiber.join()) == fx.exit.fail("boom")
    assert interrupted == ["slow"]


RACES = ["race", "race_first"]


# Every combinator that forks racers through the one race loop, for the
# "settles the race" titles (Effect's own run race and raceFirst).
ALL_RACES = [*RACES, "race_all", "race_all_first"]


def _race(name: str, a: fx.Effect[Any, Any], b: fx.Effect[Any, Any]) -> fx.Effect[Any, Any]:
    match name:
        case "race":
            return a.race(b)
        case "race_first":
            return a.race_first(b)
        case "race_all":
            return fx.race_all(a, b)
        case _:
            return fx.race_all_first(a, b)


@pytest.mark.parametrize("name", ALL_RACES)
@testing.effect
def test_interrupts_a_loser_that_settles_the_race_while_starting(name: str):
    """${name} interrupts a loser that settles the race while starting"""
    after_settle_ran = False
    loser_exit: list[fx.Exit[int, Any]] = []

    def after_settle() -> int:
        nonlocal after_settle_ran
        after_settle_ran = True
        return 41

    deferred = yield from fx.Deferred[str].make()
    loser = (
        deferred.succeed("winner")
        .and_then(fx.sync(after_settle))
        .on_exit(lambda ex: fx.sync(lambda: loser_exit.append(ex)))
    )
    result = yield from _race(name, deferred.wait(), loser)
    assert result == "winner"
    assert not after_settle_ran
    assert len(loser_exit) == 1
    assert isinstance(loser_exit[0], fx.Failure)
    assert loser_exit[0].cause.has_interrupts_only


@pytest.mark.parametrize("name", ALL_RACES)
@testing.effect
def test_does_not_evaluate_a_loser_when_the_race_settles_during_fiber_construction(name: str):
    """${name} does not evaluate a loser when the race settles during fiber construction"""
    stop = yield from fx.Deferred[str].make()
    starts = 0
    ends = 0
    ran = False

    class Metrics:
        def record_fiber_start(self, context: fx.Context) -> None:
            nonlocal starts
            starts += 1
            if starts == 2:
                stop.done_unsafe(fx.exit.succeed("stop"))

        def record_fiber_end(self, context: fx.Context, exit: fx.Exit[Any, Any]) -> None:
            nonlocal ends
            ends += 1

    def loser() -> str:
        nonlocal ran
        ran = True
        return "loser"

    result = yield from _race(name, stop.wait(), fx.sync(loser)).pipe(
        fx.provide_service(metric.FiberRuntimeMetrics, Metrics())
    )
    assert result == "stop"
    assert not ran
    assert starts == 2
    assert ends == 2


@pytest.mark.parametrize("name", RACES)
@testing.effect
def test_interrupts_the_loser_when_interrupted_while_starting(name: str):
    """${name} interrupts the loser when interrupted while starting"""
    interrupted: list[str] = []

    @fx.gen
    def body():
        parent = fx.Fiber.get_current()
        assert parent is not None
        loser = _on_interrupt(
            fx.sync(lambda: parent.interrupt_as_unsafe(None)).and_then(fx.never),
            interrupted,
            "loser",
        )
        return (yield from _race(name, loser, fx.void))

    fiber = yield from body.fork()
    yield from fiber.await_exit()
    assert interrupted == ["loser"]


@pytest.mark.parametrize("name", RACES)
@testing.effect
def test_interrupts_a_pending_loser_before_the_parent_resumes(name: str):
    """${name} interrupts a pending loser before the parent resumes"""
    tasks: list[Callable[[], None]] = []
    parent: list[Fiber[Any, Any]] = []
    yield_parent = [False]

    def should_yield(fiber: Fiber[Any, Any]) -> bool:
        if not yield_parent[0] or fiber not in parent:
            return False
        yield_parent[0] = False
        return True

    scheduler = Custom(should_yield, tasks)
    winner = fx.Deferred[str]()
    frame = StackFrame("race", lambda: None, None)
    loser_exit: list[fx.Exit[str, Any]] = []

    def record(ex: fx.Exit[str, Any]) -> fx.Effect[None]:
        return fx.sync(lambda: loser_exit.append(ex))

    def racing(fiber: Fiber[Any, Any]) -> fx.Effect[str]:
        parent.append(fiber)
        loser = queue.take().on_exit(record)
        return _race(name, loser, winner.wait())

    queue = yield from fx.Queue[str].unbounded().pipe(on(scheduler))
    fiber = yield from (
        fx.with_fiber(racing)
        .pipe(fx.provide_service(CurrentStackFrame, frame))
        .pipe(on(scheduler))
        .fork(start_immediately=True)
    )
    # Wake the loser through a scheduled task, then settle the race while the
    # parent yields before it could interrupt the loser.
    queue.offer_unsafe("loser")
    yield_parent[0] = True
    winner.done_unsafe(fx.Success("winner"))
    drain(tasks)
    assert (yield from fiber.join()) == "winner"
    assert (yield from queue.size()) == 1
    [ex] = loser_exit
    assert isinstance(ex, fx.Failure)
    annotations = fx.cause.reason_annotations(ex.cause.reasons[0])
    assert annotations.get_unsafe(InterruptorStackTrace) is frame


def _record(done: list[int], i: int) -> fx.Effect[int]:
    def go() -> int:
        done.append(i)
        return i

    return fx.sync(go)


@testing.effect
def test_sequential_interrupt():
    """sequential interrupt"""
    done: list[int] = []
    fiber = yield from fx.for_each(
        range(1, 7), lambda i: _record(done, i).delay("300 millis")
    ).fork()
    yield from testing.adjust("800 millis")
    yield from fiber.interrupt()
    assert _interrupted((yield from fiber.await_exit()))
    assert done == [1, 2]


@testing.effect
def test_unbounded_interrupt():
    """unbounded interrupt"""
    done: list[int] = []
    fiber = yield from fx.for_each(
        range(1, 4), lambda i: _record(done, i).delay("150 millis"), concurrency="unbounded"
    ).fork()
    yield from testing.adjust("50 millis")
    yield from fiber.interrupt()
    assert _interrupted((yield from fiber.await_exit()))
    assert done == []


@testing.effect
def test_bounded_interrupt():
    """bounded interrupt"""
    done: list[int] = []
    fiber = yield from fx.for_each(
        range(1, 7), lambda i: _record(done, i).delay("200 millis"), concurrency=2
    ).fork()
    yield from testing.adjust("350 millis")
    yield from fiber.interrupt()
    assert _interrupted((yield from fiber.await_exit()))
    assert done == [1, 2]


@testing.live
def test_releases_on_interrupt():
    """releases on interrupt"""
    released: list[bool] = []
    fiber = yield from fx.scoped(
        fx.acquire_release(
            fx.succeed("foo").delay("100 millis"),
            lambda _a, _ex: fx.sync(lambda: released.append(True)),
        )
    ).fork(start_immediately=True)
    fiber.interrupt_as_unsafe(None)
    yield from fiber.await_exit()
    assert released == [True]


class ATag(fx.Tag[str], key="ATag"): ...


@testing.effect
def test_supports_release_dependencies():
    """supports release dependencies"""
    released: list[str] = []
    scope = CloseableScope()
    yield from (
        fx.acquire_release(
            fx.succeed("foo"),
            lambda _a, _ex: ATag().flat_map(lambda a: fx.sync(lambda: released.append(a))),
        )
        .pipe(fx.provide_service(ATag, "A"))
        .pipe(fx.scope.provide(scope))
    )
    yield from scope.close(fx.exit.succeed(None))
    assert released == ["A"]


@testing.effect
def test_sync_forever_is_interruptible():
    """sync forever is interruptible"""
    fiber = yield from fx.succeed(1).forever().fork()
    yield from fiber.interrupt()
    assert _interrupted(fiber.poll_unsafe())


@testing.effect
def test_interrupt_of_never_is_interrupted_with_cause():
    """interrupt of never is interrupted with cause"""
    fiber = yield from fx.never.fork()
    yield from fiber.interrupt()
    assert _interrupted(fiber.poll_unsafe())


@testing.live
def test_closing_scope_is_uninterruptible():
    """closing scope is uninterruptible"""
    ref: list[bool] = []
    child = fx.sleep("10 millis").and_then(fx.sync(lambda: ref.append(True)))
    fiber = yield from child.uninterruptible().fork(start_immediately=True)
    yield from fiber.interrupt()
    assert ref == [True]


@testing.effect
def test_callback_cleanup_effect_runs_on_interrupt():
    """callback cleanup effect runs on interrupt"""
    cleaned_up: list[bool] = []
    fiber = yield from fx.callback(lambda _resume: fx.sync(lambda: cleaned_up.append(True))).fork(
        start_immediately=True
    )
    yield from fiber.interrupt()
    assert cleaned_up == [True]
