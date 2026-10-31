"""RFC 9557 strings (``2024-07-21T20:12:34+12:00[Pacific/Auckland]``):
ISO 8601 plus the zone's name, which ``isoformat`` / ``fromisoformat``
leave out."""

from __future__ import annotations

import re
from datetime import UTC, datetime, timedelta, tzinfo
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
    """Effect's ``DateTime.formatIsoZoned``: ``dt``'s wall clock to the
    millisecond, its offset to the minute (``+05:30``), then ``[zone]``
    when the zone is a named ``ZoneInfo``:
    ``2024-07-21T20:12:34.000+12:00[Pacific/Auckland]``."""
    zone = zone_of(dt, "dt")
    offset = dt.utcoffset() or timedelta(0)
    wall = dt.replace(tzinfo=None).isoformat(timespec="milliseconds")
    text = wall + _offset_text(offset // timedelta(milliseconds=1))
    return f"{text}[{zone.key}]" if isinstance(zone, ZoneInfo) else text


def _offset_text(millis: int) -> str:
    # Effect's ``offsetToString``: whole minutes, rounded half up.
    hours, rest = divmod(abs(millis), 3_600_000)
    minutes = (rest + 30_000) // 60_000
    if minutes == 60:
        hours, minutes = hours + 1, 0
    return f"{'-' if millis < 0 else '+'}{hours:02d}:{minutes:02d}"


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
    if zone is None or instant is None:
        return None
    exact = _exact_wall_clock(instant, zone)
    return exact if exact is not None else instant.astimezone(zone)


def _exact_wall_clock(written: datetime, zone: tzinfo) -> datetime | None:
    """The instant a named zone puts at ``written``'s wall clock, when the
    zone's offset there rounds to the written one: ``format_iso_zoned``
    writes whole minutes, so a historical offset with seconds
    (``+05:21:10``) reads back exactly."""
    offset = written.utcoffset()
    if not isinstance(zone, ZoneInfo) or offset is None:
        return None
    text = _offset_text(offset // timedelta(milliseconds=1))
    for fold in (0, 1):
        local = written.replace(tzinfo=zone, fold=fold)
        local_offset = local.utcoffset() or timedelta(0)
        if _offset_text(local_offset // timedelta(milliseconds=1)) == text:
            return local
    return None


def _parse_instant(iso: str) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(iso)
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
