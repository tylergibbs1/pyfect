"""Cryptographically secure random values and message digests as a service
(Effect's ``Crypto``)::

    c = yield from Crypto()
    token = yield from c.random_bytes(32)
    uuid = yield from c.random_uuid_v7()
    digest = yield from c.digest("SHA-256", b"hello")

``make(random_bytes=, digest=)`` builds a service from the two primitives;
every other operation (numbers, shuffles, UUIDv4 / UUIDv7, ULIDs) is
derived from ``random_bytes``, as in Effect. ``layer`` is the host's
(``os.urandom`` and ``hashlib``); ``platform.layer`` includes it.
"""

from __future__ import annotations

import hashlib
import math
import os
from collections.abc import Callable, Iterable
from typing import Literal, overload

from pyfect._core import Effect
from pyfect._isaac import between_of
from pyfect.clock import clock_with, now_millis_unsafe
from pyfect.context import Tag
from pyfect.effect import fail, succeed, sync, try_
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed
from pyfect.platform_error import PlatformError, bad_argument, system_error

type DigestAlgorithm = Literal["SHA-1", "SHA-256", "SHA-384", "SHA-512"]
"""SHA-1 is there for existing protocols; do not use it for new designs."""

type UuidFormat = Literal["hex", "bytes"]

_MAX_SAFE = 2**53 - 1
_MAX_TIMESTAMP = 2**48 - 1


class CryptoService:
    """Effect's ``Crypto``; build one with ``make``."""

    __slots__ = ("_digest", "_random_bytes")

    def __init__(
        self,
        random_bytes: Callable[[int], bytes],
        digest: Callable[[DigestAlgorithm, bytes], Effect[bytes, PlatformError]],
    ) -> None:
        self._random_bytes = random_bytes
        self._digest = digest

    def _uint53(self, data: bytes) -> int:
        return int.from_bytes(bytes([data[0] & 0x1F]) + data[1:7])

    def next_double_unsafe(self) -> float:
        """A random float in ``[0, 1)`` from 53 random bits."""
        return self._uint53(self._random_bytes(7)) / 2**53

    def next_int_unsafe(self) -> int:
        """A random integer between ``-(2**53 - 1)`` and ``2**53 - 1``,
        both inclusive, each equally likely."""
        while True:
            data = self._random_bytes(7)
            value = self._uint53(data)
            if data[0] & 0x20 == 0:
                return value - _MAX_SAFE
            if value < _MAX_SAFE:
                return value + 1

    def random_bytes(self, size: int) -> Effect[bytes, PlatformError]:
        """``size`` secure random bytes; fails for a size below 0 or past
        ``2**53 - 1``."""
        if not 0 <= size <= _MAX_SAFE:
            return fail(
                bad_argument(
                    module="Crypto",
                    method="random_bytes",
                    description="size must be a non-negative safe integer",
                )
            )
        return sync(lambda: self._random_bytes(size))

    def digest(self, algorithm: DigestAlgorithm, data: bytes) -> Effect[bytes, PlatformError]:
        """The ``algorithm`` digest of ``data``."""
        return self._digest(algorithm, data)

    @property
    def random(self) -> Effect[float]:
        """A secure random float in ``[0, 1)``."""
        return sync(self.next_double_unsafe)

    @property
    def random_boolean(self) -> Effect[bool]:
        return sync(lambda: self.next_double_unsafe() > 0.5)

    @property
    def random_int(self) -> Effect[int]:
        """A secure random integer between ``-(2**53 - 1)`` and ``2**53 - 1``."""
        return sync(self.next_int_unsafe)

    def random_between(self, low: float, high: float) -> Effect[float]:
        """A secure random float in ``[low, high)``."""
        return sync(lambda: between_of(low, high, self.next_double_unsafe()))

    def random_int_between(
        self, low: float, high: float, *, half_open: bool = False
    ) -> Effect[int]:
        """A secure random integer from ``ceil(low)`` to ``floor(high)``,
        inclusive unless ``half_open``."""
        low_int, high_int = math.ceil(low), math.floor(high)
        span = high_int - low_int + (0 if half_open else 1)
        return sync(lambda: math.floor(self.next_double_unsafe() * span) + low_int)

    def random_shuffle[A](self, elements: Iterable[A]) -> Effect[list[A]]:
        """A securely shuffled copy of ``elements``."""

        def go() -> list[A]:
            buffer = list(elements)
            for i in range(len(buffer) - 1, 0, -1):
                j = min(i, math.floor(self.next_double_unsafe() * (i + 1)))
                buffer[i], buffer[j] = buffer[j], buffer[i]
            return buffer

        return sync(go)

    @overload
    def random_uuid_v4(self, *, format: Literal["hex"] = "hex") -> Effect[str, PlatformError]: ...
    @overload
    def random_uuid_v4(self, *, format: Literal["bytes"]) -> Effect[bytes, PlatformError]: ...
    def random_uuid_v4(self, *, format: UuidFormat = "hex") -> Effect[str | bytes, PlatformError]:
        """A UUIDv4: the lowercase hyphenated string (36 characters), or its
        16 bytes with ``format="bytes"``."""
        return sync(lambda: _formatted(uuid_v4_bytes(self._random_bytes(16)), format))

    @overload
    def random_uuid_v7(self, *, format: Literal["hex"] = "hex") -> Effect[str, PlatformError]: ...
    @overload
    def random_uuid_v7(self, *, format: Literal["bytes"]) -> Effect[bytes, PlatformError]: ...
    def random_uuid_v7(self, *, format: UuidFormat = "hex") -> Effect[str | bytes, PlatformError]:
        """A UUIDv7 holding the ``Clock``'s time in milliseconds."""
        return clock_with(
            lambda clock: succeed(
                _formatted(uuid_v7_bytes(now_millis_unsafe(clock), self._random_bytes(16)), format)
            )
        )

    @property
    def random_ulid(self) -> Effect[str, PlatformError]:
        """A ULID: 26 Crockford base32 characters, the ``Clock``'s time in
        milliseconds (clamped to 48 bits) then 80 random bits."""
        return clock_with(
            lambda clock: succeed(ulid_string(now_millis_unsafe(clock), self._random_bytes(10)))
        )


class Crypto(Tag[CryptoService]):
    """Secure random values and digests."""


def make(
    *,
    random_bytes: Callable[[int], bytes],
    digest: Callable[[DigestAlgorithm, bytes], Effect[bytes, PlatformError]],
) -> CryptoService:
    """A ``Crypto`` from a source of secure random bytes and a digest."""
    return CryptoService(random_bytes, digest)


# --- UUIDs and ULIDs (Effect's internal/uuid.ts and internal/ulid.ts) -------------


def uuid_string(data: bytes) -> str:
    """16 bytes as a lowercase hyphenated UUID."""
    text = data.hex()
    return f"{text[:8]}-{text[8:12]}-{text[12:16]}-{text[16:20]}-{text[20:32]}"


def uuid_v4_bytes(data: bytes) -> bytes:
    """``data`` (16 random bytes) with the version 4 and variant bits set."""
    out = bytearray(data)
    out[6] = (out[6] & 0x0F) | 0x40
    out[8] = (out[8] & 0x3F) | 0x80
    return bytes(out)


def uuid_v7_bytes(timestamp_millis: int, data: bytes) -> bytes:
    """``data`` (16 random bytes) with the timestamp (clamped to 48 bits) in
    the first six and the version 7 and variant bits set."""
    timestamp = min(max(0, timestamp_millis), _MAX_TIMESTAMP)
    out = bytearray(data)
    out[:6] = timestamp.to_bytes(6)
    out[6] = (out[6] & 0x0F) | 0x70
    out[8] = (out[8] & 0x3F) | 0x80
    return bytes(out)


_BASE32 = "0123456789ABCDEFGHJKMNPQRSTVWXYZ"


def ulid_string(timestamp_millis: int, data: bytes) -> str:
    """A ULID from a millisecond timestamp (clamped to 48 bits) and 10
    random bytes."""
    timestamp = min(max(0, timestamp_millis), _MAX_TIMESTAMP)
    head = "".join(_BASE32[(timestamp >> shift) & 0x1F] for shift in range(45, -1, -5))
    bits = int.from_bytes(data)
    tail = "".join(_BASE32[(bits >> shift) & 0x1F] for shift in range(75, -1, -5))
    return head + tail


def _formatted(data: bytes, format: UuidFormat) -> str | bytes:
    return data if format == "bytes" else uuid_string(data)


# --- the host's service -------------------------------------------------------------

_HASHLIB_NAMES: dict[DigestAlgorithm, str] = {
    "SHA-1": "sha1",
    "SHA-256": "sha256",
    "SHA-384": "sha384",
    "SHA-512": "sha512",
}


def _host_digest(algorithm: DigestAlgorithm, data: bytes) -> Effect[bytes, PlatformError]:
    return try_(
        lambda: hashlib.new(_HASHLIB_NAMES[algorithm], data).digest(),
        lambda cause: system_error(
            "Unknown",
            module="Crypto",
            method="digest",
            description="Could not compute digest",
            cause=cause,
        ),
    )


live: CryptoService = make(random_bytes=os.urandom, digest=_host_digest)
"""The host's ``Crypto``: ``os.urandom`` and ``hashlib``."""

layer: Layer[Crypto] = layer_succeed(Crypto, live)

__all__ = [
    "Crypto",
    "CryptoService",
    "DigestAlgorithm",
    "UuidFormat",
    "layer",
    "live",
    "make",
    "ulid_string",
    "uuid_string",
    "uuid_v4_bytes",
    "uuid_v7_bytes",
]
