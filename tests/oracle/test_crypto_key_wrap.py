"""Ports of Effect's ``crypto/KeyWrap.test.ts``.

``node:crypto``'s ``privateDecrypt`` is the ``cryptography`` package's,
called directly on the stored PKCS#8 key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import cast

import pyfect as fx
from pyfect import testing
from pyfect.crypto import aead, cipher, digest, key_wrap, mac, secure_random, signature
from pyfect.crypto._subtle import host
from pyfect.crypto.key_wrap import KeyWrap
from pyfect.crypto.secure_random import SecureRandom
from pyfect.crypto.web_crypto import CryptoKeyPair, KeyUsage, Params
from pyfect.layer import Layer

from ._crypto import assert_reason, fake_subtle, from_hex, raises


@dataclass(frozen=True)
class Vector:
    algorithm: key_wrap.AesKw
    kek: str
    target: aead.AesGcm
    key: str
    wrapped: str


# RFC 3394, sections 4.1 and 4.6.
RFC_3394 = [
    Vector(
        key_wrap.aes128_kw,
        "000102030405060708090a0b0c0d0e0f",
        aead.aes128_gcm,
        "00112233445566778899aabbccddeeff",
        "1fa68b0a8112b447aef34bd8fb5a7b829d3e862371d2cfe5",
    ),
    Vector(
        key_wrap.aes256_kw,
        "000102030405060708090a0b0c0d0e0f101112131415161718191a1b1c1d1e1f",
        aead.aes256_gcm,
        "00112233445566778899aabbccddeeff000102030405060708090a0b0c0d0e0f",
        "28c9f404c4b810f4cbccb35cfb87f8263f5786e2d80ed326cbc7f0e71a99f43bfb988b9b7a02dd21",
    ),
]

# A small modulus keeps generation fast.
rsa_oaep_2048 = key_wrap.rsa_oaep(hash=digest.sha256, modulus_length=2048)

seeded: Layer[SecureRandom] = fx.layer.succeed(
    SecureRandom, secure_random.make(lambda size: bytes([7] * size))
)
layer = key_wrap.layer_web_crypto.pipe(fx.provide(seeded))

subtle = host.subtle
assert subtle is not None


def rsa_oaep_pair(usages: tuple[KeyUsage, ...]) -> CryptoKeyPair:
    assert subtle is not None
    pair = subtle.generate_key(
        Params(
            name="RSA-OAEP", hash="SHA-256", modulus_length=2048, public_exponent=bytes([1, 0, 1])
        ),
        False,
        usages,
    )
    assert isinstance(pair, CryptoKeyPair)
    return pair


@testing.effect
def test_reports_the_imported_rsa_crypto_key_modulus_rather_than_the_generation_default():
    """reports the imported RSA CryptoKey modulus rather than the generation default"""
    pair = rsa_oaep_pair(("encrypt", "decrypt"))
    key = yield from key_wrap.private_key_from_crypto_key(
        key_wrap.rsa_oaep_sha256, pair.private_key
    )
    assert key.algorithm.modulus_length == 2048


@testing.effect
def test_wraps_and_unwraps_the_rfc_3394_aes_kw_vectors_into_typed_keys():
    """wraps and unwraps the RFC 3394 AES-KW vectors into typed keys"""

    @fx.gen
    def program():
        service = yield from KeyWrap()
        for vector in RFC_3394:
            kek = yield from key_wrap.key(vector.algorithm, from_hex(vector.kek))
            assert kek.algorithm is vector.algorithm
            target = yield from aead.key(vector.target, from_hex(vector.key))
            wrapped = yield from service.wrap(kek, target)
            assert wrapped.hex() == vector.wrapped

            unwrapped = yield from service.unwrap(kek, vector.target, wrapped)
            assert unwrapped.algorithm is vector.target
            assert (yield from aead.to_bytes(unwrapped)).hex() == vector.key
            # The same bytes can come back as a key of another family.
            mac_key = yield from service.unwrap(kek, mac.hmac_sha256, wrapped)
            assert (yield from mac.to_bytes(mac_key)).hex() == vector.key

            tampered = bytes([wrapped[0] ^ 1]) + wrapped[1:]
            error = yield from service.unwrap(kek, vector.target, tampered).flip()
            assert_reason(error, "DecryptionFailed", "unwrap")
            assert error.cause is None

    return program.pipe(fx.provide(layer))


# Only unwrap turns an OperationError into DecryptionFailed. Arguments are
# checked before wrap reaches Web Crypto, so its OperationError is a bug.
@testing.effect
def test_keeps_an_unexpected_wrap_failure_a_defect_unlike_an_unwrap_failure():
    """keeps an unexpected wrap failure a defect, unlike an unwrap failure"""

    @fx.gen
    def program():
        service = yield from KeyWrap()
        kek = yield from key_wrap.key(key_wrap.aes128_kw, bytes(16))
        target = yield from aead.key(aead.aes128_gcm, bytes(16))
        exit = yield from service.wrap(kek, target).exit()
        assert exit.has_dies, "expected a defect"

        error = yield from service.unwrap(kek, aead.aes128_gcm, bytes(24)).flip()
        assert_reason(error, "DecryptionFailed", "unwrap")
        assert error.cause is None

    failing = fake_subtle(
        wrap_key=raises("OperationError", "failed"), unwrap_key=raises("OperationError", "failed")
    )
    return program.pipe(
        fx.provide(key_wrap.layer_web_crypto.pipe(fx.provide(fx.layer.merge(seeded, failing))))
    )


@testing.effect
def test_builds_aes_kw_keys_from_secure_random_bytes_and_applies_the_rfc_3394_length_rule():
    """builds AES-KW keys from SecureRandom bytes and applies the RFC 3394 length rule"""

    @fx.gen
    def program():
        service = yield from KeyWrap()
        kek = yield from service.generate_key(key_wrap.aes256_kw)
        assert (yield from key_wrap.to_bytes(kek)) == bytes([7] * 32)
        for length in [0, 15, 24, 32]:
            error = yield from key_wrap.key(key_wrap.aes128_kw, bytes(length)).flip()
            assert_reason(error, "InvalidKey", "key")

        # Wrapped keys must be a multiple of 8 bytes and at least 16.
        target = yield from mac.key(mac.hmac_sha256, bytes([1] * 24))
        assert len((yield from service.wrap(kek, target))) == 32
        for length in [8, 20]:
            short = yield from mac.key(mac.hmac_sha256, bytes([1] * length))
            assert_reason((yield from service.wrap(kek, short).flip()), "InvalidArgument", "wrap")
        error = yield from service.unwrap(kek, mac.hmac_sha256, bytes(20)).flip()
        assert_reason(error, "InvalidArgument", "unwrap")

    return program.pipe(fx.provide(layer))


@testing.effect
def test_wraps_with_rsa_oaep_storing_spki_and_pkcs8_and_binding_mgf1_to_the_hash():
    """wraps with RSA-OAEP, storing SPKI and PKCS#8 and binding MGF1 to the hash"""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.serialization import (
        Encoding,
        PublicFormat,
        load_der_private_key,
    )

    @fx.gen
    def program():
        service = yield from KeyWrap()
        # RSA-OAEP-256 is the default, with RSA-OAEP for JOSE interop.
        assert key_wrap.rsa_oaep_sha256.hash is digest.sha256
        assert key_wrap.rsa_oaep_sha256.modulus_length == 3072
        assert key_wrap.rsa_oaep_sha1.hash is digest.sha1

        pair = yield from service.generate_key_pair(rsa_oaep_2048)
        assert pair.private_key.algorithm is rsa_oaep_2048
        target = yield from cipher.key(cipher.aes256_cbc, bytes([3] * 32))
        wrapped = yield from service.wrap(pair.public_key, target)
        assert len(wrapped) == 256
        unwrapped = yield from service.unwrap(pair.private_key, cipher.aes256_cbc, wrapped)
        assert (yield from cipher.to_bytes(unwrapped)) == bytes([3] * 32)

        # cryptography decrypts with the stored PKCS#8 key, independently of the layer.
        pkcs8 = cast(
            "rsa.RSAPrivateKey",
            load_der_private_key((yield from key_wrap.to_bytes(pair.private_key)), None),
        )
        oaep = padding.OAEP(
            mgf=padding.MGF1(hashes.SHA256()), algorithm=hashes.SHA256(), label=None
        )
        assert pkcs8.decrypt(wrapped, oaep) == bytes([3] * 32)
        public_der = pkcs8.public_key().public_bytes(
            Encoding.DER, PublicFormat.SubjectPublicKeyInfo
        )
        assert public_der == (yield from key_wrap.to_bytes(pair.public_key))

        other = yield from service.generate_key_pair(rsa_oaep_2048)
        error = yield from service.unwrap(other.private_key, cipher.aes256_cbc, wrapped).flip()
        assert_reason(error, "DecryptionFailed", "unwrap")
        assert error.cause is None

    return program.pipe(fx.provide(layer))


@testing.effect
def test_mixes_the_encrypt_and_wrap_key_routes_for_rsa_oaep_crypto_keys():
    """mixes the encrypt and wrapKey routes for RSA-OAEP CryptoKeys"""

    @fx.gen
    def program():
        assert subtle is not None
        service = yield from KeyWrap()
        pair = yield from service.generate_key_pair(rsa_oaep_2048)
        params = Params(name="RSA-OAEP", hash="SHA-256")
        spki = yield from key_wrap.to_bytes(pair.public_key)
        pkcs8 = yield from key_wrap.to_bytes(pair.private_key)
        wrap_only = yield from key_wrap.public_key_from_crypto_key(
            rsa_oaep_2048, subtle.import_key("spki", spki, params, True, ["wrapKey"])
        )
        unwrap_only = yield from key_wrap.private_key_from_crypto_key(
            rsa_oaep_2048, subtle.import_key("pkcs8", pkcs8, params, False, ["unwrapKey"])
        )

        target = yield from aead.key(aead.aes128_gcm, bytes([5] * 16))
        pairs = [
            (pair.public_key, unwrap_only),
            (wrap_only, pair.private_key),
            (wrap_only, unwrap_only),
        ]
        for public_key, private_key in pairs:
            wrapped = yield from service.wrap(public_key, target)
            unwrapped = yield from service.unwrap(private_key, aead.aes128_gcm, wrapped)
            assert (yield from aead.to_bytes(unwrapped)) == bytes([5] * 16)

        # The message bound uses the key's real modulus: 191 bytes would fit
        # a 3072-bit key, but this one has 2048 bits.
        narrow = yield from key_wrap.public_key_from_crypto_key(
            key_wrap.rsa_oaep_sha256, subtle.import_key("spki", spki, params, True, ["encrypt"])
        )
        too_long = yield from mac.key(mac.hmac_sha256, bytes([1] * 191))
        assert_reason((yield from service.wrap(narrow, too_long).flip()), "InvalidArgument", "wrap")

    return program.pipe(fx.provide(layer))


@testing.effect
def test_uses_non_extractable_key_encryption_keys_but_cannot_wrap_non_extractable_targets():
    """uses non-extractable key-encryption keys, but cannot wrap non-extractable targets"""
    vector = RFC_3394[0]

    def import_kw(usages: tuple[KeyUsage, ...]):
        assert subtle is not None
        return subtle.import_key("raw", from_hex(vector.kek), "AES-KW", False, usages)

    @fx.gen
    def program():
        assert subtle is not None
        service = yield from KeyWrap()
        kek = yield from key_wrap.from_crypto_key(
            key_wrap.aes128_kw, import_kw(("wrapKey", "unwrapKey"))
        )
        target = yield from aead.key(aead.aes128_gcm, from_hex(vector.key))
        assert (yield from service.wrap(kek, target)).hex() == vector.wrapped
        assert_reason((yield from key_wrap.to_bytes(kek).flip()), "NotExtractable", "toBytes")

        sealed = yield from aead.from_crypto_key(
            aead.aes128_gcm,
            subtle.import_key(
                "raw", from_hex(vector.key), "AES-GCM", False, ["encrypt", "decrypt"]
            ),
        )
        assert_reason((yield from service.wrap(kek, sealed).flip()), "NotExtractable", "wrap")

        # AES-KW keys need both usages and the right size.
        aes256 = subtle.import_key("raw", bytes(32), "AES-KW", False, ["wrapKey", "unwrapKey"])
        for crypto_key in [import_kw(("wrapKey",)), aes256]:
            error = yield from key_wrap.from_crypto_key(key_wrap.aes128_kw, crypto_key).flip()
            assert_reason(error, "InvalidKey", "fromCryptoKey")
        rsa = rsa_oaep_pair(("encrypt", "decrypt"))
        # The roles and the hash must match.
        error = yield from key_wrap.public_key_from_crypto_key(
            rsa_oaep_2048, rsa.private_key
        ).flip()
        assert_reason(error, "InvalidKey", "publicKeyFromCryptoKey")
        error = yield from key_wrap.private_key_from_crypto_key(
            key_wrap.rsa_oaep_sha1, rsa.private_key
        ).flip()
        assert_reason(error, "InvalidKey", "privateKeyFromCryptoKey")

        def type_errors() -> None:
            service.wrap(kek, bytes(16))  # pyright: ignore[reportArgumentType]
            service.unwrap(kek, signature.ed25519, bytes(24))  # pyright: ignore[reportArgumentType, reportCallIssue]
            key_wrap.key(key_wrap.rsa_oaep_sha256, bytes(32))  # pyright: ignore[reportArgumentType]

        del type_errors

    return program.pipe(fx.provide(layer))


@testing.effect
def test_tells_the_key_roles_apart_and_redacts_secret_keys():
    """tells the key roles apart, and redacts secret keys"""

    @fx.gen
    def program():
        service = yield from KeyWrap()
        kek = yield from service.generate_key(key_wrap.aes128_kw)
        pair = yield from service.generate_key_pair(rsa_oaep_2048)
        assert key_wrap.is_key(kek)
        assert not key_wrap.is_key(pair.private_key)
        assert key_wrap.is_private_key(pair.private_key)
        assert not key_wrap.is_private_key(pair.public_key)
        assert key_wrap.is_public_key(pair.public_key)
        assert not key_wrap.is_public_key(kek)
        assert not key_wrap.is_key((yield from aead.key(aead.aes128_gcm, bytes(16))))

        other = yield from key_wrap.key(key_wrap.aes128_kw, bytes([1] * 16))
        assert str(kek) == str(other) == '{"_id":"KeyWrap.Key","algorithm":"aes128Kw"}'
        assert kek.to_json() == other.to_json()
        assert repr(kek) == repr(other)

    return program.pipe(fx.provide(layer))
