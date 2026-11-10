"""Ports of Effect's ``crypto/Cipher.test.ts``."""

from __future__ import annotations

import pyfect as fx
from pyfect import testing
from pyfect.crypto import cipher, mac, secure_random
from pyfect.crypto._subtle import host
from pyfect.crypto.cipher import Cipher
from pyfect.crypto.secure_random import SecureRandom
from pyfect.crypto.web_crypto import CryptoKey, KeyUsage
from pyfect.layer import Layer

from ._crypto import assert_reason, from_hex, unreachable, view

# NIST SP 800-38A, appendix F.2 and F.5.
KEY_128 = "2b7e151628aed2a6abf7158809cf4f3c"
KEY_256 = "603deb1015ca71be2b73aef0857d77811f352c073b6108d72d9810a30914dff4"
PLAINTEXT = from_hex(
    "6bc1bee22e409f96e93d7e117393172aae2d8a571e03ac9c9eb76fac45af8e51"
    "30c81c46a35ce411e5fbc1191a0a52eff69f2445df4f9b17ad2b417be66c3710"
)
CTR_IV = "f0f1f2f3f4f5f6f7f8f9fafbfcfdfeff"
CBC_IV = "000102030405060708090a0b0c0d0e0f"
VECTORS: list[tuple[cipher.Algorithm, str, str, str]] = [
    (
        cipher.aes128_ctr,
        KEY_128,
        CTR_IV,
        "874d6191b620e3261bef6864990db6ce9806f66b7970fdff8617187bb9fffdff"
        "5ae4df3edbd5d35e5b4f09020db03eab1e031dda2fbe03d1792170a0f3009cee",
    ),
    (
        cipher.aes256_ctr,
        KEY_256,
        CTR_IV,
        "601ec313775789a5b7a7f504bbf3d228f443e3ca4d62b59aca84e990cacaf5c5"
        "2b0930daa23de94ce87017ba2d84988ddfc9c58db67aada613c2dd08457941a6",
    ),
    # The NIST ciphertext followed by the PKCS#7 padding block, from OpenSSL.
    (
        cipher.aes128_cbc,
        KEY_128,
        CBC_IV,
        "7649abac8119b246cee98e9b12e9197d5086cb9b507219ee95db113a917678b2"
        "73bed6b8e3c1743b7116e69e222295163ff1caa1681fac09120eca307586e1a7"
        "8cb82807230e1321d3fae00d18cc2012",
    ),
    (
        cipher.aes256_cbc,
        KEY_256,
        CBC_IV,
        "f58c4c04d6e5f1ba779eabfb5f7bfbd69cfc4e967edb808d679f777bc6702c7d"
        "39f23369a9d9bacfa530e26304231461b2eb05e2c39be9fcda6c19078c6a9d1b"
        "3f461796d6b0d6b2e0c2a72b4d80e644",
    ),
]

seeded: Layer[SecureRandom] = fx.layer.succeed(
    SecureRandom, secure_random.make(lambda size: bytes([7] * size))
)
layer = cipher.layer_web_crypto.pipe(fx.provide(seeded))


def import_aes(
    name: str, length: int, usages: tuple[KeyUsage, ...] = ("encrypt", "decrypt")
) -> CryptoKey:
    subtle = host.subtle
    assert subtle is not None
    return subtle.import_key("raw", bytes([1] * (length // 8)), name, False, usages)


@testing.effect
def test_is_key_accepts_cipher_keys_and_rejects_mac_keys():
    """isKey accepts Cipher keys and rejects Mac keys"""
    data = bytes(32)
    assert cipher.is_key((yield from cipher.key(cipher.aes256_ctr, data)))
    assert not cipher.is_key((yield from mac.key(mac.hmac_sha256, data)))


@testing.effect
def test_encrypts_and_decrypts_the_published_vectors():
    """encrypts and decrypts the published vectors"""

    @fx.gen
    def program():
        service = yield from Cipher()
        for algorithm, key_hex, iv, expected in VECTORS:
            key = yield from cipher.key(algorithm, from_hex(key_hex))
            assert key.algorithm is algorithm
            iv_view = view(from_hex(iv))
            assert (yield from service.encrypt(key, view(PLAINTEXT), iv=iv_view)).hex() == expected
            decrypted = yield from service.decrypt(key, view(from_hex(expected)), iv=iv_view)
            assert decrypted == PLAINTEXT

    return program.pipe(fx.provide(layer))


# A 64-bit counter would wrap to zero after the first block instead of
# carrying into the upper half, as OpenSSL, Go and noble do.
@testing.effect
def test_counts_aes_ctr_blocks_with_the_whole_128_bit_block():
    """counts AES-CTR blocks with the whole 128-bit block"""
    from cryptography.hazmat.primitives.ciphers import Cipher as Primitive
    from cryptography.hazmat.primitives.ciphers import algorithms, modes

    @fx.gen
    def program():
        service = yield from Cipher()
        key_bytes = from_hex(KEY_128)
        iv = from_hex("0000000000000000ffffffffffffffff")
        data = bytes(48)
        encryptor = Primitive(algorithms.AES(key_bytes), modes.CTR(iv)).encryptor()
        expected = encryptor.update(data) + encryptor.finalize()
        key = yield from cipher.key(cipher.aes128_ctr, key_bytes)
        assert (yield from service.encrypt(key, data, iv=iv)) == expected
        # The second block's counter carries into the upper half.
        second = Primitive(algorithms.AES(key_bytes), modes.ECB()).encryptor()
        counter = from_hex("00000000000000010000000000000000")
        assert expected[16:32] == second.update(counter)

    return program.pipe(fx.provide(layer))


# Distinguishable padding and length failures would be a padding oracle.
@testing.effect
def test_fails_aes_cbc_decryption_identically_for_bad_padding_and_bad_lengths_never_ctr():
    """fails AES-CBC decryption identically for bad padding and bad lengths, and never fails AES-CTR"""  # noqa: E501

    @fx.gen
    def program():
        service = yield from Cipher()
        iv = from_hex(CBC_IV)
        messages: set[str] = set()
        for algorithm, key_hex, _, sealed in VECTORS[2:]:
            key = yield from cipher.key(algorithm, from_hex(key_hex))
            ciphertext = from_hex(sealed)
            # The last plaintext block is all padding, so this turns its
            # final 0x10 into 0x00.
            bad_padding = ciphertext[:63] + bytes([ciphertext[63] ^ 0x10]) + ciphertext[64:]
            for data in [bad_padding, ciphertext[:79], ciphertext[:15], b""]:
                error = yield from service.decrypt(key, data, iv=iv).flip()
                assert error.module == "Cipher"
                assert_reason(error, "DecryptionFailed", "decrypt")
                assert error.cause is None
                assert error.__cause__ is None
                messages.add(error.message)
        assert len(messages) == 1

        ctr = yield from cipher.key(cipher.aes128_ctr, from_hex(KEY_128))
        for data in [from_hex(VECTORS[2][3]), bytes(15)]:
            assert len((yield from service.decrypt(ctr, data, iv=iv))) == len(data)

    return program.pipe(fx.provide(layer))


@testing.effect
def test_checks_the_iv_length_before_calling_web_crypto():
    """checks the IV length before calling Web Crypto"""

    @fx.gen
    def program():
        service = yield from Cipher()
        cases: list[tuple[cipher.Algorithm, int]] = [
            (cipher.aes128_ctr, 16),
            (cipher.aes256_ctr, 32),
            (cipher.aes128_cbc, 16),
            (cipher.aes256_cbc, 32),
        ]
        for algorithm, key_length in cases:
            key = yield from cipher.key(algorithm, bytes(key_length))
            for length in [0, 12, 15, 17]:
                iv, data = bytes(length), bytes(32)
                error = yield from service.encrypt(key, data, iv=iv).flip()
                assert_reason(error, "InvalidArgument", "encrypt")
                error = yield from service.decrypt(key, data, iv=iv).flip()
                assert_reason(error, "InvalidArgument", "decrypt")

    return program.pipe(
        fx.provide(cipher.layer_web_crypto.pipe(fx.provide(fx.layer.merge(seeded, unreachable))))
    )


@testing.effect
def test_builds_keys_from_bytes_secure_random_and_matching_crypto_keys():
    """builds keys from bytes, SecureRandom and matching CryptoKeys"""

    @fx.gen
    def program():
        service = yield from Cipher()
        # No AES-192.
        cases: list[tuple[cipher.Algorithm, int, list[int]]] = [
            (cipher.aes128_ctr, 16, [0, 24, 32]),
            (cipher.aes256_ctr, 32, [0, 16, 24]),
            (cipher.aes128_cbc, 16, [0, 24, 32]),
            (cipher.aes256_cbc, 32, [0, 16, 24]),
        ]
        for algorithm, length, wrong_lengths in cases:
            key = yield from service.generate_key(algorithm)
            assert key.algorithm is algorithm
            assert (yield from cipher.to_bytes(key)) == bytes([7] * length)
            for wrong in wrong_lengths:
                error = yield from cipher.key(algorithm, bytes(wrong)).flip()
                assert_reason(error, "InvalidKey", "key")

        key = yield from cipher.from_crypto_key(cipher.aes256_cbc, import_aes("AES-CBC", 256))
        byte_key = yield from cipher.key(cipher.aes256_cbc, bytes([1] * 32))
        iv = from_hex(CBC_IV)
        encrypted = yield from service.encrypt(key, PLAINTEXT, iv=iv)
        assert (yield from service.decrypt(byte_key, encrypted, iv=iv)) == PLAINTEXT
        assert_reason((yield from cipher.to_bytes(key).flip()), "NotExtractable", "toBytes")

        mismatched = [
            import_aes("AES-CBC", 128),
            import_aes("AES-CTR", 256),
            import_aes("AES-CBC", 256, ("decrypt",)),
        ]
        for crypto_key in mismatched:
            error = yield from cipher.from_crypto_key(cipher.aes256_cbc, crypto_key).flip()
            assert_reason(error, "InvalidKey", "fromCryptoKey")

    return program.pipe(fx.provide(layer))
