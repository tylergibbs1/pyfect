"""Effect's ``DateTime.format``, ``formatLocal``, ``formatUtc``: what
``Intl.DateTimeFormat`` prints under Node::

    intl.format_utc(dt, locale="en-GB", date_style="full")
    intl.format_utc(dt, year="numeric", month="long", day="numeric")

No option is ``3/15/2024``, as ``Intl.DateTimeFormat``'s default; no
``locale`` is the environment's, as Node's default (``LC_ALL``,
``LC_MESSAGES``, ``LANG``; ``en-US`` when unset). ``time_zone`` names the zone
(the ``datetime``'s own for ``format``, the system's for ``format_local``;
``format_utc`` is always UTC, as Effect's). V8's option handling and ICU's
formatting are ported, reading the data ICU 78.3 ships (CLDR 48, as Node
24.22.1 has it), so the text is that Node's.
A ``-u-ca-`` calendar other than ``gregory``, ``buddhist`` and ``persian`` is a
``ValueError``.
"""

from __future__ import annotations

from datetime import UTC, datetime, tzinfo
from typing import Final, Literal, NotRequired, TypedDict, Unpack

from pyfect.date_time._intl._format import format_instant, request_of
from pyfect.date_time._zones import zone_local, zone_named

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


_KEYS: Final = {"date_style": "dateStyle", "time_style": "timeStyle"}


def _in(dt: datetime, zone: tzinfo, options: FormatOptions) -> str:
    asked = {
        _KEYS.get(key, key): value
        for key, value in options.items()
        if key not in ("locale", "time_zone") and isinstance(value, str)
    }
    return format_instant(dt, zone, options.get("locale"), request_of(asked))


def _zone(options: FormatOptions, default: tzinfo) -> tzinfo:
    name = options.get("time_zone")
    if name is None:
        return default
    zone = zone_named(name)
    if zone is None:
        raise ValueError(f"Invalid time zone specified: {name}")
    return zone


def format_utc(dt: datetime, **options: Unpack[FormatOptions]) -> str:
    """``dt`` in UTC, for the locale (Effect's ``formatUtc``, which puts UTC
    over a ``time_zone``)."""
    return _in(dt, UTC, options)


def format_local(dt: datetime, **options: Unpack[FormatOptions]) -> str:
    """``dt`` in the system's zone (or ``time_zone``) (Effect's ``formatLocal``)."""
    return _in(dt, _zone(options, zone_local()), options)


def format(dt: datetime, **options: Unpack[FormatOptions]) -> str:
    """``dt`` in its own zone (or ``time_zone``) (Effect's ``format``)."""
    own = dt.tzinfo
    return _in(dt, _zone(options, UTC if own is None else own), options)


__all__ = ["FormatOptions", "format", "format_local", "format_utc"]
