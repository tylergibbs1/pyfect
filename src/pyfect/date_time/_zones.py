"""Time zones: a named zone is a ``ZoneInfo``, a fixed offset a
``datetime.timezone``. Turning a wall-clock time into an instant is where
``zoneinfo`` is easy to misuse (``fold`` means opposite things in gaps and
overlaps), so ``make_zoned`` does it with Effect's disambiguation names."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from typing import Literal, overload
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

type Disambiguation = Literal["compatible", "earlier", "later", "reject"]
"""How ``make_zoned`` resolves a wall-clock time that a DST change skips
(a gap) or repeats (an overlap). ``compatible`` takes the later instant
in a gap and the earlier one in an overlap; ``earlier`` / ``later`` take
that instant in both; ``reject`` gives ``None`` in both."""


def zone_of(value: datetime, name: str) -> tzinfo:
    """``value``'s zone; a naive datetime is a ``ValueError``."""
    zone = value.tzinfo
    if zone is None or value.utcoffset() is None:
        raise ValueError(f"{name} must be an aware datetime (with tzinfo), got {value!r}")
    return zone


@overload
def make_zoned(
    wall: datetime,
    zone: tzinfo,
    *,
    disambiguation: Literal["compatible", "earlier", "later"] = "compatible",
) -> datetime: ...
@overload
def make_zoned(
    wall: datetime, zone: tzinfo, *, disambiguation: Disambiguation
) -> datetime | None: ...
def make_zoned(
    wall: datetime, zone: tzinfo, *, disambiguation: Disambiguation = "compatible"
) -> datetime | None:
    """The instant whose wall-clock time in ``zone`` is ``wall`` (a naive
    datetime), expressed in ``zone``. ``None`` only for a gap or an
    overlap under ``disambiguation="reject"``."""
    if wall.tzinfo is not None:
        raise ValueError(f"wall must be a naive datetime (a wall-clock time), got {wall!r}")
    first = wall.replace(tzinfo=zone, fold=0).astimezone(UTC)
    second = wall.replace(tzinfo=zone, fold=1).astimezone(UTC)
    if first == second:
        return first.astimezone(zone)
    if disambiguation == "reject":
        return None
    # PEP 495: in an overlap fold=0 is the earlier instant; in a gap fold=0
    # reads the wall time with the offset from before the gap, which gives
    # the later instant.
    earlier, later = sorted((first, second))
    if disambiguation == "earlier":
        return earlier.astimezone(zone)
    if disambiguation == "later":
        return later.astimezone(zone)
    in_gap = first.astimezone(zone).replace(tzinfo=None) != wall
    return (later if in_gap else earlier).astimezone(zone)


def zone_named(zone_id: str) -> ZoneInfo | None:
    """The IANA zone ``zone_id``, or ``None`` if there is no such zone."""
    try:
        return ZoneInfo(zone_id)
    except (ZoneInfoNotFoundError, ValueError):
        return None


def zone_offset(offset: timedelta) -> timezone | None:
    """A fixed offset from UTC, or ``None`` outside ``timezone``'s range
    (strictly within a day)."""
    try:
        return timezone(offset)
    except ValueError:
        return None


_OFFSET_ZONE = re.compile(r"^(?:GMT)?[+-]")
_OFFSET = re.compile(r"([+-])(\d{2}):?(\d{2})$")


def parse_offset(text: str) -> timedelta | None:
    """The ``±HH:MM`` or ``±HHMM`` offset ending ``text``."""
    found = _OFFSET.search(text)
    if found is None:
        return None
    sign, hours, minutes = found.groups()
    size = timedelta(hours=int(hours), minutes=int(minutes))
    return size if sign == "+" else -size


def zone_from_string(text: str) -> tzinfo | None:
    """A zone from an offset (``+05:30``, ``-0530``, ``GMT+05:30``) or an
    IANA name (``Europe/London``, ``GMT``)."""
    if _OFFSET_ZONE.match(text):
        offset = parse_offset(text)
        return None if offset is None else zone_offset(offset)
    return zone_named(text)


_LOCALTIME = "/etc/localtime"


def zone_local() -> tzinfo:
    """The system's zone: ``$TZ``, else ``/etc/localtime`` (named when it
    links into a zoneinfo tree), else the current fixed offset."""
    for key in (os.environ.get("TZ", "").removeprefix(":"), _localtime_key()):
        zone = zone_named(key) if key else None
        if zone is not None:
            return zone
    try:
        with open(_LOCALTIME, "rb") as file:
            return ZoneInfo.from_file(file)
    except (OSError, ValueError):
        return datetime.now().astimezone().tzinfo or UTC


def _localtime_key() -> str:
    try:
        return os.readlink(_LOCALTIME).partition("zoneinfo/")[2]
    except OSError:
        return ""
