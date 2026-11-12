"""The calendar fields ICU formats an instant with: Gregorian (proleptic, as
V8 sets it), Buddhist (Julian before ICU's 1582 cutover, which V8 leaves on)
and Persian (``gregocal.cpp``, ``buddhcal.cpp``, ``persncal.cpp``)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final, Literal

type CalendarName = Literal["gregorian", "buddhist", "persian"]

_EPOCH_JULIAN_DAY: Final = 2440588
_CUTOVER_JULIAN_DAY: Final = 2299161  # 1582-10-15, ICU's Gregorian cutover
_PERSIAN_EPOCH: Final = 1948320
_PERSIAN_MONTH_START: Final = (0, 31, 62, 93, 124, 155, 186, 216, 246, 276, 306, 336)
# ICU's years the 33-year arithmetic calls leap and are not (persncal.cpp).
_PERSIAN_NOT_LEAP: Final = frozenset(
    (
        *(1502, 1601, 1634, 1667, 1700, 1733, 1766, 1799, 1832, 1865, 1898, 1931, 1964, 1997),
        *(2030, 2059, 2063, 2096, 2129, 2158, 2162, 2191, 2195, 2224, 2228, 2257, 2261, 2290),
        *(2294, 2323, 2327, 2356, 2360, 2389, 2393, 2422, 2426, 2455, 2459, 2488, 2492, 2521),
        *(2525, 2554, 2558, 2587, 2591, 2620, 2624, 2653, 2657, 2686, 2690, 2719, 2723, 2748),
        *(2752, 2756, 2781, 2785, 2789, 2818, 2822, 2847, 2851, 2855, 2880, 2884, 2888, 2913),
        *(2917, 2921, 2946, 2950, 2954, 2979, 2983, 2987),
    )
)
_PERSIAN_FIRST_CORRECTION: Final = 1502


@dataclass(frozen=True, slots=True)
class Fields:
    era: int
    year: int
    month: int
    """0-based, as ICU's."""
    day: int
    weekday: int
    """0 is Sunday."""
    hour: int
    minute: int
    second: int


def _gregorian(julian_day: int, *, proleptic: bool) -> tuple[int, int, int, int]:
    """Era, year in era, 0-based month and day of a Julian day number."""
    if proleptic or julian_day >= _CUTOVER_JULIAN_DAY:
        year, month, day = _civil(julian_day)
    else:
        year, month, day = _julian(julian_day)
    return (1, year, month - 1, day) if year > 0 else (0, 1 - year, month - 1, day)


def _civil(julian_day: int) -> tuple[int, int, int]:
    a = julian_day + 32044
    b = (4 * a + 3) // 146097
    c = a - 146097 * b // 4
    d = (4 * c + 3) // 1461
    e = c - 1461 * d // 4
    m = (5 * e + 2) // 153
    return 100 * b + d - 4800 + m // 10, m + 3 - 12 * (m // 10), e - (153 * m + 2) // 5 + 1


def _julian(julian_day: int) -> tuple[int, int, int]:
    c = julian_day + 32082
    d = (4 * c + 3) // 1461
    e = c - 1461 * d // 4
    m = (5 * e + 2) // 153
    return d - 4800 + m // 10, m + 3 - 12 * (m // 10), e - (153 * m + 2) // 5 + 1


def _persian(julian_day: int) -> tuple[int, int, int]:
    days = julian_day - _PERSIAN_EPOCH
    year = (33 * days + 3) // 12053 + 1
    first = 365 * (year - 1) + (8 * year + 21) // 33
    if year > _PERSIAN_FIRST_CORRECTION and year - 1 in _PERSIAN_NOT_LEAP:
        first -= 1
    day_of_year = days - first
    if day_of_year == 365 and year >= _PERSIAN_FIRST_CORRECTION and year in _PERSIAN_NOT_LEAP:
        year += 1
        day_of_year = 0
    month = day_of_year // 31 if day_of_year < 216 else (day_of_year - 6) // 30
    return year, month, day_of_year + 1 - _PERSIAN_MONTH_START[month]


def fields(epoch_ms: int, offset_seconds: int, calendar: CalendarName) -> Fields:
    """The fields of the wall-clock time ``offset_seconds`` from UTC."""
    local_ms = epoch_ms + offset_seconds * 1000
    days, in_day = divmod(local_ms, 86_400_000)
    julian_day = days + _EPOCH_JULIAN_DAY
    if calendar == "persian":
        era = 0
        year, month, day = _persian(julian_day)
    else:
        era, year, month, day = _gregorian(julian_day, proleptic=calendar == "gregorian")
        if calendar == "buddhist":
            extended = year if era == 1 else 1 - year
            era, year = 0, extended + 543
    return Fields(
        era=era,
        year=year,
        month=month,
        day=day,
        weekday=(julian_day + 1) % 7,
        hour=in_day // 3_600_000,
        minute=in_day // 60_000 % 60,
        second=in_day // 1000 % 60,
    )
