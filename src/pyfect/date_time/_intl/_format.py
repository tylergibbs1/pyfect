"""V8's ``Intl.DateTimeFormat`` (``js-date-time-format.cc``): the options
turned into an ICU skeleton or style pattern, and the instant formatted with
it."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timezone, tzinfo
from functools import cache
from typing import Final, Literal
from zoneinfo import ZoneInfo

from pyfect.date_time._icu_zones import CANONICAL
from pyfect.date_time._intl import _pattern
from pyfect.date_time._intl._data import STYLES, locale_data
from pyfect.date_time._intl._fields import CalendarName, fields
from pyfect.date_time._intl._generator import Generator, simple_format, skeleton_of
from pyfect.date_time._intl._locale import HourChar, Resolved, resolve
from pyfect.date_time._intl._zone_names import ZoneAt

type Style = Literal["full", "long", "medium", "short"]

# GetPatternItems: each option's values as skeleton letters, in V8's order.
_ITEMS: Final[tuple[tuple[str, dict[str, str]], ...]] = (
    ("weekday", {"narrow": "EEEEE", "short": "EEE", "long": "EEEE"}),
    ("year", {"2-digit": "yy", "numeric": "y"}),
    ("month", {"2-digit": "MM", "numeric": "M", "narrow": "MMMMM", "short": "MMM", "long": "MMMM"}),
    ("day", {"2-digit": "dd", "numeric": "d"}),
    ("hour", {"2-digit": "jj", "numeric": "j"}),
    ("minute", {"2-digit": "mm", "numeric": "m"}),
    ("second", {"2-digit": "ss", "numeric": "s"}),
)
_TIME_SKELETONS: Final = ("jmmsszzzz", "jmmssz", "jmmss", "jmm")
_OFFSET_KEY: Final = re.compile(r"[+-][0-9]{2}:[0-9]{2}")


@dataclass(frozen=True, slots=True)
class Request:
    """The options, as V8 reads them."""

    date_style: Style | None
    time_style: Style | None
    fields: tuple[tuple[str, str], ...]


@cache
def _generator(
    data_locale: str,
    calendar: str,
    hour_char: HourChar,
    allowed: tuple[str, ...],
    *,
    standard_patterns: bool = True,
    match_hour: bool = True,
) -> Generator:
    data = locale_data(data_locale)
    return Generator(
        data.calendars[calendar],
        data.fields,
        hour_char,
        allowed,
        standard_patterns=standard_patterns,
        match_hour=match_hour,
    )


def _locale_generator(locale: Resolved) -> Generator:
    return _generator(
        locale.data_locale, locale.generator_calendar, locale.hour_char, locale.allowed_hours
    )


def _replace_hour_cycle(pattern: str, hour: HourChar) -> str:
    """``ReplaceHourCycleInPattern``: every hour letter as ``hour``, and a space
    between a day and an hour that touch."""
    out: list[str] = []
    replace = True
    last = ""
    for char in pattern:
        if char == "'":
            replace = not replace
            out.append(char)
        elif char in "HhKk":
            if replace and last == "d":
                out.append(" ")
            out.append(hour if replace else char)
        else:
            out.append(char)
        last = char
    return "".join(out)


def _hour_cycle_of(pattern: str) -> str | None:
    in_quote = False
    for char in pattern:
        if char == "'":
            in_quote = not in_quote
        elif char in "KhHk" and not in_quote:
            return char
    return None


def _from_skeleton(locale: Resolved, skeleton: str, hour: HourChar) -> str:
    """``CreateICUDateFormat``."""
    return _replace_hour_cycle(_locale_generator(locale).best_pattern(skeleton), hour)


def _style_pattern(locale: Resolved, date_style: Style | None, time_style: Style | None) -> str:
    """``DateTimeStylePattern``: ICU's style patterns, joined as ``SimpleDateFormat`` does."""
    calendar = locale_data(locale.data_locale).calendars[locale.calendar]
    if time_style is None:
        assert date_style is not None
        return calendar.date_formats[STYLES.index(date_style)]
    time_index = STYLES.index(time_style)
    if locale.explicit_hour_cycle:
        time = _generator(
            locale.data_locale,
            locale.generator_calendar,
            locale.hour_char,
            locale.allowed_hours,
            standard_patterns=False,
            match_hour=False,
        ).best_pattern(_TIME_SKELETONS[time_index])
    else:
        time = calendar.time_formats[time_index]
    if date_style is None:
        pattern = time
    else:
        date_index = STYLES.index(date_style)
        glue = calendar.at_time[date_index] or calendar.date_time_formats[date_index]
        pattern = simple_format(glue, time, calendar.date_formats[date_index])
    if _hour_cycle_of(pattern) == locale.hour_char:
        return pattern
    skeleton = skeleton_of(pattern).skeleton()
    replaced = "".join(
        locale.hour_char if char in "hHKk" else char for char in skeleton if char not in "abB"
    )
    return _from_skeleton(locale, replaced, locale.hour_char)


def pattern(locale: Resolved, request: Request) -> str:
    """The ICU pattern ``Intl.DateTimeFormat`` formats with."""
    if request.date_style is not None or request.time_style is not None:
        if request.fields:
            raise TypeError("Invalid option : option")
        return _style_pattern(locale, request.date_style, request.time_style)
    asked = dict(request.fields)
    skeleton = "".join(
        values[asked[name]].replace("j", locale.hour_char)
        for name, values in _ITEMS
        if name in asked
    )
    if not any(
        name in asked for name in ("weekday", "year", "month", "day", "hour", "minute", "second")
    ):
        skeleton += "yMd"
    return _from_skeleton(locale, skeleton, locale.hour_char)


def request_of(options: dict[str, str]) -> Request:
    """The options checked as V8 checks them."""
    found: list[tuple[str, str]] = []
    for name, values in _ITEMS:
        value = options.get(name)
        if value is None:
            continue
        if value not in values:
            raise ValueError(
                f"Value {value} out of range for Intl.DateTimeFormat options property {name}"
            )
        found.append((name, value))
    styles: list[Style | None] = []
    for name in ("dateStyle", "timeStyle"):
        value = options.get(name)
        if value is not None and value not in STYLES:
            raise ValueError(
                f"Value {value} out of range for Intl.DateTimeFormat options property {name}"
            )
        styles.append(_style(value))
    return Request(styles[0], styles[1], tuple(found))


def _style(value: str | None) -> Style | None:
    match value:
        case "full" | "long" | "medium" | "short":
            return value
        case _:
            return None


def zone_at(zone: tzinfo, instant: datetime) -> ZoneAt | None:
    """``zone`` at ``instant`` as ICU sees it; ``None`` for a zone ICU does
    not know (Effect then formats the wall-clock time as UTC)."""
    local = instant.astimezone(zone)
    offset = local.utcoffset()
    seconds = 0 if offset is None else int(offset.total_seconds())
    if zone is UTC:
        return ZoneAt("Etc/UTC", 0, daylight=False)
    # typeshed types ZoneInfo.key as str, but ZoneInfo.from_file (zone_local's
    # /etc/localtime fallback) gives None.
    key: str | None = getattr(zone, "key", None) if isinstance(zone, ZoneInfo) else None
    if key is not None:
        if _OFFSET_KEY.fullmatch(key):
            return ZoneAt("Etc/GMT" if seconds == 0 else None, seconds, daylight=False)
        icu = CANONICAL.get(key)
        if icu is None:
            return None
        dst = local.dst()
        daylight = dst is not None and dst.total_seconds() != 0
        return ZoneAt("Etc/UTC" if icu == "UTC" else icu, seconds, daylight=daylight)
    if isinstance(zone, timezone) and seconds == 0:
        return ZoneAt("Etc/GMT", 0, daylight=False)
    return ZoneAt(None, seconds, daylight=False)


def format_instant(instant: datetime, zone: tzinfo, locale: str | None, request: Request) -> str:
    """``new Intl.DateTimeFormat(locale, {timeZone, ...options}).format(instant)``."""
    resolved = resolve(locale)
    at = zone_at(zone, instant)
    if at is None:
        # Effect's catch: the wall-clock time, formatted in UTC.
        wall = instant.astimezone(zone).replace(tzinfo=UTC)
        return format_instant(wall, UTC, locale, request)
    found = pattern(resolved, request)
    utc = instant.astimezone(UTC)
    epoch_ms = (
        (utc.toordinal() - 719163) * 86_400_000
        + ((utc.hour * 60 + utc.minute) * 60 + utc.second) * 1000
        + utc.microsecond // 1000
    )
    calendar: CalendarName = (
        "buddhist" if resolved.calendar == "buddhist" else
        "persian" if resolved.calendar == "persian" else "gregorian"
    )  # fmt: skip
    data = locale_data(resolved.data_locale)
    context = _pattern.Context(
        data=data,
        calendar=data.calendars[resolved.calendar],
        digits=resolved.digits,
        minus_sign=resolved.minus_sign,
        rules_locale=resolved.rules_locale,
        zone=at,
        instant=utc,
    )
    text = _pattern.format_pattern(found, fields(epoch_ms, at.offset, calendar), context)
    # V8 prints ICU's narrow no-break space as a space.
    return text.replace("\u202f", " ")
