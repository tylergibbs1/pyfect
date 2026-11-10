"""Ports of Effect's ``crypto/Kdf.test.ts``."""

from __future__ import annotations

import pyfect as fx
from pyfect import testing
from pyfect.crypto import digest, kdf
from pyfect.crypto.kdf import Kdf

from ._crypto import assert_reason, encode, from_hex, unreachable


@testing.effect
def test_derives_the_published_hkdf_and_pbkdf2_vectors():
    """derives the published HKDF and PBKDF2 vectors"""

    @fx.gen
    def program():
        service = yield from Kdf()
        # RFC 5869, test case 1.
        okm = yield from service.derive(
            kdf.hkdf_sha256,
            bytes([0x0B] * 22),
            salt=from_hex("000102030405060708090a0b0c"),
            info=from_hex("f0f1f2f3f4f5f6f7f8f9"),
            length=42,
        )
        assert okm.hex() == (
            "3cb25f25faacd57a90434f64d0362f2a2d2d0a90cf1a5a4c5db02d56ecc4c5bf34007208d5b887185865"
        )
        # PBKDF2-HMAC-SHA256, "password" / "salt" at 2 iterations.
        derived = yield from service.derive(
            kdf.pbkdf2(hash=digest.sha256, iterations=2),
            encode("password"),
            salt=encode("salt"),
            length=32,
        )
        assert derived.hex() == "ae4d0c95af6b46d32d0adff928f06dd02a303f8ef3c251dfd6e2d85a95474c43"

    return program.pipe(fx.provide(kdf.layer_web_crypto))


# Some backends wrap lengths of 2^32 bits or more, and Node.js aborts the
# process on PBKDF2 iteration counts of 2^31 or more.
@testing.effect
def test_checks_arguments_before_calling_web_crypto():
    """checks arguments before calling Web Crypto"""

    @fx.gen
    def program():
        service = yield from Kdf()
        data = bytes(16)
        cases: list[tuple[kdf.Algorithm, int, bytes | None]] = [
            (kdf.hkdf_sha256, 0, None),
            (kdf.hkdf_sha256, 255 * 32 + 1, None),
            (kdf.pbkdf2(hash=digest.sha256, iterations=0), 32, None),
            (kdf.pbkdf2(hash=digest.sha256, iterations=2**31), 32, None),
            (kdf.pbkdf2(hash=digest.sha256, iterations=1), 2**29, None),
            # info only applies to HKDF.
            (kdf.pbkdf2_sha256, 32, data),
            (kdf.hkdf(digest.md5), 32, None),
        ]
        for algorithm, length, info in cases:
            error = yield from service.derive(
                algorithm, data, salt=data, length=length, info=info
            ).flip()
            assert_reason(error, "InvalidArgument", "derive")

    return program.pipe(fx.provide(kdf.layer_web_crypto.pipe(fx.provide(unreachable))))


@testing.effect
def test_does_not_provide_argon2id_in_the_web_crypto_layer():
    """does not provide Argon2id in the Web Crypto layer"""

    @fx.gen
    def program():
        # Omitted costs default to RFC 9106's second recommended setting:
        # 64 MiB, 3 passes, 4 lanes.
        assert kdf.argon2id() == kdf.Argon2id(memory=65_536, passes=3, parallelism=4)
        assert kdf.argon2id().name == "argon2id"
        assert kdf.argon2id(memory=19_456) == kdf.Argon2id(memory=19_456, passes=3, parallelism=4)
        service = yield from Kdf()
        error = yield from service.derive(
            kdf.argon2id(), encode("password"), salt=encode("somesalt"), length=32
        ).flip()
        assert error.module == "Kdf"
        assert_reason(error, "Unsupported", "derive")

    return program.pipe(fx.provide(kdf.layer_web_crypto))
