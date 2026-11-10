"""UUIDs and ULIDs from random bytes (Effect's ``internal/uuid.ts`` and
``internal/ulid.ts``). The monotonic generators keep their ids strictly
increasing below the 48-bit timestamp limit, also within one millisecond
and when the clock moves back; each holds a lock, since fibers may run on
several threads."""

from __future__ import annotations

import math
import threading
from collections.abc import Callable

_MAX_TIMESTAMP = 2**48 - 1
_MAX_V7_COUNTER = 2**42 - 1
_BASE32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"
_SEGMENTS = ((0, 4), (4, 6), (6, 8), (8, 10), (10, 16))


def stringify(data: bytes | bytearray) -> str:
    """The hyphenated lowercase hex form, segment by segment."""
    return "-".join(bytes(data[start:end]).hex() for start, end in _SEGMENTS)


def v4_bytes(data: bytes | bytearray) -> bytearray:
    """``data`` (16 random bytes) with the version 4 and variant bits set."""
    out = bytearray(data)
    out[6] = (out[6] & 0x0F) | 0x40
    out[8] = (out[8] & 0x3F) | 0x80
    return out


def _clamp(timestamp_millis: float) -> int:
    if math.isnan(timestamp_millis) or timestamp_millis < 0:
        return 0
    return min(math.trunc(timestamp_millis), _MAX_TIMESTAMP)


def v7_bytes(timestamp_millis: float, data: bytes | bytearray) -> bytearray:
    """``data`` (16 random bytes) with the timestamp (clamped to 48 bits) in
    the first six and the version 7 and variant bits set."""
    out = bytearray(data)
    out[:6] = _clamp(timestamp_millis).to_bytes(6)
    out[6] = (out[6] & 0x0F) | 0x70
    out[8] = (out[8] & 0x3F) | 0x80
    return out


def _seed_v7_counter(data: bytearray) -> int:
    # Clears the counter's top bit, so a millisecond has at least 2^41
    # increments before it overflows.
    high = ((data[6] & 0x07) << 8) | data[7]
    low = ((data[8] & 0x3F) << 24) | (data[9] << 16) | (data[10] << 8) | data[11]
    return high * 2**30 + low


def make_v7_monotonic() -> Callable[[float, bytes | bytearray], bytearray]:
    """A UUIDv7 generator whose ids strictly increase: a 42-bit counter
    follows the timestamp, seeded from the random bytes each new millisecond."""
    lock = threading.Lock()
    last_timestamp = -1
    counter = 0

    def next_v7(timestamp_millis: float, data: bytes | bytearray) -> bytearray:
        nonlocal last_timestamp, counter
        out = bytearray(data)
        timestamp = _clamp(timestamp_millis)
        with lock:
            if timestamp > last_timestamp:
                last_timestamp = timestamp
                counter = _seed_v7_counter(out)
            elif counter < _MAX_V7_COUNTER:
                # The clock stalled or moved back, so keep the last timestamp.
                counter += 1
            else:
                last_timestamp = min(last_timestamp + 1, _MAX_TIMESTAMP)
                counter = _seed_v7_counter(out)
            stamp, value = last_timestamp, counter
        out = v7_bytes(stamp, out)
        high, low = divmod(value, 2**30)
        out[6] = 0x70 | (high >> 8)
        out[7] = high & 0xFF
        out[8] = 0x80 | (low >> 24)
        out[9] = (low >> 16) & 0xFF
        out[10] = (low >> 8) & 0xFF
        out[11] = low & 0xFF
        return out

    return next_v7


v7_monotonic = make_v7_monotonic()
"""The generator shared by the ``*_unsafe`` functions and model defaults."""


def ulid_string(timestamp_millis: float, data: bytes | bytearray) -> str:
    """A ULID from a millisecond timestamp (clamped to 48 bits) and 10
    random bytes."""
    if len(data) != 10:
        raise ValueError(f"ULID randomness must be exactly 10 bytes, received {len(data)}")
    timestamp = _clamp(timestamp_millis)
    head = "".join(_BASE32[(timestamp >> shift) & 0x1F] for shift in range(45, -1, -5))
    bits = int.from_bytes(data)
    tail = "".join(_BASE32[(bits >> shift) & 0x1F] for shift in range(75, -1, -5))
    return head + tail


def make_ulid_monotonic() -> Callable[[float, Callable[[], bytes]], str]:
    """A ULID generator whose ids strictly increase: within a millisecond
    the random part counts up; when it overflows, the timestamp advances."""
    lock = threading.Lock()
    last_timestamp = -1
    random = 0

    def next_ulid(timestamp_millis: float, random_bytes: Callable[[], bytes]) -> str:
        nonlocal last_timestamp, random
        timestamp = _clamp(timestamp_millis)
        with lock:
            if timestamp > last_timestamp:
                last_timestamp = timestamp
                random = int.from_bytes(random_bytes())
            elif random < 2**80 - 1:
                random += 1
            else:
                last_timestamp = min(last_timestamp + 1, _MAX_TIMESTAMP)
                random = int.from_bytes(random_bytes())
            stamp, value = last_timestamp, random
        return ulid_string(stamp, value.to_bytes(10))

    return next_ulid


ulid_monotonic = make_ulid_monotonic()
"""The generator shared by ``secure_random.ulid_unsafe``."""
