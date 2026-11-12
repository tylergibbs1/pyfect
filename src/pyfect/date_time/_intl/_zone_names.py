"""ICU's ``TimeZoneFormat`` for the specific names (``z``, ``zzzz``): the
zone's own name or its metazone's at that instant, else the localized GMT
offset (``tzfmt.cpp``, ``tznames_impl.cpp``)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from pyfect.date_time._intl._data import LocaleData, meta


@dataclass(frozen=True, slots=True)
class ZoneAt:
    """A zone at an instant: CLDR's id for it (``None`` for an offset zone,
    which has no names), the offset in seconds, and whether it is DST."""

    cldr_id: str | None
    offset: int
    daylight: bool


def _metazone(cldr_id: str, instant: datetime) -> str | None:
    stamp = (
        f"{instant.year:04d}-{instant.month:02d}-{instant.day:02d} "
        f"{instant.hour:02d}:{instant.minute:02d}"
    )
    for name, start, end in meta().metazones.get(cldr_id, ()):
        if start <= stamp < end:
            return name
    return None


def _name(data: LocaleData, zone: ZoneAt, width: str, instant: datetime) -> str:
    if zone.cldr_id is None:
        return ""
    kind = "daylight" if zone.daylight else "standard"
    own = data.zones.get(zone.cldr_id, {}).get(width, {}).get(kind)
    if own:
        return own
    metazone = _metazone(zone.cldr_id, instant)
    if metazone is None:
        return ""
    return data.metazones.get(metazone, {}).get(width, {}).get(kind, "")


def _unquote(text: str) -> str:
    out: list[str] = []
    previous_quote = False
    for char in text:
        if char == "'":
            if previous_quote:
                out.append(char)
                previous_quote = False
            else:
                previous_quote = True
        else:
            previous_quote = False
            out.append(char)
    return "".join(out)


def _offset_patterns(hour_format: str) -> tuple[dict[str, str], dict[str, str]]:
    """The positive and negative ``H``, ``HM`` and ``HMS`` offset patterns."""
    found: list[dict[str, str]] = []
    for hm in hour_format.split(";", 1):
        at_mm = hm.find("mm")
        before = hm[:at_mm]
        at_h = before.rfind("H")
        separator = before[at_h + 1 :] if at_h >= 0 else ""
        hms = hm[: at_mm + 2] + separator + "ss" + hm[at_mm + 2 :]
        at_hh = before.rfind("HH")
        h = hm[: at_hh + 2] if at_hh >= 0 else hm[: at_h + 1]
        found.append({"H": h, "HM": hm, "HMS": hms})
    return found[0], found[1]


def localized_gmt(data: LocaleData, digits: str, offset: int, *, short: bool) -> str:
    """``formatOffsetLocalizedGMT``: ``GMT+1`` (short), ``GMT+01:00`` (long)."""
    gmt = data.zone_formats.get("gmtFormat", "GMT{0}")
    at = gmt.find("{0}")
    prefix, suffix = _unquote(gmt[:at]), _unquote(gmt[at + 3 :])
    hour_format = data.zone_formats.get("hourFormat", "+H:mm;-H:mm")
    if ";" not in hour_format or "mm" not in hour_format:
        hour_format = "+H:mm;-H:mm"
    positive, negative = _offset_patterns(hour_format)
    patterns = positive if offset >= 0 else negative
    magnitude = abs(offset)
    hours, minutes, seconds = magnitude // 3600, magnitude // 60 % 60, magnitude % 60
    if seconds:
        pattern = patterns["HMS"]
    elif minutes or not short:
        pattern = patterns["HM"]
    else:
        pattern = patterns["H"]

    def number(value: int, width: int) -> str:
        return "".join(digits[int(d)] for d in str(value).rjust(width, "0"))

    out: list[str] = []
    index = 0
    in_quote = False
    while index < len(pattern):
        char = pattern[index]
        end = index + 1
        while end < len(pattern) and pattern[end] == char and char in "Hms":
            end += 1
        if char == "'":
            in_quote = not in_quote
        elif in_quote or char not in "Hms":
            out.append(char)
        elif char == "H":
            out.append(number(hours, 1 if short else 2))
        elif char == "m":
            out.append(number(minutes, 2))
        else:
            out.append(number(seconds, 2))
        index = end
    return prefix + "".join(out) + suffix


def specific(data: LocaleData, digits: str, zone: ZoneAt, instant: datetime, *, long: bool) -> str:
    """``z`` (short) or ``zzzz`` (long) for ``zone`` at ``instant`` (UTC)."""
    name = _name(data, zone, "long" if long else "short", instant)
    return name or localized_gmt(data, digits, zone.offset, short=not long)
