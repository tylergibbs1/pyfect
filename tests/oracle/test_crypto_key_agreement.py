"""Ports of Effect's ``crypto/KeyAgreement.test.ts``.

``node:crypto``'s ``diffieHellman`` is the ``cryptography`` package's
``exchange``, called directly on the stored forms.
"""

from __future__ import annotations

from typing import Any, Literal, cast

import pyfect as fx
from pyfect import testing
from pyfect.crypto import key_agreement, secure_random
from pyfect.crypto._subtle import host
from pyfect.crypto.key_agreement import KeyAgreement
from pyfect.crypto.secure_random import SecureRandom
from pyfect.crypto.web_crypto import AlgorithmIdentifier, CryptoKey, CryptoKeyPair, KeyUsage, Params
from pyfect.layer import Layer

from ._crypto import assert_reason, fake_subtle, from_hex, point, spki

# RFC 7748, section 6.1.
ALICE = "77076d0a7318a57d3c16c17251b26645df4c2f87ebc0992ab177fba51db92c2a"
ALICE_PUBLIC = "8520f0098930a754748b7ddcb43ef75a0dbf3a0d26381af4eba4a98eaa9b4e6a"
BOB = "5dab087e624a8a4b79e17f8b83800ee66f3bb1292618b6fd1c2f8b27ff88e0eb"
BOB_PUBLIC = "de9edb7d7b7dc1b4d35b61c2ece435373f8343c85b78674dadfc7e146f882b4f"
SHARED = "4a5d9d5ba4ce2de1728e3bf480350f25e07e21c947d19e3376f09b3c1e161742"

# Each curve with its coordinate size, which is also the shared secret's.
ECDH: list[tuple[key_agreement.Ecdh[Any], str, int]] = [
    (key_agreement.ecdh_p256, "P-256", 32),
    (key_agreement.ecdh_p384, "P-384", 48),
    (key_agreement.ecdh_p521, "P-521", 66),
]

seeded: Layer[SecureRandom] = fx.layer.succeed(
    SecureRandom, secure_random.make(lambda size: bytes([7] * size))
)
layer = key_agreement.layer_web_crypto.pipe(fx.provide(seeded))


def generate(
    params: AlgorithmIdentifier, usages: tuple[KeyUsage, ...] = ("deriveBits",)
) -> CryptoKeyPair:
    subtle = host.subtle
    assert subtle is not None
    pair = subtle.generate_key(params, False, usages)
    assert isinstance(pair, CryptoKeyPair)
    return pair


def exchange(pkcs8: bytes, public_spki: bytes) -> bytes:
    from cryptography.hazmat.primitives.asymmetric import ec
    from cryptography.hazmat.primitives.serialization import (
        load_der_private_key,
        load_der_public_key,
    )

    private_key = cast("ec.EllipticCurvePrivateKey", load_der_private_key(pkcs8, None))
    public_key = cast("ec.EllipticCurvePublicKey", load_der_public_key(public_spki))
    return private_key.exchange(ec.ECDH(), public_key)


@testing.effect
def test_derives_the_rfc_7748_x25519_shared_secret_on_both_sides():
    """derives the RFC 7748 X25519 shared secret on both sides"""

    @fx.gen
    def program():
        service = yield from KeyAgreement()
        alice = yield from key_agreement.private_key(key_agreement.x25519, from_hex(ALICE))
        bob = yield from key_agreement.private_key(key_agreement.x25519, from_hex(BOB))
        assert alice.algorithm is key_agreement.x25519
        assert (yield from key_agreement.to_bytes(alice)).hex() == ALICE
        alice_derived = yield from service.public_key_of(alice)
        assert (yield from key_agreement.to_bytes(alice_derived)).hex() == ALICE_PUBLIC
        bob_public = yield from key_agreement.public_key(key_agreement.x25519, from_hex(BOB_PUBLIC))
        alice_public = yield from key_agreement.public_key(
            key_agreement.x25519, from_hex(ALICE_PUBLIC)
        )
        assert (yield from service.derive_shared_secret(alice, bob_public)).hex() == SHARED
        assert (yield from service.derive_shared_secret(bob, alice_public)).hex() == SHARED

    return program.pipe(fx.provide(layer))


@testing.effect
def test_builds_x25519_keys_from_secure_random_bytes_and_rejects_other_raw_lengths():
    """builds X25519 keys from SecureRandom bytes and rejects other raw lengths"""

    @fx.gen
    def program():
        service = yield from KeyAgreement()
        pair = yield from service.generate_key_pair(key_agreement.x25519)
        assert (yield from key_agreement.to_bytes(pair.private_key)) == bytes([7] * 32)
        derived = yield from service.public_key_of(pair.private_key)
        assert (yield from key_agreement.to_bytes(derived)) == (
            yield from key_agreement.to_bytes(pair.public_key)
        )

        # The 64-byte libsodium seed‖pk form must be sliced by the caller.
        for length in [0, 31, 33, 64]:
            error = yield from key_agreement.private_key(key_agreement.x25519, bytes(length)).flip()
            assert_reason(error, "InvalidKey", "privateKey")
        for length in [0, 31, 33]:
            error = yield from key_agreement.public_key(key_agreement.x25519, bytes(length)).flip()
            assert_reason(error, "InvalidKey", "publicKey")

    return program.pipe(fx.provide(layer))


@testing.effect
def test_derives_ecdh_secrets_of_the_coordinate_size_storing_sec1_points_and_pkcs8_private_keys():
    """derives ECDH secrets of the coordinate size, storing SEC1 points and PKCS#8 private keys"""

    @fx.gen
    def program():
        service = yield from KeyAgreement()
        for algorithm, named_curve, size in ECDH:
            first = yield from service.generate_key_pair(algorithm)
            second = yield from service.generate_key_pair(algorithm)
            assert first.private_key.algorithm is algorithm
            shared = yield from service.derive_shared_secret(first.private_key, second.public_key)
            assert len(shared) == size
            assert (
                yield from service.derive_shared_secret(second.private_key, first.public_key)
            ) == shared

            raw = yield from key_agreement.to_bytes(second.public_key)
            assert len(raw) == 2 * size + 1
            assert raw[0] == 4
            derived = yield from service.public_key_of(second.private_key)
            assert (yield from key_agreement.to_bytes(derived)) == raw
            # cryptography reads the stored forms and agrees on the secret.
            pkcs8 = yield from key_agreement.to_bytes(first.private_key)
            public_spki = spki(raw, Params(name="ECDH", named_curve=named_curve))
            assert exchange(pkcs8, public_spki) == shared

    return program.pipe(fx.provide(layer))


@testing.effect
def test_checks_raw_ec_public_keys_and_keeps_curves_apart_in_the_types():
    """checks raw EC public keys and keeps curves apart in the types"""

    @fx.gen
    def program():
        service = yield from KeyAgreement()
        for algorithm, _, size in ECDH:
            for raw in [point(size, 2), point(size, 3), point(size + 1), point(size - 1)]:
                error = yield from key_agreement.public_key(algorithm, raw).flip()
                assert_reason(error, "InvalidKey", "publicKey")
        # The point (0, 0) has the right encoding but is not on the curve.
        p256 = yield from service.generate_key_pair(key_agreement.ecdh_p256)
        off_curve = yield from key_agreement.public_key(key_agreement.ecdh_p256, point(32))
        error = yield from service.derive_shared_secret(p256.private_key, off_curve).flip()
        assert_reason(error, "InvalidKey", "deriveSharedSecret")

        # Keys typed with Any algorithm still differ at run time.
        p384 = yield from service.generate_key_pair(key_agreement.ecdh_p384)
        mixed_private: key_agreement.PrivateKey[Any] = p256.private_key
        mixed_public: key_agreement.PublicKey[Any] = p384.public_key
        error = yield from service.derive_shared_secret(mixed_private, mixed_public).flip()
        assert_reason(error, "InvalidKey", "deriveSharedSecret")
        assert error.message == (
            "KeyAgreement.deriveSharedSecret: Expected a ecdhP256 public key, not ecdhP384"
        )

    def mixed(
        service: key_agreement.KeyAgreementService,
        p256: key_agreement.KeyPair[key_agreement.Ecdh[Literal["P-256"]]],
        p384: key_agreement.PublicKey[key_agreement.Ecdh[Literal["P-384"]]],
        x25519: key_agreement.PrivateKey[key_agreement.X25519],
    ) -> None:
        service.derive_shared_secret(p256.private_key, p384)  # pyright: ignore[reportArgumentType]
        service.derive_shared_secret(x25519, p256.public_key)  # pyright: ignore[reportArgumentType]
        # Only X25519 private keys have a raw form.
        key_agreement.private_key(key_agreement.ecdh_p256, bytes(32))  # pyright: ignore[reportArgumentType]

    del mixed
    return program.pipe(fx.provide(layer))


# Runtimes either reject a low-order point or return the all-zero output.
@testing.effect
def test_rejects_a_low_order_x25519_peer_key():
    """rejects a low-order X25519 peer key"""
    low_order = yield from key_agreement.public_key(key_agreement.x25519, bytes(32))
    zeros = fx.layer.merge(seeded, fake_subtle(derive_bits=lambda *_args: bytes(32)))
    for provided in [seeded, zeros]:

        @fx.gen
        def program():
            service = yield from KeyAgreement()
            private_key = yield from key_agreement.private_key(
                key_agreement.x25519, bytes([7] * 32)
            )
            return (yield from service.derive_shared_secret(private_key, low_order).flip())

        error = yield from program.pipe(
            fx.provide(key_agreement.layer_web_crypto.pipe(fx.provide(provided)))
        )
        assert_reason(error, "InvalidKey", "deriveSharedSecret")


@testing.effect
def test_uses_crypto_keys_that_match_the_algorithm_without_exporting_non_extractable_ones():
    """uses CryptoKeys that match the algorithm, without exporting non-extractable ones"""

    @fx.gen
    def program():
        service = yield from KeyAgreement()
        ec = generate(Params(name="ECDH", named_curve="P-256"))
        private_key = yield from key_agreement.private_key_from_crypto_key(
            key_agreement.ecdh_p256, ec.private_key
        )
        public_key = yield from key_agreement.public_key_from_crypto_key(
            key_agreement.ecdh_p256, ec.public_key
        )
        peer = yield from service.generate_key_pair(key_agreement.ecdh_p256)
        assert (yield from service.derive_shared_secret(private_key, peer.public_key)) == (
            yield from service.derive_shared_secret(peer.private_key, public_key)
        )
        error = yield from key_agreement.to_bytes(private_key).flip()
        assert_reason(error, "NotExtractable", "toBytes")

        x25519 = generate("X25519")
        yield from key_agreement.private_key_from_crypto_key(
            key_agreement.x25519, x25519.private_key
        )

        p384 = generate(Params(name="ECDH", named_curve="P-384"))
        ecdsa = generate(Params(name="ECDSA", named_curve="P-256"), ("sign", "verify"))
        derive_key_only = generate(Params(name="ECDH", named_curve="P-256"), ("deriveKey",))
        mismatched: list[tuple[key_agreement.Algorithm, CryptoKey]] = [
            (key_agreement.ecdh_p256, p384.private_key),
            (key_agreement.ecdh_p256, ecdsa.private_key),
            (key_agreement.ecdh_p256, ec.public_key),
            (key_agreement.ecdh_p256, derive_key_only.private_key),
            (key_agreement.ecdh_p256, x25519.private_key),
            (key_agreement.x25519, ec.private_key),
        ]
        for algorithm, crypto_key in mismatched:
            error = yield from key_agreement.private_key_from_crypto_key(
                algorithm, crypto_key
            ).flip()
            assert_reason(error, "InvalidKey", "privateKeyFromCryptoKey")
        error = yield from key_agreement.public_key_from_crypto_key(
            key_agreement.ecdh_p256, p384.public_key
        ).flip()
        assert_reason(error, "InvalidKey", "publicKeyFromCryptoKey")

    return program.pipe(fx.provide(layer))


@testing.effect
def test_tells_private_and_public_keys_apart_and_redacts_private_keys():
    """tells private and public keys apart, and redacts private keys"""

    @fx.gen
    def program():
        service = yield from KeyAgreement()
        pair = yield from service.generate_key_pair(key_agreement.x25519)
        assert key_agreement.is_private_key(pair.private_key)
        assert not key_agreement.is_private_key(pair.public_key)
        assert key_agreement.is_public_key(pair.public_key)
        assert not key_agreement.is_public_key(pair.private_key)
        assert not key_agreement.is_public_key(bytes(32))

        other = yield from key_agreement.private_key(key_agreement.x25519, bytes([1] * 32))
        assert str(pair.private_key) == str(other)
        assert pair.private_key.to_json() == other.to_json()
        assert repr(pair.private_key) == repr(other)

    return program.pipe(fx.provide(layer))
