"""Effect's ``DateTime.format``, ``formatLocal``, ``formatUtc`` (``Intl``), on
babel's CLDR data (extra ``pyfect-dev[intl]``)::

    intl.format_utc(dt, locale="en-GB", date_style="full")
    intl.format_utc(dt, year="numeric", month="long", day="numeric")

No option is ``3/15/2024``, as ``Intl.DateTimeFormat``'s default. ``time_zone``
names the zone (the ``datetime``'s own for ``format``). babel has no CLDR
``atTime`` pattern, so a full or long date with a time joins with ``, `` where
``Intl`` writes ``at``.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, tzinfo
from typing import Literal, NotRequired, TypedDict, Unpack

from pyfect._extras import missing_extra
from pyfect.date_time._zones import zone_named

try:
    from babel import Locale
    from babel.dates import format_date, format_datetime, format_time, match_skeleton
except ImportError as error:  # pragma: no cover - depends on the environment
    raise missing_extra("pyfect.date_time.intl", "intl") from error

type Style = Literal["full", "long", "medium", "short"]
type Numeric = Literal["numeric", "2-digit"]
type Text = Literal["long", "short", "narrow"]


class FormatOptions(TypedDict):
    """``Intl.DateTimeFormatOptions`` with ``locale``."""

    locale: NotRequired[str]
    time_zone: NotRequired[str]
    date_style: NotRequired[Style]
    time_style: NotRequired[Style]
    weekday: NotRequired[Text]
    year: NotRequired[Numeric]
    month: NotRequired[Numeric | Text]
    day: NotRequired[Numeric]
    hour: NotRequired[Numeric]
    minute: NotRequired[Numeric]
    second: NotRequired[Numeric]


_WIDTHS = {"numeric": 1, "2-digit": 2}
_MONTH = {"numeric": "M", "2-digit": "MM", "short": "MMM", "long": "MMMM", "narrow": "MMMMM"}
_WEEKDAY = {"short": "EEE", "long": "EEEE", "narrow": "EEEEE"}


def _skeleton(options: FormatOptions) -> str:
    parts: list[str] = []
    if "weekday" in options:
        parts.append(_WEEKDAY[options["weekday"]])
    if "year" in options:
        parts.append("yy" if options["year"] == "2-digit" else "y")
    if "month" in options:
        parts.append(_MONTH[options["month"]])
    for key, letter in (("day", "d"), ("hour", "j"), ("minute", "m"), ("second", "s")):
        value = options.get(key)
        if isinstance(value, str):
            parts.append(letter * _WIDTHS[value])
    return "".join(parts) or "yMd"


def _spaces(text: str) -> str:
    # ECMA-402 implementations print CLDR's narrow space as a plain one.
    return text.replace("\u202f", " ")


_FIELDS = re.compile(r"(?:'[^']*')+|([a-zA-Z])\1*")


def _widened(pattern: str, skeleton: str) -> str:
    """``pattern`` with each numeric field as wide as the skeleton asks, as
    ICU's skeleton matcher does."""

    def adjust(match: re.Match[str]) -> str:
        field = match[0]
        letter = field[0]
        if letter in "cE" and "E" in skeleton:
            return letter * skeleton.count("E")
        asked = skeleton.count("M" if letter == "L" else letter)
        if asked == 0 or letter == "'":
            return field
        if letter in "ML" and len(field) >= 3 and asked >= 3:
            return letter * asked
        return letter * asked if asked == 2 else field

    return _FIELDS.sub(adjust, pattern)


def _in(dt: datetime, zone: tzinfo, options: FormatOptions) -> str:
    locale = options.get("locale", "en-US").replace("-", "_")
    date_style = options.get("date_style")
    time_style = options.get("time_style")
    if date_style is not None and time_style is not None:
        joined = str(Locale.parse(locale).datetime_formats[date_style])
        date = format_date(dt.astimezone(zone), date_style, locale=locale)
        time = format_time(dt, time_style, tzinfo=zone, locale=locale)
        return _spaces(joined.replace("'", "").replace("{1}", date).replace("{0}", time))
    if date_style is not None:
        return format_date(dt.astimezone(zone), date_style, locale=locale)
    if time_style is not None:
        return _spaces(format_time(dt, time_style, tzinfo=zone, locale=locale))
    short_time = str(Locale.parse(locale).time_formats["short"])
    hour = "h" if "h" in short_time else "H"
    skeleton = _skeleton(options).replace("j", hour)
    found = match_skeleton(skeleton, Locale.parse(locale).datetime_skeletons)
    pattern = str(Locale.parse(locale).datetime_skeletons[found]) if found else skeleton
    return _spaces(format_datetime(dt, _widened(pattern, skeleton), tzinfo=zone, locale=locale))


def _zone(options: FormatOptions, default: tzinfo) -> tzinfo:
    name = options.get("time_zone")
    if name is None:
        return default
    zone = zone_named(name)
    if zone is None:
        raise ValueError(f"Invalid time zone specified: {name}")
    return zone


def format_utc(dt: datetime, **options: Unpack[FormatOptions]) -> str:
    """``dt`` in UTC (or ``time_zone``), for the locale (Effect's ``formatUtc``)."""
    return _in(dt, _zone(options, UTC), options)


def format_local(dt: datetime, **options: Unpack[FormatOptions]) -> str:
    """``dt`` in the system's zone (or ``time_zone``) (Effect's ``formatLocal``)."""
    local = datetime.now().astimezone().tzinfo
    return _in(dt, _zone(options, UTC if local is None else local), options)


def format(dt: datetime, **options: Unpack[FormatOptions]) -> str:
    """``dt`` in its own zone (or ``time_zone``) (Effect's ``format``)."""
    own = dt.tzinfo
    return _in(dt, _zone(options, UTC if own is None else own), options)


__all__ = ["FormatOptions", "format", "format_local", "format_utc"]
