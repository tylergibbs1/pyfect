"""Time zones: a named zone is a ``ZoneInfo``, a fixed offset a
``datetime.timezone``. Turning a wall-clock time into an instant is where
``zoneinfo`` is easy to misuse (``fold`` means opposite things in gaps and
overlaps), so ``make_zoned`` does it with Effect's disambiguation names."""

from __future__ import annotations

import base64
import contextlib
import io
import os
import re
import struct
import zoneinfo
from collections.abc import Callable
from datetime import UTC, datetime, timedelta, timezone, tzinfo
from functools import cache
from importlib import resources
from pathlib import Path
from typing import Literal, overload
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from pyfect import _stable_cache
from pyfect.date_time._icu_zones import CANONICAL, DATA, TZIF

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
    """The zone ``zone_id`` names, keeping the id as given (an alias such as
    ``Europe/Kyiv`` or ``Asia/Kolkata`` included), as Effect 4.1.4 does. Only
    the casing comes from the canonical id ``Intl`` gives it in Node (ICU's,
    ``_icu_zones.ICU_VERSION``), and only when the two differ in case alone
    (``europe/london`` is ``Europe/London``). Zones compare equal and hash
    alike when ICU resolves them to the same id (``Europe/Kyiv`` and
    ``Europe/Kiev``). An offset id (``+0530``) is the fixed zone ``+05:30``.
    ``None`` for an id ICU doesn't know."""
    offset = _OFFSET_ID.fullmatch(zone_id)
    if offset is not None:
        sign, hours, minutes = offset.group(1), int(offset.group(2)), int(offset.group(3) or 0)
        total = (hours * 60 + minutes) * (-1 if sign in "-\u2212" else 1)
        return _offset_zone(total)
    canonical = _canonical_ids().get(zone_id.lower())
    if canonical is None:
        return None
    if canonical.lower() == zone_id.lower():
        return _zone(canonical)
    return _alias_zone(zone_id, canonical)


def resolved_zone_id(zone: ZoneInfo) -> str:
    """The id ICU resolves ``zone``'s to (Effect's ``resolvedId``), which equality uses."""
    return zone.resolved_id if isinstance(zone, _AliasZone) else zone.key


# An offset time zone as ECMA-402 reads one (``±HH``, ``±HHMM``, ``±HH:MM``).
_OFFSET_ID = re.compile(r"([+\-\u2212])([01][0-9]|2[0-3])(?::?([0-5][0-9]))?", re.ASCII)


@_stable_cache.stable_cache
def _offset_zone(minutes: int) -> ZoneInfo:
    """The fixed zone ``Intl`` names ``+05:30`` (``-00:00`` is ``+00:00``)."""
    hours, rest = divmod(abs(minutes), 60)
    key = f"{'-' if minutes < 0 else '+'}{hours:02}:{rest:02}"
    name = key.replace(":", "")
    posix = f"<{name}>{'' if minutes < 0 else '-'}{hours}:{rest:02}"
    header = b"TZif2" + bytes(15) + struct.pack(">6l", 0, 0, 0, 0, 1, len(name) + 1)
    ttinfo = struct.pack(">lBB", minutes * 60, 0, 0) + name.encode("ascii") + b"\0"
    tzif = header + ttinfo + header + ttinfo + f"\n{posix}\n".encode("ascii")
    return _IcuZone.from_file(io.BytesIO(tzif), key=key)


class _IcuZone(ZoneInfo):
    """A zone under a canonical id ``zoneinfo`` has no file for, read from
    another id's file or ICU's own data; pickled by its id."""

    def __reduce__(self) -> tuple[Callable[[str], ZoneInfo | None], tuple[str]]:
        return zone_named, (self.key,)


class _AliasZone(_IcuZone):
    """A zone named by an alias of ICU's canonical id: it keeps the alias as its ``key``
    and equals (and hashes as) the canonical zone, as Effect's ``Equal`` and ``Hash``
    use the resolved id."""

    resolved_id: str

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, ZoneInfo):
            return NotImplemented
        return self.resolved_id == resolved_zone_id(other)

    def __hash__(self) -> int:
        return hash(_zone(self.resolved_id))


@_stable_cache.stable_cache
def _alias_zone(key: str, canonical: str) -> ZoneInfo | None:
    data = _zone_data(canonical)
    if data is None:
        return None
    zone = _AliasZone.from_file(io.BytesIO(data), key=key)
    zone.resolved_id = canonical
    return zone


@cache
def _canonical_ids() -> dict[str, str]:
    return {zone_id.lower(): canonical for zone_id, canonical in CANONICAL.items()}


@cache
def _aliases() -> dict[str, list[str]]:
    aliases: dict[str, list[str]] = {}
    for zone_id, canonical in CANONICAL.items():
        aliases.setdefault(canonical, []).append(zone_id)
    return aliases


@_stable_cache.stable_cache
def _zone(canonical: str) -> ZoneInfo | None:
    if canonical not in TZIF:
        with contextlib.suppress(ZoneInfoNotFoundError, ValueError):
            return ZoneInfo(canonical)
    data = _zone_data(canonical)
    return None if data is None else _IcuZone.from_file(io.BytesIO(data), key=canonical)


def _zone_data(canonical: str) -> bytes | None:
    """The TZif bytes of ICU's zone ``canonical``: its own data for a zone tz dropped,
    else the file of the zone ICU reads it from or of any of its ids."""
    if canonical in TZIF:
        return base64.b64decode(TZIF[canonical], validate=True)
    for source in (canonical, DATA.get(canonical, canonical), *_aliases()[canonical]):
        data = _zone_file(source)
        if data is not None:
            return data
    return None


def _zone_file(zone_id: str) -> bytes | None:
    """The TZif bytes ``ZoneInfo(zone_id)`` reads: from ``TZPATH``, else the
    ``tzdata`` package."""
    for directory in zoneinfo.TZPATH:
        with contextlib.suppress(OSError):
            return Path(directory, zone_id).read_bytes()
    with contextlib.suppress(ImportError, OSError):
        return resources.files("tzdata.zoneinfo").joinpath(*zone_id.split("/")).read_bytes()
    return None


def zone_offset(offset: timedelta) -> timezone | None:
    """A fixed offset from UTC, or ``None`` outside ``timezone``'s range
    (strictly within a day)."""
    try:
        return timezone(offset)
    except ValueError:
        return None


_OFFSET_ZONE = re.compile(r"^(?:GMT)?[+-]")
_OFFSET = re.compile(r"([+-])([0-9]{2}):?([0-9]{2})$")


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
    IANA name (``Europe/London``, ``GMT``). An offset of a day or more
    (``+53:00``) is ``None``: Effect's zones take up to ``±99:59``, Python's
    ``tzinfo`` stays within a day."""
    if _OFFSET_ZONE.match(text):
        offset = parse_offset(text)
        return None if offset is None else zone_offset(offset)
    return zone_named(text)


_LOCALTIME = "/etc/localtime"


def zone_local() -> tzinfo:
    """The system's zone: ``$TZ``, else ``/etc/localtime`` (named when it
    links into a zoneinfo tree, under ICU's resolved id), else the current fixed
    offset."""
    for key in (os.environ.get("TZ", "").removeprefix(":"), _localtime_key()):
        zone = zone_named(key) if key else None
        if zone is not None:
            # Effect's local zone is named by Intl's resolved id, not the one TZ gives.
            return _zone(resolved_zone_id(zone)) or zone
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
