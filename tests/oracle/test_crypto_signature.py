"""Ports of Effect's ``crypto/Signature.test.ts``.

``node:crypto`` verification is the ``cryptography`` package's, called
directly, independently of the layer under test.
"""

from __future__ import annotations

from typing import Any, cast

import pyfect as fx
from pyfect import testing
from pyfect.crypto import digest, secure_random, signature
from pyfect.crypto._subtle import host
from pyfect.crypto.secure_random import SecureRandom
from pyfect.crypto.signature import Signature
from pyfect.crypto.web_crypto import CryptoKey, CryptoKeyPair, KeyUsage, Params
from pyfect.layer import Layer

from ._crypto import assert_reason, encode, fake_subtle, from_hex, point, spki

# RFC 8032, section 7.1, test 2.
ED25519_SEED = "4ccd089b28ff96da9db6c346ec114e0f5b8a319f35aba624da8cf6ed4fb8a6fb"
ED25519_PUBLIC = "3d4017c3e843895a92b70aa74d1b7ebc9c982ccf2ec4968cc0cd55f12af4660c"
ED25519_MESSAGE = "72"
ED25519_SIGNATURE = (
    "92a009a9f0d4cab8720e820b5f642540a2b27b5416503f8fb3762223ebdb69da"
    "085ac1e43e15996e458f3613d0f11d8c387b2eaeb4302aeeb00d291612bb0c00"
)

# Each curve with its bound hash and its raw r‖s signature length.
ECDSA: list[tuple[signature.Ecdsa[Any], str, str, int]] = [
    (signature.ecdsa_p256, "P-256", "sha256", 64),
    (signature.ecdsa_p384, "P-384", "sha384", 96),
    (signature.ecdsa_p521, "P-521", "sha512", 132),
]

# Small moduli keep generation fast. Import ignores the modulus length.
rsa_pss_2048 = signature.rsa_pss(hash=digest.sha256, modulus_length=2048)
rsa_pkcs1v15_2048 = signature.rsa_pkcs1v15(hash=digest.sha256, modulus_length=2048)

seeded: Layer[SecureRandom] = fx.layer.succeed(
    SecureRandom, secure_random.make(lambda size: bytes([7] * size))
)
layer = signature.layer_web_crypto.pipe(fx.provide(seeded))

DATA = encode("data")


def _hash(name: str) -> Any:
    from cryptography.hazmat.primitives import hashes

    return {"sha256": hashes.SHA256(), "sha384": hashes.SHA384(), "sha512": hashes.SHA512()}[name]


def verify_ecdsa(hash_name: str, public_spki: bytes, signed: bytes) -> bool:
    """``node:crypto``'s ``ieee-p1363`` ECDSA verification."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
    from cryptography.hazmat.primitives.serialization import load_der_public_key

    key = cast("ec.EllipticCurvePublicKey", load_der_public_key(public_spki))
    half = len(signed) // 2
    der = encode_dss_signature(int.from_bytes(signed[:half]), int.from_bytes(signed[half:]))
    try:
        key.verify(der, DATA, ec.ECDSA(_hash(hash_name)))
    except InvalidSignature:
        return False
    return True


def verify_rsa(public_spki: bytes, signed: bytes, *, pss_salt: int | None = None) -> bool:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding, rsa
    from cryptography.hazmat.primitives.serialization import load_der_public_key

    key = cast("rsa.RSAPublicKey", load_der_public_key(public_spki))
    pad = (
        padding.PKCS1v15()
        if pss_salt is None
        else padding.PSS(mgf=padding.MGF1(hashes.SHA256()), salt_length=pss_salt)
    )
    try:
        key.verify(signed, DATA, pad, hashes.SHA256())
    except InvalidSignature:
        return False
    return True


def generate(params: Params, usages: tuple[KeyUsage, ...] = ("sign", "verify")) -> CryptoKeyPair:
    subtle = host.subtle
    assert subtle is not None
    pair = subtle.generate_key(params, False, usages)
    assert isinstance(pair, CryptoKeyPair)
    return pair


def rsa_pss_params() -> Params:
    return Params(
        name="RSA-PSS", hash="SHA-256", modulus_length=2048, public_exponent=bytes([1, 0, 1])
    )


@testing.effect
def test_reports_the_imported_rsa_crypto_key_modulus_rather_than_the_generation_default():
    """reports the imported RSA CryptoKey modulus rather than the generation default"""
    pair = generate(rsa_pss_params())
    key = yield from signature.private_key_from_crypto_key(
        signature.rsa_pss_sha256, pair.private_key
    )
    assert key.algorithm.modulus_length == 2048


@testing.effect
def test_signs_and_verifies_the_rfc_8032_ed25519_vector_deriving_the_public_key_from_the_seed():
    """signs and verifies the RFC 8032 Ed25519 vector, deriving the public key from the seed"""

    @fx.gen
    def program():
        service = yield from Signature()
        private_key = yield from signature.private_key(signature.ed25519, from_hex(ED25519_SEED))
        assert private_key.algorithm is signature.ed25519
        public_key = yield from service.public_key_of(private_key)
        assert (yield from signature.to_bytes(public_key)).hex() == ED25519_PUBLIC
        assert (yield from signature.to_bytes(private_key)).hex() == ED25519_SEED

        message = from_hex(ED25519_MESSAGE)
        signed = yield from service.sign(private_key, message)
        assert signed.hex() == ED25519_SIGNATURE
        imported = yield from signature.public_key(signature.ed25519, from_hex(ED25519_PUBLIC))
        assert (yield from service.verify(imported, signed, message))
        assert not (yield from service.verify(imported, signed, encode("other")))

    return program.pipe(fx.provide(layer))


@testing.effect
def test_builds_ed25519_keys_from_secure_random_bytes_and_rejects_other_raw_lengths():
    """builds Ed25519 keys from SecureRandom bytes and rejects other raw lengths"""

    @fx.gen
    def program():
        service = yield from Signature()
        pair = yield from service.generate_key_pair(signature.ed25519)
        assert (yield from signature.to_bytes(pair.private_key)) == bytes([7] * 32)
        signed = yield from service.sign(pair.private_key, DATA)
        assert (yield from service.verify(pair.public_key, signed, DATA))

        # The 64-byte libsodium seed‖pk form must be sliced by the caller.
        for length in [0, 31, 33, 64]:
            error = yield from signature.private_key(signature.ed25519, bytes(length)).flip()
            assert_reason(error, "InvalidKey", "privateKey")
        for length in [0, 31, 33]:
            error = yield from signature.public_key(signature.ed25519, bytes(length)).flip()
            assert_reason(error, "InvalidKey", "publicKey")

    return program.pipe(fx.provide(layer))


@testing.effect
def test_signs_ecdsa_in_raw_r_s_form_with_the_hash_bound_to_the_curve():
    """signs ECDSA in raw r‖s form with the hash bound to the curve"""

    @fx.gen
    def program():
        service = yield from Signature()
        for algorithm, named_curve, hash_name, length in ECDSA:
            pair = yield from service.generate_key_pair(algorithm)
            assert pair.private_key.algorithm is algorithm
            signed = yield from service.sign(pair.private_key, DATA)
            assert len(signed) == length
            assert (yield from service.verify(pair.public_key, signed, DATA))

            # The public key is an uncompressed SEC1 point.
            raw = yield from signature.to_bytes(pair.public_key)
            assert len(raw) == length + 1
            assert raw[0] == 4
            params = Params(name="ECDSA", named_curve=named_curve)
            assert verify_ecdsa(hash_name, spki(raw, params), signed)
            derived = yield from service.public_key_of(pair.private_key)
            assert (yield from signature.to_bytes(derived)) == raw

    return program.pipe(fx.provide(layer))


@testing.effect
def test_signs_rsa_pss_salted_with_the_hash_length_and_deterministic_rsassa_pkcs1_v1_5():
    """signs RSA-PSS salted with the hash length, and deterministic RSASSA-PKCS1-v1_5"""

    @fx.gen
    def program():
        service = yield from Signature()
        # Pre-made RSA values follow current NIST guidance.
        assert signature.rsa_pss_sha256.modulus_length == 3072

        pss = yield from service.generate_key_pair(rsa_pss_2048)
        assert pss.private_key.algorithm is rsa_pss_2048
        pss_signed = yield from service.sign(pss.private_key, DATA)
        assert (yield from service.verify(pss.public_key, pss_signed, DATA))
        # RSA keys hold SPKI and PKCS#8 DER.
        pss_spki = yield from signature.to_bytes(pss.public_key)
        assert verify_rsa(pss_spki, pss_signed, pss_salt=32)
        derived = yield from service.public_key_of(pss.private_key)
        assert (yield from signature.to_bytes(derived)) == pss_spki

        pkcs1 = yield from service.generate_key_pair(rsa_pkcs1v15_2048)
        pkcs1_signed = yield from service.sign(pkcs1.private_key, DATA)
        assert (yield from service.sign(pkcs1.private_key, DATA)) == pkcs1_signed
        assert (yield from service.verify(pkcs1.public_key, pkcs1_signed, DATA))
        assert verify_rsa((yield from signature.to_bytes(pkcs1.public_key)), pkcs1_signed)

    return program.pipe(fx.provide(layer))


@testing.effect
def test_checks_the_rsa_pss_salt_length_before_signing_or_verifying():
    """checks the RSA-PSS salt length before signing or verifying"""

    @fx.gen
    def program():
        service = yield from Signature()
        pair = generate(rsa_pss_params())

        def keys(salt_length: Any):
            algorithm = signature.rsa_pss(
                hash=digest.sha256, modulus_length=2048, salt_length=salt_length
            )

            @fx.gen
            def build():
                private_key = yield from signature.private_key_from_crypto_key(
                    algorithm, pair.private_key
                )
                public_key = yield from signature.public_key_from_crypto_key(
                    algorithm, pair.public_key
                )
                return private_key, public_key

            return build

        unsalted_private, unsalted_public = yield from keys(0)
        signed = yield from service.sign(unsalted_private, DATA)
        assert (yield from service.verify(unsalted_public, signed, DATA))

        # A 2048-bit key with SHA-256 fits at most 256 - 32 - 2 = 222 bytes of salt.
        for salt_length in [-1, -0.5, 1.5, 223, True]:
            private_key, public_key = yield from keys(salt_length)
            assert_reason(
                (yield from service.sign(private_key, DATA).flip()), "InvalidArgument", "sign"
            )
            error = yield from service.verify(public_key, signed, DATA).flip()
            assert_reason(error, "InvalidArgument", "verify")

    return program.pipe(fx.provide(layer))


@testing.effect
def test_returns_false_for_any_problem_with_the_signature_bytes():
    """returns false for any problem with the signature bytes"""

    @fx.gen
    def program():
        service = yield from Signature()
        algorithms: list[signature.Algorithm] = [
            signature.ed25519,
            signature.ecdsa_p256,
            signature.ecdsa_p521,
            rsa_pss_2048,
        ]
        for algorithm in algorithms:
            pair = yield from service.generate_key_pair(algorithm)
            signed = yield from service.sign(pair.private_key, DATA)
            cases = [
                bytes([signed[0] ^ 1]) + signed[1:],
                signed[1:],
                signed + b"\x00",
                b"",
                # Out of range for r and s.
                b"\xff" * len(signed),
                bytes(len(signed)),
            ]
            for bad in cases:
                ok = yield from service.verify(pair.public_key, bad, DATA)
                assert not ok, f"{algorithm.name}: {bad.hex()}"

    return program.pipe(fx.provide(layer))


@testing.effect
def test_checks_raw_ec_public_keys_rejecting_off_curve_points_when_they_are_used():
    """checks raw EC public keys, rejecting off-curve points when they are used"""

    @fx.gen
    def program():
        service = yield from Signature()
        for algorithm, _, _, length in ECDSA:
            size = length // 2
            # Compressed points and points of another size.
            for raw in [point(size, 2), point(size, 3), point(size + 1), point(size - 1)]:
                error = yield from signature.public_key(algorithm, raw).flip()
                assert_reason(error, "InvalidKey", "publicKey")
        # The point (0, 0) has the right encoding but is not on the curve.
        off_curve = yield from signature.public_key(signature.ecdsa_p256, point(32))
        error = yield from service.verify(off_curve, bytes(64), DATA).flip()
        assert_reason(error, "InvalidKey", "verify")

    def raw_ec_private() -> None:
        # EC and RSA private keys have no raw form.
        signature.private_key(signature.ecdsa_p256, bytes(32))  # pyright: ignore[reportArgumentType]

    def raw_rsa_public() -> None:
        signature.public_key(signature.rsa_pss_sha256, bytes(32))  # pyright: ignore[reportArgumentType]

    del raw_ec_private, raw_rsa_public
    return program.pipe(fx.provide(layer))


@testing.effect
def test_uses_crypto_keys_that_match_the_algorithm_without_exporting_non_extractable_ones():
    """uses CryptoKeys that match the algorithm, without exporting non-extractable ones"""

    @fx.gen
    def program():
        service = yield from Signature()
        ec = generate(Params(name="ECDSA", named_curve="P-256"))
        private_key = yield from signature.private_key_from_crypto_key(
            signature.ecdsa_p256, ec.private_key
        )
        public_key = yield from signature.public_key_from_crypto_key(
            signature.ecdsa_p256, ec.public_key
        )
        signed = yield from service.sign(private_key, DATA)
        assert (yield from service.verify(public_key, signed, DATA))
        error = yield from signature.to_bytes(private_key).flip()
        assert_reason(error, "NotExtractable", "toBytes")

        # Import ignores the modulus length: a 2048-bit key backs rsa_pss_sha256.
        rsa = generate(rsa_pss_params())
        rsa_private = yield from signature.private_key_from_crypto_key(
            signature.rsa_pss_sha256, rsa.private_key
        )
        rsa_public = yield from signature.public_key_from_crypto_key(
            signature.rsa_pss_sha256, rsa.public_key
        )
        rsa_signed = yield from service.sign(rsa_private, DATA)
        assert (yield from service.verify(rsa_public, rsa_signed, DATA))

        p384 = generate(Params(name="ECDSA", named_curve="P-384"))
        ecdh = generate(Params(name="ECDH", named_curve="P-256"), ("deriveBits",))
        # A private key must allow signing, but its public key can lack verify usage.
        sign_only = generate(Params(name="ECDSA", named_curve="P-256"), ("sign",))
        mismatched: list[tuple[signature.Algorithm, CryptoKey]] = [
            (signature.ecdsa_p256, p384.private_key),
            (signature.ecdsa_p256, ecdh.private_key),
            (signature.ecdsa_p256, ec.public_key),
            # The hash is part of an RSA algorithm.
            (signature.rsa_pss(hash=digest.sha384, modulus_length=2048), rsa.private_key),
            (signature.rsa_pkcs1v15_sha256, rsa.private_key),
        ]
        for algorithm, crypto_key in mismatched:
            error = yield from signature.private_key_from_crypto_key(algorithm, crypto_key).flip()
            assert_reason(error, "InvalidKey", "privateKeyFromCryptoKey")
        error = yield from signature.public_key_from_crypto_key(
            signature.ecdsa_p256, sign_only.public_key
        ).flip()
        assert_reason(error, "InvalidKey", "publicKeyFromCryptoKey")
        error = yield from signature.public_key_from_crypto_key(
            signature.ecdsa_p256, ec.private_key
        ).flip()
        assert_reason(error, "InvalidKey", "publicKeyFromCryptoKey")

    return program.pipe(fx.provide(layer))


@testing.effect
def test_tells_private_and_public_keys_apart_and_redacts_private_keys():
    """tells private and public keys apart, and redacts private keys"""

    @fx.gen
    def program():
        service = yield from Signature()
        pair = yield from service.generate_key_pair(signature.ed25519)
        assert signature.is_private_key(pair.private_key)
        assert not signature.is_private_key(pair.public_key)
        assert signature.is_public_key(pair.public_key)
        assert not signature.is_public_key(pair.private_key)
        assert not signature.is_public_key(bytes(32))

        other = yield from signature.private_key(signature.ed25519, bytes([1] * 32))
        assert str(pair.private_key) == str(other)
        assert pair.private_key.to_json() == other.to_json()
        assert repr(pair.private_key) == repr(other)
        assert str(other) == '{"_id":"Signature.PrivateKey","algorithm":"ed25519"}'

    return program.pipe(fx.provide(layer))


@testing.effect
def test_rejects_a_signature_of_the_wrong_length_before_web_crypto_sees_it():
    """Effect's ``verify`` checks ``signature.length`` against the algorithm
    before calling Web Crypto (``Signature.ts``), so an implementation that
    accepts any bytes still gets only well-formed signatures."""

    @fx.gen
    def program():
        service = yield from Signature()
        public_key = yield from signature.public_key(signature.ed25519, bytes(32))
        assert (yield from service.verify(public_key, bytes(64), DATA))
        for length in [0, 63, 65]:
            assert not (yield from service.verify(public_key, bytes(length), DATA))

    accepts_all = fake_subtle(verify=lambda *_args: True)
    under_test = signature.layer_web_crypto.pipe(fx.provide(seeded)).pipe(fx.provide(accepts_all))
    return program.pipe(fx.provide(under_test))
