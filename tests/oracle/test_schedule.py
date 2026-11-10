"""Ports of Effect's ``Schedule.test.ts``.

Each test's docstring is the Effect test title. A step takes epoch
milliseconds, as in Effect; delays are ``Seconds``. A step
returns ``Continue(output, delay)`` where Effect's ``Pull`` succeeds with
``[output, delay]``, and ``Stop(output)`` where it fails with
``Cause.done(output)``.

Every title is ported. The cron ports read the times in local time, as
Effect's ``new Date(2024, 0, 1)`` does.
"""

import math
from collections.abc import Callable, Iterable
from datetime import UTC, datetime

import pytest

import pyfect as fx
from pyfect import cron, random, schedule, testing
from pyfect.cron import CronParseError
from pyfect.duration import Duration, zero
from pyfect.result import Err, Ok
from pyfect.schedule import Continue, Metadata, Schedule, Stop


def run[A, E](eff: fx.Effect[A, E]) -> fx.Effect[A, E]:
    """Effect's ``run``: fork, move the test clock to infinity, join."""

    @fx.gen
    def go():
        fiber = yield from eff.fork()
        yield from testing.set_time(math.inf)
        return (yield from fiber.join())

    return go


def run_delays[I, E](
    s: Schedule[object, I, E], inputs: Iterable[I]
) -> fx.Effect[list[Duration], E]:
    """Effect's ``runDelays``: each step's delay, then 0 once it stops."""

    @fx.gen
    def go():
        step = yield from schedule.to_step_with_metadata(s)
        out: list[Duration] = []
        for value in inputs:
            meta = yield from step(value)
            if isinstance(meta, Stop):
                out.append(zero)
                break
            out.append(meta.duration)
        return out

    return run(go)


def nones(n: int) -> list[None]:
    return [None] * n


def ms(millis: float) -> Duration:
    return Duration(millis / 1000)


# --- constructors ---------------------------------------------------------------------


@testing.effect
def test_during_recurs_while_the_duration_has_not_elapsed():
    """during recurs while the duration has not elapsed"""
    step = yield from schedule.to_step(schedule.during("1 second"))
    decision = yield from step(0.0, None)
    assert isinstance(decision, Continue)


# --- combining ------------------------------------------------------------------------


@testing.effect
def test_max_outputs_the_slowest_schedule_duration():
    """max - outputs the slowest schedule duration"""
    s = schedule.max(
        schedule.fixed("5 seconds"),
        schedule.exponential("5 seconds"),
        schedule.spaced("10 seconds"),
    )
    assert (yield from run_delays(s, nones(3))) == [10, 10, 20]


@testing.effect
def test_max_stops_when_any_schedule_completes():
    """max - stops when any schedule completes"""
    s = schedule.max(schedule.duration("1 second"), schedule.spaced("5 seconds"))
    assert (yield from run_delays(s, nones(3))) == [5, 0]


@testing.effect
def test_min_outputs_the_fastest_schedule_duration():
    """min - outputs the fastest schedule duration"""
    s = schedule.min(
        schedule.fixed("5 seconds"),
        schedule.exponential("5 seconds"),
        schedule.spaced("10 seconds"),
    )
    assert (yield from run_delays(s, nones(3))) == [5, 5, 5]


@testing.effect
def test_min_continues_after_a_schedule_completes():
    """min - continues after a schedule completes"""
    s = schedule.min(schedule.duration("1 second"), schedule.spaced("5 seconds"))
    assert (yield from run_delays(s, nones(3))) == [1, 5, 5]


# --- sequencing -----------------------------------------------------------------------


@testing.effect
def test_concat_sequences_self_then_other_and_merges_their_outputs():
    """concat - sequences self then other and merges their outputs"""
    left_ids: Schedule[str, str] = schedule.identity()
    right_ids: Schedule[str, str] = schedule.identity()
    left = left_ids.up_to(times=2).map(lambda m: f"left:{m.output}")
    right = right_ids.map(lambda m: f"right:{m.output}")
    step = yield from schedule.to_step(left.concat(right))
    first = yield from step(0.0, "a")
    second = yield from step(0.0, "b")
    third = yield from step(0.0, "c")
    assert [first, second, third] == [
        Continue("left:a", zero),
        Continue("left:b", zero),
        Continue("right:c", zero),
    ]


def expected_metadata() -> list[Metadata[int, str]]:
    return [
        Metadata(
            input="a",
            output=0,
            duration=ms(250),
            attempt=1,
            start=1_000,
            now=1_000,
            elapsed=zero,
            elapsed_since_previous=zero,
        ),
        Metadata(
            input="b",
            output=1,
            duration=ms(250),
            attempt=2,
            start=1_000,
            now=1_250,
            elapsed=ms(250),
            elapsed_since_previous=ms(250),
        ),
    ]


@testing.effect
def test_tap_provides_full_metadata():
    """tap - provides full metadata"""
    observed: list[Metadata[int, str]] = []

    def record(m: Metadata[int, str]) -> fx.Effect[None]:
        return fx.sync(lambda: observed.append(m))

    s = schedule.spaced(ms(250)).pipe(schedule.set_input_type(str)).tap(record)
    step = yield from schedule.to_step(s)
    first = yield from step(1_000, "a")
    second = yield from step(1_250, "b")
    assert first == Continue(0, ms(250))
    assert second == Continue(1, ms(250))
    assert observed == expected_metadata()


@testing.effect
def test_modify_delay_provides_full_metadata():
    """modifyDelay - provides full metadata"""
    observed: list[Metadata[int, str]] = []

    def modify(m: Metadata[int, str]) -> fx.Effect[float]:
        observed.append(m)
        return fx.succeed(m.duration + m.elapsed_since_previous)

    s = schedule.spaced(ms(250)).pipe(schedule.set_input_type(str)).modify_delay(modify)
    step = yield from schedule.to_step(s)
    first = yield from step(1_000, "a")
    second = yield from step(1_250, "b")
    assert first == Continue(0, ms(250))
    assert second == Continue(1, ms(500))
    assert observed == expected_metadata()


@testing.effect
def test_add_delay_provides_full_metadata():
    """addDelay - provides full metadata"""
    observed: list[Metadata[int, str]] = []

    def extra(m: Metadata[int, str]) -> fx.Effect[float]:
        observed.append(m)
        return fx.succeed(m.elapsed_since_previous)

    s = schedule.spaced(ms(250)).pipe(schedule.set_input_type(str)).add_delay(extra)
    step = yield from schedule.to_step(s)
    first = yield from step(1_000, "a")
    second = yield from step(1_250, "b")
    assert first == Continue(0, ms(250))
    assert second == Continue(1, ms(500))
    assert observed == expected_metadata()


@testing.effect
def test_concat_result_sequences_self_then_other_when_collecting_delays():
    """concatResult - sequences self then other when collecting delays"""
    left = schedule.fixed(ms(500)).while_effect(lambda m: fx.succeed(m.attempt <= 3))
    s = left.concat_result(schedule.fixed("1 second"))
    assert (yield from run_delays(s, nones(6))) == [0.5, 0.5, 0.5, 1, 1, 1]


@testing.effect
def test_concat_result_includes_finite_other_completion_when_collecting_delays():
    """concatResult - includes finite other completion when collecting delays"""
    left = schedule.fixed(ms(500)).while_effect(lambda m: fx.succeed(m.attempt <= 2))
    s = left.concat_result(schedule.duration("1 second"))
    assert (yield from run_delays(s, nones(5))) == [0.5, 0.5, 1, 0]


@testing.effect
def test_concat_result_wraps_self_outputs_as_failure_and_other_outputs_as_success():
    """concatResult - wraps self outputs as Failure and other outputs as Success"""
    left_ids: Schedule[str, str] = schedule.identity()
    right: Schedule[str, str] = schedule.identity()
    step = yield from schedule.to_step(left_ids.up_to(times=2).concat_result(right))
    first = yield from step(0.0, "left-1")
    second = yield from step(0.0, "left-2")
    third = yield from step(0.0, "right-1")
    assert [first, second, third] == [
        Continue(Err("left-1"), zero),
        Continue(Err("left-2"), zero),
        Continue(Ok("right-1"), zero),
    ]


# --- duration -------------------------------------------------------------------------


@testing.effect
def test_duration_recurs_once_after_the_provided_duration():
    """recurs once after the provided duration"""
    assert (yield from run_delays(schedule.duration("1 second"), nones(5))) == [1, 0]


# --- once -----------------------------------------------------------------------------


@testing.effect
def test_once_recurs_immediately_once_then_completes_with_void():
    """recurs immediately once, then completes with void"""
    step = yield from schedule.to_step(schedule.once)
    first = yield from step(0.0, "first")
    second = yield from step(1.0, "second")
    assert first == Continue(None, zero)
    assert second == Stop(None)


@testing.effect
def test_once_repeats_an_effect_exactly_once_after_its_initial_execution():
    """repeats an effect exactly once after its initial execution"""
    executions = 0

    def run_once() -> None:
        nonlocal executions
        executions += 1

    yield from fx.sync(run_once).repeat(schedule.once)
    assert executions == 2


# --- upTo -----------------------------------------------------------------------------


@testing.effect
def test_up_to_limits_by_times():
    """limits by times"""
    ids: Schedule[str, str] = schedule.identity()
    step = yield from schedule.to_step(ids.up_to(times=2))
    first = yield from step(0.0, "a")
    second = yield from step(0.0, "b")
    third = yield from step(0.0, "c")
    assert [first, second, third] == [Continue("a", zero), Continue("b", zero), Stop("c")]


@testing.effect
def test_up_to_limits_by_duration():
    """limits by duration"""
    ids: Schedule[str, str] = schedule.identity()
    step = yield from schedule.to_step(ids.up_to(duration="1 second"))
    first = yield from step(0.0, "a")
    second = yield from step(1_000, "b")
    third = yield from step(1_001, "c")
    assert [first, second, third] == [Continue("a", zero), Continue("b", zero), Stop("c")]


@testing.effect
def test_up_to_limits_by_the_first_exhausted_option():
    """limits by the first exhausted option"""
    ids: Schedule[str, str] = schedule.identity()
    step = yield from schedule.to_step(ids.up_to(duration="1 hour", times=1))
    first = yield from step(0.0, "a")
    second = yield from step(0.0, "b")
    assert [first, second] == [Continue("a", zero), Stop("b")]


@testing.effect
def test_up_to_leaves_the_schedule_unchanged_when_no_options_are_specified():
    """leaves the schedule unchanged when no options are specified"""
    ids: Schedule[str, str] = schedule.identity()
    step = yield from schedule.to_step(ids.up_to())
    first = yield from step(0.0, "a")
    second = yield from step(0.0, "b")
    assert [first, second] == [Continue("a", zero), Continue("b", zero)]


# --- jittered -------------------------------------------------------------------------


@testing.effect
def test_jittered_keeps_delays_within_80_120_percent_of_the_original():
    """keeps delays within 80%-120% of the original"""
    output = yield from run_delays(schedule.spaced("1 second").jittered(), nones(20)).pipe(
        random.with_seed("jittered-bounds")
    )
    assert len(output) == 20
    assert all(0.8 <= d <= 1.2 for d in output)


@testing.effect
def test_jittered_does_not_change_completion_output():
    """does not change completion output"""
    output = yield from run_delays(schedule.duration("1 second").jittered(), nones(5)).pipe(
        random.with_seed("jittered-completion")
    )
    assert len(output) == 2
    assert 0.8 <= output[0] <= 1.2
    assert output[1] == 0


# --- spaced, fixed, windowed ----------------------------------------------------------


@testing.effect
def test_spaced_constant_delays():
    """spaced / constant delays"""
    assert (yield from run_delays(schedule.spaced("1 second"), nones(5))) == [1] * 5


@testing.effect
def test_fibonacci_repeats_the_initial_delay():
    """repeats the initial delay"""
    output = yield from run_delays(schedule.fibonacci("100 millis"), nones(5))
    assert output == [ms(100), ms(100), ms(200), ms(300), ms(500)]


@testing.effect
def test_fixed_constant_delays():
    """fixed / constant delays"""
    assert (yield from run_delays(schedule.fixed("1 second"), nones(5))) == [1] * 5


def record_delays(s: Schedule[int], action_time: float) -> fx.Effect[list[Duration]]:
    """Effect's pattern: tap each delay, ``Effect.schedule`` an action that
    sleeps ``action_time``, record 0 when it finishes, and run the clock."""

    @fx.gen
    def go():
        delays: list[Duration] = []
        tapped = s.while_(lambda m: m.attempt <= 5).tap(
            lambda m: fx.sync(lambda: delays.append(m.duration))
        )
        yield from (
            fx.sleep(Duration(action_time))
            .schedule(tapped)
            .and_then(fx.sync(lambda: delays.append(zero)))
            .fork()
        )
        yield from testing.set_time(math.inf)
        return delays

    return go


@testing.effect
def test_fixed_delays_until_the_nearest_window_boundary_when_action_is_slow():
    """delays until the nearest window boundary when action is slow"""
    delays = yield from record_delays(schedule.fixed("1 second"), 0.5)
    assert delays == [1, 0.5, 0.5, 0.5, 0.5, 0]


@testing.effect
def test_fixed_matches_effect_v3_when_action_duration_exceeds_the_interval():
    """matches effect v3 when action duration exceeds the interval"""
    delays = yield from record_delays(schedule.fixed("1 second"), 1.5)
    assert delays == [1, 0, 0, 0, 0, 0]


@pytest.mark.parametrize("make", [schedule.fixed, schedule.windowed])
@testing.effect
def test_waits_a_full_window_when_the_delay_to_the_boundary_rounds_to_zero(
    make: Callable[[str], Schedule[int]],
):
    """waits a full window when the delay to the boundary rounds to zero"""
    step = yield from schedule.to_step(make("1 second"))
    yield from step(1000, None)
    decision = yield from step(1999.9999999999998, None)
    assert isinstance(decision, Continue)
    assert decision.delay == 1


@testing.effect
def test_windowed_constant_delays():
    """windowed / constant delays"""
    assert (yield from run_delays(schedule.windowed("1 second"), nones(5))) == [1] * 5


@testing.effect
def test_windowed_delays_until_the_nearest_window_boundary():
    """delays until the nearest window boundary"""
    delays = yield from record_delays(schedule.windowed("1 second"), 1.5)
    assert delays == [1, 0.5, 0.5, 0.5, 0.5, 0]


# --- cron -----------------------------------------------------------------------------


def cron_times(
    expression: str, start: datetime, steps: int
) -> fx.Effect[list[str], CronParseError]:
    """Effect's pattern: set the clock to ``start``, run the delays and
    format each time they add up to, in local time."""

    @fx.gen
    def go():
        yield from testing.set_time(start.timestamp() * 1000)
        delays = yield from run_delays(schedule.cron(expression), nones(steps))
        times: list[str] = []
        at = start.timestamp()
        for delay in delays:
            at += delay
            times.append(datetime.fromtimestamp(at).strftime("%a %b %d %Y %H:%M:%S"))
        return times

    return go


@testing.effect
def test_cron_waits_for_the_next_match_when_the_delay_to_the_current_one_rounds_to_zero():
    """waits for the next match when the delay to the current one rounds to zero"""
    step = yield from schedule.to_step(schedule.cron("* * * * * *"))
    decision = yield from step(1999.9999999999998, None)
    assert isinstance(decision, Continue)
    assert decision.delay == 1


def berlin_times(s: Schedule[Duration, None, CronParseError], start: str) -> fx.Effect[list[str]]:
    @fx.gen
    def go():
        at = datetime.fromisoformat(start).timestamp()
        yield from testing.set_time(at * 1000)
        delays = yield from run_delays(s, nones(4)).or_die()
        times: list[str] = []
        for delay in delays:
            at += delay
            times.append(datetime.fromtimestamp(at, UTC).isoformat().replace("+00:00", "Z"))
        return times

    return go


@testing.effect
def test_cron_honors_on_dst_overlap_across_a_dst_fold():
    """honors onDstOverlap across a DST fold"""
    # Europe/Berlin repeats local 02:00-02:59 at 01:00Z-01:59Z on 2026-10-25.
    every5 = "*/5 * * * *"
    earlier = yield from berlin_times(
        schedule.cron(every5, "Europe/Berlin"), "2026-10-25T00:55:00Z"
    )
    assert earlier == [
        "2026-10-25T02:00:00Z",
        "2026-10-25T02:05:00Z",
        "2026-10-25T02:10:00Z",
        "2026-10-25T02:15:00Z",
    ]
    both = yield from berlin_times(
        schedule.cron(every5, "Europe/Berlin", on_dst_overlap="both"), "2026-10-25T00:55:00Z"
    )
    assert both == [
        "2026-10-25T01:00:00Z",
        "2026-10-25T01:05:00Z",
        "2026-10-25T01:10:00Z",
        "2026-10-25T01:15:00Z",
    ]
    parsed = cron.parse_unsafe(every5, "Europe/Berlin", on_dst_overlap="both")
    from_cron = yield from berlin_times(schedule.cron(parsed), "2026-10-25T01:07:00Z")
    assert from_cron == [
        "2026-10-25T01:10:00Z",
        "2026-10-25T01:15:00Z",
        "2026-10-25T01:20:00Z",
        "2026-10-25T01:25:00Z",
    ]


@testing.effect
def test_cron_should_recur_on_interval_matching_cron_expression():
    """should recur on interval matching cron expression"""
    times = yield from cron_times("*/2 * * * *", datetime(2024, 1, 1, 0, 0, 35), 4)
    assert times == [
        "Mon Jan 01 2024 00:02:00",
        "Mon Jan 01 2024 00:04:00",
        "Mon Jan 01 2024 00:06:00",
        "Mon Jan 01 2024 00:08:00",
    ]


@testing.effect
def test_cron_should_recur_on_interval_matching_cron_expression_second_granularity():
    """should recur on interval matching cron expression (second granularity)"""
    times = yield from cron_times("*/3 * * * * *", datetime(2024, 1, 1), 10)
    assert times == [f"Mon Jan 01 2024 00:00:{s:02}" for s in range(3, 31, 3)]


@testing.effect
def test_cron_should_recur_at_time_matching_cron_expression():
    """should recur at time matching cron expression"""
    times = yield from cron_times("30 4 5,15 * WED", datetime(2024, 1, 1), 6)
    assert times == [
        "Wed Jan 03 2024 04:30:00",
        "Fri Jan 05 2024 04:30:00",
        "Wed Jan 10 2024 04:30:00",
        "Mon Jan 15 2024 04:30:00",
        "Wed Jan 17 2024 04:30:00",
        "Wed Jan 24 2024 04:30:00",
    ]


@testing.effect
def test_cron_does_not_fail_when_the_test_clock_is_adjusted_to_infinity():
    """does not fail when the test clock is adjusted to infinity"""
    latch = yield from fx.Deferred[None].make()
    fiber = yield from latch.wait().repeat(schedule.cron("0 0 4 8-14 * *", "UTC")).fork()
    yield from testing.adjust(math.inf)
    yield from latch.succeed(None)
    yield from fiber.join()
