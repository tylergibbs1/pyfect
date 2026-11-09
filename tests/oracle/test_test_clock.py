"""Ports of Effect's ``testing/TestClock.test.ts``, written with the
``@testing.effect`` decorator they exercise.

Time is in seconds (floats), as everywhere in pyfect; the clock reads a
float as the decimal it was written as, so ``1_000_000_000.001`` is exactly
1_000_000_000_001_000_000 nanoseconds. The warnings go to Python's
``warnings`` rather than a Console, so "warnings bypass TestConsole" checks
that the warning is raised and the ``TestConsole`` holds only the ordinary
output.
"""

import math
from typing import Literal

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.duration import Seconds, to_millis
from pyfect.testing import TestClock

HOUR = 3600.0


@pytest.mark.parametrize(
    "warning", ["not advancing the test clock", "still running without suspending"]
)
@testing.effect(warning_delay="50 millis")
def test_warnings_bypass_test_console(
    warning: Literal["not advancing the test clock", "still running without suspending"],
    recwarn: pytest.WarningsRecorder,
):
    """TestClock.test.ts "warnings bypass TestConsole - ${warning}"."""
    yield from fx.console.log("ordinary output")
    then = fx.yield_now().forever() if warning == "still running without suspending" else fx.void
    yield from fx.sleep("1 minute").and_then(then).fork()
    if warning == "still running without suspending":
        yield from testing.adjust("1 minute")

    def seen() -> bool:
        return any(warning in str(w.message) for w in recwarn)

    @fx.gen
    def wait_for_warning():
        while not seen():
            yield from fx.sleep("10 millis")

    yield from testing.with_live(wait_for_warning.timeout("3 seconds"))
    assert (yield from testing.log_lines) == ["ordinary output"]
    assert seen()


@pytest.mark.parametrize("cancellation", ["interrupted sleep", "successful timeout"])
@testing.effect
def test_adjust_skips_the_cancelled_deadline(
    cancellation: Literal["interrupted sleep", "successful timeout"],
):
    """TestClock.test.ts "adjust - skips the cancelled deadline (${cancellation})"."""
    clock = TestClock(warning_delay="50 millis")
    if cancellation == "interrupted sleep":
        sleeper = yield from clock.sleep(fx.duration.Seconds(60)).fork()
        yield from fx.yield_now()
        yield from sleeper.interrupt()
    else:
        yield from fx.yield_now().timeout("1 minute").pipe(fx.provide_service(fx.Clock, clock))

    # Record the clock whenever adjustment yields to other fibers
    observed: set[int] = set()
    yield from (
        fx.sync(lambda: observed.add(clock.now_nanos_unsafe()))
        .and_then(fx.yield_now())
        .forever()
        .fork()
    )
    yield from clock.adjust("2 minutes")
    assert 60 * 10**9 not in observed


@testing.effect
def test_sleep_does_not_require_passage_of_wall_time():
    """TestClock.test.ts "sleep - does not require passage of wall time"."""
    elapsed: list[bool] = []
    yield from fx.sync(lambda: elapsed.append(True)).delay(Seconds(10 * HOUR)).fork()
    yield from testing.adjust(Seconds(11 * HOUR))
    assert elapsed == [True]


@testing.effect
def test_sleep_delays_effects_until_time_is_adjusted():
    """TestClock.test.ts "sleep - delays effects until time is adjusted"."""
    elapsed: list[bool] = []
    fiber = yield from fx.sync(lambda: elapsed.append(True)).delay(Seconds(10 * HOUR)).fork()
    yield from testing.adjust(Seconds(9 * HOUR))
    assert fiber.poll_unsafe() is None
    yield from testing.adjust(Seconds(11 * HOUR))
    assert fiber.poll_unsafe() == fx.Success(None)
    assert elapsed == [True]


@testing.effect
def test_sleep_handles_multiple_sleeps():
    """TestClock.test.ts "sleep - handles multiple sleeps"."""
    message: list[str] = []
    yield from fx.sync(lambda: message.append("World!")).delay(Seconds(3 * HOUR)).fork_scoped()
    yield from fx.sync(lambda: message.append("Hello, ")).delay(Seconds(HOUR)).fork_scoped()
    yield from testing.adjust(Seconds(HOUR))
    assert "".join(message) == "Hello, "
    yield from testing.adjust(Seconds(4 * HOUR))
    assert "".join(message) == "Hello, World!"


@testing.effect
def test_set_time_sleep_correctly_handles_new_set_time():
    """TestClock.test.ts "setTime - sleep correctly handles new set time"."""
    elapsed: list[bool] = []
    yield from fx.sync(lambda: elapsed.append(True)).delay(Seconds(10 * HOUR)).fork()
    assert elapsed == []
    yield from testing.set_time(to_millis(Seconds(11 * HOUR)))
    assert elapsed == [True]


@testing.effect
def test_set_time_floors_nanoseconds_for_fractional_millisecond_instants():
    """TestClock.test.ts "setTime - floors nanoseconds for fractional millisecond instants"."""
    clock = TestClock()
    yield from clock.set_time(199023438.0000004)
    assert clock.now_nanos_unsafe() == 199023438000000


@testing.effect
def test_set_time_preserves_wall_clock_nanoseconds_for_large_timestamps():
    """TestClock.test.ts "setTime - preserves wall-clock nanoseconds for large timestamps"."""
    clock = TestClock()
    timestamp = 1_000_000_000_001
    yield from clock.set_time(timestamp)
    assert clock.now_nanos_unsafe() == timestamp * 1_000_000


@testing.effect
def test_adjust_advances_wall_and_monotonic_time():
    """TestClock.test.ts "adjust - advances wall and monotonic time"."""
    clock = yield from testing.test_clock()
    yield from clock.adjust("1 second")
    assert clock.current_time_millis_unsafe() == 1_000
    assert clock.monotonic_nanos_unsafe() == 1_000_000_000
    assert (yield from fx.clock.monotonic()) == 1.0


@testing.effect
def test_adjust_preserves_precision_for_nanosecond_durations_beyond_max_safe_integer():
    """TestClock.test.ts "adjust - preserves precision for nanosecond durations beyond
    Number.MAX_SAFE_INTEGER"."""
    clock = TestClock()
    yield from clock.adjust(Seconds(999_999_999.999_999))
    assert clock.monotonic_nanos_unsafe() == 999_999_999_999_999_000
    assert clock.now_nanos_unsafe() == 999_999_999_999_999_000


@testing.effect
def test_adjust_keeps_nanosecond_access_total_after_infinite_durations():
    """TestClock.test.ts "adjust - keeps nanosecond access total after infinite durations"."""
    for duration in (math.inf, -math.inf):
        clock = TestClock()
        yield from clock.adjust(Seconds(duration))
        assert isinstance(clock.now_nanos_unsafe(), int)


@testing.effect
def test_set_time_advances_monotonic_time_only_when_moving_forward():
    """TestClock.test.ts "setTime - advances monotonic time only when moving forward"."""
    clock = TestClock()
    yield from clock.set_time(2_000)
    assert clock.monotonic_nanos_unsafe() == 2_000_000_000
    yield from clock.set_time(500)
    assert clock.current_time_millis_unsafe() == 500
    assert clock.monotonic_nanos_unsafe() == 2_000_000_000
    yield from clock.set_time(1_000)
    assert clock.monotonic_nanos_unsafe() == 2_500_000_000


@testing.effect
def test_set_time_preserves_nanosecond_precision_for_far_future_timestamps():
    """TestClock.test.ts "setTime - preserves nanosecond precision for far-future
    timestamps"."""
    clock = TestClock()
    far_future = 1_000_000_000_000
    yield from clock.set_time(far_future)
    before = clock.monotonic_nanos_unsafe()
    yield from clock.set_time(far_future + 1)
    assert clock.monotonic_nanos_unsafe() - before == 1_000_000


@testing.effect
def test_adjust_advances_monotonic_time_to_intermediate_sleep_deadlines():
    """TestClock.test.ts "adjust - advances monotonic time to intermediate sleep deadlines"."""
    clock = TestClock()
    observed: list[int] = []

    @fx.gen
    def sleeper():
        yield from clock.sleep(fx.duration.Seconds(1))
        observed.append(clock.monotonic_nanos_unsafe())

    yield from sleeper.fork()
    yield from clock.adjust("2 seconds")
    assert observed == [1_000_000_000]
    assert clock.monotonic_nanos_unsafe() == 2_000_000_000


@testing.effect
def test_adjust_runs_sleeps_registered_after_a_yield():
    """TestClock.test.ts "adjust - runs sleeps registered after a yield"."""
    ticks: list[None] = []
    fiber = yield from (
        fx.sleep("1 second")
        .and_then(fx.sync(lambda: ticks.append(None)))
        .and_then(fx.yield_now())
        .forever()
        .fork()
    )
    yield from testing.adjust("5 seconds")
    yield from fiber.interrupt()
    assert len(ticks) == 5


@testing.effect
def test_set_time_runs_sleeps_registered_after_a_fork_and_join():
    """TestClock.test.ts "setTime - runs sleeps registered after a fork and join"."""
    ticks: list[None] = []
    fork_and_join = fx.yield_now().fork().flat_map(lambda f: f.join())
    fiber = yield from (
        fx.sleep("1 second")
        .and_then(fx.sync(lambda: ticks.append(None)))
        .and_then(fork_and_join)
        .forever()
        .fork()
    )
    yield from testing.set_time(5_000)
    yield from fiber.interrupt()
    assert len(ticks) == 5


@pytest.mark.filterwarnings("ignore::pyfect.testing.BusyFiberWarning")
@testing.effect
def test_adjust_completes_when_a_nested_clock_wakes_a_busy_fiber():
    """TestClock.test.ts "adjust - completes when a nested clock wakes a busy fiber"."""
    later: list[bool] = []

    @fx.gen
    def program():
        yield from fx.sleep("1 second").and_then(fx.yield_now().forever()).fork()
        yield from fx.sleep("2 seconds").and_then(fx.sync(lambda: later.append(True))).fork()
        yield from testing.adjust("5 seconds")

    yield from program.pipe(fx.provide(TestClock.layer(warning_delay="10 millis")))
    assert later == [True]


@testing.effect
def test_adjust_waits_for_woken_fibers_when_the_advancing_fiber_yields_on_its_operation_budget():
    """TestClock.test.ts "adjust - waits for woken fibers when the advancing fiber yields
    on its operation budget"."""
    done: list[bool] = []

    @fx.gen
    def program():
        yield from (
            fx.sleep("1 second")
            .and_then(fx.yield_now())
            .and_then(fx.sync(lambda: done.append(True)))
            .fork()
        )
        yield from testing.adjust("1 second")

    yield from program.pipe(fx.provide(TestClock.layer(warning_delay=math.inf))).pipe(
        fx.provide_service(fx.MaxOpsBeforeYield, 4)
    )
    assert done == [True]


def test_layer_can_adjust_when_provided_without_an_ambient_scope() -> None:
    """TestClock.test.ts "layer - can adjust when provided without an ambient Scope"."""
    fx.run_blocking(testing.adjust("1 second").pipe(fx.provide(TestClock.layer())))
