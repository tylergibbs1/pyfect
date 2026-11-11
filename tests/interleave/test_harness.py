"""The harness itself: it finds the bugs it is for, replays them exactly,
and explores what it claims to."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import contextvars
from collections.abc import Callable
from typing import Any

import pytest

import pyfect as fx
from pyfect._core import Effect
from pyfect._fiber import Fiber

from ._harness import (
    InterleaveFailure,
    RandomWalk,
    Replay,
    Scenario,
    ThreadBody,
    World,
    decode,
    encode,
    explore,
    replay,
    run_once,
)
from .scenarios import BY_NAME


class _HandingMailbox:
    """A broken primitive: ``put`` hands its value to a parked taker
    through a later step, which an interrupt can land on (CLAUDE.md: never
    hand a value to a parked fiber)."""

    def __init__(self) -> None:
        self.parked: list[Callable[[Effect[int]], None]] = []
        self.items: list[int] = []

    def take(self) -> fx.Effect[int]:
        def register(resume: Callable[[Effect[int]], None]) -> None:
            if self.items:
                resume(fx.succeed(self.items.pop(0)))
            else:
                self.parked.append(resume)

        return fx.callback(register)

    def put(self, value: int) -> fx.Effect[None]:
        def run() -> None:
            if self.parked:
                self.parked.pop(0)(fx.yield_now().as_(value))
            else:
                self.items.append(value)

        return fx.sync(run)


def _handing(w: World) -> None:
    box = _HandingMailbox()
    seen: list[int] = []

    @fx.gen
    def main():
        taker = yield from box.take().map(seen.append).fork()
        putter = yield from box.put(1).fork()
        yield from fx.yield_now()
        yield from taker.interrupt()
        yield from putter.await_exit()

    w.fork(main)
    w.check(lambda: None if len(seen) + len(box.items) == 1 else f"1 put, seen {seen}")


HANDING = Scenario("handing", _handing)


def test_it_finds_a_value_handed_to_a_parked_fiber_and_replays_it():
    with pytest.raises(InterleaveFailure) as failure:
        explore(HANDING)
    message = str(failure.value)
    assert "1 put, seen []" in message
    schedule = message.split("replay(BY_NAME['handing'], '")[1].split("'", maxsplit=1)[0]
    with pytest.raises(InterleaveFailure, match="1 put, seen"):
        replay(HANDING, schedule)


def _lost_wakeup(w: World) -> None:
    """A broken wait: checks, yields, then parks; a notify in between finds
    nobody to wake."""
    ready = [False]
    parked: list[Callable[[Effect[None]], None]] = []

    def notify() -> None:
        ready[0] = True
        for resume in parked:
            resume(fx.void)

    def park(resume: Callable[[Effect[None]], None]) -> None:
        parked.append(resume)

    wait = fx.suspend(lambda: fx.void if ready[0] else fx.yield_now().and_then(fx.callback(park)))

    @fx.gen
    def main():
        waiter = yield from wait.fork()
        yield from fx.yield_now()
        yield from fx.sync(notify)
        yield from waiter.join()

    w.fork(main)


def test_it_reports_a_fiber_left_parked_forever():
    with pytest.raises(InterleaveFailure, match="never ended"):
        explore(Scenario("lost_wakeup", _lost_wakeup))


def _resumed_from_a_thread(w: World) -> None:
    parked: list[Callable[[Effect[None]], None]] = []

    def park(resume: Callable[[Effect[None]], None]) -> None:
        parked.append(resume)

    w.fork(fx.callback(park))

    def resumer() -> ThreadBody:
        yield lambda: bool(parked)
        parked[0](fx.void)

    w.thread("resumer", resumer)


def test_a_simulated_thread_resumes_through_the_scheduler():
    """Not nested in the thread's step: the resume is a task the harness
    schedules, as a resume from another real thread is."""
    outcome = run_once(Scenario("resumed", _resumed_from_a_thread), Replay([]))
    assert outcome.problems == []
    assert outcome.log == [
        "Fiber._start(Fiber(#{}))".format(outcome.log[0].split("#")[1].split(")")[0]),
        "thread resumer",
        "thread resumer",
        outcome.log[3],
    ]
    assert outcome.log[3].startswith("_Wait.resume") and outcome.log[3].endswith("<from resumer>")


def _two_children(w: World) -> None:
    @fx.gen
    def main():
        a = yield from fx.void.fork()
        b = yield from fx.void.fork()
        yield from a.join()
        yield from b.join()

    w.fork(main)


def test_a_small_scenario_is_explored_exhaustively():
    report = explore(Scenario("two_children", _two_children))
    assert report.exhaustive
    assert report.distinct == 2  # which child starts first


def test_a_seed_replays_the_same_schedule():
    scenario = BY_NAME["deferred"]
    first = run_once(scenario, RandomWalk(11))
    again = run_once(scenario, RandomWalk(11))
    assert first.trace == again.trace
    assert run_once(scenario, Replay(first.choices)).trace == first.trace


def test_schedules_encode_compactly_and_round_trip():
    assert encode([0, 0, 0, 2, 0, 1, 0, 0]) == "0*3.2.0.1"
    assert decode("0*3.2.0.1") == [0, 0, 0, 2, 0, 1]


@pytest.fixture
def start_as_in_0_5_3(monkeypatch: pytest.MonkeyPatch) -> None:
    """``Fiber._start`` before 0.5.4: the first run takes the context of
    whatever drains the scheduler."""

    def old(
        self: Fiber[Any, Any], effect: Effect[Any, Any, Any], *, caller_drives: bool = False
    ) -> None:
        self._scheduler.schedule(lambda: self._drive(effect))

    monkeypatch.setattr(Fiber, "_start", old)


@pytest.mark.parametrize("name", ["contextvars", "managed_runtime"])
@pytest.mark.usefixtures("start_as_in_0_5_3")
def test_the_context_scenarios_catch_the_0_5_3_leak(name: str):
    with pytest.raises(InterleaveFailure, match="read another"):
        explore(BY_NAME[name])


def test_each_simulated_thread_has_its_own_contextvars():
    var: contextvars.ContextVar[str] = contextvars.ContextVar("var", default="-")
    seen: list[str] = []

    def build(w: World) -> None:
        def setter() -> ThreadBody:
            var.set("set")
            yield
            seen.append(var.get())

        def reader() -> ThreadBody:
            seen.append(var.get())
            yield

        w.thread("setter", setter)
        w.thread("reader", reader)

    run_once(Scenario("threads", build), Replay([0, 1]))
    assert seen == ["-", "set"]
