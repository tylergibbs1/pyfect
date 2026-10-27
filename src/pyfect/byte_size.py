"""``ByteSize``: an exact, non-negative number of bytes (Effect's ``ByteSize``).

Decimal units (``kB``, ``MB``, ...) are powers of 1,000 and binary units
(``KiB``, ``MiB``, ...) powers of 1,024. ``from_string`` reads Effect's
syntax (``"10 MB"``, ``"1.5KiB"``, ``"3 kilobytes"``) and gives ``None``
unless it is a whole number of bytes.
"""

from __future__ import annotations

import re
from typing import NewType

from pyfect._js import SPACE

ByteSize = NewType("ByteSize", int)

_DECIMAL = ("kB", "kilobyte"), ("MB", "megabyte"), ("GB", "gigabyte"), ("TB", "terabyte")
_DECIMAL_BIG = ("PB", "petabyte"), ("EB", "exabyte"), ("ZB", "zettabyte"), ("YB", "yottabyte")
_DECIMAL_HUGE = ("RB", "ronnabyte"), ("QB", "quettabyte")
_BINARY = ("KiB", "kibibyte"), ("MiB", "mebibyte"), ("GiB", "gibibyte"), ("TiB", "tebibyte")
_BINARY_BIG = ("PiB", "pebibyte"), ("EiB", "exbibyte"), ("ZiB", "zebibyte"), ("YiB", "yobibyte")


def _factors() -> dict[str, int]:
    factors = {"B": 1, "byte": 1, "bytes": 1}
    for base, units in (
        (1000, _DECIMAL + _DECIMAL_BIG + _DECIMAL_HUGE),
        (1024, _BINARY + _BINARY_BIG),
    ):
        for power, (symbol, name) in enumerate(units, start=1):
            for spelling in (symbol, name, name + "s"):
                factors[spelling] = base**power
    return factors


_FACTORS = _factors()
_SYNTAX = re.compile(rf"[{SPACE}]*([0-9]+)(?:\.([0-9]+))?[{SPACE}]*([A-Za-z]+)[{SPACE}]*")


def from_string(text: str) -> ByteSize | None:
    """The size ``text`` spells, or ``None`` when it is not Effect's syntax,
    names no unit, or is not a whole number of bytes."""
    match = _SYNTAX.fullmatch(text)
    if match is None:
        return None
    whole, fraction, unit = match.group(1), match.group(2) or "", match.group(3)
    factor = _FACTORS.get(unit)
    if factor is None:
        return None
    numerator = int(whole + fraction) * factor
    scale = 10 ** len(fraction)
    return ByteSize(numerator // scale) if numerator % scale == 0 else None
