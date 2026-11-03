"""Growing schedules saturate to an infinite delay, as JavaScript numbers do.

Effect computes delays in float milliseconds: ``base * Math.pow(factor, n)``
and the Fibonacci sums become ``Infinity`` past float range and
``Duration.millis(Infinity)`` is ``Duration.infinity``. Python raises
``OverflowError`` for ``float ** n`` and for big ``int / int`` instead
(DOGFOOD outlay #10). Expected values were read from Effect 4.0.6 under Node.
"""

import math

import pyfect as fx
from pyfect import schedule, testing
from pyfect.duration import Seconds
from pyfect.exit import Success
from pyfect.schedule import Continue, Schedule


def delays_after[I](s: Schedule[object, I], input: I, steps: int) -> list[Seconds]:
    """Every delay of the first ``steps`` steps, stepped at time 0."""

    @fx.gen
    def go():
        step = yield from schedule.to_step(s)
        out: list[Seconds] = []
        for _ in range(steps):
            decision = yield from step(0.0, input)
            assert isinstance(decision, Continue)
            out.append(decision.delay)
        return out

    return testing.run_test(go)


def test_capped_exponential_keeps_recurring_past_float_range():
    """min(exponential(0.2, 1.5), spaced(30)) recurs 2000 times (the repro;
    upTo(times) bounds it, as min with recurs would recur for ever)."""
    capped = schedule.min(schedule.exponential(0.2, 1.5), schedule.spaced(30))

    @fx.gen
    def scenario():
        bounded = capped.up_to(times=2_000)
        running = yield from fx.void.repeat(bounded).exit().fork()
        yield from testing.adjust(2_000 * 30)
        return (yield from running.join())

    result = testing.run_test(scenario)
    assert isinstance(result, Success)


def test_exponential_delay_becomes_infinite():
    """Effect: exponential(200ms, 1.5) is first Duration.infinity at index 1738
    (its milliseconds pass float range)."""
    delays = delays_after(schedule.exponential(0.2, 1.5), None, 2_000)
    assert math.isfinite(delays[1_737])
    assert delays[1_738:] == [math.inf] * (2_000 - 1_738)


def test_exponential_with_a_huge_factor_becomes_infinite():
    """Effect: exponential(1s, 1e300) gives 1e303s, then Duration.infinity."""
    delays = delays_after(schedule.exponential(1, 1e300), None, 3)
    assert delays == [1.0, 1e300, math.inf]


def test_fibonacci_delay_becomes_infinite():
    """Effect: fibonacci(1s) is first Duration.infinity at index 1461."""
    delays = delays_after(schedule.fibonacci(1), None, 1_500)
    assert math.isfinite(delays[1_460])
    assert delays[1_461:] == [math.inf] * (1_500 - 1_461)


def test_min_with_spaced_keeps_the_finite_side():
    """min(exponential(1s, 1e300), spaced(30)) waits 1s, 30s, 30s, 30s."""
    capped = schedule.min(schedule.exponential(1, 1e300), schedule.spaced(30))
    assert delays_after(capped, None, 4) == [1.0, 30.0, 30.0, 30.0]


def test_max_with_spaced_waits_forever():
    """max(exponential(1s, 1e300), spaced(30)) waits Infinity once it overflows."""
    longest = schedule.max(schedule.exponential(1, 1e300), schedule.spaced(30))
    assert delays_after(longest, None, 3) == [30.0, 1e300, math.inf]


def test_jittered_infinite_delay_stays_infinite():
    """Effect: jittered keeps Duration.infinity infinite."""
    jittered = schedule.exponential(1, 1e300).jittered()
    assert delays_after(jittered, None, 3)[-1] == math.inf


def test_add_delay_to_an_infinite_delay_stays_infinite():
    """Effect: addDelay(Duration.infinity, 1s) is Duration.infinity."""
    added = schedule.exponential(1, 1e300).add_delay(lambda _: fx.succeed(1.0))
    assert delays_after(added, None, 3)[-1] == math.inf


def test_an_infinite_delay_never_wakes_under_adjust():
    """Effect: once exponential(1s, 1e200) waits Infinity, adjust never wakes it."""

    @fx.gen
    def scenario():
        running = yield from fx.void.repeat(schedule.exponential(1, 1e200)).fork()
        yield from testing.adjust(1e201)
        clock = yield from testing.test_clock()
        seen = running.poll_unsafe(), clock.pending_sleeps
        yield from running.interrupt()
        return seen

    assert testing.run_test(scenario) == (None, 1)


def test_up_to_duration_stops_after_an_infinite_delay():
    """Effect: upTo(exponential(1s, 1e200), 60s) under setTime(Infinity) stops
    with Duration.infinity, the delay it would have waited next."""

    @fx.gen
    def scenario():
        bounded = schedule.exponential(1, 1e200).up_to(duration=60)
        running = yield from fx.void.repeat(bounded).fork()
        yield from testing.set_time(math.inf)
        return (yield from running.join())

    assert testing.run_test(scenario) == math.inf
