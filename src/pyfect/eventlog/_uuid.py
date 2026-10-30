"""UUID bytes for entry and remote ids (Effect's ``internal/uuid.ts``)."""

from __future__ import annotations

import os

_SEGMENTS = ((0, 4), (4, 6), (6, 8), (8, 10), (10, 16))


def v4_bytes() -> bytes:
    """A random RFC 9562 version 4 UUID's 16 bytes."""
    raw = bytearray(os.urandom(16))
    raw[6] = (raw[6] & 0x0F) | 0x40
    raw[8] = (raw[8] & 0x3F) | 0x80
    return bytes(raw)


def v7_bytes(millis: int) -> bytearray:
    """A version 7 UUID's bytes for ``millis`` (its 48-bit timestamp), the
    rest random, as a ``bytearray`` the caller may still adjust."""
    raw = bytearray(millis.to_bytes(6) + os.urandom(10))
    raw[6] = (raw[6] & 0x0F) | 0x70
    raw[8] = (raw[8] & 0x3F) | 0x80
    return raw


def stringify(data: bytes) -> str:
    """The hyphenated hex form, segment by segment, so an id of any length
    formats as Effect's formatter does."""
    return "-".join(data[start:end].hex() for start, end in _SEGMENTS)


__all__ = ["stringify", "v4_bytes", "v7_bytes"]
