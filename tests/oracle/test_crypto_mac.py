"""Ports of Effect's ``crypto/Mac.test.ts``."""

from __future__ import annotations

from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.crypto import aead, mac, secure_random
from pyfect.crypto._subtle import host
from pyfect.crypto.mac import Mac
from pyfect.crypto.secure_random import SecureRandom
from pyfect.crypto.web_crypto import CryptoKey, KeyUsage, Params

from ._crypto import assert_reason, encode, from_hex

# RFC 2202 and RFC 4231, test case 2.
JEFE = encode("Jefe")
MESSAGE = encode("what do ya want for nothing?")
VECTORS: list[tuple[mac.Algorithm, str]] = [
    (mac.hmac_sha1, "effcdf6ae5eb2fa2d27416d5f184df9c259a7c79"),
    (mac.hmac_sha256, "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"),
    (
        mac.hmac_sha384,
        "af45d2e376484031617f78d2b58a6b1b9c7ef464f5a01b47"
        "e42ec3736322445e8e2240ca5e69e2c78b3239ecfab21649",
    ),
    (
        mac.hmac_sha512,
        "164b7a7bfcf819e2e395fbe73b56e0a387bd64222e831fd610270cd7ea250554"
        "9758bf75c05a994a6d034f65f8f0e6fdcaeab1a34d4a6b4b636e070a38bce737",
    ),
]

layer = mac.layer_web_crypto.pipe(fx.provide(secure_random.layer_web_crypto))


def import_hmac(
    hash: str, extractable: bool, usages: tuple[KeyUsage, ...] = ("sign", "verify")
) -> CryptoKey:
    subtle = host.subtle
    assert subtle is not None
    return subtle.import_key("raw", JEFE, Params(name="HMAC", hash=hash), extractable, usages)


@testing.effect
def test_is_key_accepts_mac_keys_and_rejects_aead_keys():
    """isKey accepts Mac keys and rejects Aead keys"""
    data = bytes(32)
    assert mac.is_key((yield from mac.key(mac.hmac_sha256, data)))
    assert not mac.is_key((yield from aead.key(aead.aes256_gcm, data)))


@testing.effect
def test_signs_and_verifies_the_published_vectors():
    """signs and verifies the published vectors"""

    @fx.gen
    def program():
        service = yield from Mac()
        for algorithm, hex_text in VECTORS:
            key = yield from mac.key(algorithm, JEFE)
            assert key.algorithm is algorithm
            tag = yield from service.sign(key, MESSAGE)
            assert tag.hex() == hex_text
            assert (yield from service.verify(key, tag, MESSAGE))
            tampered = bytes([tag[0] ^ 1]) + tag[1:]
            assert not (yield from service.verify(key, tampered, MESSAGE))
            assert not (yield from service.verify(key, tag[1:], MESSAGE))
        assert_reason((yield from mac.key(mac.hmac_sha256, b"").flip()), "InvalidKey", "key")

    return program.pipe(fx.provide(layer))


@testing.effect
def test_generates_keys_from_secure_random_bytes():
    """generates keys from SecureRandom bytes"""

    @fx.gen
    def program():
        service = yield from Mac()
        key = yield from service.generate_key(mac.hmac_sha256)
        assert key.algorithm is mac.hmac_sha256
        # The hash's block size, as Web Crypto generates.
        assert (yield from mac.to_bytes(key)) == bytes([7] * 64)

    return program.pipe(fx.provide(mac.layer_web_crypto)).pipe(
        fx.provide_service(SecureRandom, secure_random.make(lambda size: bytes([7] * size)))
    )


@testing.effect
def test_copies_key_bytes_in_and_out_redacts_them_and_compares_keys_by_reference():
    """copies key bytes in and out, redacts them and compares keys by reference"""

    @fx.gen
    def program():
        service = yield from Mac()
        backing = bytearray(JEFE)
        # A memoryview shares its buffer, so it must not be how bytes are kept.
        for data in [bytearray(JEFE), memoryview(backing)]:
            key = yield from mac.key(mac.hmac_sha256, data)
            data[:] = bytes(len(JEFE))
            assert (yield from mac.to_bytes(key)) == JEFE
            assert (yield from service.sign(key, MESSAGE)).hex() == VECTORS[1][1]
        key = yield from mac.key(mac.hmac_sha256, JEFE)

        # Display shows only the algorithm, so keys with different bytes look the same.
        other = yield from mac.key(mac.hmac_sha256, encode("other"))
        assert str(key) == str(other) == '{"_id":"Mac.Key","algorithm":"hmacSha256"}'
        assert key.to_json() == other.to_json()
        assert repr(key) == repr(other)
        assert key != (yield from mac.key(mac.hmac_sha256, JEFE))
        assert key == key  # noqa: PLR0124 (keys compare by reference)
        assert hash(key) != hash((yield from mac.key(mac.hmac_sha256, JEFE)))

    return program.pipe(fx.provide(layer))


@testing.effect
def test_uses_crypto_keys_that_match_the_algorithm_without_exporting_non_extractable_ones():
    """uses CryptoKeys that match the algorithm, without exporting non-extractable ones"""

    @fx.gen
    def program():
        service = yield from Mac()
        key = yield from mac.from_crypto_key(mac.hmac_sha256, import_hmac("SHA-256", False))
        tag = yield from service.sign(key, MESSAGE)
        assert tag.hex() == VECTORS[1][1]
        assert (yield from service.verify(key, tag, MESSAGE))
        assert_reason((yield from mac.to_bytes(key).flip()), "NotExtractable", "toBytes")

        extractable = yield from mac.from_crypto_key(mac.hmac_sha256, import_hmac("SHA-256", True))
        assert (yield from mac.to_bytes(extractable)) == JEFE

        subtle = host.subtle
        assert subtle is not None
        wrong_hash = import_hmac("SHA-512", False)
        # A mac.Key both signs and verifies, so it needs both usages.
        sign_only = import_hmac("SHA-256", False, ("sign",))
        verify_only = import_hmac("SHA-256", False, ("verify",))
        aes = subtle.import_key("raw", bytes(32), "AES-GCM", False, ["encrypt"])
        for crypto_key in [wrong_hash, sign_only, verify_only, aes]:
            error = yield from mac.from_crypto_key(mac.hmac_sha256, crypto_key).flip()
            assert_reason(error, "InvalidKey", "fromCryptoKey")

    return program.pipe(fx.provide(layer))


@testing.effect
def test_layer_web_crypto_with_runs_hmac_for_byte_backed_keys_and_web_crypto_for_crypto_keys():
    """layerWebCryptoWith runs hmac for byte-backed keys and WebCrypto for CryptoKeys"""
    calls: list[tuple[str, bytes, bytes]] = []
    # Differs from the real tag, so a Web Crypto result cannot pass for it.
    marker = bytes([9] * 32)

    def hmac(hash_name: Any, key: bytes, data: bytes) -> bytes:
        calls.append((hash_name, key, data))
        return marker

    @fx.gen
    def program():
        service = yield from Mac()
        key = yield from mac.key(mac.hmac_sha256, JEFE)
        assert (yield from service.sign(key, MESSAGE)) == marker
        assert (yield from service.verify(key, marker, MESSAGE))
        assert not (yield from service.verify(key, from_hex(VECTORS[1][1]), MESSAGE))
        assert not (yield from service.verify(key, marker[1:], MESSAGE))
        assert calls[0] == ("SHA-256", JEFE, MESSAGE)

        count = len(calls)
        crypto_key = yield from mac.from_crypto_key(mac.hmac_sha256, import_hmac("SHA-256", False))
        tag = yield from service.sign(crypto_key, MESSAGE)
        assert tag.hex() == VECTORS[1][1]
        assert (yield from service.verify(crypto_key, tag, MESSAGE))
        assert len(calls) == count

    return program.pipe(
        fx.provide(
            mac.layer_web_crypto_with(hmac=hmac).pipe(fx.provide(secure_random.layer_web_crypto))
        )
    )


def test_compares_bytes_synchronously_returning_false_for_unequal_lengths():
    """compares bytes synchronously, returning false for unequal lengths"""
    assert mac.timing_safe_equal(encode("tag"), encode("tag"))
    assert not mac.timing_safe_equal(encode("tag"), encode("tab"))
    assert not mac.timing_safe_equal(encode("tag"), encode("tags"))
