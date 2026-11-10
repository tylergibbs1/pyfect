"""Ordered UUIDv7s (Effect's ``internal/uuid.ts`` ``makeV7Monotonic``), RFC 9562 §6.2
Method 1: a 42-bit counter fills the 12 bits of ``rand_a`` and the top 30 bits of
``rand_b``; the last 32 bits stay random. A clock that stalls or moves back keeps the last
timestamp and counts up; a counter that overflows moves the timestamp on by one
millisecond. The ordering ends at the maximum timestamp, 2**48 - 1 ms.
"""

from __future__ import annotations

import threading
from collections.abc import Callable

_MAX_TIMESTAMP = 2**48 - 1
_MAX_COUNTER = 2**42 - 1

type V7Monotonic = Callable[[float, bytes], bytes]
"""Sixteen random bytes and a time in milliseconds to an ordered UUIDv7's bytes."""


def _clamp(millis: float) -> int:
    return min(int(millis), _MAX_TIMESTAMP) if millis >= 0 else 0


def _seed(data: bytes) -> int:
    """The counter from random bytes, its top bit clear, so a millisecond has at least
    2**41 increments before it overflows."""
    high = ((data[6] & 0x07) << 8) | data[7]
    low = ((data[8] & 0x3F) << 24) | (data[9] << 16) | (data[10] << 8) | data[11]
    return high * 2**30 + low


def make_v7_monotonic() -> V7Monotonic:
    """A generator of UUIDv7s that sort in the order it makes them (thread-safe)."""
    lock = threading.Lock()
    last_timestamp = -1
    counter = 0

    def next_bytes(millis: float, data: bytes) -> bytes:
        nonlocal last_timestamp, counter
        timestamp = _clamp(millis)
        with lock:
            if timestamp > last_timestamp:
                last_timestamp = timestamp
                counter = _seed(data)
            elif counter < _MAX_COUNTER:
                counter += 1
            else:
                last_timestamp = min(last_timestamp + 1, _MAX_TIMESTAMP)
                counter = _seed(data)
            stamp, count = last_timestamp, counter
        out = bytearray(data[:16])
        out[0:6] = stamp.to_bytes(6)
        high, low = divmod(count, 2**30)
        out[6] = 0x70 | (high >> 8)
        out[7] = high & 0xFF
        out[8] = 0x80 | (low >> 24)
        out[9] = (low >> 16) & 0xFF
        out[10] = (low >> 8) & 0xFF
        out[11] = low & 0xFF
        return bytes(out)

    return next_bytes


v7_monotonic: V7Monotonic = make_v7_monotonic()
"""The ordering shared by every caller in the process (Effect's realm-wide ``v7Monotonic``)."""
