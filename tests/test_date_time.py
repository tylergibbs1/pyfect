"""``date_time`` beyond Effect's ``DateTime.test.ts``: the effectful
helpers (``is_future`` / ``is_past``, the ``CurrentTimeZone`` providers
and layers), boundary validation, and zone parsing."""

from datetime import UTC, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pytest

import pyfect as fx
from pyfect import date_time, testing

NEW_YORK = ZoneInfo("America/New_York")


@testing.effect
def test_is_future_and_is_past_compare_with_the_clock():
    yield from testing.set_time(100)
    at = datetime.fromtimestamp(100, UTC)
    assert (yield from date_time.is_future(at + timedelta(microseconds=1))) is True
    assert (yield from date_time.is_past(at + timedelta(microseconds=1))) is False
    assert (yield from date_time.is_past(at - timedelta(microseconds=1))) is True
    assert (yield from date_time.is_future(at)) is False
    assert (yield from date_time.is_past(at)) is False
    yield from testing.adjust("1 second")
    assert (yield from date_time.is_past(at.astimezone(NEW_YORK))) is True


@testing.effect
def test_now_floors_to_a_millisecond():
    yield from testing.set_time(1.001_9)
    assert (yield from date_time.now()) == datetime(1970, 1, 1, 0, 0, 1, 1000, tzinfo=UTC)


@testing.effect
def test_with_current_zone_and_offset_set_the_zone():
    now_ny = yield from date_time.now_in_current_zone().pipe(date_time.with_current_zone(NEW_YORK))
    assert now_ny.tzinfo is NEW_YORK
    assert now_ny.isoformat() == "1969-12-31T19:00:00-05:00"
    plus_two = yield from date_time.now_in_current_zone().pipe(
        date_time.with_current_zone_offset(timedelta(hours=2))
    )
    assert plus_two.utcoffset() == timedelta(hours=2)
    minus_half = yield from date_time.set_zone_current(datetime(2024, 1, 1, tzinfo=UTC)).pipe(
        date_time.with_current_zone_offset("-30 minutes")
    )
    assert minus_half.isoformat() == "2023-12-31T23:30:00-00:30"


@testing.effect
def test_with_current_zone_named_fails_for_an_unknown_zone():
    result = (
        yield from date_time.now_in_current_zone()
        .pipe(date_time.with_current_zone_named("Not/AZone"))
        .flip()
    )
    assert result == fx.IllegalArgumentError("Invalid time zone: Not/AZone")


@testing.effect
def test_layers_provide_the_current_zone():
    offset = yield from date_time.now_in_current_zone().pipe(
        fx.provide(date_time.layer_current_zone_offset("1 hour"))
    )
    assert offset.isoformat() == "1970-01-01T01:00:00+01:00"
    named = yield from date_time.now_in_current_zone().pipe(
        fx.provide(date_time.layer_current_zone(NEW_YORK))
    )
    assert named.tzinfo is NEW_YORK
    failed = (
        yield from date_time.now_in_current_zone()
        .pipe(fx.provide(date_time.layer_current_zone_named("Nope")))
        .flip()
    )
    assert isinstance(failed, fx.IllegalArgumentError)


@testing.effect
def test_local_zone_follows_tz(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("TZ", "Asia/Kathmandu")
    assert date_time.zone_local() == ZoneInfo("Asia/Kathmandu")
    local = yield from date_time.now_in_current_zone().pipe(date_time.with_current_zone_local())
    assert local.tzinfo == ZoneInfo("Asia/Kathmandu")
    from_layer = yield from date_time.now_in_current_zone().pipe(
        fx.provide(date_time.layer_current_zone_local())
    )
    assert from_layer.tzinfo == ZoneInfo("Asia/Kathmandu")


def test_local_zone_without_tz_is_usable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.delenv("TZ", raising=False)
    zone = date_time.zone_local()
    assert datetime(2024, 1, 1, tzinfo=zone).utcoffset() is not None


def test_naive_datetimes_are_rejected_at_the_boundary():
    naive = datetime(2024, 1, 1)
    with pytest.raises(ValueError, match="aware"):
        date_time.add(naive, days=1)
    with pytest.raises(ValueError, match="aware"):
        date_time.start_of(naive, "day")
    with pytest.raises(ValueError, match="aware"):
        date_time.is_future(naive)
    with pytest.raises(ValueError, match="naive"):
        date_time.make_zoned(datetime(2024, 1, 1, tzinfo=UTC), NEW_YORK)


def test_an_offset_outside_a_day_is_rejected():
    assert date_time.zone_offset(timedelta(hours=24)) is None
    assert date_time.zone_from_string("+24:00") is None
    with pytest.raises(ValueError, match="within a day"):
        date_time.with_current_zone_offset(timedelta(hours=-25))


def test_zone_strings_that_do_not_parse_give_none():
    assert date_time.zone_from_string("+5") is None
    assert date_time.zone_from_string("Mars/Olympus") is None
    assert date_time.zone_from_string("../etc/passwd") is None
    assert date_time.make_zoned_from_string("2024-07-21T20:12:34") is None
    assert date_time.make_zoned_from_string("2024-07-21T20:12:34+12:00[Mars/Olympus]") is None
    assert date_time.make_zoned_from_string("not a date+12:00") is None


def test_format_iso_zoned_names_only_named_zones():
    instant = datetime(2024, 7, 21, 8, 12, 34, tzinfo=UTC)
    assert date_time.format_iso_zoned(instant.astimezone(NEW_YORK)) == (
        "2024-07-21T04:12:34.000-04:00[America/New_York]"
    )
    fixed = instant.astimezone(timezone(timedelta(hours=5, minutes=30)))
    assert date_time.format_iso_zoned(fixed) == "2024-07-21T13:42:34.000+05:30"
    bracketed_utc = date_time.make_zoned_from_string("2024-07-21T08:12:34[UTC]")
    assert bracketed_utc == instant


def test_calendar_units_keep_the_wall_clock_across_dst():
    saturday = datetime(2025, 3, 8, 12, tzinfo=NEW_YORK)
    assert date_time.add(saturday, weeks=1).isoformat() == "2025-03-15T12:00:00-04:00"
    assert date_time.subtract(saturday, years=1, months=1).isoformat() == (
        "2024-02-08T12:00:00-05:00"
    )


def test_start_of_and_nearest_resolve_in_the_zone():
    # Sunday 2025-03-09 is the spring-forward day: its midnight is EST, its noon EDT.
    noon = datetime(2025, 3, 9, 12, tzinfo=NEW_YORK)
    assert date_time.start_of(noon, "day").isoformat() == "2025-03-09T00:00:00-05:00"
    assert date_time.end_of(noon, "day").isoformat() == "2025-03-09T23:59:59.999000-04:00"
    assert date_time.nearest(noon, "day").isoformat() == "2025-03-10T00:00:00-04:00"
    assert date_time.start_of(noon, "year").isoformat() == "2025-01-01T00:00:00-05:00"
    assert date_time.end_of(noon, "hour").isoformat() == "2025-03-09T12:59:59.999000-04:00"


def test_fractional_time_units_truncate_the_instant_like_effect():
    # Effect adds each time unit to the epoch value and truncates the sum toward zero
    # (JavaScript's TimeClip). Checked under Node at Effect's millisecond resolution:
    # 1000 - 0.5ms is 999, -1000 + 0.5ms is -999, -1000 - 0.5ms is -1000.
    one = datetime.fromtimestamp(1, UTC)
    minus_one = datetime.fromtimestamp(-1, UTC)
    milli = timedelta(milliseconds=1)
    assert date_time.subtract(one, milliseconds=0.5) == one - milli
    assert date_time.add(one, milliseconds=-0.5) == one - milli
    assert date_time.add(minus_one, milliseconds=0.5) == minus_one + milli
    assert date_time.add(minus_one, milliseconds=-0.5) == minus_one
    assert date_time.add(one, milliseconds=0.5) == one


def test_millisecond_is_a_unit():
    dt = datetime(2024, 3, 20, 12, 0, 0, 123_456, tzinfo=UTC)
    assert date_time.start_of(dt, "millisecond") == dt.replace(microsecond=123_000)
    assert date_time.end_of(dt, "millisecond") == dt.replace(microsecond=123_000)
    assert date_time.nearest(dt, "millisecond") == dt.replace(microsecond=123_000)
    assert date_time.nearest(dt.replace(microsecond=123_500), "millisecond") == (
        dt.replace(microsecond=124_000)
    )


@pytest.mark.parametrize(
    ("unit", "start", "end", "nearest"),
    [
        ("minute", "12:34:00.000", "12:34:59.999", "12:35:00.000"),
        ("hour", "12:00:00.000", "12:59:59.999", "13:00:00.000"),
    ],
)
def test_start_end_and_nearest_of_time_units(
    unit: date_time.Unit, start: str, end: str, nearest: str
):
    # Expected values printed by Effect's DateTime under Node.
    at = datetime.fromisoformat("2024-03-14T12:34:56.789+00:00").astimezone(
        ZoneInfo("Pacific/Auckland")
    )

    def utc_time(dt: datetime) -> str:
        return dt.astimezone(UTC).strftime("%H:%M:%S.%f")[:-3]

    assert utc_time(date_time.start_of(at, unit)) == start
    assert utc_time(date_time.end_of(at, unit)) == end
    assert utc_time(date_time.nearest(at, unit)) == nearest


@pytest.mark.parametrize(
    ("unit", "start", "end", "nearest"),
    [
        ("day", "2024-03-14T11:00", "2024-03-15T10:59", "2024-03-14T11:00"),
        ("week", "2024-03-09T11:00", "2024-03-16T10:59", "2024-03-16T11:00"),
        ("month", "2024-02-29T11:00", "2024-03-31T10:59", "2024-02-29T11:00"),
        ("year", "2023-12-31T11:00", "2024-12-31T10:59", "2023-12-31T11:00"),
    ],
)
def test_start_end_and_nearest_of_calendar_units_in_a_zone(
    unit: date_time.Unit, start: str, end: str, nearest: str
):
    # Expected values printed by Effect's DateTime under Node.
    at = datetime.fromisoformat("2024-03-14T12:34:56.789+00:00").astimezone(
        ZoneInfo("Pacific/Auckland")
    )

    def utc_minute(dt: datetime) -> str:
        return dt.astimezone(UTC).strftime("%Y-%m-%dT%H:%M")

    assert utc_minute(date_time.start_of(at, unit)) == start
    assert utc_minute(date_time.end_of(at, unit)) == end
    assert date_time.end_of(at, unit).microsecond == 999_000
    assert utc_minute(date_time.nearest(at, unit)) == nearest
