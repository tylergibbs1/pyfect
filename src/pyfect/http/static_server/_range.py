"""``Range: bytes=...`` headers (one range; several are served whole)."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Literal

_DIGITS = re.compile(r"\d+\Z", re.ASCII)


@dataclass(frozen=True, slots=True)
class ByteRange:
    """The inclusive byte range ``start``..``end``."""

    start: int
    end: int


def _integer(value: str) -> int | None:
    return int(value) if _DIGITS.match(value) else None


def parse_range(header: str, file_size: int) -> ByteRange | Literal["unsatisfiable"] | None:  # noqa: PLR0911
    """The range ``header`` asks for of a ``file_size``-byte file; ``None``
    when the header is not one byte range (the file is served whole)."""
    value = header.strip()
    if not value.lower().startswith("bytes="):
        return None
    range_value = value[6:].strip()
    if range_value == "" or "," in range_value or "-" not in range_value:
        return None
    start_part, _, end_part = range_value.partition("-")
    start_part, end_part = start_part.strip(), end_part.strip()
    if start_part == "" and end_part == "":
        return None
    if start_part == "":
        suffix = _integer(end_part)
        if suffix is None:
            return None
        if suffix == 0 or file_size == 0:
            return "unsatisfiable"
        return ByteRange(max(file_size - suffix, 0), file_size - 1)
    start = _integer(start_part)
    if start is None:
        return None
    if end_part == "":
        return "unsatisfiable" if start >= file_size else ByteRange(start, file_size - 1)
    end = _integer(end_part)
    if end is None:
        return None
    if start > end or start >= file_size:
        return "unsatisfiable"
    return ByteRange(start, min(end, file_size - 1))
