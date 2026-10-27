"""Wall-clock arithmetic with JavaScript ``Date``'s overflow rules, which
Effect's cron search relies on: setting day 0 gives the previous month's
last day, minute 60 the next hour, month 13 January of the next year.

A wall-clock time is a naive ``datetime`` read in the cron's zone."""

from __future__ import annotations

import calendar
from datetime import datetime, timedelta


def with_fields(
    wall: datetime,
    *,
    year: int | None = None,
    month: int | None = None,
    day: int | None = None,
    hour: int | None = None,
    minute: int | None = None,
    second: int | None = None,
) -> datetime:
    """``wall`` with the given fields replaced, each free to overflow into
    the next as with ``Date.UTC`` (months are 1-based). Sub-second parts
    are dropped."""
    carry, month_index = divmod((wall.month if month is None else month) - 1, 12)
    first_of_month = datetime((wall.year if year is None else year) + carry, month_index + 1, 1)
    return first_of_month + timedelta(
        days=(wall.day if day is None else day) - 1,
        hours=wall.hour if hour is None else hour,
        minutes=wall.minute if minute is None else minute,
        seconds=wall.second if second is None else second,
    )


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def weekday(wall: datetime) -> int:
    """0 for Sunday to 6 for Saturday, as ``Date.getUTCDay``."""
    return wall.isoweekday() % 7
