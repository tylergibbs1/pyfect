"""retry and repeat with schedules, on the test clock."""

import pyfect as fx
from pyfect import schedule
from pyfect.testing import run_test as run


def flaky(failures: int, attempts: list[float]) -> fx.Effect[str, str]:
    """Fails ``failures`` times, recording the time of each attempt."""

    @fx.gen
    def attempt():
        now = yield from fx.clock.monotonic()
        attempts.append(now)
        if len(attempts) <= failures:
            return (yield from fx.fail(f"attempt {len(attempts)} failed"))
        return "ok"

    return attempt


def test_retry_recurs_succeeds_after_failures():
    attempts: list[float] = []
    assert run(flaky(2, attempts).retry(schedule.recurs(3)).or_die()) == "ok"
    assert len(attempts) == 3


def test_retry_gives_up_with_the_last_error():
    attempts: list[float] = []
    ex = fx.testing.run_test_exit(flaky(5, attempts).retry(schedule.recurs(2)))
    assert isinstance(ex, fx.Failure) and ex.cause.failures == ("attempt 3 failed",)
    assert len(attempts) == 3


@fx.testing.effect
def test_exponential_backoff_timing():
    attempts: list[float] = []
    fiber = yield from flaky(3, attempts).retry(schedule.exponential(1).take(5)).fork()
    yield from fx.testing.adjust(100)
    assert (yield from fiber.join()) == "ok"
    assert attempts == [0, 1, 3, 7]


def test_while_input_only_retries_matching_errors():
    attempts: list[float] = []
    only_first = schedule.forever().while_input(lambda e: e == "attempt 1 failed")
    ex = fx.testing.run_test_exit(flaky(5, attempts).retry(only_first))
    assert isinstance(ex, fx.Failure) and ex.cause.failures == ("attempt 2 failed",)


def test_retry_does_not_retry_defects():
    calls: list[int] = []
    eff = fx.sync(lambda: calls.append(1)).and_then(fx.die(RuntimeError("bug")))
    ex = fx.testing.run_test_exit(eff.retry(schedule.recurs(5)))
    assert isinstance(ex, fx.Failure) and len(calls) == 1


def test_repeat_spaced_with_take():
    ticks: list[float] = []

    @fx.gen
    def program():
        tick = fx.clock.monotonic().map(ticks.append)
        fiber = yield from tick.repeat(schedule.spaced(2).take(3)).fork()
        yield from fx.testing.adjust(10)
        return (yield from fiber.join())

    assert run(program) == 3
    assert ticks == [0, 2, 4, 6]


@fx.testing.effect
def test_fixed_keeps_a_beat_from_the_first_decision_regardless_of_work_time():
    ticks: list[float] = []
    work = fx.clock.monotonic().map(ticks.append).and_then(fx.sleep(1))
    fiber = yield from work.repeat(schedule.fixed(3).take(2)).fork()
    yield from fx.testing.adjust(20)
    yield from fiber.join()
    # First run at 0 takes 1s; beats are then every 3s from t=1.
    assert ticks == [0, 4, 7]


def test_both_stops_when_either_stops():
    s = schedule.both(schedule.recurs(5), schedule.recurs(2))
    count = 0

    def bump() -> None:
        nonlocal count
        count += 1

    run(fx.sync(bump).repeat(s))
    assert count == 3


@fx.testing.effect
def test_up_to_bounds_total_time():
    attempts: list[float] = []
    fiber = yield from flaky(100, attempts).retry(schedule.spaced(1).up_to(3)).exit().fork()
    yield from fx.testing.adjust(10)
    yield from fiber.join()
    # Elapsed is measured from the first decision; at t=3 it is still <= 3.
    assert attempts == [0, 1, 2, 3, 4]


def test_up_to_limits_by_duration_inclusively():
    """Schedule.test.ts "upTo" / "limits by duration"."""
    s = schedule.forever().up_to(1.0)
    st, _, first = s.run_step(0.0, None, s.initial)
    st, _, second = s.run_step(1.0, None, st)
    _, _, third = s.run_step(1.001, None, st)
    assert (first, second, third) == (0.0, 0.0, None)


def steps(s: schedule.Schedule[None, object], times: list[float]) -> list[schedule.Decision]:
    """Run ``s`` at each of ``times`` and collect its decisions."""
    state = s.initial
    out: list[schedule.Decision] = []
    for now in times:
        state, _, decision = s.run_step(now, None, state)
        out.append(decision)
    return out


def test_fibonacci_sums_the_two_preceding_delays():
    """Schedule.ts fibonacci: a=0, b=one; each step yields a+b."""
    assert steps(schedule.fibonacci(1), [0.0] * 6) == [1, 2, 3, 5, 8, 13]


def test_fixed_recurs_immediately_when_the_action_outlasts_the_interval():
    """Schedule.test.ts "fixed" / "matches effect v3 when action duration
    exceeds the interval"."""
    delays: list[schedule.Decision] = []
    tapped = schedule.fixed(1).take(5)

    @fx.gen
    def program():
        state = tapped.initial
        while True:
            yield from fx.sleep(1.5)
            now = yield from fx.clock.monotonic()
            state, _, decision = tapped.run_step(now, None, state)
            delays.append(decision)
            if decision is None:
                return
            yield from fx.sleep(decision)

    @fx.gen
    def driver():
        fiber = yield from program.fork()
        yield from fx.testing.adjust(100)
        yield from fiber.join()

    run(driver)
    assert delays == [1, 0, 0, 0, 0, None]


def test_fixed_runs_late_actions_at_once_without_replaying_missed_beats():
    ticks: list[float] = []

    @fx.gen
    def program():
        work = fx.clock.monotonic().map(ticks.append).and_then(fx.sleep(1.5))
        fiber = yield from work.repeat(schedule.fixed(1).take(4)).fork()
        yield from fx.testing.adjust(100)
        yield from fiber.join()

    run(program)
    assert ticks == [0, 2.5, 4.0, 5.5, 7.0]


def test_fixed_with_a_zero_interval_never_waits():
    assert steps(schedule.fixed(0), [0.0, 1.0, 5.0]) == [0, 0, 0]


def test_fixed_waits_for_the_window_boundary_when_on_time():
    """Schedule.test.ts "fixed" / "delays until the nearest window boundary"
    shape: a 0.5s action on a 1s beat waits out the rest of each beat."""
    assert steps(schedule.fixed(1), [0.0, 1.5, 2.5, 3.5]) == [1, 0.5, 0.5, 0.5]
