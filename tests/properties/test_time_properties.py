"""Durations, date-times and cron schedules: round trips, laws and monotonicity."""

from __future__ import annotations

import itertools
import math
from collections.abc import Generator
from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

from hypothesis import example, given
from hypothesis import strategies as st

import pyfect as fx
from pyfect import cron, date_time, duration, schedule, testing
from pyfect import schema as S
from pyfect.duration import Duration

# --- durations -------------------------------------------------------------------------------

_SAFE = 2**53 - 1
_nanos = st.integers(-(10**24), 10**24).map(duration.nanos)
_whole_millis = st.integers(-_SAFE, _SAFE).map(duration.millis)
_fractional_millis = st.floats(-1e15, 1e15, allow_nan=False).map(duration.millis)
_finite: st.SearchStrategy[Duration] = st.one_of(_nanos, _whole_millis, _fractional_millis)
_durations = st.one_of(_finite, st.sampled_from([duration.infinity, duration.negative_infinity]))
_exact = st.one_of(_nanos, st.integers(-(2**40), 2**40).map(duration.millis))
"""Durations whose sums are exact: nanoseconds, or millis small enough that float sums are."""


@given(_durations)
def test_a_durations_text_parses_back_to_it(d: Duration):
    assert duration.from_input_unsafe(str(d)) == d


@given(_finite)
def test_an_iso_duration_parses_back_to_it(d: Duration):
    iso = d.format_iso()
    assert iso is not None
    assert duration.from_iso(iso) == d


@given(_finite)
def test_format_writes_a_negative_as_the_negation_of_its_absolute_value(d: Duration):
    if d.is_negative():
        assert d.format() == "-" + d.abs().format()
    else:
        assert not d.format().startswith("-")


@given(st.sampled_from([math.nan, -0.0, 0.0]))
def test_nan_and_negative_zero_are_zero(x: float):
    for d in (duration.millis(x), duration.seconds(x), duration.from_input_unsafe(x)):
        assert d == duration.zero
        assert d.is_zero()
        assert not d.is_negative()
        assert d.to_millis() == 0
        assert math.copysign(1, d.to_millis()) == 1


@given(_exact, _exact, _exact)
def test_addition_is_associative_and_commutative(a: Duration, b: Duration, c: Duration):
    assert (a + b) + c == a + (b + c)
    assert a + b == b + a


@given(_durations)
def test_zero_is_the_identity(d: Duration):
    assert d + duration.zero == d
    assert duration.zero + d == d
    assert d * 1 == d


@given(_exact)
def test_subtracting_a_duration_from_itself_is_zero(d: Duration):
    assert d - d == duration.zero
    assert d + (-d) == duration.zero


@given(_durations, _durations, _durations)
def test_order_is_total_transitive_and_kept_by_addition(a: Duration, b: Duration, c: Duration):
    assert (a < b) + (a == b) + (a > b) == 1
    if a <= b <= c:
        assert a <= c
    if a.is_finite() and b.is_finite() and c.is_finite():
        assert (a <= b) == (a + c <= b + c)


@given(_finite, _finite)
def test_order_agrees_with_nanoseconds(a: Duration, b: Duration):
    assert (a < b) == (a.to_nanos_unsafe() < b.to_nanos_unsafe())
    assert (a == b) == (a.to_nanos_unsafe() == b.to_nanos_unsafe())


@given(st.timedeltas())
def test_a_timedelta_converts_back_to_itself(td: timedelta):
    assert duration.from_input_unsafe(td).to_timedelta() == td


# --- date-times ------------------------------------------------------------------------------

_ZONES = [
    "UTC",
    "Europe/London",
    "Europe/Berlin",
    "America/New_York",
    "America/Sao_Paulo",
    "Asia/Kolkata",
    "Australia/Lord_Howe",
    "Pacific/Chatham",
    "Pacific/Kiritimati",
]
_utc = st.datetimes(
    min_value=datetime(1, 1, 2), max_value=datetime(9999, 12, 30), timezones=st.just(UTC)
).map(lambda dt: dt.replace(microsecond=dt.microsecond // 1000 * 1000))
"""Instants to the millisecond (the ISO strings' precision), any year Python has."""
_offsets = st.integers(-(23 * 60 + 59), 23 * 60 + 59).map(
    lambda minutes: timezone(timedelta(minutes=minutes))
)
_zones = st.one_of(st.sampled_from(_ZONES).map(ZoneInfo), _offsets)

_decode_utc = S.decode_unknown_sync(S.DateTimeUtcFromString)


@given(_utc)
@example(datetime(999, 12, 31, 23, 59, 59, 999_000, tzinfo=UTC))
@example(datetime(1, 1, 2, tzinfo=UTC))
def test_an_iso_string_parses_back_to_its_instant(dt: datetime):
    text = date_time.format_iso(dt)
    assert len(text) == len("2024-01-01T00:00:00.000Z")
    assert _decode_utc(text) == dt


@given(_utc, _utc)
def test_iso_strings_sort_as_their_instants(a: datetime, b: datetime):
    assert (date_time.format_iso(a) < date_time.format_iso(b)) == (a < b)


def _offset_to_the_minute(offset: timedelta) -> timedelta:
    """The offset a zoned string writes: Effect's ``offsetToString`` rounds the minutes
    (``Math.round``, halves up) of the offset's absolute value."""
    millis = abs(offset) // timedelta(milliseconds=1)
    hours, rest = divmod(millis, 3_600_000)
    minutes = math.floor(rest / 60_000 + 0.5)
    written = timedelta(hours=hours, minutes=minutes)
    return -written if offset < timedelta() else written


@given(_utc, _zones)
@example(datetime(500, 6, 1, 12, tzinfo=UTC), timezone(timedelta(hours=5, minutes=30)))
@example(datetime(500, 6, 1, 12, tzinfo=UTC), ZoneInfo("Europe/Berlin"))
def test_a_zoned_string_parses_back_to_its_instant_and_zone(dt: datetime, zone: Any):
    """The wall clock is written to the millisecond and the offset to the minute, so the
    instant comes back shifted by what rounding the offset dropped: nothing, but for a
    zone's local mean time before standard time (Berlin's +00:53:28), as in Effect."""
    zoned = dt.astimezone(zone)
    offset = zoned.utcoffset() or timedelta()
    parsed = date_time.make_zoned_from_string(date_time.format_iso_zoned(zoned))
    assert parsed is not None
    assert parsed == zoned + (offset - _offset_to_the_minute(offset))
    if isinstance(zone, ZoneInfo):
        # Read back under ICU's canonical id, as Effect's Intl does (Asia/Kolkata is Asia/Calcutta).
        canonical = date_time.zone_named(zone.key)
        assert canonical is not None
        assert date_time.zone_to_string(parsed.tzinfo or UTC) == canonical.key
    else:
        assert parsed.utcoffset() == offset


_inner_utc = st.datetimes(
    min_value=datetime(3, 1, 1), max_value=datetime(9997, 1, 1), timezones=st.just(UTC)
).map(lambda dt: dt.replace(microsecond=dt.microsecond // 1000 * 1000))
"""Instants to the millisecond (adding a time unit cuts to one, as Effect's ``setTime``), far
enough from Python's year limits that the shifts below stay within them."""


@given(_inner_utc, st.integers(-400, 400), st.integers(-48, 48))
@example(datetime(2249, 1, 1, 0, 0, 0, 1, tzinfo=UTC), 0, 0)
def test_adding_days_and_hours_then_subtracting_them_is_the_identity(
    dt: datetime, days: int, hours: int
):
    """Adding nothing kept a far year's microseconds only as well as a float holds them
    (2249-01-01T00:00:00.000001 came back .000002)."""
    later = date_time.add(dt, days=days, hours=hours)
    assert date_time.subtract(later, days=days, hours=hours) == dt


@given(_inner_utc, _inner_utc, st.integers(-30, 30), _zones)
def test_adding_months_keeps_the_order(a: datetime, b: datetime, months: int, zone: Any):
    a, b = sorted((a.astimezone(zone), b.astimezone(zone)))
    assert date_time.add(a, months=months) <= date_time.add(b, months=months)


# --- cron ------------------------------------------------------------------------------------


def _subset(low: int, high: int) -> st.SearchStrategy[frozenset[int]]:
    return st.frozensets(st.integers(low, high), min_size=1, max_size=4)


@st.composite
def _crons(draw: st.DrawFn, zones: st.SearchStrategy[Any]) -> cron.Cron:
    """Crons that always match somewhere: days of month up to the 28th."""
    every = st.just(frozenset[int]())
    return cron.make(
        seconds=draw(st.one_of(st.just(frozenset({0})), _subset(0, 59))),
        minutes=draw(st.one_of(every, _subset(0, 59))),
        hours=draw(st.one_of(every, _subset(0, 23))),
        days=draw(st.one_of(every, _subset(1, 28))),
        months=draw(st.one_of(every, _subset(1, 12))),
        weekdays=draw(st.one_of(every, _subset(0, 6))),
        tz=draw(zones),
    )


_fixed_zones = st.one_of(st.just(UTC), _offsets)
_instants = st.datetimes(
    min_value=datetime(1990, 1, 1), max_value=datetime(2060, 1, 1), timezones=st.just(UTC)
)


@given(_crons(_fixed_zones), _instants)
def test_the_next_run_is_later_and_matches(c: cron.Cron, now: datetime):
    after = cron.next(c, now)
    assert after > now
    assert cron.match(c, after)
    before = cron.prev(c, now)
    assert before < now
    assert cron.match(c, before)


@given(_crons(st.one_of(_fixed_zones, st.sampled_from(_ZONES).map(ZoneInfo))), _instants)
def test_no_run_is_skipped_between_the_previous_and_the_next(c: cron.Cron, now: datetime):
    """``next`` of the previous run is at or after ``now``, ``prev`` of the next one at or
    before it: no matching time lies strictly between."""
    assert cron.next(c, cron.prev(c, now)) >= now
    assert cron.prev(c, cron.next(c, now)) <= now


@given(
    _crons(st.one_of(_fixed_zones, st.sampled_from(_ZONES).map(ZoneInfo))),
    _instants,
    _instants,
)
def test_the_next_run_is_monotonic(c: cron.Cron, a: datetime, b: datetime):
    a, b = sorted((a, b))
    assert cron.next(c, a) <= cron.next(c, b)
    assert cron.prev(c, a) <= cron.prev(c, b)


@given(_crons(_fixed_zones), _instants)
def test_a_sequence_strictly_increases(c: cron.Cron, now: datetime):
    runs = [run for run, _ in zip(cron.sequence(c, now), range(6), strict=False)]
    assert all(x < y for x, y in itertools.pairwise(runs))
    assert runs[0] == cron.next(c, now)


@given(_crons(st.none()))
def test_a_formatted_cron_parses_back_to_it(c: cron.Cron):
    text = cron.format(c, include_seconds=True)
    assert cron.parse_unsafe(text) == c


@given(_crons(st.just(UTC)), _instants.map(lambda dt: dt.replace(microsecond=0)))
def test_a_cron_schedule_runs_at_the_crons_times(c: cron.Cron, start: datetime):
    """``schedule.cron`` on the ``TestClock``: each repetition lands on the next cron time.
    The start is a whole second, as Effect's ``Date`` reads whole milliseconds."""
    expected = [run for run, _ in zip(cron.sequence(c, start), range(3), strict=False)]
    seen: list[datetime] = []

    @fx.gen
    def program() -> Generator[fx.Effect[Any, Any, Any], Any]:
        yield from testing.set_time(start.timestamp() * 1000)
        record = date_time.now().flat_map(lambda now: fx.sync(lambda: seen.append(now)))
        fiber = yield from record.repeat(schedule.cron(c)).fork()
        for run in expected:
            yield from testing.set_time(run.timestamp() * 1000)
        yield from fiber.interrupt()

    testing.run_test(program.or_die())
    assert seen[1:] == expected
