"""Ports of Effect's ``Cron.test.ts``. Each test's docstring is the Effect
test title.

Effect's ``Date`` inputs are aware datetimes here. A JavaScript date
string without a zone (``new Date("2024-08-01 00:05:00")``) is local time,
so it becomes ``local("2024-08-01 00:05:00")``, an aware datetime at the
local offset, which a cron without a zone runs in, as Effect's does.
``Cron.isCron`` / ``isCronParseError`` are ``isinstance``; Effect's
``RangeError`` from ``make`` is a ``ValueError``.

Every title is ported. JavaScript rolls the invalid ``2025-02-29`` over to
March 1, which is what the leap-year port passes."""

from builtins import next as builtins_next
from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

from pyfect import cron
from pyfect.cron import Cron, CronParseError
from pyfect.date_time import format_iso_zoned, make_zoned, make_zoned_from_string
from pyfect.result import Err, Ok

UTC_ZONE = ZoneInfo("UTC")
BERLIN = ZoneInfo("Europe/Berlin")
ALL_DAYS = list(range(1, 32))
ALL_WEEKDAYS = list(range(7))


def local(text: str) -> datetime:
    """A JavaScript date string without a zone: local time."""
    return datetime.fromisoformat(text).astimezone()


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text).astimezone(UTC)


def zoned(text: str) -> datetime:
    parsed = make_zoned_from_string(text)
    assert parsed is not None
    return parsed


def iso(text: str) -> str:
    """Effect's ``formatIsoZoned(makeZonedFromString(text))``."""
    return format_iso_zoned(zoned(text))


def as_cron(value: Cron | str) -> Cron:
    return value if isinstance(value, Cron) else cron.parse_unsafe(value)


def match(value: Cron | str, date: datetime) -> bool:
    return cron.match(as_cron(value), date)


def next_(value: Cron | str, after: datetime | None = None) -> datetime:
    return cron.next(as_cron(value), after)


def prev(value: Cron | str, before: datetime | None = None) -> datetime:
    return cron.prev(as_cron(value), before)


def plain(
    *,
    minutes: list[int],
    hours: list[int],
    days: list[int],
    months: list[int],
    weekdays: list[int],
) -> Cron:
    return cron.make(minutes=minutes, hours=hours, days=days, months=months, weekdays=weekdays)


def test_is_cron_parse_error():
    """isCronParseError"""
    result = cron.parse("")
    assert isinstance(result, Err)
    assert isinstance(result.error, CronParseError)
    assert not isinstance(Exception("regular error"), CronParseError)
    assert not isinstance("not an error", CronParseError)


def test_cron_parse_error_constructor():
    """CronParseError constructor"""
    error = CronParseError(message="boom", input="0 0 * * *")
    assert isinstance(error, Exception)
    assert type(error).__name__ == "CronParseError"
    assert error.message == "boom"
    assert str(error) == "boom"
    assert error.input == "0 0 * * *"


def test_parse():
    """parse"""
    assert cron.parse("0 4 8-14 * 0-6") == Ok(
        plain(
            minutes=[0],
            hours=[4],
            days=[8, 9, 10, 11, 12, 13, 14],
            months=[],
            weekdays=ALL_WEEKDAYS,
        )
    )
    assert cron.parse("0 0 1,15 * 3") == Ok(
        plain(minutes=[0], hours=[0], days=[1, 15], months=[], weekdays=[3])
    )
    assert cron.parse("23 0-20/2 * * *") == Ok(
        plain(minutes=[23], hours=list(range(0, 21, 2)), days=[], months=[], weekdays=[])
    )
    assert cron.parse("5/15 * * * *") == Ok(
        plain(minutes=[5, 20, 35, 50], hours=[], days=[], months=[], weekdays=[])
    )
    assert cron.parse("0 0 1/1 * 1") == Ok(
        plain(minutes=[0], hours=[0], days=ALL_DAYS, months=[], weekdays=[1])
    )
    assert cron.parse("0 0 */1 * 1") == Ok(
        plain(minutes=[0], hours=[0], days=[], months=[], weekdays=[1])
    )
    assert cron.parse("0 0 1-31 * MON") == Ok(
        plain(minutes=[0], hours=[0], days=ALL_DAYS, months=[], weekdays=[1])
    )
    assert cron.parse("0 0 1-31/1 * MON") == Ok(
        plain(minutes=[0], hours=[0], days=ALL_DAYS, months=[], weekdays=[1])
    )
    assert cron.parse("0 0 1 * 0-6") == Ok(
        plain(minutes=[0], hours=[0], days=[1], months=[], weekdays=ALL_WEEKDAYS)
    )
    assert cron.parse("0 0 1 * SUN-SAT") == Ok(
        plain(minutes=[0], hours=[0], days=[1], months=[], weekdays=ALL_WEEKDAYS)
    )
    assert cron.parse("0\t0\t*\t*\t7") == Ok(
        plain(minutes=[0], hours=[0], days=[], months=[], weekdays=[0])
    )

    def failure(expression: str) -> str:
        result = cron.parse(expression)
        assert isinstance(result, Err)
        return result.error.message

    assert failure("0/1,60 * * * *") == "Expected a value between 0 and 59"
    assert failure("0 0 1/1,32 * *") == "Expected a value between 1 and 31"
    assert failure("*/60 * * * *") == "Expected step value to be less than or equal to 59"
    for invalid in (
        "0,,5 * * * *",
        ",5 * * * *",
        "-5 * * * *",
        "0- * * * *",
        "1e1 * * * *",
        "0x10 * * * *",
        "+5 * * * *",
    ):
        assert isinstance(cron.parse(invalid), Err)

    named = cron.parse_unsafe("23 0-20/2 * * *", "Europe/Berlin")
    assert named.tz == BERLIN
    offset = cron.parse_unsafe("23 0-20/2 * * *", "+02:00")
    assert offset.tz == timezone(timedelta(hours=2))
    assert cron.parse_unsafe("23 0-20/2 * * *").tz is None


def test_parse_unsafe():
    """parseUnsafe"""
    with pytest.raises(CronParseError) as segments:
        cron.parse_unsafe("")
    assert segments.value.message == "Invalid number of segments in cron expression"
    assert segments.value.input == ""
    with pytest.raises(CronParseError) as zone:
        cron.parse_unsafe("0 0 4 8-14 * *", "")
    assert zone.value.message == "Invalid time zone in cron expression"
    assert zone.value.input == ""


def test_format_preserves_compact_cron_syntax():
    """format preserves compact cron syntax"""
    assert cron.format(cron.parse_unsafe("23 0-20/2 * * 0", "Europe/Berlin")) == "23 0-20/2 * * 0"


def test_format_can_include_the_default_seconds_field():
    """format can include the default seconds field"""
    expression = cron.parse_unsafe("23 0-20/2 * * 0")
    assert cron.format(expression, include_seconds=True) == "0 23 0-20/2 * * 0"


def test_format_compacts_multiple_runs_within_a_field():
    """format compacts multiple runs within a field"""
    expression = plain(minutes=[0, 1, 2, 10, 20, 30], hours=[], days=[], months=[], weekdays=[])
    assert cron.format(expression) == "0-2,10-30/10 * * * *"


def test_format_preserves_non_uniform_values():
    """format preserves non-uniform values"""
    expression = plain(minutes=[1, 5, 11], hours=[], days=[], months=[], weekdays=[])
    assert cron.format(expression) == "1,5,11 * * * *"


def test_format_handles_default_non_default_and_unrestricted_seconds():
    """format handles default, non-default, and unrestricted seconds"""

    def format(seconds: list[int] | None = None) -> str:
        if seconds is None:
            return cron.format(plain(minutes=[], hours=[], days=[], months=[], weekdays=[]))
        return cron.format(
            cron.make(seconds=seconds, minutes=[], hours=[], days=[], months=[], weekdays=[])
        )

    assert format() == "* * * * *"
    assert format([15, 30]) == "15,30 * * * * *"
    assert format([]) == "* * * * * *"


def test_make_supports_requiring_both_days_and_weekdays():
    """make supports requiring both days and weekdays"""

    def make(*, and_: bool) -> Cron:
        return cron.make(
            minutes=[0], hours=[0], days=[1], months=[], weekdays=[1], tz=UTC_ZONE, and_=and_
        )

    or_cron = make(and_=False)
    and_cron = make(and_=True)

    assert cron.match(or_cron, utc("2024-01-08T00:00:00Z"))
    assert not cron.match(and_cron, utc("2024-01-08T00:00:00Z"))
    assert cron.match(and_cron, utc("2024-01-01T00:00:00Z"))
    assert or_cron != and_cron
    assert cron.next(or_cron, utc("2024-01-02T00:00:00Z")) == utc("2024-01-08T00:00:00Z")
    assert cron.next(and_cron, utc("2024-01-02T00:00:00Z")) == utc("2024-04-01T00:00:00Z")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("seconds", 60),
        ("minutes", -1),
        ("hours", 24),
        ("days", 0),
        ("months", 13),
        ("weekdays", 8),
        ("seconds", 0.5),
        ("minutes", float("nan")),
    ],
)
def test_make_validates_field_values_and_normalizes_weekday_7(field: str, value: float):
    """make validates field values and normalizes weekday 7"""
    fields: dict[str, list[float]] = {
        name: [value] if name == field else []
        for name in ("seconds", "minutes", "hours", "days", "months", "weekdays")
    }
    with pytest.raises(ValueError):
        cron.make(**fields)  # pyright: ignore[reportArgumentType]

    normalized = cron.make(minutes=[], hours=[], days=[], months=[], weekdays=[7])
    assert normalized.seconds == frozenset({0})
    assert normalized.weekdays == frozenset({0})


def test_make_treats_weekday_7_as_sunday_when_matching():
    """make treats weekday 7 as Sunday when matching"""
    expression = cron.make(minutes=[0], hours=[0], days=[], months=[], weekdays=[7], tz=UTC_ZONE)
    assert cron.match(expression, utc("2024-01-07T00:00:00Z"))
    assert not cron.match(expression, utc("2024-01-08T00:00:00Z"))


def test_make_treats_weekday_7_as_sunday_when_stepping():
    """make treats weekday 7 as Sunday when stepping"""
    expression = cron.make(minutes=[0], hours=[0], days=[], months=[], weekdays=[7], tz=UTC_ZONE)
    assert cron.next(expression, utc("2024-01-05T00:00:00Z")) == utc("2024-01-07T00:00:00Z")
    assert cron.prev(expression, utc("2024-01-08T00:00:00Z")) == utc("2024-01-07T00:00:00Z")


def test_match():
    """match"""
    assert match("5 0 * 8 *", local("2024-08-01 00:05:00"))
    assert not match("5 0 * 8 *", local("2024-09-01 00:05:00"))
    assert not match("5 0 * 8 *", local("2024-08-01 01:05:00"))

    assert match("15 14 1 * *", local("2024-02-01 14:15:00"))
    assert not match("15 14 1 * *", local("2024-02-01 15:15:00"))
    assert not match("15 14 1 * *", local("2024-02-02 14:15:00"))

    assert match("23 0-20/2 * * 0", local("2024-01-07 00:23:00"))
    assert not match("23 0-20/2 * * 0", local("2024-01-07 03:23:00"))
    assert not match("23 0-20/2 * * 0", local("2024-01-08 00:23:00"))

    assert match("5 4 * * SUN", local("2024-01-07 04:05:00"))
    assert not match("5 4 * * SUN", local("2024-01-08 04:05:00"))
    assert not match("5 4 * * SUN", local("2025-01-07 04:05:00"))

    assert match("5 4 * DEC SUN", local("2024-12-01 04:05:00"))
    assert not match("5 4 * DEC SUN", local("2024-12-01 04:06:00"))
    assert not match("5 4 * DEC SUN", local("2024-12-02 04:05:00"))

    assert match("0 0 1/1 * 1", local("2024-01-02 00:00:00"))
    assert match("0 0 1-31 * 1", local("2024-01-02 00:00:00"))
    assert match("0 0 1 * SUN-SAT", local("2024-01-02 00:00:00"))
    assert match("0 0 * * 7", local("2024-01-07 00:00:00"))
    assert not match("0 0 */2 * MON", local("2024-01-03 00:00:00"))
    assert match("0 0 */2 * MON", local("2024-01-15 00:00:00"))
    assert match("0 0 1-31/2 * MON", local("2024-01-03 00:00:00"))
    assert not match("0 0 *,5 * MON", local("2024-01-03 00:00:00"))
    assert match("0 0 5,* * MON", local("2024-01-03 00:00:00"))

    assert match("42 5 0 * 8 *", local("2024-08-01 00:05:42"))
    assert not match("42 5 0 * 8 *", local("2024-09-01 00:05:42"))
    assert not match("42 5 0 * 8 *", local("2024-08-01 01:05:42"))

    london = ZoneInfo("Europe/London")
    london_time = make_zoned(datetime(2024, 6, 1, 14, 15), london)
    amsterdam_time = make_zoned(datetime(2024, 6, 1, 15, 15), ZoneInfo("Europe/Amsterdam"))
    assert match(cron.parse_unsafe("15 14 1 * *", london), london_time)
    assert match(cron.parse_unsafe("15 14 1 * *", london), amsterdam_time)


def test_next():
    """next"""
    after = local("2024-01-04 16:21:00")
    assert next_("5 0 8 2 *", after) == local("2024-02-08 00:05:00")
    assert next_("15 14 1 * *", after) == local("2024-02-01 14:15:00")
    assert next_("23 0-20/2 * * 0", after) == local("2024-01-07 00:23:00")
    assert next_("5 4 * * SUN", after) == local("2024-01-07 04:05:00")
    assert next_("5 4 * DEC SUN", after) == local("2024-12-01 04:05:00")
    assert next_("30 5 0 8 2 *", after) == local("2024-02-08 00:05:30")

    london = ZoneInfo("Europe/London")
    london_time = make_zoned(datetime(2024, 2, 8, 0, 5), london)
    amsterdam_time = make_zoned(datetime(2024, 2, 8, 1, 5), ZoneInfo("Europe/Amsterdam"))
    assert next_(cron.parse_unsafe("5 0 8 2 *", london), after) == london_time
    assert next_(cron.parse_unsafe("5 0 8 2 *", london), after) == amsterdam_time


def test_next_adheres_to_day_of_month_and_weekday_semantics():
    """next adheres to day-of-month and weekday semantics"""
    after = utc("2024-01-02T12:00:00Z")
    assert next_(cron.parse_unsafe("0 0 */2 * MON", UTC_ZONE), after) == utc("2024-01-15T00:00:00Z")
    assert next_(cron.parse_unsafe("0 0 1-31/2 * MON", UTC_ZONE), after) == utc(
        "2024-01-03T00:00:00Z"
    )
    assert next_(cron.parse_unsafe("0 0 *,5 * MON", UTC_ZONE), after) == utc("2024-01-08T00:00:00Z")
    assert next_(cron.parse_unsafe("0 0 5,* * MON", UTC_ZONE), after) == utc("2024-01-03T00:00:00Z")


def test_next_does_not_skip_earlier_days_when_the_upcoming_day_is_missing_from_the_month():
    """next does not skip earlier days when the upcoming day is missing from the month"""
    expression = cron.parse_unsafe("0 0 1,16,31 * *", UTC_ZONE)
    assert next_(expression, utc("2020-02-18T00:00:00Z")) == utc("2020-03-01T00:00:00Z")
    every_15 = cron.parse_unsafe("0 0 */15 * *", UTC_ZONE)
    assert next_(every_15, utc("2020-02-18T00:00:00Z")) == utc("2020-03-01T00:00:00Z")
    assert next_(expression, utc("2024-06-20T00:00:00Z")) == utc("2024-07-01T00:00:00Z")


def test_next_respects_day_of_month_or_weekday_constraints_when_entering_a_restricted_month():
    """next respects day-of-month or weekday constraints when entering a restricted month"""
    after = utc("2024-01-01T00:00:00Z")
    assert next_(cron.parse_unsafe("0 0 29 2 MON", UTC_ZONE), after) == utc("2024-02-05T00:00:00Z")
    assert next_(cron.parse_unsafe("0 0 30 2 MON", UTC_ZONE), after) == utc("2024-02-05T00:00:00Z")
    assert next_(cron.parse_unsafe("0 0 31 2 MON", UTC_ZONE), after) == utc("2024-02-05T00:00:00Z")


def test_prev():
    """prev"""
    before = utc("2024-01-04T16:21:00Z")

    def back(expression: str, start: datetime = before) -> datetime:
        return prev(cron.parse_unsafe(expression, UTC_ZONE), start)

    assert back("5 0 8 2 *") == utc("2023-02-08T00:05:00Z")
    assert back("15 14 1 * *") == utc("2024-01-01T14:15:00Z")
    assert back("23 0-20/2 * * * 0") == utc("2023-12-31T23:20:23Z")
    assert back("5 4 * * SUN") == utc("2023-12-31T04:05:00Z")
    assert back("5 4 * DEC SUN") == utc("2023-12-31T04:05:00Z")
    assert back("30 5 0 8 2 *") == utc("2023-02-08T00:05:30Z")

    wednesday = utc("2025-10-22T01:00:00Z")
    assert back("0 1 * * MON", wednesday) == utc("2025-10-20T01:00:00Z")
    assert next_(cron.parse_unsafe("0 1 * * MON", UTC_ZONE), wednesday) == utc(
        "2025-10-27T01:00:00Z"
    )
    assert back("0 1 * * TUE", wednesday) == utc("2025-10-21T01:00:00Z")
    assert next_(cron.parse_unsafe("0 1 * * TUE", UTC_ZONE), wednesday) == utc(
        "2025-10-28T01:00:00Z"
    )


def test_prev_includes_an_occurrence_earlier_in_the_same_second():
    """prev includes an occurrence earlier in the same second"""
    daily = cron.parse_unsafe("0 0 * * *", "UTC")
    assert prev(daily, utc("2024-01-01T00:00:00.001Z")) == utc("2024-01-01T00:00:00Z")
    assert prev(daily, utc("2024-01-01T00:00:00.000Z")) == utc("2023-12-31T00:00:00Z")
    seconds = cron.parse_unsafe("10,30 * * * * *", "UTC")
    assert prev(seconds, utc("2024-01-01T00:00:30.999Z")) == utc("2024-01-01T00:00:30Z")


def test_returns_the_latest_second_when_rolling_back_a_minute():
    """returns the latest second when rolling back a minute"""
    expression = cron.parse_unsafe("10,30 * * * * *", UTC_ZONE)
    assert prev(expression, utc("2024-01-01T00:00:05Z")) == utc("2023-12-31T23:59:30Z")


@pytest.mark.parametrize(
    ("expression", "lower", "upper"),
    [
        ("5 2 * * 1", "2020-01-01T00:00:01Z", "2021-01-01T00:00:01Z"),
        ("0 12 1 * *", "2020-01-01T00:00:01Z", "2021-01-01T00:00:01Z"),
        ("10,30 * * * * *", "2024-01-01T00:00:00Z", "2024-01-02T00:00:00Z"),
    ],
)
def test_forward_and_reverse_sequences_stay_aligned(expression: str, lower: str, upper: str):
    """forward and reverse sequences stay aligned"""
    c = cron.parse_unsafe(expression, UTC_ZONE)

    forward: list[datetime] = []
    current = utc(lower)
    while (current := cron.next(c, current)) < utc(upper):
        forward.append(current)

    reverse: list[datetime] = []
    current = utc(upper)
    while (current := cron.prev(c, current)) > utc(lower):
        reverse.append(current)

    assert forward == reverse[::-1]


def test_prev_prefers_the_latest_matching_day_within_the_previous_month():
    """prev prefers the latest matching day within the previous month"""
    expression = cron.parse_unsafe("0 0 8 5,20 * *", UTC_ZONE)
    assert prev(expression, utc("2024-06-03T00:00:00Z")) == utc("2024-05-20T08:00:00Z")


def test_prev_wraps_weekday_using_the_last_allowed_value():
    """prev wraps weekday using the last allowed value"""
    expression = cron.parse_unsafe("0 1 * * MON,FRI", UTC_ZONE)
    assert prev(expression, utc("2025-10-19T12:00:00Z")) == utc("2025-10-17T01:00:00Z")


def test_prev_wraps_a_later_weekday_into_the_previous_week():
    """prev wraps a later weekday into the previous week"""
    expression = cron.parse_unsafe("0 0 * * SAT", UTC_ZONE)
    assert prev(expression, utc("2025-10-23T12:00:00Z")) == utc("2025-10-18T00:00:00Z")


def test_prev_weekday_wrapping_returns_matching_instants_strictly_before_the_input():
    """prev weekday wrapping returns matching instants strictly before the input"""
    expression = cron.parse_unsafe("0 0 * * SAT", UTC_ZONE)
    for day in range(19, 25):
        start = datetime(2025, 10, day, 12, tzinfo=UTC)
        result = prev(expression, start)
        assert result < start
        assert cron.match(expression, result)


def test_prev_chooses_the_preferred_occurrence_in_dst_fall_back():
    """prev chooses the preferred occurrence in DST fall-back"""
    expression = cron.parse_unsafe("0 30 2 * * *", "Europe/Berlin")
    before = zoned("2024-10-27T03:30:00.000+01:00[Europe/Berlin]")
    result = prev(expression, before).astimezone(BERLIN)
    assert format_iso_zoned(result) == iso("2024-10-27T02:30:00.000+02:00[Europe/Berlin]")


def test_prev_respects_combined_day_of_month_and_weekday_constraints():
    """prev respects combined day-of-month and weekday constraints"""
    expression = cron.parse_unsafe("0 0 9 1,15 * MON", UTC_ZONE)
    assert prev(expression, utc("2024-04-02T12:00:00Z")) == utc("2024-04-01T09:00:00Z")


def test_prev_handles_step_expressions_across_day_boundary():
    """prev handles step expressions across day boundary"""
    expression = cron.parse_unsafe("0 */7 8-10 * * *", UTC_ZONE)
    assert prev(expression, utc("2024-01-01T08:01:00Z")) == utc("2024-01-01T08:00:00Z")


def test_prev_works_with_fixed_offset_time_zones():
    """prev works with fixed offset time zones"""
    expression = cron.parse_unsafe("0 0 10 * * *", timezone(timedelta(hours=2)))
    assert prev(expression, utc("2024-05-01T07:00:00Z")) == utc("2024-04-30T08:00:00Z")


def test_prev_wraps_across_year_boundary():
    """prev wraps across year boundary"""
    expression = cron.parse_unsafe("0 0 1 1 *", UTC_ZONE)
    assert prev(expression, utc("2024-01-01T00:00:00Z")) == utc("2023-01-01T00:00:00Z")


def test_prev_handles_day_31_skipping_months_without_it():
    """prev handles day 31 skipping months without it"""
    expression = cron.parse_unsafe("0 0 31 * *", UTC_ZONE)
    assert prev(expression, utc("2024-03-01T00:00:00Z")) == utc("2024-01-31T00:00:00Z")


def test_prev_skips_an_invalid_day_in_the_immediately_preceding_month():
    """prev skips an invalid day in the immediately preceding month"""
    expression = cron.parse_unsafe("0 0 31 * *", UTC_ZONE)
    assert prev(expression, utc("2024-03-15T00:00:00Z")) == utc("2024-01-31T00:00:00Z")


def test_prev_finds_the_previous_leap_day():
    """prev finds the previous leap day"""
    expression = cron.parse_unsafe("0 0 29 2 *", UTC_ZONE)
    assert prev(expression, utc("2024-01-01T00:00:00Z")) == utc("2020-02-29T00:00:00Z")


@pytest.mark.parametrize(
    ("expression", "start"),
    [("0 0 31 * *", "2024-03-15T00:00:00Z"), ("0 0 29 2 *", "2024-01-01T00:00:00Z")],
)
def test_prev_day_of_month_rollovers_preserve_match_and_ordering_invariants(
    expression: str, start: str
):
    """prev day-of-month rollovers preserve match and ordering invariants"""
    c = cron.parse_unsafe(expression, UTC_ZONE)
    result = prev(c, utc(start))
    assert cron.match(c, result)
    assert result < utc(start)


def test_prev_terminates_for_an_impossible_day_and_month_combination():
    """prev terminates for an impossible day and month combination"""
    expression = cron.parse_unsafe("0 0 30 2 *", UTC_ZONE)
    with pytest.raises(ValueError, match="Unable to find cron date"):
        prev(expression, utc("2024-03-01T00:00:00Z"))


def test_prev_clamps_to_the_last_valid_day_when_rolling_back_a_month_with_only_month_constraints():
    """prev clamps to the last valid day when rolling back a month with only month constraints"""
    expression = cron.parse_unsafe("0 0 0 * FEB *", UTC_ZONE)
    assert prev(expression, utc("2024-03-31T12:00:00Z")) == utc("2024-02-29T00:00:00Z")


def test_prev_with_multiple_months_specified():
    """prev with multiple months specified"""
    expression = cron.parse_unsafe("0 0 15 1,4,7,10 *", UTC_ZONE)
    assert prev(expression, utc("2024-05-01T00:00:00Z")) == utc("2024-04-15T00:00:00Z")


def test_sequence():
    """sequence"""
    times = cron.sequence(cron.parse_unsafe("23 0-20/2 * * 0"), local("2024-01-01 00:00:00"))
    assert next(times) == local("2024-01-07 00:23:00")
    assert next(times) == local("2024-01-07 02:23:00")
    assert next(times) == local("2024-01-07 04:23:00")
    assert next(times) == local("2024-01-07 06:23:00")
    assert next(times) == local("2024-01-07 08:23:00")


def test_equal():
    """equal"""
    plain_cron = cron.parse_unsafe("23 0-20/2 * * 0")
    utc_cron = cron.parse_unsafe("23 0-20/2 * * 0", "UTC")
    another_utc = cron.parse_unsafe("23 0-20/2 * * 0", "UTC")
    berlin = cron.parse_unsafe("23 0-20/2 * * 0", "Europe/Berlin")
    assert plain_cron == plain_cron  # noqa: PLR0124 - Effect checks reflexivity
    assert plain_cron == cron.parse_unsafe("23 0-20/2 * * 0")
    assert utc_cron == another_utc
    assert hash(utc_cron) == hash(another_utc)
    assert len({plain_cron, utc_cron, another_utc, berlin}) == 3
    assert plain_cron != utc_cron
    assert utc_cron != berlin
    assert plain_cron != cron.parse_unsafe("23 0-20/2 * * 1")
    assert plain_cron != cron.parse_unsafe("23 0-20/2 * * 0-6")
    assert plain_cron != cron.parse_unsafe("23 0-20/2 1 * 0")


def test_handles_leap_years():
    """handles leap years"""
    assert match("0 0 29 2 *", local("2024-02-29 00:00:00"))
    assert not match("0 0 29 2 *", local("2025-03-01 00:00:00"))
    assert not match("0 0 29 2 *", local("2026-03-01 00:00:00"))
    assert not match("0 0 29 2 *", local("2027-03-01 00:00:00"))
    assert match("0 0 29 2 *", local("2028-02-29 00:00:00"))

    assert next_("0 0 29 2 *", local("2024-01-01 00:00:00")) == local("2024-02-29 00:00:00")
    assert next_("0 0 29 2 *", local("2025-01-01 00:00:00")) == local("2028-02-29 00:00:00")


def iso_all(*texts: str) -> list[str]:
    return [iso(text) for text in texts]


def berlin_sequence(start: str) -> list[str]:
    times = cron.sequence(cron.parse_unsafe("30 * * * *", "Europe/Berlin"), zoned(start))
    return [format_iso_zoned(next(times).astimezone(BERLIN)) for _ in range(5)]


def test_handles_transition_into_daylight_savings_time():
    """handles transition into daylight savings time"""
    assert berlin_sequence("2024-03-31T00:00:00.000+01:00[Europe/Berlin]")[:4] == iso_all(
        "2024-03-31T00:30:00.000+01:00[Europe/Berlin]",
        "2024-03-31T01:30:00.000+01:00[Europe/Berlin]",
        "2024-03-31T03:30:00.000+02:00[Europe/Berlin]",
        "2024-03-31T04:30:00.000+02:00[Europe/Berlin]",
    )


def test_handles_transition_out_of_daylight_savings_time():
    """handles transition out of daylight savings time"""
    assert berlin_sequence("2024-10-27T00:00:00.000+02:00[Europe/Berlin]") == iso_all(
        "2024-10-27T00:30:00.000+02:00[Europe/Berlin]",
        "2024-10-27T01:30:00.000+02:00[Europe/Berlin]",
        "2024-10-27T02:30:00.000+02:00[Europe/Berlin]",
        "2024-10-27T03:30:00.000+01:00[Europe/Berlin]",
        "2024-10-27T04:30:00.000+01:00[Europe/Berlin]",
    )


def test_next_skips_the_repeated_hour_when_starting_in_the_second_dst_fold_hour():
    """next skips the repeated hour when starting in the second DST fold hour"""
    expression = cron.parse_unsafe("30 * * * *", "Europe/Berlin")
    start = datetime.fromisoformat("2024-10-27T02:15:00+01:00")
    assert next_(expression, start) == datetime.fromisoformat("2024-10-27T03:30:00+01:00")


def test_next_skips_the_repeated_interval_when_starting_in_a_three_hour_fold():
    """next skips the repeated interval when starting in a three-hour fold"""
    expression = cron.parse_unsafe("* * * * * *", "Antarctica/Casey")
    start = datetime.fromisoformat("2023-03-09T00:00:00+08:00")
    assert next_(expression, start) == datetime.fromisoformat("2023-03-09T03:00:00+08:00")


def test_handles_utc_timezone():
    """handles utc timezone"""
    times = cron.sequence(
        cron.parse_unsafe("30 * * * *", UTC_ZONE), zoned("2024-10-27T00:00:00.000+00:00[UTC]")
    )
    assert [format_iso_zoned(next(times).astimezone(UTC_ZONE)) for _ in range(4)] == iso_all(
        "2024-10-27T00:30:00.000+00:00[UTC]",
        "2024-10-27T01:30:00.000+00:00[UTC]",
        "2024-10-27T02:30:00.000+00:00[UTC]",
        "2024-10-27T03:30:00.000+00:00[UTC]",
    )


# --- onDstOverlap ---------------------------------------------------------------
# Europe/Berlin falls back on 2026-10-25: local 02:00-02:59 runs first at
# 00:00Z-00:59Z (+02:00) and again at 01:00Z-01:59Z (+01:00).

_EVERY5 = "*/5 * * * *"
_DAILY = "0 30 2 * * *"


def test_on_dst_overlap_defaults_to_earlier():
    """defaults to earlier"""

    def make(on_dst_overlap: cron.DstOverlapPolicy | None = None) -> Cron:
        fields = cron.make(minutes=[0], hours=[2], days=[], months=[], weekdays=[])
        if on_dst_overlap is None:
            return fields
        return cron.make(
            minutes=[0], hours=[2], days=[], months=[], weekdays=[], on_dst_overlap=on_dst_overlap
        )

    assert cron.parse_unsafe(_EVERY5, "Europe/Berlin").on_dst_overlap == "earlier"
    assert make() == make("earlier")
    assert make() != make("both")
    assert hash(make()) == hash(make("earlier"))


_NEXT_CASES: list[tuple[str, str, cron.DstOverlapPolicy, str, str]] = [
    (_EVERY5, "Europe/Berlin", "earlier", "2026-10-25T00:55:00Z", "2026-10-25T02:00:00Z"),
    (_EVERY5, "Europe/Berlin", "later", "2026-10-25T00:55:00Z", "2026-10-25T01:00:00Z"),
    (_EVERY5, "Europe/Berlin", "both", "2026-10-25T00:55:00Z", "2026-10-25T01:00:00Z"),
    # inside the first occurrence
    (_EVERY5, "Europe/Berlin", "earlier", "2026-10-25T00:07:00Z", "2026-10-25T00:10:00Z"),
    (_EVERY5, "Europe/Berlin", "later", "2026-10-25T00:07:00Z", "2026-10-25T01:00:00Z"),
    (_EVERY5, "Europe/Berlin", "both", "2026-10-25T00:07:00Z", "2026-10-25T00:10:00Z"),
    # inside the second occurrence
    (_EVERY5, "Europe/Berlin", "earlier", "2026-10-25T01:07:00Z", "2026-10-25T02:00:00Z"),
    (_EVERY5, "Europe/Berlin", "later", "2026-10-25T01:07:00Z", "2026-10-25T01:10:00Z"),
    (_EVERY5, "Europe/Berlin", "both", "2026-10-25T01:07:00Z", "2026-10-25T01:10:00Z"),
    # daily schedule inside the fold
    (_DAILY, "Europe/Berlin", "earlier", "2026-10-24T23:00:00Z", "2026-10-25T00:30:00Z"),
    (_DAILY, "Europe/Berlin", "later", "2026-10-24T23:00:00Z", "2026-10-25T01:30:00Z"),
    (_DAILY, "Europe/Berlin", "both", "2026-10-25T00:30:00Z", "2026-10-25T01:30:00Z"),
    (_DAILY, "Europe/Berlin", "both", "2026-10-25T01:30:00Z", "2026-10-26T01:30:00Z"),
    # three-hour fold: Casey repeats 00:00:00-02:59:59 rolling back from +11:00 to +08:00
    (
        "* * * * * *",
        "Antarctica/Casey",
        "both",
        "2023-03-09T00:00:00+08:00",
        "2023-03-09T00:00:01+08:00",
    ),
    # spring-forward gaps are unaffected
    (_DAILY, "Europe/Berlin", "earlier", "2026-03-28T23:00:00Z", "2026-03-29T01:30:00Z"),
    (_DAILY, "Europe/Berlin", "later", "2026-03-28T23:00:00Z", "2026-03-29T01:30:00Z"),
    (_DAILY, "Europe/Berlin", "both", "2026-03-28T23:00:00Z", "2026-03-29T01:30:00Z"),
    # UTC has no repeated times
    (_EVERY5, "UTC", "earlier", "2026-10-25T00:55:00Z", "2026-10-25T01:00:00Z"),
    (_EVERY5, "UTC", "later", "2026-10-25T00:55:00Z", "2026-10-25T01:00:00Z"),
    (_EVERY5, "UTC", "both", "2026-10-25T00:55:00Z", "2026-10-25T01:00:00Z"),
]


@pytest.mark.parametrize(("expression", "tz", "policy", "start", "expected"), _NEXT_CASES)
def test_on_dst_overlap_next(
    expression: str, tz: str, policy: cron.DstOverlapPolicy, start: str, expected: str
):
    """next"""
    parsed = cron.parse_unsafe(expression, tz, on_dst_overlap=policy)
    # In UTC: an aware datetime in a fold never equals one in another zone (PEP 495).
    assert cron.next(parsed, utc(start)).astimezone(UTC) == utc(expected)


def test_on_dst_overlap_next_raises_when_nothing_matches():
    with pytest.raises(ValueError, match="Unable to find cron date"):
        cron.next(cron.parse_unsafe("0 0 30 2 *", "Europe/Berlin", on_dst_overlap="both"))


_PREV_CASES: list[tuple[cron.DstOverlapPolicy, str, str]] = [
    ("earlier", "2026-10-25T02:00:00Z", "2026-10-25T00:55:00Z"),
    ("later", "2026-10-25T02:00:00Z", "2026-10-25T01:55:00Z"),
    ("both", "2026-10-25T02:00:00Z", "2026-10-25T01:55:00Z"),
    # inside the second occurrence
    ("earlier", "2026-10-25T01:07:00Z", "2026-10-25T00:55:00Z"),
    ("later", "2026-10-25T01:07:00Z", "2026-10-25T01:05:00Z"),
    ("both", "2026-10-25T01:07:00Z", "2026-10-25T01:05:00Z"),
    # start of the second occurrence
    ("earlier", "2026-10-25T01:00:00Z", "2026-10-25T00:55:00Z"),
    ("later", "2026-10-25T01:00:00Z", "2026-10-24T23:55:00Z"),
    ("both", "2026-10-25T01:00:00Z", "2026-10-25T00:55:00Z"),
    # inside the first occurrence
    ("earlier", "2026-10-25T00:07:00Z", "2026-10-25T00:05:00Z"),
    ("later", "2026-10-25T00:07:00Z", "2026-10-24T23:55:00Z"),
    ("both", "2026-10-25T00:07:00Z", "2026-10-25T00:05:00Z"),
]


@pytest.mark.parametrize(("policy", "start", "expected"), _PREV_CASES)
def test_on_dst_overlap_prev(policy: cron.DstOverlapPolicy, start: str, expected: str):
    """prev"""
    parsed = cron.parse_unsafe(_EVERY5, "Europe/Berlin", on_dst_overlap=policy)
    assert cron.prev(parsed, utc(start)).astimezone(UTC) == utc(expected)


@pytest.mark.parametrize("policy", ["earlier", "later", "both"])
@pytest.mark.parametrize(
    ("expression", "start", "expected"),
    [
        (_DAILY, "2026-03-29T01:40:00Z", "2026-03-29T01:30:00Z"),
        (_DAILY, "2026-03-29T01:20:00Z", "2026-03-28T01:30:00Z"),
        ("30 * * * *", "2026-03-29T01:20:00Z", "2026-03-29T00:30:00Z"),
    ],
)
def test_prev_across_a_spring_forward_gap(
    policy: cron.DstOverlapPolicy, expression: str, start: str, expected: str
):
    """prev across a spring-forward gap"""
    # Europe/Berlin skips local 02:00-02:59 on 2026-03-29; 02:30 resolves to 03:30 (01:30Z).
    parsed = cron.parse_unsafe(expression, "Europe/Berlin", on_dst_overlap=policy)
    assert cron.prev(parsed, utc(start)).astimezone(UTC) == utc(expected)


def test_sequence_with_both_visits_every_instant_of_the_fold_in_order():
    """sequence with both visits every instant of the fold in order"""
    parsed = cron.parse_unsafe(_EVERY5, "Europe/Berlin", on_dst_overlap="both")
    found = cron.sequence(parsed, utc("2026-10-25T00:55:00Z"))
    expected = [datetime(2026, 10, 25, 1, tzinfo=UTC) + timedelta(minutes=i * 5) for i in range(13)]
    assert [builtins_next(found).astimezone(UTC) for _ in range(13)] == expected
