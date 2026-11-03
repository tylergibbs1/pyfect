"""Ports of Effect's ``test/Crypto.test.ts`` and platform-node's
``NodeCrypto.test.ts``.

Each test's docstring is the Effect test title. Omitted: "uses the module
path for its type ID" (a service is its class; ``isinstance`` is the guard).
"""

from __future__ import annotations

import re
from collections.abc import Callable

import pyfect as fx
from pyfect import crypto, testing
from pyfect._core import Effect
from pyfect.crypto import Crypto, CryptoService, DigestAlgorithm
from pyfect.platform_error import PlatformError

MIN_SAFE_INTEGER = -(2**53 - 1)
MAX_SAFE_INTEGER = 2**53 - 1


def _test_random_bytes(size: int) -> bytes:
    return bytes([0x18, 0, 0, 0, 0, 0, 0]) if size == 7 else bytes(range(size))


def _test_digest(algorithm: DigestAlgorithm, data: bytes) -> Effect[bytes, PlatformError]:
    return fx.succeed(bytes([len(data), len(algorithm)]))


test_crypto = crypto.make(random_bytes=_test_random_bytes, digest=_test_digest)


def _identity_digest(algorithm: DigestAlgorithm, data: bytes) -> Effect[bytes, PlatformError]:
    return fx.succeed(data)


def make_crypto(value: int) -> CryptoService:
    def random_bytes(size: int) -> bytes:
        return bytes(
            [
                (value >> 48) & 0x3F,
                (value >> 40) & 0xFF,
                (value >> 32) & 0xFF,
                (value >> 24) & 0xFF,
                (value >> 16) & 0xFF,
                (value >> 8) & 0xFF,
                value & 0xFF,
            ]
        )

    return crypto.make(random_bytes=random_bytes, digest=_identity_digest)


def with_test_crypto[A, E](
    body: Callable[[CryptoService], Effect[A, E, Crypto]], service: CryptoService = test_crypto
) -> Effect[A, E]:
    return Crypto().flat_map(body).pipe(fx.provide_service(Crypto, service))


def test_supports_string_literal_digest_algorithms() -> None:
    """supports string literal digest algorithms"""
    algorithm: DigestAlgorithm = "SHA-256"
    assert algorithm == "SHA-256"


@testing.effect
def test_random_bytes_delegates_to_the_service():
    """randomBytes delegates to the service"""
    data = yield from with_test_crypto(lambda c: c.random_bytes(4))
    assert data == bytes([0, 1, 2, 3])


@testing.effect
def test_random_generators_delegate_to_the_service():
    """random generators delegate to the service"""
    c = test_crypto
    assert (yield from c.random) == 0.75
    assert (yield from c.random_int) == -2251799813685247
    assert (yield from c.random_boolean) is True
    assert (yield from c.random_between(10, 20)) == 17.5
    assert (yield from c.random_between(10.5, 20.5)) == 18
    assert (yield from c.random_int_between(1, 6)) == 5
    assert (yield from c.random_shuffle([1, 2, 3])) == [1, 2, 3]


@testing.effect
def test_random_between_excludes_the_upper_bound_when_the_result_rounds_up():
    """randomBetween excludes the upper bound when the result rounds up"""
    value = yield from make_crypto((1 << 53) - 2).random_between(10, 20)
    assert 10 <= value < 20
    assert value == 20 - 2**-48


def test_maps_adjacent_random_values_to_adjacent_safe_integers() -> None:
    """maps adjacent random values to adjacent safe integers"""
    assert make_crypto(0).next_int_unsafe() == MIN_SAFE_INTEGER
    assert make_crypto(1).next_int_unsafe() == MIN_SAFE_INTEGER + 1
    assert make_crypto(1 << 53).next_int_unsafe() == 1
    assert make_crypto((1 << 54) - 2).next_int_unsafe() == MAX_SAFE_INTEGER


@testing.effect
def test_random_int_between_excludes_the_upper_bound_in_half_open_ranges():
    """randomIntBetween excludes the upper bound in half-open ranges"""
    service = crypto.make(random_bytes=lambda size: b"\xff" * size, digest=_identity_digest)
    value = yield from with_test_crypto(
        lambda c: c.random_int_between(1, 6, half_open=True), service
    )
    assert value == 5


@testing.effect
def test_random_uuid_v4_formats_uuid_bytes_from_random_bytes():
    """randomUUIDv4 formats UUID bytes from randomBytes"""
    uuid = yield from test_crypto.random_uuid_v4()
    assert uuid == "00010203-0405-4607-8809-0a0b0c0d0e0f"
    text = yield from test_crypto.random_uuid_v4(format="hex")
    assert text == "00010203-0405-4607-8809-0a0b0c0d0e0f"


@testing.effect
def test_random_uuid_v7_formats_uuid_bytes_with_the_clock_timestamp():
    """randomUUIDv7 formats UUID bytes with the Clock timestamp"""
    yield from testing.set_time(0x0123456789AB / 1000)
    uuid = yield from test_crypto.random_uuid_v7()
    assert uuid == "01234567-89ab-7607-8809-0a0b0c0d0e0f"
    text = yield from test_crypto.random_uuid_v7(format="hex")
    assert text == "01234567-89ab-7607-8809-0a0b0c0d0e0f"


@testing.effect
def test_random_uuid_v4_returns_16_bytes_with_the_version_and_variant_bits_set():
    """randomUUIDv4 returns 16 bytes with the version and variant bits set"""
    data = yield from test_crypto.random_uuid_v4(format="bytes")
    assert data == bytes([0, 1, 2, 3, 4, 5, 0x46, 7, 0x88, 9, 10, 11, 12, 13, 14, 15])


@testing.effect
def test_random_uuid_v7_returns_16_bytes_containing_the_clock_timestamp_version_and_variant():
    """randomUUIDv7 returns 16 bytes containing the Clock timestamp, version and variant"""
    yield from testing.set_time(0x0123456789AB / 1000)
    data = yield from test_crypto.random_uuid_v7(format="bytes")
    assert data == bytes(
        [0x01, 0x23, 0x45, 0x67, 0x89, 0xAB, 0x76, 7, 0x88, 9, 10, 11, 12, 13, 14, 15]
    )


@testing.effect
def test_random_ulid_encodes_the_clock_timestamp_and_random_bytes():
    """randomULID encodes the Clock timestamp and random bytes"""
    yield from testing.set_time(0x0123456789AB / 1000)
    assert (yield from test_crypto.random_ulid) == "014D2PF2DB000G40R40M30E209"


@testing.effect
def test_random_ulid_clamps_an_overflowing_clock_timestamp():
    """randomULID clamps an overflowing Clock timestamp"""
    yield from testing.set_time(2**48 / 1000)
    assert (yield from test_crypto.random_ulid) == "7ZZZZZZZZZ000G40R40M30E209"


@testing.effect
def test_digest_delegates_to_the_service():
    """digest delegates to the service"""
    digest = yield from with_test_crypto(lambda c: c.digest("SHA-256", bytes([1, 2, 3])))
    assert digest == bytes([3, len("SHA-256")])


@testing.effect
def test_can_access_a_provided_custom_crypto_service():
    """can access a provided custom Crypto service"""
    data = yield from with_test_crypto(lambda c: c.random_bytes(1))
    assert data == bytes([0])


# --- NodeCrypto.test.ts, on the live service -------------------------------------

UUID_V4 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
UUID_V7 = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-7[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")


def live[A, E](body: Callable[[CryptoService], Effect[A, E, Crypto]]) -> Effect[A, E]:
    return Crypto().flat_map(body).pipe(fx.provide(crypto.layer))


@testing.effect
def test_generates_empty_random_bytes():
    """generates empty random bytes"""
    assert (yield from live(lambda c: c.random_bytes(0))) == b""


@testing.effect
def test_generates_random_bytes_with_the_requested_size():
    """generates random bytes with the requested size"""
    assert len((yield from live(lambda c: c.random_bytes(32)))) == 32


@testing.effect
def test_fails_invalid_random_byte_sizes():
    """fails invalid random byte sizes"""
    error = yield from live(lambda c: c.random_bytes(-1)).flip()
    assert isinstance(error, PlatformError)
    assert error.message == "Crypto.random_bytes: size must be a non-negative safe integer"


@testing.effect
def test_generates_uuid_v4_values():
    """generates UUIDv4 values"""
    first = yield from live(lambda c: c.random_uuid_v4())
    second = yield from live(lambda c: c.random_uuid_v4())
    assert UUID_V4.match(first)
    assert UUID_V4.match(second)
    assert first != second


@testing.effect
def test_generates_uuid_v7_values():
    """generates UUIDv7 values"""
    yield from testing.set_time(0x0123456789AB / 1000)
    uuid = yield from live(lambda c: c.random_uuid_v7())
    assert UUID_V7.match(uuid)
    assert uuid[:13] == "01234567-89ab"


@testing.effect
def test_computes_sha_256_digests():
    """computes SHA-256 digests"""
    digest = yield from live(lambda c: c.digest("SHA-256", b"hello"))
    assert digest.hex() == "2cf24dba5fb0a30e26e83b2ac5b9e29e1b161e5c1fa7425e73043362938b9824"
