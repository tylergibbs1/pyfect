"""Cron behavior beyond Effect's tests. The expected times were printed by
Effect's ``Cron`` under Node (``Cron.next`` / ``prev`` in a loop), and a
3,000-expression random sweep over eight zones matched Effect exactly."""

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import pyfect as fx
from pyfect import cron, schedule, testing
from pyfect.cron import CronParseError


def walk(expression: str, zone: str, start: str, steps: int, *, back: bool = False) -> list[str]:
    c = cron.parse_unsafe(expression, zone)
    at = datetime.fromisoformat(start)
    out: list[str] = []
    for _ in range(steps):
        at = cron.prev(c, at) if back else cron.next(c, at)
        out.append(at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"))
    return out


def test_a_half_hour_dst_fold_runs_each_wall_time_once():
    # Lord Howe falls back from +11:00 to +10:30, repeating 01:30-01:59.
    assert walk("15,45 * * * *", "Australia/Lord_Howe", "2024-04-07T00:00:00+11:00", 5) == [
        "2024-04-06T13:15:00Z",
        "2024-04-06T13:45:00Z",
        "2024-04-06T14:15:00Z",
        "2024-04-06T14:45:00Z",
        "2024-04-06T15:45:00Z",
    ]


def test_prev_across_a_half_hour_dst_fold():
    times = walk("15,45 * * * *", "Australia/Lord_Howe", "2024-04-07T03:00:00+10:30", 5, back=True)
    assert times == [
        "2024-04-06T16:15:00Z",
        "2024-04-06T15:45:00Z",
        "2024-04-06T14:45:00Z",
        "2024-04-06T14:15:00Z",
        "2024-04-06T13:45:00Z",
    ]


def test_a_half_hour_dst_gap_moves_to_the_time_after_it():
    # Lord Howe springs forward from 02:00 +10:30 to 02:30 +11:00.
    assert walk("15,45 * * * *", "Australia/Lord_Howe", "2024-10-06T01:00:00+10:30", 4) == [
        "2024-10-05T14:45:00Z",
        "2024-10-05T15:15:00Z",
        "2024-10-05T15:45:00Z",
        "2024-10-05T16:15:00Z",
    ]


def test_a_leading_step_of_one_leaves_the_whole_field_unrestricted():
    # Effect ignores the rest of a list that starts with ``*/1``, as with ``*``.
    c = cron.parse_unsafe("*/1,5 * */1,3 * *")
    assert c == cron.parse_unsafe("* * * * *")
    assert cron.format(c) == "* * * * *"


def test_prev_of_a_time_a_dst_gap_skips_matches_effect():
    # Effect 4.0.6 under Node: prev lands on the instant after Lord Howe's
    # gap (02:30 +11:00) and stays there, and in Berlin it finds nothing.
    times = walk("30 2 * * *", "Australia/Lord_Howe", "2024-10-05T18:00:00+00:00", 3, back=True)
    assert times == ["2024-10-05T15:30:00Z"] * 3
    with pytest.raises(ValueError, match="Unable to find cron date"):
        walk("30 2 * * *", "Europe/Berlin", "2024-03-31T03:00:00+00:00", 1, back=True)


def test_next_raises_for_a_day_that_never_exists():
    with pytest.raises(ValueError, match="Unable to find cron date"):
        cron.next(cron.parse_unsafe("0 0 30 2 *", "UTC"), datetime(2024, 1, 1, tzinfo=UTC))


def test_a_cron_without_a_zone_runs_in_the_zone_of_its_input():
    c = cron.parse_unsafe("0 9 * * *")
    tokyo = ZoneInfo("Asia/Tokyo")
    found = cron.next(c, datetime(2024, 1, 1, 12, tzinfo=tokyo))
    assert found == datetime(2024, 1, 2, 9, tzinfo=tokyo)
    assert found.tzinfo is tokyo
    plus_two = timezone(timedelta(hours=2))
    assert cron.match(c, datetime(2024, 1, 1, 9, tzinfo=plus_two))
    assert not cron.match(c, datetime(2024, 1, 1, 9, tzinfo=UTC).astimezone(plus_two))


def test_naive_datetimes_are_rejected():
    c = cron.parse_unsafe("* * * * *")
    with pytest.raises(ValueError, match="aware"):
        cron.next(c, datetime(2024, 1, 1))
    with pytest.raises(ValueError, match="aware"):
        cron.match(c, datetime(2024, 1, 1))


def test_parse_reports_the_time_zone_before_the_fields():
    result = cron.parse("61 * * * *", "Not/AZone")
    assert result == fx.result.Err(
        CronParseError("Invalid time zone in cron expression", "Not/AZone")
    )


@testing.effect
def test_an_invalid_expression_fails_the_schedule_with_cron_parse_error():
    exit = yield from fx.void.repeat(schedule.cron("61 * * * *")).exit()
    assert exit == fx.Failure(
        fx.cause.fail(CronParseError("Expected a value between 0 and 59", "61"))
    )


@pytest.mark.parametrize(
    ("expression", "message"),
    [
        ("*/0 * * * *", "Expected step value to be greater than 0"),
        ("*/61 * * * *", "Expected step value to be less than or equal to 59"),
        ("* */24 * * *", "Expected step value to be less than or equal to 23"),
        ("* * * */13 *", "Expected step value to be less than or equal to 12"),
        ("*/a * * * *", "Expected step value to be a positive integer"),
    ],
)
def test_step_values_out_of_range_are_rejected_like_effect(expression: str, message: str):
    # Messages printed by Effect's Cron.parse under Node.
    result = cron.parse(expression)
    assert isinstance(result, fx.result.Err)
    assert result.error.message == message


def test_next_without_a_start_searches_from_now():
    c = cron.parse_unsafe("* * * * *", "UTC")
    before = datetime.now(UTC)
    found = cron.next(c)
    assert before < found <= before + timedelta(minutes=1)
    assert found.second == 0
    assert found.tzinfo == ZoneInfo("UTC")
