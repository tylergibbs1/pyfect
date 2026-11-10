"""Ports of Effect's ``crypto/Aead.test.ts``."""

from __future__ import annotations

import os
import secrets
from dataclasses import dataclass
from typing import Any, Never

import pyfect as fx
from pyfect import testing
from pyfect.crypto import aead, cipher, secure_random
from pyfect.crypto._subtle import host
from pyfect.crypto.aead import Aead
from pyfect.crypto.crypto_error import CryptoError
from pyfect.crypto.secure_random import SecureRandom
from pyfect.crypto.web_crypto import CryptoKey, KeyUsage
from pyfect.layer import Layer

from ._crypto import assert_reason, encode, from_hex, unreachable, view


@dataclass(frozen=True)
class Vector:
    algorithm: aead.Algorithm
    key: str
    nonce: str
    aad: str
    plaintext: bytes
    sealed: str


# The GCM specification (McGrew and Viega), test cases 4 and 16.
GCM_PLAINTEXT = from_hex(
    "d9313225f88406e5a55909c5aff5269a86a7a9531534f7da2e4c303d8a318a72"
    "1c3c0c95956809532fcf0e2449a6b525b16aedf5aa0de657ba637b39"
)
GCM_NONCE = "cafebabefacedbaddecaf888"
GCM_AAD = "feedfacedeadbeeffeedfacedeadbeefabaddad2"
# RFC 8439, section 2.8.2, and draft-irtf-cfrg-xchacha-03, Appendix A.3.1.
SUNSCREEN = encode(
    "Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the "
    "future, sunscreen would be it."
)
CHACHA_KEY = "808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9f"
CHACHA_AAD = "50515253c0c1c2c3c4c5c6c7"

VECTORS = [
    Vector(
        aead.aes128_gcm,
        "feffe9928665731c6d6a8f9467308308",
        GCM_NONCE,
        GCM_AAD,
        GCM_PLAINTEXT,
        "42831ec2217774244b7221b784d0d49ce3aa212f2c02a4e035c17e2329aca12e"
        "21d514b25466931c7d8f6a5aac84aa051ba30b396a0aac973d58e091"
        "5bc94fbc3221a5db94fae95ae7121a47",
    ),
    Vector(
        aead.aes256_gcm,
        "feffe9928665731c6d6a8f9467308308feffe9928665731c6d6a8f9467308308",
        GCM_NONCE,
        GCM_AAD,
        GCM_PLAINTEXT,
        "522dc1f099567d07f47f37a32a84427d643a8cdcbfe5c0c97598a2bd2555d1aa"
        "8cb08e48590dbb3da7b08b1056828838c5f61e6393ba7a0abcc9f662"
        "76fc6ece0f4e1768cddf8853bb2d551b",
    ),
    Vector(
        aead.chacha20_poly1305,
        CHACHA_KEY,
        "070000004041424344454647",
        CHACHA_AAD,
        SUNSCREEN,
        "d31a8d34648e60db7b86afbc53ef7ec2a4aded51296e08fea9e2b5a736ee62d6"
        "3dbea45e8ca9671282fafb69da92728b1a71de0a9e060b2905d6a5b67ecd3b36"
        "92ddbd7f2d778b8c9803aee328091b58fab324e4fad675945585808b4831d7bc"
        "3ff4def08e4b7a9de576d26586cec64b61161ae10b594f09e26a7e902ecbd0600691",
    ),
    Vector(
        aead.xchacha20_poly1305,
        CHACHA_KEY,
        "404142434445464748494a4b4c4d4e4f5051525354555657",
        CHACHA_AAD,
        SUNSCREEN,
        "bd6d179d3e83d43b9576579493c0e939572a1700252bfaccbed2902c21396cbb"
        "731c7f1b0b4aa6440bf3a82f4eda7e39ae64c6708c54c216cb96b72e1213b452"
        "2f8c9ba40db5d945b11b69b982c1bb9e3f3fac2bc369488f76b2383565d3fff9"
        "21f9664c97637da9768812f615c68b13b52ec0875924c1c7987947deafd8780acf49",
    ),
]

seeded: Layer[SecureRandom] = fx.layer.succeed(
    SecureRandom, secure_random.make(lambda size: bytes([7] * size))
)
layer = aead.layer_web_crypto.pipe(fx.provide(seeded))


def import_aes(
    name: str, length: int, usages: tuple[KeyUsage, ...] = ("encrypt", "decrypt")
) -> CryptoKey:
    subtle = host.subtle
    assert subtle is not None
    return subtle.import_key("raw", bytes([1] * (length // 8)), name, False, usages)


@testing.effect
def test_is_key_accepts_aead_keys_and_rejects_cipher_keys():
    """isKey accepts Aead keys and rejects Cipher keys"""
    data = bytes(32)
    assert aead.is_key((yield from aead.key(aead.aes256_gcm, data)))
    assert not aead.is_key((yield from cipher.key(cipher.aes256_ctr, data)))


@testing.effect
def test_encrypts_and_decrypts_the_published_vectors():
    """encrypts and decrypts the published vectors"""

    @fx.gen
    def program():
        service = yield from Aead()
        for vector in VECTORS:
            key = yield from aead.key(vector.algorithm, from_hex(vector.key))
            assert key.algorithm is vector.algorithm
            nonce, aad = view(from_hex(vector.nonce)), view(from_hex(vector.aad))
            sealed = yield from service.encrypt(key, view(vector.plaintext), nonce=nonce, aad=aad)
            assert sealed.hex() == vector.sealed
            opened = yield from service.decrypt(
                key, view(from_hex(vector.sealed)), nonce=nonce, aad=aad
            )
            assert opened == vector.plaintext

    return program.pipe(fx.provide(layer))


# Neither the host nor the in-process code may reveal which check failed.
@testing.effect
def test_fails_decryption_identically_for_a_tampered_tag_aad_or_ciphertext():
    """fails decryption identically for a tampered tag, AAD or ciphertext"""

    @fx.gen
    def program():
        service = yield from Aead()
        messages: set[str] = set()
        for vector in VECTORS:
            key = yield from aead.key(vector.algorithm, from_hex(vector.key))
            sealed = from_hex(vector.sealed)
            nonce, aad = from_hex(vector.nonce), from_hex(vector.aad)
            ciphertext = bytes([sealed[0] ^ 1]) + sealed[1:]
            tag = sealed[:-1] + bytes([sealed[-1] ^ 1])
            cases: list[tuple[bytes, bytes | None]] = [
                (ciphertext, aad),
                (tag, aad),
                (sealed, aad[1:]),
                (sealed, None),
                # Shorter than the tag.
                (sealed[:15], aad),
            ]
            for data, case_aad in cases:
                error = yield from service.decrypt(key, data, nonce=nonce, aad=case_aad).flip()
                assert error.module == "Aead"
                assert_reason(error, "DecryptionFailed", "decrypt")
                assert error.cause is None
                assert error.__cause__ is None
                messages.add(error.message)
        assert len(messages) == 1

    return program.pipe(fx.provide(layer))


# Web Crypto and the in-process code report other lengths with the same
# error as a tag mismatch, so the length must be checked first.
@testing.effect
def test_checks_the_nonce_length_before_any_work():
    """checks the nonce length before any work"""

    @fx.gen
    def program():
        service = yield from Aead()
        cases: list[tuple[aead.Algorithm, int, list[int]]] = [
            (aead.aes128_gcm, 16, [0, 8, 16, 24]),
            (aead.aes256_gcm, 32, [0, 8, 16, 24]),
            (aead.chacha20_poly1305, 32, [0, 8, 16, 24]),
            (aead.xchacha20_poly1305, 32, [0, 12, 16, 32]),
        ]
        for algorithm, key_length, nonce_lengths in cases:
            key = yield from aead.key(algorithm, bytes(key_length))
            for length in nonce_lengths:
                nonce, data = bytes(length), bytes(32)
                encrypt_error = yield from service.encrypt(key, data, nonce=nonce).flip()
                assert_reason(encrypt_error, "InvalidArgument", "encrypt")
                decrypt_error = yield from service.decrypt(key, data, nonce=nonce).flip()
                assert_reason(decrypt_error, "InvalidArgument", "decrypt")

    return program.pipe(
        fx.provide(aead.layer_web_crypto.pipe(fx.provide(fx.layer.merge(seeded, unreachable))))
    )


# An effect may run later than it is built, or more than once.
@testing.effect
def test_checks_the_nonce_length_when_the_effect_runs():
    """checks the nonce length when the effect runs"""

    @fx.gen
    def program():
        service = yield from Aead()
        for algorithm in [aead.aes256_gcm, aead.chacha20_poly1305, aead.xchacha20_poly1305]:
            key = yield from aead.key(algorithm, bytes(32))
            nonce = bytearray(algorithm.nonce_length)
            data = bytes(32)
            encrypt = service.encrypt(key, data, nonce=nonce)
            decrypt = service.decrypt(key, data, nonce=nonce)
            nonce.extend(bytes(4))
            assert_reason((yield from encrypt.flip()), "InvalidArgument", "encrypt")
            assert_reason((yield from decrypt.flip()), "InvalidArgument", "decrypt")

    return program.pipe(fx.provide(layer))


@testing.effect
def test_builds_keys_of_each_algorithms_length_from_bytes_and_secure_random():
    """builds keys of each algorithm's length from bytes and SecureRandom"""

    @fx.gen
    def program():
        service = yield from Aead()
        # No AES-192, and ChaCha keys are 32 bytes.
        cases: list[tuple[aead.Algorithm, int, list[int]]] = [
            (aead.aes128_gcm, 16, [0, 24, 32]),
            (aead.aes256_gcm, 32, [0, 16, 24]),
            (aead.chacha20_poly1305, 32, [0, 16, 24]),
            (aead.xchacha20_poly1305, 32, [0, 16, 24]),
        ]
        for algorithm, length, wrong_lengths in cases:
            key = yield from service.generate_key(algorithm)
            assert key.algorithm is algorithm
            assert (yield from aead.to_bytes(key)) == bytes([7] * length)
            for wrong in wrong_lengths:
                error = yield from aead.key(algorithm, bytes(wrong)).flip()
                assert_reason(error, "InvalidKey", "key")

    return program.pipe(fx.provide(layer))


@testing.effect
def test_uses_aes_gcm_crypto_keys_that_match_the_algorithm_without_exporting_non_extractable():
    """uses AES-GCM CryptoKeys that match the algorithm, without exporting non-extractable ones"""

    @fx.gen
    def program():
        service = yield from Aead()
        key = yield from aead.from_crypto_key(aead.aes256_gcm, import_aes("AES-GCM", 256))
        byte_key = yield from aead.key(aead.aes256_gcm, bytes([1] * 32))
        nonce, aad = bytes(12), encode("aad")
        sealed = yield from service.encrypt(key, SUNSCREEN, nonce=nonce, aad=aad)
        assert (yield from service.decrypt(byte_key, sealed, nonce=nonce, aad=aad)) == SUNSCREEN
        assert_reason((yield from aead.to_bytes(key).flip()), "NotExtractable", "toBytes")

        mismatched = [
            import_aes("AES-GCM", 128),
            import_aes("AES-CBC", 256),
            # An aead.Key both encrypts and decrypts, so it needs both usages.
            import_aes("AES-GCM", 256, ("encrypt",)),
        ]
        for crypto_key in mismatched:
            error = yield from aead.from_crypto_key(aead.aes256_gcm, crypto_key).flip()
            assert_reason(error, "InvalidKey", "fromCryptoKey")

    def from_chacha() -> None:
        # ChaCha never runs on subtle.
        aead.from_crypto_key(aead.chacha20_poly1305, import_aes("AES-GCM", 256))  # pyright: ignore[reportArgumentType]

    del from_chacha
    return program.pipe(fx.provide(layer))


_CHACHA = aead.chacha20_poly1305.implementation
assert _CHACHA is not None


def recorded() -> tuple[list[str], Layer[Aead, Never, SecureRandom]]:
    calls: list[str] = []
    chacha = _CHACHA
    assert chacha is not None

    def encrypt(*args: Any) -> bytes:
        calls.append("encrypt")
        return chacha.encrypt(*args)

    def decrypt(*args: Any) -> bytes | None:
        calls.append("decrypt")
        return chacha.decrypt(*args)

    implementation = aead.Implementation(encrypt=encrypt, decrypt=decrypt)
    built = aead.layer_web_crypto_with(
        implementations={"chacha20Poly1305": implementation, "aes256Gcm": implementation}
    )
    return calls, built


@testing.effect
def test_layer_web_crypto_with_runs_implementations_for_byte_keys_and_web_crypto_for_crypto_keys():
    """runs implementations for byte-backed keys and WebCrypto for CryptoKeys"""
    calls, recorded_layer = recorded()

    @fx.gen
    def program():
        service = yield from Aead()
        vector = VECTORS[2]
        key = yield from aead.key(vector.algorithm, from_hex(vector.key))
        nonce, aad = from_hex(vector.nonce), from_hex(vector.aad)
        sealed = yield from service.encrypt(key, vector.plaintext, nonce=nonce, aad=aad)
        assert sealed.hex() == vector.sealed
        opened = yield from service.decrypt(key, from_hex(vector.sealed), nonce=nonce, aad=aad)
        assert opened == vector.plaintext
        assert calls == ["encrypt", "decrypt"]

        crypto_key = yield from aead.from_crypto_key(aead.aes256_gcm, import_aes("AES-GCM", 256))
        gcm_nonce, gcm_aad = bytes(12), encode("aad")
        sealed = yield from service.encrypt(crypto_key, SUNSCREEN, nonce=gcm_nonce, aad=gcm_aad)
        opened = yield from service.decrypt(crypto_key, sealed, nonce=gcm_nonce, aad=gcm_aad)
        assert opened == SUNSCREEN
        assert calls == ["encrypt", "decrypt"]

    return program.pipe(fx.provide(recorded_layer.pipe(fx.provide(seeded))))


def _failures(
    built: Layer[Aead, Never, SecureRandom],
) -> fx.Effect[list[tuple[str, str, str]], CryptoError | bytes]:
    @fx.gen
    def program():
        service = yield from Aead()
        errors: list[tuple[str, str, str]] = []
        for algorithm in [aead.chacha20_poly1305, aead.aes256_gcm]:
            key = yield from aead.key(algorithm, bytes(32))
            nonce = bytes(algorithm.nonce_length)
            bad_nonce = bytes(algorithm.nonce_length + 4)
            for effect in [
                service.encrypt(key, bytes(32), nonce=bad_nonce),
                service.decrypt(key, bytes(32), nonce=bad_nonce),
                service.decrypt(key, bytes(15), nonce=nonce),
            ]:
                error = yield from effect.flip()
                errors.append((error.method, error.reason.tag, error.message))
        return errors

    return program.pipe(fx.provide(built.pipe(fx.provide(fx.layer.merge(seeded, unreachable)))))


@testing.effect
def test_rejects_bad_nonces_and_short_ciphertexts_before_implementations_as_layer_web_crypto_does():
    """rejects bad nonces and short ciphertexts before implementations, as layerWebCrypto does"""
    calls, recorded_layer = recorded()
    expected = yield from _failures(aead.layer_web_crypto)
    assert [(method, reason) for method, reason, _ in expected] == [
        ("encrypt", "InvalidArgument"),
        ("decrypt", "InvalidArgument"),
        ("decrypt", "DecryptionFailed"),
        ("encrypt", "InvalidArgument"),
        ("decrypt", "InvalidArgument"),
        ("decrypt", "DecryptionFailed"),
    ]
    assert (yield from _failures(recorded_layer)) == expected
    assert calls == []


@testing.effect
def test_matches_node_crypto_chacha20_poly1305_on_random_inputs():
    """matches node:crypto ChaCha20-Poly1305 on random inputs"""
    from cryptography.hazmat.primitives.ciphers.aead import ChaCha20Poly1305

    @fx.gen
    def program():
        service = yield from Aead()
        for _ in range(64):
            # Lengths cross the 16-byte Poly1305 and 64-byte ChaCha20 blocks.
            key_bytes, nonce = os.urandom(32), os.urandom(12)
            aad = os.urandom(secrets.randbelow(40))
            plaintext = os.urandom(secrets.randbelow(300))
            expected = ChaCha20Poly1305(key_bytes).encrypt(nonce, plaintext, aad)
            key = yield from aead.key(aead.chacha20_poly1305, key_bytes)
            sealed = yield from service.encrypt(key, plaintext, nonce=nonce, aad=aad)
            assert sealed == expected
            assert (yield from service.decrypt(key, expected, nonce=nonce, aad=aad)) == plaintext

    return program.pipe(fx.provide(layer))
