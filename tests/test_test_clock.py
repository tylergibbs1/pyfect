"""TestClock.adjust: waits for the work each wake-up starts, and never
hangs on a fiber that will not suspend.

Before moving time, adjust lets every fiber settle (deeper than Effect's
single yield, because pyfect starts forked children on the next scheduler
turn rather than immediately). A fiber that never suspends cannot settle,
so adjust gives up after ``warning_delay`` with a ``BusyFiberWarning``."""

import time

import pytest

import pyfect as fx
from pyfect import testing


def test_timeout_repetition_of_uninterruptible_effect():
    """Effect.test.ts "timeout repetition of uninterruptible effect"."""

    @fx.gen
    def program():
        fiber = yield from fx.void.uninterruptible().forever().timeout(0.01).exit().fork()
        yield from testing.adjust(0.01)
        return (yield from fiber.join())

    with pytest.warns(testing.BusyFiberWarning, match="stopped waiting for every fiber"):
        ex = testing.run_test(program, warning_delay=0.05)
    assert isinstance(ex, fx.Failure)
    assert isinstance(ex.cause.failures[0], fx.TimeoutException)


def test_adjust_stops_waiting_for_a_busy_fiber_it_did_not_wake():
    @fx.gen
    def program():
        busy = yield from fx.yield_now().forever().fork()
        sleeper = yield from fx.sleep(1).as_("woke").fork()
        yield from testing.adjust(1)
        woke = yield from sleeper.join()
        yield from busy.interrupt()
        return woke

    with pytest.warns(testing.BusyFiberWarning, match="stopped waiting for every fiber"):
        assert testing.run_test(program, warning_delay=0.05) == "woke"


def test_adjust_warns_and_moves_on_when_a_woken_fiber_never_suspends():
    @fx.gen
    def program():
        busy = yield from fx.sleep(1).and_then(fx.yield_now().forever()).fork()
        later = yield from fx.sleep(2).as_("later").fork()
        yield from testing.adjust(2)
        result = yield from later.join()
        yield from busy.interrupt()
        return result

    started = time.monotonic()
    with pytest.warns(testing.BusyFiberWarning, match="still running without suspending"):
        assert testing.run_test(program, warning_delay=0.05) == "later"
    assert time.monotonic() - started < 1


def test_adjust_waits_for_work_started_transitively_by_a_wake_up():
    """A woken fiber forks a child that sleeps again: the child's sleep is
    registered relative to the wake-up time and woken in the same adjust."""
    log: list[float] = []

    @fx.gen
    def child():
        yield from fx.sleep(1)
        log.append((yield from fx.clock.monotonic()))

    @fx.gen
    def parent():
        yield from fx.sleep(1)
        inner = yield from child.fork()
        yield from inner.join()

    @fx.gen
    def program():
        fiber = yield from parent.fork()
        yield from testing.adjust(2)
        return fiber.unsafe_poll()

    assert testing.run_test(program) == fx.Success(None)
    assert log == [2.0]


def test_an_unrelated_busy_fiber_does_not_stall_each_wake_up():
    """Only the work a wake-up causes is waited for, so a busy fiber the clock
    never woke costs one settle warning, not one per sleeper woken."""
    log: list[float] = []

    def sleeper(seconds: float) -> fx.Effect[None]:
        return fx.sleep(seconds).and_then(fx.clock.monotonic()).map(log.append)

    @fx.gen
    def program():
        busy = yield from fx.yield_now().forever().fork()
        first = yield from sleeper(1).fork()
        second = yield from sleeper(2).fork()
        third = yield from sleeper(3).fork()
        yield from testing.adjust(3)
        for fiber in (first, second, third):
            yield from fiber.join()
        yield from busy.interrupt()

    with pytest.warns(testing.BusyFiberWarning) as caught:
        testing.run_test(program, warning_delay=0.05)
    assert [str(w.message) for w in caught] == [testing._SETTLE_WARNING]  # pyright: ignore[reportPrivateUsage]
    assert log == [1.0, 2.0, 3.0]
