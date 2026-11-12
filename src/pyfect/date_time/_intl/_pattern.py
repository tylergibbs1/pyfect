"""ICU's ``SimpleDateFormat::format`` for the pattern letters CLDR's patterns
use (``smpdtfmt.cpp``): numbers in the locale's digits, names from its
calendar data, day periods from CLDR's rules."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime
from typing import Final

from pyfect.date_time._intl import _zone_names
from pyfect.date_time._intl._data import CalendarData, LocaleData, meta
from pyfect.date_time._intl._fields import Fields
from pyfect.date_time._intl._generator import tokens

# DayPeriodRules::DayPeriod, in ICU's order.
_PERIODS: Final = (
    "midnight",
    "noon",
    "morning1",
    "afternoon1",
    "evening1",
    "night1",
    "morning2",
    "afternoon2",
    "evening2",
    "night2",
    "am",
    "pm",
)


@dataclass(frozen=True, slots=True)
class Context:
    """What one formatting needs besides the pattern."""

    data: LocaleData
    calendar: CalendarData
    digits: str
    minus_sign: str
    rules_locale: str
    """The locale whose day period rules ``B`` reads (ICU falls back by parent)."""
    zone: _zone_names.ZoneAt
    instant: datetime


def _number(context: Context, value: int, minimum: int, maximum: int = 10) -> str:
    text = str(abs(value)).rjust(minimum, "0")
    if len(text) > maximum:
        text = text[-maximum:]
    sign = context.minus_sign if value < 0 else ""
    return sign + "".join(context.digits[int(digit)] for digit in text)


def _width(count: int) -> str:
    return {4: "wide", 5: "narrow"}.get(count, "abbreviated")


def _name(
    table: dict[str, dict[str, tuple[str, ...]]], context: str, width: str, index: int
) -> str:
    names = table.get(context, {}).get(width) or table["format"][width]
    return names[index]


def _period_rules(locale: str) -> tuple[list[str], bool, bool] | None:
    """The day period of each hour, and whether there are midnight and noon."""
    rules = meta().day_period_rules
    current: str | None = locale
    while current is not None:
        found = rules.get(current)
        if found is not None:
            break
        current = current.rsplit("-", 1)[0] if "-" in current else None
    else:
        return None
    hours = [""] * 24
    for name, rule in found.items():
        if "_from" in rule:
            start = int(rule["_from"].split(":")[0])
            end = int(rule["_before"].split(":")[0]) % 24
            hour = start
            while hour != end:
                hours[hour] = name
                hour = (hour + 1) % 24
                if hour == start:
                    break
    if not hours[0]:
        return None
    return hours, "midnight" in found, "noon" in found


def _am_pm(context: Context, fields: Fields, count: int) -> str:
    table = context.calendar.day_periods["format"]
    names = table.get(_width(count), table["abbreviated"])
    return names["pm" if fields.hour >= 12 else "am"]


def _noon(context: Context, fields: Fields, count: int, has_minute: bool, has_second: bool) -> str:
    """``b``: ``noon`` at exactly noon, else AM or PM."""
    if (
        fields.hour == 12
        and (not has_minute or fields.minute == 0)
        and (not has_second or fields.second == 0)
    ):
        text = context.calendar.day_periods["format"].get(_width(count), {}).get("noon")
        if text:
            return text
    return _am_pm(context, fields, count)


def _flexible(
    context: Context, fields: Fields, count: int, has_minute: bool, has_second: bool
) -> str:
    """``B``: CLDR's flexible day periods (``in the morning``)."""
    rules = _period_rules(context.rules_locale)
    if rules is None:
        return _am_pm(context, fields, count)
    hours, has_midnight, has_noon = rules
    minute = fields.minute if has_minute else 0
    second = fields.second if has_second else 0
    if fields.hour == 0 and minute == 0 and second == 0 and has_midnight:
        period = "midnight"
    elif fields.hour == 12 and minute == 0 and second == 0 and has_noon:
        period = "noon"
    else:
        period = hours[fields.hour]
    names = context.calendar.day_periods["format"].get(_width(count), {})
    text = names.get(period) if period not in ("am", "pm", "midnight") else None
    if not text and period in ("midnight", "noon"):
        period = hours[fields.hour]
        text = names.get(period)
    if period in ("am", "pm") or not text:
        return _am_pm(context, fields, count)
    return text


# The fields that are a number, padded to the letter's count.
_NUMBERS: Final[dict[str, Callable[[Fields], int]]] = {
    "d": lambda fields: fields.day,
    "h": lambda fields: fields.hour % 12 or 12,
    "K": lambda fields: fields.hour % 12,
    "H": lambda fields: fields.hour,
    "k": lambda fields: fields.hour or 24,
    "m": lambda fields: fields.minute,
    "s": lambda fields: fields.second,
}


def _month(context: Context, month: int, char: str, count: int) -> str:
    if count < 3:
        return _number(context, month + 1, count)
    kind = "format" if char == "M" else "stand-alone"
    return _name(context.calendar.months, kind, _width(count), month)


def _weekday(context: Context, weekday: int, char: str, count: int) -> str:
    if char != "E" and count < 3:
        return _number(context, weekday + 1, count if char == "e" else 1)
    kind = "stand-alone" if char == "c" else "format"
    width = {4: "wide", 5: "narrow", 6: "short"}.get(count, "abbreviated")
    return _name(context.calendar.days, kind, width, weekday)


def _field(  # noqa: PLR0911 - one case per pattern letter, as ICU's subFormat
    context: Context, fields: Fields, char: str, count: int, flags: tuple[bool, bool]
) -> str:
    number = _NUMBERS.get(char)
    if number is not None:
        return _number(context, number(fields), count)
    calendar = context.calendar
    match char:
        case "G":
            width = {4: "wide", 5: "narrow"}.get(count, "abbreviated")
            return calendar.eras.get(width, calendar.eras["abbreviated"]).get(fields.era, "")
        case "y":
            return (
                _number(context, fields.year, 2, 2)
                if count == 2
                else _number(context, fields.year, count)
            )
        case "M" | "L":
            return _month(context, fields.month, char, count)
        case "E" | "c" | "e":
            return _weekday(context, fields.weekday, char, count)
        case "a":
            return _am_pm(context, fields, count)
        case "b":
            return _noon(context, fields, count, *flags)
        case "B":
            return _flexible(context, fields, count, *flags)
        case "z":
            return _zone_names.specific(
                context.data, context.digits, context.zone, context.instant, long=count >= 4
            )
        case _:
            return ""


def _parts(pattern: str) -> list[tuple[str, int]]:
    """The pattern as fields (a letter and its count) and literal text (count 0)."""
    items = tokens(pattern)
    parts: list[tuple[str, int]] = []
    in_quote = False
    index = 0
    while index < len(items):
        item = items[index]
        index += 1
        if item == "'":
            if index < len(items) and items[index] == "'":
                parts.append(("'", 0))
                index += 1
            else:
                in_quote = not in_quote
        elif in_quote or not (item[0].isascii() and item[0].isalpha()):
            parts.append((item, 0))
        else:
            parts.append((item[0], len(item)))
    return parts


def format_pattern(pattern: str, fields: Fields, context: Context) -> str:
    """``pattern`` filled in with ``fields``."""
    parts = _parts(pattern)
    letters = {text for text, count in parts if count}
    flags = ("m" in letters, "s" in letters)
    return "".join(
        _field(context, fields, text, count, flags) if count else text for text, count in parts
    )
