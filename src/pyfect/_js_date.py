"""Dates as JavaScript's ``Date`` reads them from the ECMAScript date-time
string format: every Effect API that parses with ``new Date(text)`` (the
CLI's ``Date`` primitive, ``DateTime.makeZonedFromString``) parses here,
never with ``datetime.fromisoformat``, which takes and rejects different
text (``tests/test_js_date_guard.py``).

``YYYY``, ``YYYY-MM`` or ``YYYY-MM-DD`` (or a signed six-digit year), then
optionally ``THH:mm``, ``:ss`` and a fraction, then ``Z`` or an offset. A
date alone is midnight UTC; a date-time without an offset is local time.
V8 also takes a space for ``T``, lowercase ``t`` / ``z``, ``+HHmm``
offsets, a ``Z`` after a date alone, and any day up to 31 (``02-30`` is
March 1st), so these are read too. Its other, implementation-defined
formats (``Jan 15 2024``) are not.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, timezone

_FORMAT = re.compile(
    r"(?P<year>[0-9]{4}|[+-][0-9]{6})(?:-(?P<month>[0-9]{2})(?:-(?P<day>[0-9]{2}))?)?"
    r"(?:[Tt ](?P<hour>[0-9]{2}):(?P<minute>[0-9]{2})"
    r"(?::(?P<second>[0-9]{2})(?:\.(?P<fraction>[0-9]+))?)?"
    r"(?P<zone>[Zz]|[+-][0-9]{2}:?[0-9]{2})?|[Zz])?"
)


def _offset(zone: str) -> timezone | None:
    """``Z`` / ``±HH:mm`` / ``±HHmm`` as a fixed offset; ``None`` when out of range."""
    if zone in ("Z", "z"):
        return UTC
    digits = zone[1:].replace(":", "")
    hours, minutes = int(digits[:2]), int(digits[2:])
    if hours > 23 or minutes > 59:
        return None
    delta = timedelta(hours=hours, minutes=minutes)
    return timezone(-delta if zone[0] == "-" else delta)


_HAS_ZONE = re.compile(r"Z|GMT|[+-][0-9]{2}$|[+-][0-9]{2}:?[0-9]{2}$|\]$")
_ENDS_IN_ZONE = re.compile(r"(?:z|gmt)$", re.IGNORECASE)


def parse_input(text: str) -> datetime | None:
    """A ``DateTime.Input`` string, as Effect's ``DateTime.makeUnsafe``
    reads it: ``parse``, with a ``Z`` added when ``text`` names no zone,
    so a date-time without an offset is UTC rather than local time."""
    has_zone = _HAS_ZONE.search(text) is not None or _ENDS_IN_ZONE.search(text) is not None
    return parse(text if has_zone else text + "Z")


def parse(text: str) -> datetime | None:
    """``text`` as an aware ``datetime``, or ``None`` when JavaScript's
    ``Date`` would be invalid (or the year is outside 1 to 9999)."""
    match = _FORMAT.fullmatch(text)
    if match is None or match["year"] == "-000000":
        return None
    hour = int(match["hour"] or 0)
    minute = int(match["minute"] or 0)
    second = int(match["second"] or 0)
    micro = int((match["fraction"] or "0")[:6].ljust(6, "0"))
    end_of_day = hour == 24 and minute == second == micro == 0
    zone = match["zone"]
    tz = UTC if match["hour"] is None else (None if zone is None else _offset(zone))
    if zone is not None and tz is None:
        return None
    day = int(match["day"] or 1)
    if not 1 <= day <= 31:
        return None
    try:
        parsed = datetime(
            int(match["year"]),
            int(match["month"] or 1),
            1,
            0 if end_of_day else hour,
            minute,
            second,
            micro,
            tzinfo=tz,
        ) + timedelta(days=day - 1 + end_of_day)
    except (ValueError, OverflowError):
        return None
    return parsed if parsed.tzinfo is not None else parsed.astimezone()
