"""Whether a zone is on daylight time, as ICU's ``zoneinfo64`` says.

ICU builds its zones from tz's rearguard data, where daylight saving is never
negative. tz's main data, which Linux distributions ship, writes Irish winter
time (and Windhoek's and Prague's 1946 winters, Casablanca's Ramadan) as a
negative save from summer time, so ``datetime.dst()`` there says the opposite
of ICU. Rearguard turns each such period into standard time and the periods
next to it into daylight time, and so does ``is_daylight``, whichever data
the ``zoneinfo`` module reads.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta, tzinfo
from functools import cache
from typing import Final

_DAY: Final = timedelta(days=1)
# A zone's periods of negative save each last under a year, and the sampling
# below is monthly, so it finds every one.
_SAMPLED_YEARS: Final = range(1900, 2101)
_LONGEST_PERIOD_DAYS: Final = 400


def is_daylight(zone: tzinfo, instant: datetime) -> bool:
    """Whether ``zone`` keeps daylight time at ``instant`` (a UTC ``datetime``)."""
    save = _save(zone, instant)
    if save != timedelta(0):
        return save > timedelta(0)
    if not _has_negative_save(zone):
        return False
    return any(
        _save(zone, neighbour) < timedelta(0)
        for neighbour in (_period_edge(zone, instant, -_DAY), _period_edge(zone, instant, _DAY))
        if neighbour is not None
    )


def _save(zone: tzinfo, instant: datetime) -> timedelta:
    return instant.astimezone(zone).dst() or timedelta(0)


def _offset(zone: tzinfo, instant: datetime) -> timedelta | None:
    return instant.astimezone(zone).utcoffset()


@cache
def _has_negative_save(zone: tzinfo) -> bool:
    return any(
        _save(zone, datetime(year, month, 15, tzinfo=UTC)) < timedelta(0)
        for year in _SAMPLED_YEARS
        for month in range(1, 13)
    )


def _period_edge(zone: tzinfo, instant: datetime, step: timedelta) -> datetime | None:
    """The first day, stepping from ``instant``, in the period next to its own."""
    offset = _offset(zone, instant)
    current = instant
    for _ in range(_LONGEST_PERIOD_DAYS):
        try:
            current += step
        except OverflowError:
            return None
        if _offset(zone, current) != offset:
            return current
    return None
