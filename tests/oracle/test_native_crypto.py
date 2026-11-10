"""Ports of Effect's ``platform/node/test/NodeCrypto.test.ts``
(``pyfect.crypto.native``: the host's own libraries)."""

from __future__ import annotations

import pyfect as fx
from pyfect import testing
from pyfect.crypto import aead, digest, kdf, mac, native, secure_random
from pyfect.crypto._subtle import host
from pyfect.crypto.aead import Aead
from pyfect.crypto.digest import Digest
from pyfect.crypto.kdf import Kdf
from pyfect.crypto.mac import Mac
from pyfect.crypto.web_crypto import Params

from ._crypto import encode, from_hex

# RFC 8439, section 2.8.2, and draft-irtf-cfrg-xchacha-03, Appendix A.3.1.
SUNSCREEN = encode(
    "Ladies and Gentlemen of the class of '99: If I could offer you only one tip for the "
    "future, sunscreen would be it."
)
CHACHA_KEY = "808182838485868788898a8b8c8d8e8f909192939495969798999a9b9c9d9e9f"
AEAD_VECTORS: list[tuple[aead.Algorithm, str, str, str]] = [
    (
        aead.chacha20_poly1305,
        CHACHA_KEY,
        "070000004041424344454647",
        "d31a8d34648e60db7b86afbc53ef7ec2a4aded51296e08fea9e2b5a736ee62d63dbea45e8ca9671282fafb69da92728b"
        "1a71de0a9e060b2905d6a5b67ecd3b3692ddbd7f2d778b8c9803aee328091b58fab324e4fad675945585808b4831d7bc"
        "3ff4def08e4b7a9de576d26586cec64b61161ae10b594f09e26a7e902ecbd0600691",
    ),
    (
        aead.xchacha20_poly1305,
        CHACHA_KEY,
        "404142434445464748494a4b4c4d4e4f5051525354555657",
        "bd6d179d3e83d43b9576579493c0e939572a1700252bfaccbed2902c21396cbb731c7f1b0b4aa6440bf3a82f4eda7e39"
        "ae64c6708c54c216cb96b72e1213b4522f8c9ba40db5d945b11b69b982c1bb9e3f3fac2bc369488f76b2383565d3fff9"
        "21f9664c97637da9768812f615c68b13b52ec0875924c1c7987947deafd8780acf49",
    ),
]

aead_layer = native.layer_aead.pipe(fx.provide(secure_random.layer_web_crypto))


@testing.effect
def test_layer_digest_computes_md5_and_sha_digests():
    """layerDigest computes MD5 and SHA digests"""

    @fx.gen
    def program():
        service = yield from Digest()
        abc = encode("abc")
        # RFC 1321 and FIPS 180-2 "abc" vectors.
        assert (
            yield from service.digest_hex(digest.md5, abc)
        ) == "900150983cd24fb0d6963f7d28e17f72"
        assert (
            yield from service.digest_hex(digest.sha1, abc)
        ) == "a9993e364706816aba3e25717850c26c9cd0d89d"
        assert (
            yield from service.digest_hex(digest.sha256, abc)
        ) == "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad"
        assert len((yield from service.digest(digest.sha512, abc))) == 64

    return program.pipe(fx.provide(native.layer_digest))


@testing.effect
def test_layer_mac_signs_with_byte_backed_and_crypto_key_backed_keys():
    """layerMac signs with byte-backed and CryptoKey-backed keys"""

    @fx.gen
    def program():
        subtle = host.subtle
        assert subtle is not None
        service = yield from Mac()
        # RFC 4231, test case 2.
        secret = encode("Jefe")
        message = encode("what do ya want for nothing?")
        expected = "5bdcc146bf60754e6a042426089575c75a003f089d2739839dec58b964ec3843"
        crypto_key = subtle.import_key(
            "raw", secret, Params(name="HMAC", hash="SHA-256"), False, ["sign", "verify"]
        )
        keys = [
            (yield from mac.key(mac.hmac_sha256, secret)),
            (yield from mac.from_crypto_key(mac.hmac_sha256, crypto_key)),
        ]
        for key in keys:
            tag = yield from service.sign(key, message)
            assert tag.hex() == expected
            assert (yield from service.verify(key, tag, message))
            assert not (yield from service.verify(key, memoryview(tag)[1:], message))

    return program.pipe(fx.provide(native.layer_mac))


@testing.effect
def test_layer_kdf_derives_argon2id_where_the_host_has_it_and_hkdf_through_the_core():
    """layerKdf derives Argon2id where node:crypto has it, and HKDF through the core implementation"""  # noqa: E501

    @fx.gen
    def program():
        service = yield from Kdf()
        password = encode("password")
        salt = encode("somesalt")
        # From the Argon2 reference CLI: `argon2 somesalt -id -t 2 -k 64 -p 1 -l 32`.
        argon2id = kdf.argon2id(memory=64, passes=2, parallelism=1)
        derived = yield from service.derive(argon2id, password, salt=salt, length=32).result()
        match derived:
            case fx.Ok(value):
                assert value.hex() == (
                    "16a1a498734609dd01456da406de9f3d9da93e6c86c300a12fc1465214ce4922"
                )
            case fx.Err(error):
                assert error.reason.tag == "Unsupported"
        # RFC 5869, test case 3.
        hkdf = yield from service.derive(kdf.hkdf_sha256, bytes([0x0B] * 22), salt=b"", length=42)
        assert hkdf.hex() == (
            "8da4e775a563c18f715f802a063c5a31b8a11f5c5ee1879ec3454e5f3c738d2d9d201395faa4b61a96c8"
        )

    return program.pipe(fx.provide(native.layer_kdf))


@testing.effect
def test_layer_aead_encrypts_chacha20_poly1305_natively_and_the_rest_through_the_core():
    """layerAead encrypts ChaCha20-Poly1305 on node:crypto and the other algorithms through the core implementation"""  # noqa: E501

    @fx.gen
    def program():
        subtle = host.subtle
        assert subtle is not None
        service = yield from Aead()
        aad = from_hex("50515253c0c1c2c3c4c5c6c7")
        for algorithm, key_hex, nonce_hex, expected in AEAD_VECTORS:
            key = yield from aead.key(algorithm, from_hex(key_hex))
            nonce = from_hex(nonce_hex)
            sealed = yield from service.encrypt(key, SUNSCREEN, nonce=nonce, aad=aad)
            assert sealed.hex() == expected
            assert (yield from service.decrypt(key, sealed, nonce=nonce, aad=aad)) == SUNSCREEN
            tampered = sealed[:-1] + bytes([sealed[-1] ^ 1])
            for data in [tampered, tampered[:15]]:
                error = yield from service.decrypt(key, data, nonce=nonce, aad=aad).flip()
                assert error.reason.tag == "DecryptionFailed"
                assert error.message == "Aead.decrypt: Could not decrypt the data"
            # The native implementation would raise its own error for a wrong nonce length.
            error = yield from service.encrypt(key, SUNSCREEN, nonce=bytes(16)).flip()
            assert error.reason.tag == "InvalidArgument"

        crypto_key = subtle.import_key("raw", bytes(32), "AES-GCM", False, ["encrypt", "decrypt"])
        keys = [
            (yield from aead.key(aead.aes256_gcm, bytes(32))),
            (yield from aead.from_crypto_key(aead.aes256_gcm, crypto_key)),
        ]
        for key in keys:
            # The GCM specification, test case 13.
            sealed = yield from service.encrypt(key, b"", nonce=bytes(12))
            assert sealed.hex() == "530f8afbc74536b9a963b4f1c4cb738b"

    return program.pipe(fx.provide(aead_layer))


# An effect may run later than it is built, so the native implementation
# must not see a nonce that was valid only when the effect was built.
@testing.effect
def test_layer_aead_checks_the_chacha20_poly1305_nonce_length_when_the_effect_runs():
    """layerAead checks the ChaCha20-Poly1305 nonce length when the effect runs"""

    @fx.gen
    def program():
        service = yield from Aead()
        key = yield from aead.key(aead.chacha20_poly1305, from_hex(CHACHA_KEY))
        nonce = bytearray(12)
        data = bytes(32)
        encrypt = service.encrypt(key, data, nonce=nonce)
        decrypt = service.decrypt(key, data, nonce=nonce)
        nonce.extend(bytes(4))
        assert (yield from encrypt.flip()).reason.tag == "InvalidArgument"
        assert (yield from decrypt.flip()).reason.tag == "InvalidArgument"

    return program.pipe(fx.provide(aead_layer))
