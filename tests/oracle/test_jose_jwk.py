"""Ports of Effect's ``jose/Jwk.test.ts``."""

from __future__ import annotations

from typing import Any, cast

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.crypto import digest, signature
from pyfect.jose import jwk, jwks, jws
from pyfect.jose.jwk import PrivateJwk, PublicJwk, SecretJwk
from pyfect.redacted import Redacted
from pyfect.redacted import make as redacted
from pyfect.redacted import value as reveal

from ._jose import (
    ES256_JWK,
    ES256_PUBLIC_JWK,
    HS256_JWK,
    NODE,
    RS256_JWK,
    RS256_PUBLIC_JWK,
    SECRET_JWK,
    assert_reason,
    b64,
    layer,
    reference_verify,
    unb64,
    utf8,
    without,
)


@testing.effect
def test_generates_algorithm_bound_key_pairs_that_import_for_signing_and_verification():
    """generates algorithm-bound key pairs that import for signing and verification"""

    @fx.gen
    def program():
        algorithms: tuple[jwk.AsymmetricAlgorithm, ...] = (
            "RS256",
            "PS256",
            "ES256",
            "ES384",
            "ES512",
            "EdDSA",
        )
        for algorithm in algorithms:
            pair = yield from jwk.generate_key_pair(algorithm, kid="k1")
            assert pair.public_key.get("alg") == algorithm
            assert pair.public_key.get("kid") == "k1"
            assert pair.public_key.get("use") == "sig"
            assert "d" not in pair.public_key

            private_key = yield from jwk.import_private(pair.private_key, algorithm)
            public_key = yield from jwk.import_public(pair.public_key, algorithm)
            assert private_key.algorithm == algorithm
            assert private_key.kid == "k1"
            assert public_key.algorithm == algorithm
            assert public_key.kid == "k1"
            assert signature.is_private_key(private_key.key)
            assert signature.is_public_key(public_key.key)
            assert public_key.jwk == pair.public_key
            assert (yield from jwk.export_public(public_key)) == pair.public_key

    return program.pipe(fx.provide(layer))


@testing.effect
def test_rejects_non_canonical_base64url_key_members_without_exposing_private_input():
    """rejects non-canonical base64url key members without exposing private input"""
    ec_public = without(ES256_JWK, "d")
    public_error = yield from jwk.import_public(
        cast("PublicJwk", {**ec_public, "x": f"{ec_public['x']}="}), "ES256"
    ).flip()
    reason = assert_reason(public_error, "InvalidKey").reason
    assert "base64url" in reason.message

    d = f"{ES256_JWK['d']}="
    assert not S.is_(jwk.PrivateJwkSchema)({**ES256_JWK, "d": d})
    private_error = yield from jwk.import_private(
        redacted(cast("PrivateJwk", {**ES256_JWK, "d": d})), "ES256"
    ).flip()
    assert_reason(private_error, "InvalidKey")
    assert private_error.cause is None
    assert d not in repr(private_error)
    assert d not in private_error.message


@testing.effect
def test_binds_imported_keys_to_the_selected_algorithm_and_honours_jwk_metadata():
    """binds imported keys to the selected algorithm and honours JWK metadata"""
    key = yield from jwk.import_public(ES256_PUBLIC_JWK, "ES256")
    assert key.algorithm == "ES256"
    assert key.kid is None

    # Curve family and selected algorithm must agree.
    assert_reason((yield from jwk.import_public(ES256_PUBLIC_JWK, "EdDSA").flip()), "InvalidKey")
    assert_reason((yield from jwk.import_public(ES256_PUBLIC_JWK, "ES384").flip()), "InvalidKey")
    # Declared ``alg`` wins over the selection when they disagree.
    assert_reason(
        (
            yield from jwk.import_public(
                cast("PublicJwk", {**ES256_PUBLIC_JWK, "alg": "RS256"}), "ES256"
            ).flip()
        ),
        "InvalidKey",
    )
    # ``use`` / ``key_ops`` that exclude signing are not verification keys.
    assert_reason(
        (
            yield from jwk.import_public(
                cast("PublicJwk", {**ES256_PUBLIC_JWK, "use": "enc"}), "ES256"
            ).flip()
        ),
        "InvalidKey",
    )
    # Private members never satisfy the public schema.
    assert not S.is_(jwk.PublicJwkSchema)(ES256_JWK)
    assert S.is_(jwk.PrivateJwkSchema)(ES256_JWK)
    # Not even RSA factors without ``d``.
    factors = without(RS256_JWK, "d")
    assert not S.is_(jwk.PublicJwkSchema)(factors)
    assert not S.is_(jwks.KeySetSchema)({"keys": [factors]})
    assert_reason(
        (yield from jwk.import_public(cast("PublicJwk", factors), "RS256").flip()), "InvalidKey"
    )


def _rsa_1024() -> tuple[PublicJwk, str, bytes]:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)
    numbers = private_key.public_key().public_numbers()

    def member(value: int) -> str:
        return b64(value.to_bytes((value.bit_length() + 7) // 8, "big"))

    public_jwk: PublicJwk = {"kty": "RSA", "n": member(numbers.n), "e": member(numbers.e)}
    spki_pem = (
        private_key.public_key()
        .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
        .decode()
    )
    pkcs8_der = private_key.private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )
    return public_jwk, spki_pem, pkcs8_der


@testing.effect
def test_rejects_rsa_keys_below_2048_bits():
    """rejects RSA keys below 2048 bits"""
    public_jwk, spki_pem, pkcs8_der = _rsa_1024()
    assert_reason((yield from jwk.import_public(public_jwk, "RS256").flip()), "InvalidKey")
    assert_reason((yield from jwk.import_spki(spki_pem, "RS384").flip()), "InvalidKey")
    assert_reason((yield from jwk.import_pkcs8(redacted(pkcs8_der), "PS512").flip()), "InvalidKey")


@testing.effect
def test_interoperates_with_jose_for_spki_and_pkcs8_in_der_and_pem_form():
    """interoperates with jose for SPKI and PKCS#8 in DER and PEM form"""
    node = NODE["es384"]

    @fx.gen
    def program():
        cases: list[tuple[str, bytes | str, bytes | str]] = [
            ("der", unb64(node["publicDer"]), unb64(node["privateDer"])),
            ("pem", node["publicPem"], node["privatePem"]),
        ]
        for format, public_data, private_data in cases:
            public_key = yield from jwk.import_spki(public_data, "ES384", kid="key-1")
            private_key = yield from jwk.import_pkcs8(
                cast("Redacted[bytes] | Redacted[str]", redacted(private_data)),
                "ES384",
                kid="key-1",
            )
            assert {name: public_key.jwk.get(name) for name in ("alg", "kid", "use")} == {
                "alg": "ES384",
                "kid": "key-1",
                "use": "sig",
            }
            # The JWK jose exports for the same key.
            assert without(public_key.jwk, "alg", "kid", "use") == node["publicJwk"]
            if format == "pem":
                assert isinstance(public_data, str)
                assert isinstance(private_data, str)
                spki = yield from jwk.export_spki_pem(public_key)
                pkcs8 = reveal((yield from jwk.export_pkcs8_pem(private_key)))
                assert spki.strip() == public_data.strip()
                assert pkcs8.strip() == private_data.strip()
            else:
                assert (yield from jwk.export_spki(public_key)) == public_data
                assert reveal((yield from jwk.export_pkcs8(private_key))) == private_data

            token = yield from jws.sign(utf8("key formats"), private_key)
            reference_verify(reveal(token), node["publicJwk"])

    return program.pipe(fx.provide(layer))


@testing.effect
def test_rejects_mismatched_pem_roles_and_algorithms_without_exposing_private_input():
    """rejects mismatched PEM roles and algorithms without exposing private input"""

    @fx.gen
    def program():
        pair = yield from jwk.generate_key_pair("ES384")
        public_pem = yield from jwk.export_spki_pem(
            (yield from jwk.import_public(pair.public_key, "ES384"))
        )
        assert_reason((yield from jwk.import_spki(public_pem, "ES256").flip()), "InvalidKey")
        assert_reason(
            (yield from jwk.import_pkcs8(redacted(public_pem), "ES384").flip()), "InvalidKey"
        )

        marker = "private-pem-marker"
        error = yield from jwk.import_pkcs8(redacted(marker), "ES384").flip()
        assert_reason(error, "InvalidKey")
        assert error.cause is None
        assert marker not in repr(error)
        assert marker not in error.message

    return program.pipe(fx.provide(layer))


def _oct(size: int) -> Redacted[SecretJwk]:
    return redacted({"kty": "oct", "k": b64(bytes(size))})


@testing.effect
def test_imports_octet_keys_with_per_algorithm_length_rules():
    """imports octet keys with per-algorithm length rules"""
    hmac = yield from jwk.import_secret(redacted(HS256_JWK), "HS256")
    assert hmac.algorithm == "HS256"
    dir_key = yield from jwk.import_secret(redacted({**SECRET_JWK, "kid": "enc-1"}), "dir")
    assert dir_key.algorithm == "dir"
    assert dir_key.kid == "enc-1"

    lengths: tuple[tuple[jwk.HmacAlgorithm, int], ...] = (
        ("HS256", 32),
        ("HS384", 48),
        ("HS512", 64),
    )
    for algorithm, length in lengths:
        assert_reason(
            (yield from jwk.import_hmac(_oct(length - 1), algorithm).flip()), "InvalidKey"
        )
        assert (yield from jwk.import_hmac(_oct(length), algorithm)).algorithm == algorithm
    assert_reason((yield from jwk.import_secret(redacted(HS256_JWK), "dir").flip()), "InvalidKey")
    assert_reason(
        (yield from jwk.import_secret(redacted({**SECRET_JWK, "alg": "HS256"}), "dir").flip()),
        "InvalidKey",
    )
    # A symmetric key performs both operations, so ``key_ops`` must allow both.
    yield from jwk.import_secret(redacted({**SECRET_JWK, "key_ops": ["sign", "verify"]}), "HS256")
    assert_reason(
        (
            yield from jwk.import_secret(
                redacted({**SECRET_JWK, "key_ops": ["verify"]}), "HS256"
            ).flip()
        ),
        "InvalidKey",
    )
    assert_reason(
        (
            yield from jwk.import_secret(
                redacted({**SECRET_JWK, "key_ops": ["decrypt"]}), "dir"
            ).flip()
        ),
        "InvalidKey",
    )


@testing.effect
def test_generates_redacted_secrets_with_the_required_length_and_metadata():
    """generates redacted secrets with the required length and metadata"""

    @fx.gen
    def program():
        cases: tuple[tuple[jwk.SecretAlgorithm, int, str], ...] = (
            ("HS512", 64, "sig"),
            ("dir", 32, "enc"),
        )
        for algorithm, length, use in cases:
            secret = yield from jwk.generate_secret(algorithm, kid="secret-1")
            value = reveal(secret)
            assert without(value, "k") == {
                "kty": "oct",
                "alg": algorithm,
                "use": use,
                "kid": "secret-1",
            }
            assert len(unb64(value["k"])) == length
            assert value["k"] not in repr(secret)
            assert value["k"] not in str(secret)
            assert (yield from jwk.import_secret(secret, algorithm)).algorithm == algorithm

    return program.pipe(fx.provide(layer))


@testing.effect
def test_matches_jose_thumbprints_for_every_key_type_and_input_form():
    """matches jose thumbprints for every key type and input form"""
    node = NODE["thumbprints"]

    @fx.gen
    def program():
        cases: list[tuple[PublicJwk, Redacted[PrivateJwk], str]] = [
            (RS256_PUBLIC_JWK, redacted(RS256_JWK), node["rs256"]),
            (ES256_PUBLIC_JWK, redacted(ES256_JWK), node["es256"]),
            (
                node["ed25519PublicJwk"],
                redacted(cast("PrivateJwk", node["ed25519PrivateJwk"])),
                node["ed25519"],
            ),
        ]
        for public_jwk, private_jwk, expected in cases:
            assert (yield from jwk.thumbprint(public_jwk)) == expected
            assert (yield from jwk.thumbprint(private_jwk)) == expected

        # Metadata is ignored, and imported keys hash their public members.
        public_key = yield from jwk.import_public(ES256_PUBLIC_JWK, "ES256")
        private_key = yield from jwk.import_private(redacted(ES256_JWK), "ES256")
        inputs: list[jwk.ThumbprintInput] = [
            cast("PublicJwk", {**ES256_PUBLIC_JWK, "kid": "ignored", "use": "enc"}),
            public_key,
            private_key,
        ]
        for input in inputs:
            assert (yield from jwk.thumbprint(input, digest.sha512)) == node["es256Sha512"]
        assert (yield from jwk.thumbprint_uri(public_key)) == node["es256Uri"]

        assert (yield from jwk.thumbprint(redacted(SECRET_JWK))) == node["secret"]
        hmac = yield from jwk.import_secret(redacted(SECRET_JWK), "HS256")
        assert (yield from jwk.thumbprint(hmac)) == node["secret"]

    return program.pipe(fx.provide(layer))


@testing.effect
def test_rejects_invalid_thumbprint_members_and_unsupported_hashes_without_exposing_secrets():
    """rejects invalid thumbprint members and unsupported hashes without exposing secrets"""

    @fx.gen
    def program():
        marker = "secret-thumbprint-marker!"
        inputs: list[Any] = [
            {**ES256_PUBLIC_JWK, "x": "AB"},
            redacted({**SECRET_JWK, "k": marker}),
            {"kty": "unsupported"},
        ]
        for input in inputs:
            error = yield from jwk.thumbprint(input).flip()
            assert_reason(error, "InvalidKey")
            assert error.cause is None
            assert marker not in repr(error)
            assert marker not in error.message
        assert_reason(
            (yield from jwk.thumbprint(RS256_PUBLIC_JWK, digest.sha1).flip()), "InvalidArgument"
        )

    return program.pipe(fx.provide(layer))
