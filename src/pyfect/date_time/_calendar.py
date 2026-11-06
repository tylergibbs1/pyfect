"""Calendar arithmetic on aware datetimes, as Effect's ``DateTime.add`` /
``startOf`` / ``endOf`` / ``nearest``.

Time units (hours and smaller) move the instant: ``add(dt, hours=24)`` is
always 24 elapsed hours. Calendar units (days and larger) move the
wall-clock time in ``dt``'s zone, then resolve it with
``make_zoned(..., disambiguation="compatible")``. Plain ``dt +
timedelta(hours=1)`` on a ``ZoneInfo`` datetime moves the wall clock
instead, which is wrong for elapsed time across a DST change."""

from __future__ import annotations

import calendar
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, tzinfo
from decimal import Decimal
from typing import Literal

from pyfect.date_time._zones import make_zoned, zone_of

_EPOCH = datetime(1970, 1, 1, tzinfo=UTC)
_MICRO = timedelta(microseconds=1)

type _DayUnit = Literal["day", "week", "month", "year"]
type Unit = Literal["millisecond", "second", "minute", "hour"] | _DayUnit


def add(
    dt: datetime,
    *,
    years: int = 0,
    months: int = 0,
    weeks: int = 0,
    days: int = 0,
    hours: float = 0,
    minutes: float = 0,
    seconds: float = 0,
    milliseconds: float = 0,
    microseconds: float = 0,
) -> datetime:
    """``dt`` moved by the given units, keeping its zone. Months and years
    clamp to the last day of the month (Jan 31 + 1 month = Feb 28/29).
    Time units are added one at a time, smallest first, each sum cut to a
    whole millisecond toward the epoch (Effect's ``setTime``)."""
    zone = zone_of(dt, "dt")
    epoch_millis = Decimal((dt - _EPOCH) // _MICRO) / 1_000
    for amount, millis_per_unit in (
        (microseconds, Decimal("0.001")),
        (milliseconds, Decimal(1)),
        (seconds, Decimal(1_000)),
        (minutes, Decimal(60_000)),
        (hours, Decimal(3_600_000)),
    ):
        if amount:
            epoch_millis = _add_truncated(epoch_millis, amount, millis_per_unit)
    shifted = (_EPOCH + timedelta(milliseconds=float(epoch_millis))).astimezone(zone)
    if not (days or weeks or months or years):
        return shifted

    def move(wall: datetime) -> datetime:
        wall += timedelta(days=days + 7 * weeks)
        if months:
            wall = _with_month(wall, wall.year * 12 + wall.month - 1 + months)
        if years:
            wall = _with_month(wall, (wall.year + years) * 12 + wall.month - 1)
        return wall

    return _on_wall_clock(shifted, zone, move)


def subtract(
    dt: datetime,
    *,
    years: int = 0,
    months: int = 0,
    weeks: int = 0,
    days: int = 0,
    hours: float = 0,
    minutes: float = 0,
    seconds: float = 0,
    milliseconds: float = 0,
    microseconds: float = 0,
) -> datetime:
    """``add`` with every unit negated."""
    return add(
        dt,
        years=-years,
        months=-months,
        weeks=-weeks,
        days=-days,
        hours=-hours,
        minutes=-minutes,
        seconds=-seconds,
        milliseconds=-milliseconds,
        microseconds=-microseconds,
    )


def start_of(
    dt: datetime, unit: Unit, *, week_starts_on: calendar.Day = calendar.SUNDAY
) -> datetime:
    """The first millisecond of ``dt``'s ``unit``, on its wall clock."""
    return _on_wall_clock(dt, zone_of(dt, "dt"), lambda wall: _start(wall, unit, week_starts_on))


def end_of(dt: datetime, unit: Unit, *, week_starts_on: calendar.Day = calendar.SUNDAY) -> datetime:
    """The last millisecond of ``dt``'s ``unit``, on its wall clock
    (``.999``)."""
    return _on_wall_clock(dt, zone_of(dt, "dt"), lambda wall: _end(wall, unit, week_starts_on))


def nearest(
    dt: datetime, unit: Unit, *, week_starts_on: calendar.Day = calendar.SUNDAY
) -> datetime:
    """The start of ``dt``'s ``unit`` or of the next one, whichever is
    closer on the wall clock; halfway rounds up."""
    zone = zone_of(dt, "dt")

    def round_wall(wall: datetime) -> datetime:
        start = _start(wall, unit, week_starts_on)
        after = _end(wall, unit, week_starts_on) + timedelta(milliseconds=1)
        return start if wall - start < after - wall else after

    return _on_wall_clock(dt, zone, round_wall)


def _add_truncated(epoch_millis: Decimal, amount: float, millis_per_unit: Decimal) -> Decimal:
    """``epoch_millis`` plus ``amount`` units, cut toward zero as
    JavaScript's TimeClip cuts a time value. The float is read as the
    decimal that prints it, so ``1.001`` seconds is 1,001ms."""
    return Decimal(int(epoch_millis + Decimal(repr(amount)) * millis_per_unit))


def _on_wall_clock(dt: datetime, zone: tzinfo, f: Callable[[datetime], datetime]) -> datetime:
    """Apply ``f`` to ``dt``'s naive wall-clock time and resolve the result
    in ``zone``."""
    return make_zoned(f(dt.replace(tzinfo=None, fold=0)), zone)


def _with_month(wall: datetime, month_index: int) -> datetime:
    """``wall`` in month ``month_index`` (years * 12 + zero-based month),
    with the day clamped to that month's length."""
    year, month0 = divmod(month_index, 12)
    last_day = calendar.monthrange(year, month0 + 1)[1]
    return wall.replace(year=year, month=month0 + 1, day=min(wall.day, last_day))


def _days_into_week(wall: datetime, week_starts_on: calendar.Day) -> int:
    return (wall.weekday() - week_starts_on) % 7


def _start(wall: datetime, unit: Unit, week_starts_on: calendar.Day) -> datetime:
    match unit:
        case "millisecond":
            return wall.replace(microsecond=wall.microsecond // 1_000 * 1_000)
        case "second":
            return wall.replace(microsecond=0)
        case "minute":
            return wall.replace(second=0, microsecond=0)
        case "hour":
            return wall.replace(minute=0, second=0, microsecond=0)
        case "day" | "week" | "month" | "year":
            return _start_of_days(_midnight(wall), unit, week_starts_on)


def _start_of_days(midnight: datetime, unit: _DayUnit, week_starts_on: calendar.Day) -> datetime:
    match unit:
        case "day":
            return midnight
        case "week":
            return midnight - timedelta(days=_days_into_week(midnight, week_starts_on))
        case "month":
            return midnight.replace(day=1)
        case "year":
            return midnight.replace(month=1, day=1)


def _end(wall: datetime, unit: Unit, week_starts_on: calendar.Day) -> datetime:
    match unit:
        case "millisecond":
            return wall.replace(microsecond=wall.microsecond // 1_000 * 1_000)
        case "second":
            return wall.replace(microsecond=999_000)
        case "minute":
            return wall.replace(second=59, microsecond=999_000)
        case "hour":
            return wall.replace(minute=59, second=59, microsecond=999_000)
        case "day" | "week" | "month" | "year":
            return _end_of_days(_last_moment(wall), unit, week_starts_on)


def _end_of_days(last: datetime, unit: _DayUnit, week_starts_on: calendar.Day) -> datetime:
    match unit:
        case "day":
            return last
        case "week":
            return last + timedelta(days=6 - _days_into_week(last, week_starts_on))
        case "month":
            return last.replace(day=calendar.monthrange(last.year, last.month)[1])
        case "year":
            return last.replace(month=12, day=31)


def _midnight(wall: datetime) -> datetime:
    return wall.replace(hour=0, minute=0, second=0, microsecond=0)


def _last_moment(wall: datetime) -> datetime:
    return wall.replace(hour=23, minute=59, second=59, microsecond=999_000)
