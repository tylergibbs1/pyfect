"""TestClock.adjust: waits for the work each wake-up starts, and never
hangs on a fiber that will not suspend.

Before moving time, adjust lets the fibers that are ready run once (a
forked ``yield_now``, as in Effect), so a busy fiber the clock did not wake
costs nothing. A woken fiber that never suspends makes adjust give up after
``warning_delay`` with a ``BusyFiberWarning``."""

import math
import time
import warnings
from collections.abc import Generator
from contextlib import contextmanager

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.duration import Seconds


@contextmanager
def _no_busy_warning() -> Generator[None]:
    with warnings.catch_warnings():
        warnings.simplefilter("error", testing.BusyFiberWarning)
        yield


def test_timeout_repetition_of_uninterruptible_effect():
    """Effect.test.ts "timeout repetition of uninterruptible effect"."""

    @fx.gen
    def program():
        fiber = yield from fx.void.uninterruptible().forever().timeout("10 millis").exit().fork()
        yield from testing.adjust("10 millis")
        return (yield from fiber.join())

    with _no_busy_warning():
        ex = testing.run_test(program, warning_delay="50 millis")
    assert isinstance(ex, fx.Failure)
    assert isinstance(ex.cause.failures[0], fx.TimeoutException)


def test_adjust_does_not_wait_for_a_busy_fiber_it_did_not_wake():
    @fx.gen
    def program():
        busy = yield from fx.yield_now().forever().fork()
        sleeper = yield from fx.sleep("1 second").as_("woke").fork()
        yield from testing.adjust("1 second")
        woke = yield from sleeper.join()
        yield from busy.interrupt()
        return woke

    started = time.monotonic()
    with _no_busy_warning():
        assert testing.run_test(program, warning_delay="1 second") == "woke"
    assert time.monotonic() - started < 0.5


def test_adjust_warns_and_moves_on_when_a_woken_fiber_never_suspends():
    @fx.gen
    def program():
        busy = yield from fx.sleep("1 second").and_then(fx.yield_now().forever()).fork()
        later = yield from fx.sleep("2 seconds").as_("later").fork()
        yield from testing.adjust("2 seconds")
        result = yield from later.join()
        yield from busy.interrupt()
        return result

    started = time.monotonic()
    with pytest.warns(testing.BusyFiberWarning, match="still running without suspending"):
        assert testing.run_test(program, warning_delay="50 millis") == "later"
    assert time.monotonic() - started < 1


@testing.effect
def test_adjust_waits_for_work_started_transitively_by_a_wake_up():
    """A woken fiber forks a child that sleeps again: the child's sleep is
    registered relative to the wake-up time and woken in the same adjust."""
    log: list[float] = []

    @fx.gen
    def child():
        yield from fx.sleep("1 second")
        log.append((yield from fx.clock.monotonic()))

    @fx.gen
    def parent():
        yield from fx.sleep("1 second")
        inner = yield from child.fork()
        yield from inner.join()

    fiber = yield from parent.fork()
    yield from testing.adjust("2 seconds")
    assert fiber.poll_unsafe() == fx.Success(None)
    assert log == [2.0]


def test_an_unrelated_busy_fiber_does_not_stall_each_wake_up():
    """Only the work a wake-up causes is waited for, so a busy fiber the clock
    never woke costs no warning and no waiting."""
    log: list[float] = []

    def sleeper(seconds: float) -> fx.Effect[None]:
        return fx.sleep(Seconds(seconds)).and_then(fx.clock.monotonic()).map(log.append)

    @fx.gen
    def program():
        busy = yield from fx.yield_now().forever().fork()
        first = yield from sleeper(1).fork()
        second = yield from sleeper(2).fork()
        third = yield from sleeper(3).fork()
        yield from testing.adjust("3 seconds")
        for fiber in (first, second, third):
            yield from fiber.join()
        yield from busy.interrupt()

    with _no_busy_warning():
        testing.run_test(program, warning_delay="1 second")
    assert log == [1.0, 2.0, 3.0]


@testing.effect
def test_deadlines_add_up_exactly():
    """0.05 + 0.001 is 0.051000000000000004 in floats; the clock must still
    wake a sleep of 0.05 then 0.001 when moved by 0.051, as Effect's
    millisecond TestClock does."""
    fiber = yield from fx.sleep("50 millis").and_then(fx.sleep("1 millis")).as_("woke").fork()
    yield from testing.adjust("51 millis")
    assert fiber.poll_unsafe() == fx.Success("woke")


@testing.effect
def test_repeated_sleeps_end_at_their_exact_sum():
    fiber = yield from fx.sleep("100 millis").replicate_effect(3).as_("woke").fork()
    yield from testing.adjust("300 millis")
    assert fiber.poll_unsafe() == fx.Success("woke")


@testing.effect
def test_wall_time_reads_infinite_after_moving_to_infinity():
    """Effect's ``currentTimeMillis`` is the TestClock's timestamp, so a
    schedule stepping after ``adjust(Infinity)`` sees ``now`` infinite and
    stops (``Schedule.cron``'s infinity port depends on it)."""
    yield from testing.set_time(5.0)
    yield from testing.adjust(math.inf)
    assert (yield from fx.clock.now()) == math.inf
    assert (yield from fx.clock.now_nanos()) == 5_000_000_000
