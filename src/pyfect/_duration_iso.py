"""ISO 8601 durations as whole nanoseconds (Effect's ``Duration.fromIso`` / ``formatIso``).

A day is 24 hours and a week 7 days; years and months, which have no fixed length, are
rejected, as are fractional weeks and days and a fraction on any but the last time
component. Formatting balances into days, hours, minutes and seconds with up to nine
fractional digits and never writes weeks.
"""

from __future__ import annotations

import re

_PATTERN = re.compile(
    r"([+-])?P(?!\Z)(?:(\d+)W)?(?:(\d+)D)?"
    r"(?:T(?!\Z)(?:(\d+)(?:[.,](\d{1,9}))?H)?(?:(\d+)(?:[.,](\d{1,9}))?M)?"
    r"(?:(\d+)(?:[.,](\d{1,9}))?S)?)?\Z",
    re.ASCII,
)
_SECOND = 1_000_000_000
_MINUTE = 60 * _SECOND
_HOUR = 60 * _MINUTE
_DAY = 24 * _HOUR
_WEEK = 7 * _DAY


def _component(whole: str | None, fraction: str | None, scale: int) -> int:
    """``scale`` is the nanoseconds in one unit."""
    value = 0 if whole is None else int(whole) * scale
    return value if fraction is None else value + int(fraction.ljust(9, "0")) * (scale // _SECOND)


def parse_iso_nanos(text: str) -> int | None:
    """The nanoseconds an ISO 8601 duration denotes, or ``None`` if it is not one."""
    match = _PATTERN.match(text)
    if match is None:
        return None
    sign, w, d, h, hf, m, mf, s, sf = match.groups()
    if (hf is not None and (m is not None or s is not None)) or (mf is not None and s is not None):
        return None
    total = (
        _component(w, None, _WEEK)
        + _component(d, None, _DAY)
        + _component(h, hf, _HOUR)
        + _component(m, mf, _MINUTE)
        + _component(s, sf, _SECOND)
    )
    return -total if sign == "-" else total


def format_iso_nanos(nanos: int) -> str:
    """``nanos`` as an ISO 8601 duration: ``PT0S`` for zero, ``-`` before a negative one."""
    a = abs(nanos)
    days, rest = divmod(a, _DAY)
    hours, rest = divmod(rest, _HOUR)
    minutes, rest = divmod(rest, _MINUTE)
    seconds, fraction = divmod(rest, _SECOND)
    time = ""
    if hours:
        time += f"{hours}H"
    if minutes:
        time += f"{minutes}M"
    if fraction:
        time += f"{seconds}.{str(fraction).rjust(9, '0').rstrip('0')}S"
    elif seconds:
        time += f"{seconds}S"
    out = "-P" if nanos < 0 else "P"
    if days:
        out += f"{days}D"
    if time:
        out += f"T{time}"
    return "PT0S" if out == "P" else out
