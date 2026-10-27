"""RFC 9557 strings (``2024-07-21T20:12:34+12:00[Pacific/Auckland]``):
ISO 8601 plus the zone's name, which ``isoformat`` / ``fromisoformat``
leave out."""

from __future__ import annotations

import re
from datetime import UTC, datetime, tzinfo
from zoneinfo import ZoneInfo

from pyfect.date_time._zones import parse_offset, zone_from_string, zone_of, zone_offset

_ZONED = re.compile(r"^(.{17,35})\[(.+)\]$")


def format_iso(dt: datetime) -> str:
    """``dt`` in UTC to the millisecond, as JavaScript's ``toISOString``
    (Effect's ``DateTime.formatIso``): ``2024-01-01T00:00:00.000Z``."""
    utc = dt.astimezone(UTC)
    return utc.strftime("%Y-%m-%dT%H:%M:%S.") + f"{utc.microsecond // 1000:03d}Z"


def zone_to_string(zone: tzinfo) -> str:
    """A named zone's IANA key, else its offset as ``+03:00`` (Effect's
    ``DateTime.zoneToString``)."""
    if isinstance(zone, ZoneInfo):
        return zone.key
    offset = zone.utcoffset(None)
    if offset is None:
        return str(zone)
    sign = "-" if offset.total_seconds() < 0 else "+"
    minutes = abs(int(offset.total_seconds())) // 60
    return f"{sign}{minutes // 60:02d}:{minutes % 60:02d}"


def format_iso_zoned(dt: datetime) -> str:
    """``dt.isoformat()``, followed by ``[zone]`` when ``dt``'s zone is a
    named ``ZoneInfo``."""
    zone = zone_of(dt, "dt")
    key = zone.key if isinstance(zone, ZoneInfo) else None
    return dt.isoformat() if key is None else f"{dt.isoformat()}[{key}]"


def make_zoned_from_string(text: str) -> datetime | None:
    """Parse ``format_iso_zoned``'s output, or an ISO string ending in an
    offset (whose zone is then that fixed offset). The instant comes from
    the ISO part (UTC when it has no offset); ``None`` if either part
    does not parse."""
    found = _ZONED.match(text)
    zone: tzinfo | None
    if found is None:
        iso = text
        offset = parse_offset(text)
        zone = None if offset is None else zone_offset(offset)
    else:
        iso, zone = found[1], zone_from_string(found[2])
    instant = _parse_instant(iso)
    return None if zone is None or instant is None else instant.astimezone(zone)


def _parse_instant(iso: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
