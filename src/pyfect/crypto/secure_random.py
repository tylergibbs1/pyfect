"""Cryptographically secure random values as a service (Effect's
``effect/crypto/SecureRandom``)::

    random = yield from SecureRandom()
    token = yield from random.random_bytes(32)
    roll = yield from random.int_between(1, 6)
    uuid = yield from random.uuid_v7()

``make(random_bytes)`` builds the service from a source of random bytes;
every other value is drawn from it. ``int_between`` rejects draws that
would bias the result. ``uuid_v7`` and ``ulid`` read the ``Clock`` and
strictly increase per service, even when the clock moves back.
``layer_web_crypto`` draws from the ``WebCrypto`` reference. Bad sizes and
empty or non-finite ranges are defects, as in Effect.
"""

from __future__ import annotations

import math
import os
import time
from collections.abc import Callable, Iterable
from typing import Literal, overload

from pyfect import _ids
from pyfect._core import Effect
from pyfect.clock import clock_with, now_millis_unsafe
from pyfect.context import Tag
from pyfect.crypto.web_crypto import Crypto, WebCrypto
from pyfect.effect import sync
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect

type UuidFormat = Literal["string", "bytes"]

_MAX_SAFE = 2**53 - 1


def _check_size(size: int) -> None:
    if type(size) is not int or not 0 <= size <= _MAX_SAFE:
        raise ValueError("size must be a non-negative safe integer")


def _read_uint53(data: bytes) -> int:
    return int.from_bytes(bytes([data[0] & 0x1F]) + data[1:7])


def _to_safe_int(bound: float, rounding: Callable[[float], int]) -> int:
    if not math.isfinite(bound):
        raise ValueError("bounds must round to safe integers")
    value = rounding(bound)
    if not -_MAX_SAFE <= value <= _MAX_SAFE:
        raise ValueError("bounds must round to safe integers")
    return value


def int_between_unsafe(low: float, high: float, half_open: bool, draw: Callable[[], bytes]) -> int:
    """An integer from ``ceil(low)`` to ``floor(high)`` (exclusive when
    ``half_open``), by rejection sampling over 53-bit draws (54-bit for
    ranges wider than 2^53), so every integer is equally likely."""
    low_int = _to_safe_int(low, math.ceil)
    high_int = _to_safe_int(high, math.floor)
    count = high_int - low_int + (0 if half_open else 1)
    if count <= 0:
        raise ValueError("range must contain at least one integer")
    if high_int - low_int < _MAX_SAFE:
        if count == 1:
            return low_int
        bucket = (2**53 - 2**53 % count) // count
        limit = bucket * count
        while True:
            value = _read_uint53(draw())
            if value < limit:
                return low_int + value // bucket
    wide = count > 2**53
    bucket = (2**54 if wide else 2**53) // count
    limit = bucket * count
    while True:
        data = draw()
        value = _read_uint53(data) + (2**53 if wide and data[0] & 0x20 else 0)
        if value < limit:
            return low_int + value // bucket


class SecureRandomService:
    """Secure random values drawn from one source of bytes; build it with
    ``make``."""

    __slots__ = ("_random_bytes", "_ulid", "_uuid_v7")

    def __init__(self, random_bytes: Callable[[int], bytes]) -> None:
        self._random_bytes = random_bytes
        self._uuid_v7 = _ids.make_v7_monotonic()
        self._ulid = _ids.make_ulid_monotonic()

    def _draw(self) -> bytes:
        return self._random_bytes(7)

    def random_bytes(self, size: int) -> Effect[bytes]:
        """``size`` random bytes; a size that is not a non-negative safe
        integer is a defect."""

        def go() -> bytes:
            _check_size(size)
            return bytes(self._random_bytes(size))

        return sync(go)

    def int_between(self, low: float, high: float, *, half_open: bool = False) -> Effect[int]:
        """A uniformly random integer from ``ceil(low)`` to ``floor(high)``,
        inclusive unless ``half_open``. An empty range, or bounds that are not
        finite or safe integers, is a defect."""
        return sync(lambda: int_between_unsafe(low, high, half_open, self._draw))

    def shuffle[A](self, elements: Iterable[A]) -> Effect[list[A]]:
        """A uniformly shuffled copy of ``elements``."""

        def go() -> list[A]:
            buffer = list(elements)
            for i in range(len(buffer) - 1, 0, -1):
                index = int_between_unsafe(0, i, False, self._draw)
                buffer[i], buffer[index] = buffer[index], buffer[i]
            return buffer

        return sync(go)

    @overload
    def uuid_v4(self, *, format: Literal["string"] = "string") -> Effect[str]: ...
    @overload
    def uuid_v4(self, *, format: Literal["bytes"]) -> Effect[bytes]: ...
    def uuid_v4(self, *, format: UuidFormat = "string") -> Effect[str] | Effect[bytes]:
        """A UUIDv4: the lowercase hyphenated text, or its 16 bytes."""
        return sync(lambda: _formatted(_ids.v4_bytes(self._random_bytes(16)), format))  # pyright: ignore[reportReturnType]

    @overload
    def uuid_v7(self, *, format: Literal["string"] = "string") -> Effect[str]: ...
    @overload
    def uuid_v7(self, *, format: Literal["bytes"]) -> Effect[bytes]: ...
    def uuid_v7(self, *, format: UuidFormat = "string") -> Effect[str] | Effect[bytes]:
        """A UUIDv7 holding the ``Clock``'s time in milliseconds; strictly
        increasing per service."""
        return clock_with(  # pyright: ignore[reportReturnType]
            lambda clock: sync(
                lambda: _formatted(
                    self._uuid_v7(now_millis_unsafe(clock), self._random_bytes(16)),
                    format,
                )
            )
        )

    @property
    def ulid(self) -> Effect[str]:
        """A ULID: the ``Clock``'s time in milliseconds, then 80 random bits;
        strictly increasing per service."""
        return clock_with(
            lambda clock: sync(
                lambda: self._ulid(now_millis_unsafe(clock), lambda: bytes(self._random_bytes(10)))
            )
        )


def _formatted(data: bytearray, format: UuidFormat) -> str | bytes:
    return bytes(data) if format == "bytes" else _ids.stringify(data)


class SecureRandom(Tag[SecureRandomService], key="effect/crypto/SecureRandom"):
    """Secure random values."""


def make(random_bytes: Callable[[int], bytes]) -> SecureRandomService:
    """A ``SecureRandom`` drawing every value from ``random_bytes(size)``."""
    return SecureRandomService(random_bytes)


def fill_random(crypto: Crypto, size: int) -> bytes:
    """``size`` bytes from ``crypto.get_random_values``, 64 KiB at a time
    (Web Crypto refuses more per call)."""
    buffer = bytearray(size)
    with memoryview(buffer) as view:
        for offset in range(0, size, 65_536):
            with view[offset : offset + 65_536] as chunk:
                crypto.get_random_values(chunk)
    return bytes(buffer)


layer_web_crypto: Layer[SecureRandom] = layer_effect(
    SecureRandom, WebCrypto().map(lambda crypto: make(lambda size: fill_random(crypto, size)))
)
"""Random bytes from the ``WebCrypto`` reference."""


def random_bytes_unsafe(size: int) -> bytes:
    """``size`` random bytes from the host, outside any effect."""
    _check_size(size)
    return os.urandom(size)


@overload
def uuid_v4_unsafe(*, format: Literal["string"] = "string") -> str: ...
@overload
def uuid_v4_unsafe(*, format: Literal["bytes"]) -> bytes: ...
def uuid_v4_unsafe(*, format: UuidFormat = "string") -> str | bytes:
    """A UUIDv4 from the host's random bytes."""
    return _formatted(_ids.v4_bytes(os.urandom(16)), format)


@overload
def uuid_v7_unsafe(*, format: Literal["string"] = "string") -> str: ...
@overload
def uuid_v7_unsafe(*, format: Literal["bytes"]) -> bytes: ...
def uuid_v7_unsafe(*, format: UuidFormat = "string") -> str | bytes:
    """A UUIDv7 from the system time and the host's random bytes; strictly
    increasing across every ``*_unsafe`` call in the process."""
    return _formatted(_ids.v7_monotonic(time.time() * 1000, os.urandom(16)), format)


def ulid_unsafe() -> str:
    """A ULID from the system time and the host's random bytes; strictly
    increasing across the process."""
    return _ids.ulid_monotonic(time.time() * 1000, lambda: os.urandom(10))


__all__ = [
    "SecureRandom",
    "SecureRandomService",
    "UuidFormat",
    "fill_random",
    "int_between_unsafe",
    "layer_web_crypto",
    "make",
    "random_bytes_unsafe",
    "ulid_unsafe",
    "uuid_v4_unsafe",
    "uuid_v7_unsafe",
]
