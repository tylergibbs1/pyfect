"""``Clock`` beyond Effect's ``Clock.test.ts``: the nanosecond readers and
the live clock's sleep semantics, checked against Effect's ``ClockImpl``
(a sleep of zero or less is ``yieldNow``; an infinite one is ``never``)."""

import math
from collections.abc import Callable

import pytest

import pyfect as fx
from pyfect import clock, testing
from pyfect._wake_tracking import WakeTracker
from pyfect.duration import Seconds
from pyfect.scheduler import Cancel, Scheduler, Task


class TimerRecordingScheduler:
    """Records the delay of every timer set on it; runs everything on ``inner``."""

    def __init__(self, inner: Scheduler) -> None:
        self.inner = inner
        self.delays: list[float] = []

    def schedule(self, task: Task) -> None:
        self.inner.schedule(task)

    def call_later(self, delay: Seconds, task: Task, *, daemon: bool = False) -> Cancel:
        self.delays.append(delay)
        return self.inner.call_later(delay, task, daemon=daemon)

    def track(self, tracker: WakeTracker, f: Callable[[], None]) -> None:
        self.inner.track(tracker, f)


def _timer_delays(eff: fx.Effect[object]) -> fx.Effect[list[float]]:
    def run(inner: Scheduler) -> fx.Effect[list[float]]:
        recording = TimerRecordingScheduler(inner)
        return eff.pipe(fx.provide_service(fx.CurrentScheduler, recording)).map(
            lambda _: recording.delays
        )

    return fx.CurrentScheduler().flat_map(run)


@testing.effect
def test_nanosecond_readers_follow_the_clock():
    yield from testing.set_time(1_000_000_000.001)
    yield from testing.adjust(0.5)
    assert (yield from clock.now_nanos()) == 1_000_000_000_501_000_000
    assert (yield from clock.monotonic_nanos()) == 1_000_000_000_501_000_000
    yield from testing.set_time(0)
    assert (yield from clock.now_nanos()) == 0
    assert (yield from clock.monotonic_nanos()) == 1_000_000_000_501_000_000


@testing.effect
def test_clock_with_passes_the_current_clock():
    current = yield from fx.Clock()
    seen = yield from clock.clock_with(fx.succeed)
    assert seen is current


@testing.effect
def test_timed_measures_whole_monotonic_nanoseconds():
    fiber = yield from fx.sleep(0.3).as_("done").timed().fork()
    yield from testing.adjust(0.1)
    yield from testing.adjust(0.2)  # 0.1 + 0.2 is 0.30000000000000004 in floats
    assert (yield from fiber.join()) == (0.3, "done")


@pytest.mark.parametrize("seconds", [0.0, -1.0])
@testing.live
def test_a_live_sleep_of_zero_or_less_yields_once(seconds: float):
    order: list[str] = []
    other = yield from fx.sync(lambda: order.append("other")).fork()
    yield from fx.sleep(seconds)
    order.append("sleeper")
    yield from other.join()
    assert order == ["other", "sleeper"]


@testing.live
def test_a_live_sleep_of_zero_or_less_sets_no_timer():
    assert (yield from _timer_delays(fx.sleep(0).zip(fx.sleep(-1)))) == []


@testing.live
def test_a_live_infinite_sleep_sets_no_timer():
    delays = yield from _timer_delays(fx.sleep(math.inf).timeout_option(0.02))
    assert math.inf not in delays


@testing.live
def test_a_live_infinite_sleep_never_wakes():
    woke = yield from fx.sleep(math.inf).timeout_option(0.02)
    assert woke is None
