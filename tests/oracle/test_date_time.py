"""Ports of the Clock- and zone-dependent cases of Effect's
``DateTime.test.ts``. Each test's docstring is the Effect test title.

A DateTime is an aware ``datetime`` (PARITY.md §4): Effect's ``Utc`` is a
datetime in ``UTC``, a ``Zoned`` one in a ``ZoneInfo`` or a fixed
``timezone``. ``toJSON`` / ``formatIso`` is ``iso`` below, and
``toDate(zoned).toISOString()`` (the wall-clock time written with a Z)
is ``wall_iso``. Effect keeps milliseconds and datetime keeps
microseconds, so ``endOf`` ends on ``.999999`` (``.999`` in ``iso``).

Omitted, with the reason:

- "preserves pre-epoch milliseconds when Intl omits fractionalSecond", "format",
  "formatUtc", "format zoned": Intl formatting (``strftime`` / Babel; Intl is skipped).
- "fromParts", "setParts", "setPartsUtc", "removeTime", "toEpochSeconds",
  "fromEpochSeconds", "parts equality", "toUtc / with a Utc", "accepts GMT as a named
  timezone", "formatIso", "formatIsoDate", "make", "makeUnsafe": the standard library
  (``datetime(...)``, ``replace``, ``combine``, ``timestamp``, ``fromtimestamp``,
  ``ZoneInfo("GMT")``, ``isoformat``, ``fromisoformat``).
- "toDate": JavaScript ``Date`` storage; datetime has no year 0 or BCE years.
- "makeZonedUnsafe no options": skipped in Effect.
"""

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta, timezone
from typing import Literal
from zoneinfo import ZoneInfo

import pytest

import pyfect as fx
from pyfect import date_time, testing
from pyfect.date_time import Disambiguation

AUCKLAND = ZoneInfo("Pacific/Auckland")
NEW_YORK = ZoneInfo("America/New_York")


def set_to_2024_nz() -> fx.Effect[None]:
    return testing.set_time(datetime(2023, 12, 31, 11, tzinfo=UTC).timestamp())


def iso(dt: datetime) -> str:
    """Effect's ``formatIso``: the instant in UTC, to the millisecond."""
    return dt.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def wall_iso(dt: datetime) -> str:
    """Effect's ``toDate(dt).toISOString()``: the wall-clock time with a Z."""
    return iso(dt.replace(tzinfo=UTC))


def utc(text: str) -> datetime:
    return datetime.fromisoformat(text)


def now_in_auckland() -> fx.Effect[datetime, fx.IllegalArgumentError]:
    return date_time.now_in_current_zone().pipe(
        date_time.with_current_zone_named("Pacific/Auckland")
    )


# --- mutate ----------------------------------------------------------------------------


@testing.effect
def test_mutate_should_mutate_the_date():
    """mutate / should mutate the date"""
    now = yield from date_time.now()
    tomorrow = now + timedelta(days=1)  # Effect's setUTCDate(getUTCDate() + 1)
    assert tomorrow - now == timedelta(days=1)


@testing.effect
def test_mutate_preserves_the_named_zone_when_mutating_across_dst():
    """mutate / preserves the named zone when mutating across DST"""
    yield from set_to_2024_nz()
    now = yield from now_in_auckland()
    future = now.replace(month=now.month + 6)  # aware replace moves the wall clock
    assert iso(future) == "2024-06-30T12:00:00.000Z"
    assert wall_iso(future) == "2024-07-01T00:00:00.000Z"
    plus_one = future + timedelta(days=1)  # aware arithmetic moves the wall clock
    assert iso(plus_one) == "2024-07-01T12:00:00.000Z"
    assert wall_iso(plus_one) == "2024-07-02T00:00:00.000Z"


# --- add -------------------------------------------------------------------------------


@testing.effect
def test_add_adds_calendar_days_to_a_utc_datetime():
    """add / adds calendar days to a UTC DateTime"""
    now = yield from date_time.now()
    tomorrow = date_time.add(now, days=1)
    assert tomorrow - now == timedelta(days=1)


def test_add_clamps_to_the_last_valid_day_when_changing_months():
    """add / clamps to the last valid day when changing months"""
    jan = datetime(2023, 1, 31, tzinfo=UTC)
    assert iso(date_time.add(jan, months=1)) == "2023-02-28T00:00:00.000Z"
    mar = datetime(2023, 3, 31, tzinfo=UTC)
    assert iso(date_time.subtract(mar, months=1)) == "2023-02-28T00:00:00.000Z"


@testing.effect
def test_add_preserves_the_named_zone_when_adding_calendar_units_across_dst():
    """add / preserves the named zone when adding calendar units across DST"""
    yield from set_to_2024_nz()
    now = yield from now_in_auckland()
    future = date_time.add(now, months=6)
    assert iso(future) == "2024-06-30T12:00:00.000Z"
    assert wall_iso(future) == "2024-07-01T00:00:00.000Z"
    plus_one = date_time.add(future, days=1)
    assert iso(plus_one) == "2024-07-01T12:00:00.000Z"
    assert wall_iso(plus_one) == "2024-07-02T00:00:00.000Z"
    minus_one = date_time.subtract(plus_one, days=1)
    assert iso(minus_one) == "2024-06-30T12:00:00.000Z"
    assert wall_iso(minus_one) == "2024-07-01T00:00:00.000Z"


@testing.effect
def test_add_leap_years():
    """add / leap years"""
    yield from set_to_2024_nz()
    now = datetime(2024, 2, 29, tzinfo=UTC)
    assert iso(now) == "2024-02-29T00:00:00.000Z"
    assert iso(date_time.add(now, years=1)) == "2025-02-28T00:00:00.000Z"


def test_add_clips_fractional_time_units_separately():
    """add / clips fractional time units separately"""
    # Effect clips each unit to whole milliseconds; datetime's unit is the microsecond.
    start = datetime.fromtimestamp(1, UTC)
    assert date_time.add(start, microseconds=0.5, milliseconds=0.0005) == start
    assert date_time.add(start, seconds=1.001) == start + timedelta(milliseconds=1001)


def test_add_adds_and_subtracts_elapsed_time_in_the_repeated_dst_hour():
    """add / adds and subtracts elapsed time in the repeated DST hour"""
    second_one_thirty = utc("2025-11-02T06:30:00.000Z").astimezone(NEW_YORK)
    later = date_time.add(second_one_thirty, minutes=1, seconds=1, milliseconds=1)
    assert iso(later) == "2025-11-02T06:31:01.001Z"
    assert iso(date_time.subtract(second_one_thirty, hours=1)) == "2025-11-02T05:30:00.000Z"


def test_add_adds_elapsed_hours_before_calendar_days_across_dst():
    """add / adds elapsed hours before calendar days across DST"""
    before_gap = utc("2025-03-08T17:00:00.000Z").astimezone(NEW_YORK)
    assert iso(date_time.add(before_gap, hours=24)) == "2025-03-09T17:00:00.000Z"
    assert iso(date_time.add(before_gap, days=1)) == "2025-03-09T16:00:00.000Z"
    assert iso(date_time.add(before_gap, days=1, hours=24)) == "2025-03-10T17:00:00.000Z"


# --- endOf -----------------------------------------------------------------------------


def test_end_of_month():
    """endOf / month"""
    end = date_time.end_of(utc("2024-03-15T12:00:00.000Z"), "month")
    assert iso(end) == "2024-03-31T23:59:59.999Z"
    assert end.microsecond == 999_000


def test_end_of_feb_leap_year():
    """endOf / feb leap year"""
    assert iso(date_time.end_of(utc("2024-02-15T12:00:00.000Z"), "month")) == (
        "2024-02-29T23:59:59.999Z"
    )


def test_end_of_week():
    """endOf / week"""
    end = date_time.end_of(utc("2024-03-15T12:00:00.000Z"), "week")
    assert iso(end) == "2024-03-16T23:59:59.999Z"
    assert end.isoweekday() == 6


def test_end_of_week_last_day():
    """endOf / week last day"""
    assert iso(date_time.end_of(utc("2024-03-16T12:00:00.000Z"), "week")) == (
        "2024-03-16T23:59:59.999Z"
    )


def test_end_of_week_with_options():
    """endOf / week with options"""
    end = date_time.end_of(utc("2024-03-15T12:00:00.000Z"), "week", week_starts_on=calendar.MONDAY)
    assert iso(end) == "2024-03-17T23:59:59.999Z"


@testing.effect
def test_end_of_returns_the_zoned_end_of_the_month():
    """endOf / returns the zoned end of the month"""
    yield from set_to_2024_nz()
    now = yield from now_in_auckland()
    future = date_time.end_of(now, "month")
    assert iso(future) == "2024-01-31T10:59:59.999Z"
    assert wall_iso(future) == "2024-01-31T23:59:59.999Z"


# --- startOf ---------------------------------------------------------------------------


def test_start_of_month():
    """startOf / month"""
    assert iso(date_time.start_of(utc("2024-03-15T12:00:00.000Z"), "month")) == (
        "2024-03-01T00:00:00.000Z"
    )


def test_start_of_month_duplicated():
    """startOf / month duplicated"""
    once = date_time.start_of(utc("2024-03-15T12:00:00.000Z"), "month")
    assert iso(date_time.start_of(once, "month")) == "2024-03-01T00:00:00.000Z"


def test_start_of_feb_leap_year():
    """startOf / feb leap year"""
    assert iso(date_time.start_of(utc("2024-02-15T12:00:00.000Z"), "month")) == (
        "2024-02-01T00:00:00.000Z"
    )


def test_start_of_week():
    """startOf / week"""
    start = date_time.start_of(utc("2024-03-15T12:00:00.000Z"), "week")
    assert iso(start) == "2024-03-10T00:00:00.000Z"
    assert start.isoweekday() % 7 == 0  # Sunday, JavaScript's weekday 0


def test_start_of_week_first_day():
    """startOf / week first day"""
    assert iso(date_time.start_of(utc("2024-03-10T12:00:00.000Z"), "week")) == (
        "2024-03-10T00:00:00.000Z"
    )


def test_start_of_week_with_options():
    """startOf / week with options"""
    start = date_time.start_of(
        utc("2024-03-15T12:00:00.000Z"), "week", week_starts_on=calendar.MONDAY
    )
    assert iso(start) == "2024-03-11T00:00:00.000Z"


# --- nearest ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("title", "start", "unit", "expected"),
    [
        ("month up", "2024-03-16T12:00:00.000Z", "month", "2024-04-01T00:00:00.000Z"),
        ("month down", "2024-03-16T11:00:00.000Z", "month", "2024-03-01T00:00:00.000Z"),
        ("second up", "2024-03-20T12:00:00.500Z", "second", "2024-03-20T12:00:01.000Z"),
        ("second down", "2024-03-20T12:00:00.400Z", "second", "2024-03-20T12:00:00.000Z"),
    ],
)
def test_nearest(title: str, start: str, unit: Literal["month", "second"], expected: str):
    """nearest / ${title} (month up, month down, second up, second down)"""
    assert iso(date_time.nearest(utc(start), unit)) == expected


# --- formatIsoOffset / layerCurrentZoneNamed ---------------------------------------------


@testing.effect
def test_format_iso_offset_correctly_adds_offset():
    """formatIsoOffset / correctly adds offset"""
    now = yield from now_in_auckland()
    assert now.isoformat(timespec="milliseconds") == "1970-01-01T12:00:00.000+12:00"


@testing.effect
def test_layer_current_zone_named_correctly_adds_offset():
    """layerCurrentZoneNamed / correctly adds offset"""
    now = yield from date_time.now_in_current_zone().pipe(
        fx.provide(date_time.layer_current_zone_named("Pacific/Auckland"))
    )
    assert now.isoformat(timespec="milliseconds") == "1970-01-01T12:00:00.000+12:00"


# --- makeZonedFromString / zoneFromString ------------------------------------------------


def test_make_zoned_from_string_parses_an_instant_with_an_offset_and_iana_zone():
    """makeZonedFromString / parses an instant with an offset and IANA zone"""
    dt = date_time.make_zoned_from_string("2024-07-21T20:12:34.112546348+12:00[Pacific/Auckland]")
    assert dt is not None
    assert dt.tzinfo == AUCKLAND
    assert iso(dt) == "2024-07-21T08:12:34.112Z"


@pytest.mark.parametrize(
    ("title", "text", "expected"),
    [
        (
            "parses an offset-only string as an Offset zone",
            "2024-07-21T20:12:34.112546348+12:00",
            "2024-07-21T08:12:34.112Z",
        ),
        (
            "parses a UTC offset-only string as an Offset zone",
            "2024-07-21T20:12:34.112546348+00:00",
            "2024-07-21T20:12:34.112Z",
        ),
        (
            "parses a compact offset without colon",
            "2024-07-21T20:12:34.112+0530",
            "2024-07-21T14:42:34.112Z",
        ),
    ],
)
def test_make_zoned_from_string_offsets(title: str, text: str, expected: str):
    """makeZonedFromString / ${title} (offset-only, UTC offset-only, compact offset)"""
    dt = date_time.make_zoned_from_string(text)
    assert dt is not None
    assert isinstance(dt.tzinfo, timezone)
    assert iso(dt) == expected


def test_make_zoned_from_string_roundtrips_a_bracketed_iana_zone_string():
    """makeZonedFromString / roundtrips a bracketed IANA zone string"""
    first = date_time.make_zoned_from_string(
        "2024-07-21T20:12:34.112546348+12:00[Pacific/Auckland]"
    )
    assert first is not None
    dt = date_time.make_zoned_from_string(date_time.format_iso_zoned(first))
    assert dt is not None
    assert isinstance(dt.tzinfo, ZoneInfo)
    assert dt.tzinfo.key == "Pacific/Auckland"
    assert iso(dt) == "2024-07-21T08:12:34.112Z"


def test_zone_from_string_parses_gmt_as_a_named_zone():
    """zoneFromString / parses GMT as a Named zone"""
    assert isinstance(date_time.zone_from_string("GMT"), ZoneInfo)
    assert date_time.zone_from_string("GMT+05:30") == timezone(timedelta(hours=5.5))


def test_zone_from_string_parses_a_compact_offset_without_colon():
    """zoneFromString / parses a compact offset without colon"""
    assert date_time.zone_from_string("+0530") == timezone(timedelta(hours=5.5))
    assert date_time.zone_from_string("-0530") == timezone(timedelta(hours=-5.5))


# --- toUtc / nowAsDate -----------------------------------------------------------------


def test_to_utc_with_a_zoned():
    """toUtc / with a Zoned"""
    dt = date_time.make_zoned(datetime(2024, 1, 1, 1), AUCKLAND)
    assert iso(dt) == "2023-12-31T12:00:00.000Z"


@testing.effect
def test_now_as_date_should_return_the_current_date():
    """nowAsDate / should return the current Date"""
    yield from set_to_2024_nz()
    now = yield from date_time.now()
    assert now == datetime(2023, 12, 31, 11, tzinfo=UTC)


# --- Disambiguation --------------------------------------------------------------------


@dataclass(frozen=True)
class Case:
    zone: str
    wall: datetime
    description: str
    compatible: str
    earlier: str
    later: str
    reject: str | None
    """None where Effect rejects the time."""


DISAMBIGUATION = [
    Case(
        "America/New_York",
        datetime(2024, 3, 10, 2),
        "America/New_York 02:00 gap time during leap year (2024)",
        "2024-03-10T07:00:00.000Z",
        "2024-03-10T06:00:00.000Z",
        "2024-03-10T07:00:00.000Z",
        None,
    ),
    Case(
        "America/New_York",
        datetime(2024, 11, 3, 1, 30),
        "America/New_York 01:30 ambiguous time during leap year (2024)",
        "2024-11-03T05:30:00.000Z",
        "2024-11-03T05:30:00.000Z",
        "2024-11-03T06:30:00.000Z",
        None,
    ),
    Case(
        "America/New_York",
        datetime(2025, 3, 9, 1),
        "America/New_York 01:00 before DST transition",
        "2025-03-09T06:00:00.000Z",
        "2025-03-09T06:00:00.000Z",
        "2025-03-09T06:00:00.000Z",
        "2025-03-09T06:00:00.000Z",
    ),
    Case(
        "America/New_York",
        datetime(2025, 3, 9, 1, 59, 59),
        "America/New_York 01:59:59 last second before DST gap",
        "2025-03-09T06:59:59.000Z",
        "2025-03-09T06:59:59.000Z",
        "2025-03-09T06:59:59.000Z",
        "2025-03-09T06:59:59.000Z",
    ),
    Case(
        "America/New_York",
        datetime(2025, 3, 9, 2),
        "America/New_York 02:00 gap time (DST spring forward)",
        "2025-03-09T07:00:00.000Z",
        "2025-03-09T06:00:00.000Z",
        "2025-03-09T07:00:00.000Z",
        None,
    ),
    Case(
        "America/New_York",
        datetime(2025, 3, 9, 2, 15),
        "America/New_York 02:15 gap time (DST spring forward)",
        "2025-03-09T07:15:00.000Z",
        "2025-03-09T06:15:00.000Z",
        "2025-03-09T07:15:00.000Z",
        None,
    ),
    Case(
        "America/New_York",
        datetime(2025, 3, 9, 2, 30),
        "America/New_York 02:30 gap time (DST spring forward)",
        "2025-03-09T07:30:00.000Z",
        "2025-03-09T06:30:00.000Z",
        "2025-03-09T07:30:00.000Z",
        None,
    ),
    Case(
        "America/New_York",
        datetime(2025, 3, 9, 2, 45),
        "America/New_York 02:45 gap time (DST spring forward)",
        "2025-03-09T07:45:00.000Z",
        "2025-03-09T06:45:00.000Z",
        "2025-03-09T07:45:00.000Z",
        None,
    ),
    Case(
        "America/New_York",
        datetime(2025, 3, 9, 3),
        "America/New_York 03:00 first valid time after DST gap",
        "2025-03-09T07:00:00.000Z",
        "2025-03-09T07:00:00.000Z",
        "2025-03-09T07:00:00.000Z",
        "2025-03-09T07:00:00.000Z",
    ),
    Case(
        "America/New_York",
        datetime(2025, 11, 2, 1),
        "America/New_York 01:00:00 exact start of ambiguous period",
        "2025-11-02T05:00:00.000Z",
        "2025-11-02T05:00:00.000Z",
        "2025-11-02T06:00:00.000Z",
        None,
    ),
    Case(
        "America/New_York",
        datetime(2025, 11, 2, 1, 30),
        "America/New_York 01:30 ambiguous time (DST fall back)",
        "2025-11-02T05:30:00.000Z",
        "2025-11-02T05:30:00.000Z",
        "2025-11-02T06:30:00.000Z",
        None,
    ),
    Case(
        "America/New_York",
        datetime(2025, 11, 2, 1, 59, 59),
        "America/New_York 01:59:59 last second of ambiguous period",
        "2025-11-02T05:59:59.000Z",
        "2025-11-02T05:59:59.000Z",
        "2025-11-02T06:59:59.000Z",
        None,
    ),
    Case(
        "Asia/Kathmandu",
        datetime(2025, 6, 15, 12),
        "Asia/Kathmandu 12:00 unusual offset (UTC+05:45)",
        "2025-06-15T06:15:00.000Z",
        "2025-06-15T06:15:00.000Z",
        "2025-06-15T06:15:00.000Z",
        "2025-06-15T06:15:00.000Z",
    ),
    Case(
        "Australia/Melbourne",
        datetime(2025, 10, 5, 2),
        "Australia/Melbourne 02:00 gap time (DST starts, spring forward)",
        "2025-10-04T16:00:00.000Z",
        "2025-10-04T15:00:00.000Z",
        "2025-10-04T16:00:00.000Z",
        None,
    ),
    Case(
        "Australia/Sydney",
        datetime(2025, 4, 6, 1),
        "Australia/Sydney 01:00 normal timezone conversion",
        "2025-04-05T14:00:00.000Z",
        "2025-04-05T14:00:00.000Z",
        "2025-04-05T14:00:00.000Z",
        "2025-04-05T14:00:00.000Z",
    ),
    Case(
        "Australia/Sydney",
        datetime(2025, 4, 6, 2, 30),
        "Australia/Sydney 02:30 ambiguous time (DST ends, fall back)",
        "2025-04-05T15:30:00.000Z",
        "2025-04-05T15:30:00.000Z",
        "2025-04-05T16:30:00.000Z",
        None,
    ),
    Case(
        "Australia/Sydney",
        datetime(2025, 10, 5, 2, 30),
        "Australia/Sydney 02:30 gap time (DST starts, spring forward)",
        "2025-10-04T16:30:00.000Z",
        "2025-10-04T15:30:00.000Z",
        "2025-10-04T16:30:00.000Z",
        None,
    ),
    Case(
        "Europe/Athens",
        datetime(2024, 10, 27, 3),
        "Europe/Athens 03:00 ambiguous time during leap year (2024)",
        "2024-10-27T00:00:00.000Z",
        "2024-10-27T00:00:00.000Z",
        "2024-10-27T01:00:00.000Z",
        None,
    ),
    Case(
        "Europe/Athens",
        datetime(2025, 3, 27, 1),
        "Europe/Athens 01:00 normal time before DST",
        "2025-03-26T23:00:00.000Z",
        "2025-03-26T23:00:00.000Z",
        "2025-03-26T23:00:00.000Z",
        "2025-03-26T23:00:00.000Z",
    ),
    Case(
        "Europe/Athens",
        datetime(2025, 3, 30, 1),
        "Europe/Athens 01:00 before DST transition (UTC+2)",
        "2025-03-29T23:00:00.000Z",
        "2025-03-29T23:00:00.000Z",
        "2025-03-29T23:00:00.000Z",
        "2025-03-29T23:00:00.000Z",
    ),
    Case(
        "Europe/Athens",
        datetime(2025, 3, 30, 2, 30),
        "Europe/Athens 02:30 normal time before DST transition",
        "2025-03-30T00:30:00.000Z",
        "2025-03-30T00:30:00.000Z",
        "2025-03-30T00:30:00.000Z",
        "2025-03-30T00:30:00.000Z",
    ),
    Case(
        "Europe/Athens",
        datetime(2025, 3, 30, 3),
        "Europe/Athens 03:00 gap time (DST spring forward)",
        "2025-03-30T01:00:00.000Z",
        "2025-03-30T00:00:00.000Z",
        "2025-03-30T01:00:00.000Z",
        None,
    ),
    Case(
        "Europe/Athens",
        datetime(2025, 3, 30, 4),
        "Europe/Athens 04:00 normal time after DST transition",
        "2025-03-30T01:00:00.000Z",
        "2025-03-30T01:00:00.000Z",
        "2025-03-30T01:00:00.000Z",
        "2025-03-30T01:00:00.000Z",
    ),
    Case(
        "Europe/Athens",
        datetime(2025, 10, 26, 3),
        "Europe/Athens 03:00 ambiguous time (DST fall back)",
        "2025-10-26T00:00:00.000Z",
        "2025-10-26T00:00:00.000Z",
        "2025-10-26T01:00:00.000Z",
        None,
    ),
    Case(
        "Europe/Berlin",
        datetime(2025, 10, 26, 2, 30),
        "Europe/Berlin 02:30 ambiguous time (DST fall back)",
        "2025-10-26T00:30:00.000Z",
        "2025-10-26T00:30:00.000Z",
        "2025-10-26T01:30:00.000Z",
        None,
    ),
    Case(
        "Europe/London",
        datetime(2024, 3, 31, 1),
        "Europe/London 01:00 gap time during leap year (2024)",
        "2024-03-31T01:00:00.000Z",
        "2024-03-31T00:00:00.000Z",
        "2024-03-31T01:00:00.000Z",
        None,
    ),
    Case(
        "Europe/London",
        datetime(2025, 3, 29, 1),
        "Europe/London 01:00 normal time day before DST",
        "2025-03-29T01:00:00.000Z",
        "2025-03-29T01:00:00.000Z",
        "2025-03-29T01:00:00.000Z",
        "2025-03-29T01:00:00.000Z",
    ),
    Case(
        "Europe/London",
        datetime(2025, 3, 30, 1),
        "Europe/London 01:00 gap time (DST spring forward)",
        "2025-03-30T01:00:00.000Z",
        "2025-03-30T00:00:00.000Z",
        "2025-03-30T01:00:00.000Z",
        None,
    ),
    Case(
        "Europe/London",
        datetime(2025, 10, 26, 1, 30),
        "Europe/London 01:30 ambiguous time (DST fall back)",
        "2025-10-26T00:30:00.000Z",
        "2025-10-26T00:30:00.000Z",
        "2025-10-26T01:30:00.000Z",
        None,
    ),
    Case(
        "Pacific/Auckland",
        datetime(2025, 1, 15, 12),
        "Pacific/Auckland 12:00 during DST period (NZDT, UTC+13)",
        "2025-01-14T23:00:00.000Z",
        "2025-01-14T23:00:00.000Z",
        "2025-01-14T23:00:00.000Z",
        "2025-01-14T23:00:00.000Z",
    ),
    Case(
        "Pacific/Auckland",
        datetime(2025, 4, 6, 1, 59),
        "Pacific/Auckland 01:59 last minute before DST ends",
        "2025-04-05T12:59:00.000Z",
        "2025-04-05T12:59:00.000Z",
        "2025-04-05T12:59:00.000Z",
        "2025-04-05T12:59:00.000Z",
    ),
    Case(
        "Pacific/Auckland",
        datetime(2025, 4, 6, 2, 30),
        "Pacific/Auckland 02:30 ambiguous time (DST ends, fall back)",
        "2025-04-05T13:30:00.000Z",
        "2025-04-05T13:30:00.000Z",
        "2025-04-05T14:30:00.000Z",
        None,
    ),
    Case(
        "Pacific/Auckland",
        datetime(2025, 4, 6, 3),
        "Pacific/Auckland 03:00 normal time after DST ends",
        "2025-04-05T15:00:00.000Z",
        "2025-04-05T15:00:00.000Z",
        "2025-04-05T15:00:00.000Z",
        "2025-04-05T15:00:00.000Z",
    ),
    Case(
        "Pacific/Auckland",
        datetime(2025, 7, 15, 12),
        "Pacific/Auckland 12:00 during standard time (NZST, UTC+12)",
        "2025-07-15T00:00:00.000Z",
        "2025-07-15T00:00:00.000Z",
        "2025-07-15T00:00:00.000Z",
        "2025-07-15T00:00:00.000Z",
    ),
    Case(
        "Pacific/Auckland",
        datetime(2025, 9, 28, 1, 59, 59),
        "Pacific/Auckland 01:59:59 last second before DST starts",
        "2025-09-27T13:59:59.000Z",
        "2025-09-27T13:59:59.000Z",
        "2025-09-27T13:59:59.000Z",
        "2025-09-27T13:59:59.000Z",
    ),
    Case(
        "Pacific/Auckland",
        datetime(2025, 9, 28, 2, 30),
        "Pacific/Auckland 02:30 gap time (DST starts, spring forward)",
        "2025-09-27T14:30:00.000Z",
        "2025-09-27T13:30:00.000Z",
        "2025-09-27T14:30:00.000Z",
        None,
    ),
    Case(
        "Pacific/Auckland",
        datetime(2025, 9, 28, 3),
        "Pacific/Auckland 03:00 first valid time after DST gap",
        "2025-09-27T14:00:00.000Z",
        "2025-09-27T14:00:00.000Z",
        "2025-09-27T14:00:00.000Z",
        "2025-09-27T14:00:00.000Z",
    ),
    Case(
        "Pacific/Kiritimati",
        datetime(2025, 6, 15, 12),
        "Pacific/Kiritimati 12:00 extreme positive offset (UTC+14)",
        "2025-06-14T22:00:00.000Z",
        "2025-06-14T22:00:00.000Z",
        "2025-06-14T22:00:00.000Z",
        "2025-06-14T22:00:00.000Z",
    ),
    Case(
        "Pacific/Marquesas",
        datetime(2025, 6, 15, 12),
        "Pacific/Marquesas 12:00 unusual negative offset (UTC-09:30)",
        "2025-06-15T21:30:00.000Z",
        "2025-06-15T21:30:00.000Z",
        "2025-06-15T21:30:00.000Z",
        "2025-06-15T21:30:00.000Z",
    ),
]


@pytest.mark.parametrize("case", DISAMBIGUATION, ids=[case.description for case in DISAMBIGUATION])
def test_disambiguation(case: Case):
    """Disambiguation / should handle $description"""
    naive, tz = case.wall, ZoneInfo(case.zone)
    strategies: dict[Disambiguation, str] = {
        "compatible": case.compatible,
        "earlier": case.earlier,
        "later": case.later,
    }
    for strategy, expected in strategies.items():
        resolved = date_time.make_zoned(naive, tz, disambiguation=strategy)
        assert resolved is not None
        assert iso(resolved) == expected, strategy
    assert iso(date_time.make_zoned(naive, tz)) == case.compatible
    rejected = date_time.make_zoned(naive, tz, disambiguation="reject")
    assert (None if rejected is None else iso(rejected)) == case.reject


# --- zone names and RFC 9557 strings, checked under Node ----------------------------


@pytest.mark.parametrize(
    ("written", "canonical"),
    [("europe/london", "Europe/London"), ("utc", "UTC"), ("AMERICA/NEW_YORK", "America/New_York")],
)
def test_zone_named_gives_the_canonical_name(written: str, canonical: str):
    """Not an Effect title: ``zoneMakeNamed`` takes any casing and keeps
    ``Intl``'s canonical name (link resolution, ``Asia/Kolkata`` to
    ``Asia/Calcutta``, follows ICU's data and is not copied)."""
    zone = date_time.zone_named(written)
    assert zone is not None
    assert date_time.zone_to_string(zone) == canonical


def test_make_zoned_from_string_canonicalizes_the_zone_name():
    """Not an Effect title: ``[europe/london]`` reads as ``Europe/London``."""
    parsed = date_time.make_zoned_from_string("2024-07-01T00:00:00Z[europe/london]")
    assert parsed is not None
    assert date_time.format_iso_zoned(parsed) == "2024-07-01T01:00:00.000+01:00[Europe/London]"


@pytest.mark.parametrize(
    "text",
    [
        "2024-01-01T00:00:00,5Z[UTC]",
        "2024-W01-1T00:00:00Z[UTC]",
        "2024-001T00:00:00Z[UTC]",
        "2024-01-01T00:00:00+05:30:15[UTC]",
        "2024-01-01T00Z[UTC]",
        "20240101T000000Z[UTC]",
        "2024-01-01T00:00:00+24:00",
    ],
)
def test_make_zoned_from_string_rejects_what_javascript_date_rejects(text: str):
    """Not an Effect title: the ISO part is read by ``new Date``."""
    assert date_time.make_zoned_from_string(text) is None


@pytest.mark.parametrize(
    ("text", "iso"),
    [
        ("2024-01-01T00:00:00z[UTC]", "2024-01-01T00:00:00.000Z"),
        ("2024-01-01t00:00:00Z[UTC]", "2024-01-01T00:00:00.000Z"),
        ("+002024-01-01T00:00:00Z[UTC]", "2024-01-01T00:00:00.000Z"),
        ("2024-01-01 00:00:00Z[UTC]", "2024-01-01T00:00:00.000Z"),
        ("2024-01-01T00:00Z[UTC]", "2024-01-01T00:00:00.000Z"),
        ("2024-02-30T00:00:00Z[UTC]", "2024-03-01T00:00:00.000Z"),
        ("2024-01-01T24:00:00Z[UTC]", "2024-01-02T00:00:00.000Z"),
        ("2024-01-01T00:00:00[Europe/London]", "2024-01-01T00:00:00.000Z"),
        ("2024-01-01T00:00:00-0130", "2024-01-01T01:30:00.000Z"),
    ],
)
def test_make_zoned_from_string_reads_what_javascript_date_reads(text: str, iso: str):
    """Not an Effect title: the ISO part is read by ``new Date`` (a ``Z``
    added when it names no zone)."""
    parsed = date_time.make_zoned_from_string(text)
    assert parsed is not None
    assert date_time.format_iso(parsed) == iso
