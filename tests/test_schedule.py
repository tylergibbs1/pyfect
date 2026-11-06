"""Schedules driving effects on the test clock, beyond Effect's own
``Schedule.test.ts`` (ported in ``tests/oracle/test_schedule.py``)."""

from collections.abc import Sequence
from typing import TypeIs

import pytest

import pyfect as fx
from pyfect import schedule, testing
from pyfect.cause import Fail
from pyfect.duration import ZERO, Seconds
from pyfect.result import Err
from pyfect.schedule import Continue, CurrentMetadata, Decision, Metadata, Schedule, Stop
from pyfect.testing import run_test as run


def flaky(failures: int, attempts: list[float]) -> fx.Effect[str, str]:
    """Fails ``failures`` times, recording the time of each attempt."""

    @fx.gen
    def attempt():
        now = yield from fx.clock.now()
        attempts.append(now)
        if len(attempts) <= failures:
            return (yield from fx.fail(f"attempt {len(attempts)} failed"))
        return "ok"

    return attempt


def decisions[O](s: Schedule[O, None], times: Sequence[float]) -> list[Decision[O]]:
    """Step a fresh run of ``s`` at each of ``times``."""

    @fx.gen
    def go():
        step = yield from schedule.to_step(s)
        return (yield from fx.for_each(times, lambda now: step(now, None)))

    return run(go)


def delays(s: Schedule[object, None], times: Sequence[float]) -> list[float | None]:
    """Each decision's delay, ``None`` where the schedule stops."""
    return [d.delay if isinstance(d, Continue) else None for d in decisions(s, times)]


def test_retry_recurs_succeeds_after_failures():
    attempts: list[float] = []
    assert run(flaky(2, attempts).retry(schedule.recurs(3)).or_die()) == "ok"
    assert len(attempts) == 3


def test_retry_gives_up_with_the_last_error():
    attempts: list[float] = []
    ex = testing.run_test_exit(flaky(5, attempts).retry(schedule.recurs(2)))
    assert isinstance(ex, fx.Failure) and ex.cause.failures == ("attempt 3 failed",)
    assert len(attempts) == 3


@testing.effect
def test_exponential_backoff_timing():
    attempts: list[float] = []
    policy = schedule.exponential(1).up_to(times=5)
    fiber = yield from flaky(3, attempts).retry(policy).fork()
    yield from testing.adjust(100)
    assert (yield from fiber.join()) == "ok"
    assert attempts == [0, 1, 3, 7]


def test_while_on_the_input_only_retries_matching_errors():
    attempts: list[float] = []
    only_first = schedule.forever.while_(lambda m: m.input == "attempt 1 failed")
    ex = testing.run_test_exit(flaky(5, attempts).retry(only_first))
    assert isinstance(ex, fx.Failure) and ex.cause.failures == ("attempt 2 failed",)


def test_retry_does_not_retry_defects():
    calls: list[int] = []
    eff = fx.sync(lambda: calls.append(1)).and_then(fx.die(RuntimeError("bug")))
    ex = testing.run_test_exit(eff.retry(schedule.recurs(5)))
    assert isinstance(ex, fx.Failure) and len(calls) == 1


def test_a_failing_schedule_step_fails_the_retry_with_its_error():
    policy = schedule.recurs(5).while_effect(lambda _: fx.fail("schedule broke"))
    ex = testing.run_test_exit(fx.fail("source").retry(policy))
    assert isinstance(ex, fx.Failure) and ex.cause.failures == ("schedule broke",)


def test_retry_or_else_gets_the_last_error_and_the_final_output():
    seen: list[tuple[str, int]] = []

    def give_up(error: str, out: int) -> fx.Effect[str]:
        seen.append((error, out))
        return fx.succeed("fallback")

    attempts: list[float] = []
    result = run(flaky(5, attempts).retry_or_else(schedule.recurs(2), give_up))
    assert result == "fallback"
    assert seen == [("attempt 3 failed", 2)]


def test_repeat_spaced_up_to_times():
    ticks: list[float] = []

    @fx.gen
    def program():
        tick = fx.clock.now().map(ticks.append)
        fiber = yield from tick.repeat(schedule.spaced(2).up_to(times=3)).fork()
        yield from testing.adjust(10)
        return (yield from fiber.join())

    assert run(program) == 3
    assert ticks == [0, 2, 4, 6]


@testing.effect
def test_fixed_keeps_a_beat_from_the_first_decision_regardless_of_work_time():
    ticks: list[float] = []
    work = fx.clock.now().map(ticks.append).and_then(fx.sleep(1))
    fiber = yield from work.repeat(schedule.fixed(3).up_to(times=2)).fork()
    yield from testing.adjust(20)
    yield from fiber.join()
    # First run at 0 takes 1s; beats are then every 3s from t=1.
    assert ticks == [0, 4, 7]


def test_fixed_runs_late_actions_at_once_without_replaying_missed_beats():
    ticks: list[float] = []

    @fx.gen
    def program():
        work = fx.clock.now().map(ticks.append).and_then(fx.sleep(1.5))
        fiber = yield from work.repeat(schedule.fixed(1).up_to(times=4)).fork()
        yield from testing.adjust(100)
        yield from fiber.join()

    run(program)
    assert ticks == [0, 2.5, 4.0, 5.5, 7.0]


def test_max_stops_when_either_stops():
    count = 0

    def bump() -> None:
        nonlocal count
        count += 1

    run(fx.sync(bump).repeat(schedule.max(schedule.recurs(5), schedule.recurs(2))))
    assert count == 3


@testing.effect
def test_up_to_duration_bounds_total_time():
    attempts: list[float] = []
    policy = schedule.spaced(1).up_to(duration=3)
    fiber = yield from flaky(100, attempts).retry(policy).exit().fork()
    yield from testing.adjust(10)
    yield from fiber.join()
    # Elapsed is measured from the first decision; at t=3 it is still <= 3.
    assert attempts == [0, 1, 2, 3, 4]


def test_fibonacci_sums_the_two_preceding_delays():
    """Schedule.ts fibonacci: a=0, b=one; each step yields a+b."""
    assert delays(schedule.fibonacci(1), [0.0] * 6) == [1, 2, 3, 5, 8, 13]


def test_exponential_multiplies_by_the_factor_each_attempt():
    assert delays(schedule.exponential(0.5, 3), [0.0] * 4) == [0.5, 1.5, 4.5, 13.5]


def test_fixed_with_a_zero_interval_never_waits():
    assert delays(schedule.fixed(0), [0.0, 1.0, 5.0]) == [0, 0, 0]


def test_fixed_waits_for_the_window_boundary_when_on_time():
    """A 0.5s action on a 1s beat waits out the rest of each beat."""
    assert delays(schedule.fixed(1), [0.0, 1.5, 2.5, 3.5]) == [1, 0.5, 0.5, 0.5]


def test_windowed_waits_for_the_end_of_the_current_window():
    assert delays(schedule.windowed(2), [10.0, 10.5, 13.0]) == [2, 1.5, 1]


def test_during_stops_once_more_than_the_duration_has_passed():
    assert decisions(schedule.during(1), [5.0, 6.0, 6.5]) == [
        Continue(Seconds(0.0), ZERO),
        Continue(Seconds(1.0), ZERO),
        Stop(Seconds(1.5)),
    ]


def test_recurs_counts_from_zero_and_stops_with_the_last_count():
    assert decisions(schedule.recurs(2), [0.0] * 3) == [
        Continue(0, ZERO),
        Continue(1, ZERO),
        Stop(2),
    ]


def test_map_also_maps_the_final_output():
    s = schedule.recurs(1).map(lambda m: f"{m.output}@{m.attempt}")
    assert decisions(s, [0.0, 0.0]) == [Continue("0@1", ZERO), Stop("1@2")]


def test_passthrough_outputs_the_inputs():
    ids = schedule.recurs(1).pipe(schedule.set_input_type(int)).passthrough()

    @fx.gen
    def go():
        step = yield from schedule.to_step(ids)
        return [(yield from step(0.0, 7)), (yield from step(0.0, 8))]

    assert run(go) == [Continue(7, ZERO), Stop(8)]


def test_a_failure_making_the_step_fails_every_step():
    broken: Schedule[int, object, str] = schedule.from_step(fx.fail("no step"))

    @fx.gen
    def go():
        step = yield from schedule.to_step(broken)
        first = yield from step(0.0, None).result()
        second = yield from step(1.0, None).result()
        return first, second

    assert run(go) == (Err("no step"), Err("no step"))


def test_each_run_starts_from_fresh_state():
    s = schedule.fibonacci(1)
    assert delays(s, [0.0] * 3) == delays(s, [0.0] * 3) == [1, 2, 3]


@testing.effect
def test_repeat_sees_the_metadata_of_the_step_that_started_each_run():
    seen: list[Metadata[object, object]] = []
    record = CurrentMetadata().map(seen.append)
    fiber = yield from record.repeat(schedule.spaced(1).up_to(times=2)).fork()
    yield from testing.adjust(10)
    yield from fiber.join()
    assert [(m.attempt, m.output, m.now, m.duration) for m in seen] == [
        (0, None, 0, 0),
        (1, 0, 0, 1),
        (2, 1, 1, 1),
    ]


def test_repeat_or_else_gets_the_error_and_the_last_metadata():
    seen: list[tuple[str, int | None]] = []
    n = 0

    def source() -> fx.Effect[int, str]:
        nonlocal n
        n += 1
        return fx.fail("first run failed") if n == 1 else fx.succeed(n)

    def recover(error: str, meta: Metadata[int, int] | None) -> fx.Effect[int]:
        seen.append((error, None if meta is None else meta.attempt))
        return fx.succeed(-1)

    assert run(fx.suspend(source).repeat_or_else(schedule.recurs(3), recover)) == -1
    assert seen == [("first run failed", None)]


def test_schedule_runs_after_each_delay_and_steps_with_each_result():
    inputs: list[object] = []
    n = 0

    def bump() -> int:
        nonlocal n
        n += 1
        return n

    tracked = schedule.recurs(3).tap(lambda m: fx.sync(lambda: inputs.append(m.input)))
    assert run(fx.sync(bump).schedule(tracked)) == 3
    assert inputs == [None, 1, 2]
    assert n == 3


def test_schedule_from_steps_first_with_the_initial_value():
    inputs: list[int] = []
    tracked = (
        schedule.recurs(2)
        .pipe(schedule.set_input_type(int))
        .tap(lambda m: fx.sync(lambda: inputs.append(m.input)))
    )
    assert run(fx.succeed(5).schedule_from(4, tracked)) == 2
    assert inputs == [4, 5]


def test_concat_continues_with_the_second_schedule_at_the_same_step():
    s = schedule.recurs(1).concat(schedule.spaced(3))
    assert delays(s, [0.0] * 4) == [0, 3, 3, 3]


def test_fixed_keeps_whole_beats_with_decimal_intervals():
    # Effect counts time in whole milliseconds, so a 100ms beat stays 100ms:
    # float seconds give 0.3 % 0.1 == 0.0999..., a near-zero delay.
    assert delays(schedule.fixed(0.1), [0.0, 0.1, 0.2, 0.3, 0.4, 0.5]) == [0.1] * 6
    assert delays(schedule.fixed(0.1), [0.0, 0.15, 0.25, 0.35]) == [0.1, 0.05, 0.05, 0.05]


def test_windowed_keeps_whole_windows_with_decimal_intervals():
    assert delays(schedule.windowed(0.1), [0.0, 0.3, 0.6, 0.7]) == [0.1] * 4
    assert delays(schedule.windowed(0.3), [0.0, 0.4, 0.7]) == [0.3, 0.2, 0.2]


def test_metadata_times_are_exact_to_the_nanosecond():
    seen: list[tuple[float, float]] = []
    s = schedule.forever.tap(
        lambda m: fx.sync(lambda: seen.append((m.elapsed, m.elapsed_since_previous)))
    )
    decisions(s, [1.0, 1.1, 1.3])
    assert seen == [(0.0, 0.0), (0.1, 0.1), (0.3, 0.2)]


@testing.effect
def test_fixed_keeps_the_beat_when_the_action_takes_the_whole_interval():
    beats: list[Seconds] = []
    tapped = (
        schedule.fixed(0.1).up_to(times=6).tap(lambda m: fx.sync(lambda: beats.append(m.duration)))
    )
    fiber = yield from fx.sleep(0.1).schedule(tapped).fork()
    yield from testing.adjust(10)
    yield from fiber.join()
    assert beats == [0.1] * 6


def test_windows_follow_effect_when_the_clock_moves_back():
    # Effect's ``%`` keeps the sign of the elapsed time, so a clock moved back
    # 0.3s before the start waits 1.3s for the window boundary.
    assert delays(schedule.windowed(1), [10.0, 9.7]) == [1, 1.3]
    assert delays(schedule.fixed(1), [10.0, 9.7]) == [1, 1.3]


def test_fibonacci_and_exponential_keep_whole_delays_with_decimal_units():
    # Effect sums whole milliseconds: 100, 200, 300, 500, 800, 1300.
    assert delays(schedule.fibonacci(0.1), [0.0] * 6) == [0.1, 0.2, 0.3, 0.5, 0.8, 1.3]
    assert delays(schedule.exponential(0.1, 3), [0.0] * 3) == [0.1, 0.3, 0.9]


def test_infinite_intervals_wait_forever():
    inf = float("inf")
    for s in (schedule.exponential(inf), schedule.fibonacci(inf), schedule.spaced(inf)):
        assert delays(s, [0.0, 1.0]) == [inf, inf]
    assert delays(schedule.fixed(inf), [0.0, 1.0]) == [inf, inf]
    assert delays(schedule.windowed(inf), [0.0, 1.0]) == [inf, inf]


def test_retry_builder_types_the_schedule_with_the_error():
    attempts: list[float] = []
    retryable = flaky(5, attempts).retry(
        lambda typed: typed(schedule.recurs(10)).while_(lambda m: m.input != "attempt 2 failed")
    )
    ex = testing.run_test_exit(retryable)
    assert isinstance(ex, fx.Failure)
    assert ex.cause.reasons == (Fail("attempt 2 failed"),)
    assert len(attempts) == 2


def test_repeat_builder_types_the_schedule_with_the_value():
    n = 0

    def bump() -> int:
        nonlocal n
        n += 1
        return n

    repeated = fx.sync(bump).repeat(
        lambda typed: typed(schedule.identity()).while_(lambda m: m.input < 4)
    )
    assert run(repeated) == 4


def test_retry_and_repeat_reject_a_schedule_with_option_keywords():
    eff = fx.succeed(1)
    with pytest.raises(TypeError, match="either a schedule or"):
        eff.retry(schedule.recurs(1), times=2)  # pyright: ignore[reportCallIssue]
    with pytest.raises(TypeError, match="either a schedule or"):
        eff.repeat(schedule.recurs(1), until=bool)  # pyright: ignore[reportCallIssue]


def test_a_builder_that_returns_no_schedule_is_rejected():
    def builder(typed: schedule.SetInputType[int]) -> int:
        return 3

    with pytest.raises(TypeError, match="must return a Schedule"):
        fx.succeed(1).repeat(builder)  # pyright: ignore[reportCallIssue, reportArgumentType]


def test_an_until_refinement_ends_with_the_narrowed_value():
    values: list[int | str] = [1, 2, "done"]

    def is_str(v: int | str) -> TypeIs[str]:
        return isinstance(v, str)

    result = fx.sync(lambda: values.pop(0)).repeat(until=is_str)
    assert run(result) == "done"


def test_map_effect_runs_an_effect_for_each_output():
    # Effect's Schedule.map with an effectful function: repeat gives 20 (checked under Node).
    s = schedule.recurs(2).map_effect(lambda m: fx.succeed(m.output * 10))
    assert run(fx.succeed(1).repeat(s)) == 20


def test_a_failing_map_effect_fails_the_repeat():
    s = schedule.recurs(2).map_effect(lambda _: fx.fail("mapped"))
    assert run(fx.succeed(1).repeat(s).result()) == Err("mapped")


@testing.effect
def test_to_step_with_sleep_sleeps_then_returns_the_decision():
    # Effect: toStepWithSleep(spaced("1 second").pipe(upTo({ times: 2 }))) gives 0, 1, Done(2).
    step = yield from schedule.to_step_with_sleep(schedule.spaced(1).up_to(times=2))
    times: list[float] = []

    def timed_step(i: int) -> fx.Effect[Decision[int]]:
        return step(i).tap(lambda _: fx.clock.now().map(times.append))

    fiber = yield from fx.for_each([0, 1, 2], timed_step).fork()
    yield from testing.adjust(2)
    decisions = yield from fiber.join()
    assert decisions == [Continue(0, Seconds(1)), Continue(1, Seconds(1)), Stop(2)]
    assert times == [1, 2, 2]
