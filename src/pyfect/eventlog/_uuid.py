"""UUID bytes for entry and remote ids (Effect's ``internal/uuid.ts``)."""

from __future__ import annotations

import math

_SEGMENTS = ((0, 4), (4, 6), (6, 8), (8, 10), (10, 16))


_MAX_V7_TIMESTAMP = 2**48 - 1


def v7_bytes(millis: float, random: bytes) -> bytearray:
    """A version 7 UUID's bytes for ``millis`` (truncated and clamped to its
    48-bit timestamp, as Effect's), the rest from the 16 bytes ``random``,
    as a ``bytearray`` the caller may still adjust."""
    timestamp = min(max(0, math.trunc(millis)), _MAX_V7_TIMESTAMP)
    raw = bytearray(timestamp.to_bytes(6) + random[6:])
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return raw


def stringify(data: bytes) -> str:
    """The hyphenated hex form, segment by segment, so an id of any length
    formats as Effect's formatter does."""
    return "-".join(data[start:end].hex() for start, end in _SEGMENTS)


__all__ = ["stringify", "v7_bytes"]
