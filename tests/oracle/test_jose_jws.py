"""Ports of Effect's ``jose/Jws.test.ts``."""

from __future__ import annotations

import functools
import hashlib
import hmac as std_hmac
import json
from collections.abc import Callable, Mapping
from typing import Any, cast

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.crypto.crypto_error import CryptoError, InvalidArgument
from pyfect.crypto.mac import Mac, MacService
from pyfect.crypto.signature import Signature
from pyfect.jose import jwk, jws
from pyfect.jose.jose_error import JoseError
from pyfect.jose.jwk import PrivateJwk, PublicJwk, SecretJwk
from pyfect.jose.jwks import Jwks, JwksService, Selection
from pyfect.layer import succeed as layer_succeed
from pyfect.redacted import make as redacted
from pyfect.redacted import value as reveal

from ._jose import (
    ES256_JWK,
    ES256_PUBLIC_JWK,
    ES256_TOKEN,
    HS256_JWK,
    HS256_TOKEN,
    NODE,
    RFC7515_PAYLOAD,
    RS256_JWK,
    RS256_PUBLIC_JWK,
    RS256_TOKEN,
    assert_reason,
    b64,
    json_b64,
    layer,
    reference_verify,
    text,
    unb64,
    utf8,
    without,
)


@testing.effect
def test_verifies_the_rfc_7515_appendix_a_compact_serializations():
    """verifies the RFC 7515 Appendix A compact serializations"""

    @fx.gen
    def program():
        payload = unb64(RFC7515_PAYLOAD)

        hmac = yield from jwk.import_hmac(redacted(HS256_JWK), "HS256")
        a1 = yield from jws.verify(HS256_TOKEN, hmac)
        assert a1.protected_header == {"typ": "JWT", "alg": "HS256"}
        assert a1.payload == payload

        rsa = yield from jwk.import_public(RS256_PUBLIC_JWK, "RS256")
        a2 = yield from jws.verify(redacted(RS256_TOKEN), rsa)
        assert a2.protected_header == {"alg": "RS256"}
        assert a2.payload == payload

        ec = yield from jwk.import_public(ES256_PUBLIC_JWK, "ES256")
        a3 = yield from jws.verify(ES256_TOKEN, ec)
        assert a3.payload == payload

    return program.pipe(fx.provide(layer))


@testing.effect
def test_reproduces_the_rfc_7515_a2_rs256_signature():
    """reproduces the RFC 7515 A.2 RS256 signature"""

    # RSASSA-PKCS1-v1_5 is deterministic, so signing the RFC payload with the
    # RFC key must reproduce the RFC token byte for byte.
    @fx.gen
    def program():
        key = yield from jwk.import_private(redacted(RS256_JWK), "RS256")
        token = yield from jws.sign(unb64(RFC7515_PAYLOAD), key)
        assert reveal(token) == RS256_TOKEN

    return program.pipe(fx.provide(layer))


@testing.effect
def test_reproduces_the_rfc_7520_section_44_hs256_signature_with_the_keys_kid():
    """reproduces the RFC 7520 Section 4.4 HS256 signature with the key's kid"""

    @fx.gen
    def program():
        key = yield from jwk.import_hmac(
            redacted(
                {
                    "kty": "oct",
                    "kid": "018c0ae5-4d9b-471b-bfd6-eef314bc7037",
                    "use": "sig",
                    "alg": "HS256",
                    "k": "hJtXIZ2uSN5kbQfbtTNWbpdmhkV8FJG-Onbc6mxCcYg",
                }
            ),
            "HS256",
        )
        payload = (
            "SXTigJlzIGEgZGFuZ2Vyb3VzIGJ1c2luZXNzLCBGcm9kbywgZ29pbmcgb3V0IHlvdXIgZG9vci4gWW91"
            "IHN0ZXAgb250byB0aGUgcm9hZCwgYW5kIGlmIHlvdSBkb24ndCBrZWVwIHlvdXIgZmVldCwgdGhlcmXi"
            "gJlzIG5vIGtub3dpbmcgd2hlcmUgeW91IG1pZ2h0IGJlIHN3ZXB0IG9mZiB0by4"
        )
        token = yield from jws.sign(unb64(payload), key)
        assert reveal(token) == (
            "eyJhbGciOiJIUzI1NiIsImtpZCI6IjAxOGMwYWU1LTRkOWItNDcxYi1iZmQ2LWVlZjMxNGJjNzAzNyJ9"
            f".{payload}.s0h6KThzkfBBBkLspW1h84VsJZFTsPPqMDA7g1Md7p0"
        )
        # An explicit ``kid=None`` falls back to the key's kid.
        assert reveal((yield from jws.sign(unb64(payload), key, {"kid": None}))) == reveal(token)

    return program.pipe(fx.provide(layer))


@testing.effect
def test_preserves_extension_headers_when_signing_verifying_and_resolving_a_key():
    """preserves extension headers when signing, verifying, and resolving a key"""

    @fx.gen
    def program():
        key = yield from jwk.import_private(redacted(ES256_JWK), "ES256")
        public = without(ES256_JWK, "d")
        header = {"typ": "dpop+jwt", "jwk": public, "jku": "https://issuer.example/keys"}
        token = yield from jws.sign(utf8("{}"), key, {**header, "alg": "none"})
        expected = {"alg": "ES256", **header}
        assert reference_verify(reveal(token), public) == expected

        def resolve(selection: Selection) -> fx.Effect[jwk.PublicKey, JoseError]:
            assert selection.protected_header == expected
            assert selection.protected_header is not None
            found = S.decode_unknown_sync(jwk.PublicJwkSchema)(
                cast("Mapping[str, object]", selection.protected_header)["jwk"]
            )
            return jwk.import_public(found, selection.algorithm)

        key_set = layer_succeed(Jwks, JwksService(resolve))
        verified = yield from jws.verify_with_key_set(token, algorithms=["ES256"]).pipe(
            fx.provide(key_set)
        )
        assert verified.protected_header == expected

        cyclic: dict[str, Any] = {}
        cyclic["self"] = cyclic
        assert_reason(
            (yield from jws.sign(utf8("{}"), key, {"ext": cyclic}).flip()), "InvalidArgument"
        )

    return program.pipe(fx.provide(layer))


_ALGORITHMS: tuple[jwk.Algorithm, ...] = (
    "HS256",
    "HS384",
    "HS512",
    "RS256",
    "RS384",
    "RS512",
    "PS256",
    "PS384",
    "PS512",
    "ES256",
    "ES384",
    "ES512",
    "EdDSA",
)
# Deterministic: the same key, header and payload give jose's token.
_DETERMINISTIC = ("HS256", "HS384", "HS512", "RS256", "RS384", "RS512", "EdDSA")


def _reference_hmac(token: str, secret: bytes) -> dict[str, Any]:
    header, payload, signature = token.split(".")
    protected: dict[str, Any] = json.loads(unb64(header))
    digest = {"HS256": hashlib.sha256, "HS384": hashlib.sha384, "HS512": hashlib.sha512}[
        protected["alg"]
    ]
    expected = std_hmac.new(secret, f"{header}.{payload}".encode(), digest).digest()
    assert std_hmac.compare_digest(expected, unb64(signature))
    return protected


@testing.effect
def test_interoperates_with_jose_for_every_supported_algorithm_and_carries_the_key_id():
    """interoperates with jose for every supported algorithm and carries the key id"""

    @fx.gen
    def program():
        for algorithm in _ALGORITHMS:
            node = NODE["jws"][algorithm]
            signing_key: jwk.SigningKey
            verification_key: jwk.VerificationKey
            check: Callable[[str], dict[str, Any]]
            if algorithm in ("HS256", "HS384", "HS512"):
                secret_jwk = cast("SecretJwk", node["secret"])
                hmac = yield from jwk.import_hmac(redacted(secret_jwk), algorithm)
                signing_key = verification_key = hmac

                check = functools.partial(_reference_hmac, secret=unb64(secret_jwk["k"]))

                # A generated secret works with any HMAC implementation too.
                generated = yield from jwk.generate_secret(algorithm, kid="k1")
                own = yield from jws.sign(
                    utf8("hello"), (yield from jwk.import_hmac(generated, algorithm))
                )
                _reference_hmac(reveal(own), unb64(reveal(generated)["k"]))
            else:
                signing_key = yield from jwk.import_private(
                    redacted(cast("PrivateJwk", node["privateJwk"])), algorithm
                )
                verification_key = yield from jwk.import_public(
                    cast("PublicJwk", node["publicJwk"]), algorithm
                )

                check = functools.partial(reference_verify, public_jwk=node["publicJwk"])

                # A generated pair works with any implementation too.
                pair = yield from jwk.generate_key_pair(algorithm, kid="k1")
                own = yield from jws.sign(
                    utf8("hello"), (yield from jwk.import_private(pair.private_key, algorithm))
                )
                reference_verify(reveal(own), pair.public_key)

            ours = yield from jws.sign(utf8("hello"), signing_key, {"typ": "JOSE"})
            # ``kid`` comes from the key, ``alg`` from its algorithm.
            assert check(reveal(ours)) == {"alg": algorithm, "kid": "k1", "typ": "JOSE"}
            assert unb64(reveal(ours).split(".")[1]) == b"hello"

            their_token: str = node["token"]
            verified = yield from jws.verify(their_token, verification_key)
            assert text(verified.payload) == "hello"
            assert verified.protected_header.get("kid") == "k1"
            if algorithm in _DETERMINISTIC:
                assert reveal((yield from jws.sign(utf8("hello"), signing_key))) == their_token

    return program.pipe(fx.provide(layer))


@testing.effect
def test_rejects_forged_malformed_and_algorithm_confused_tokens():
    """rejects forged, malformed, and algorithm-confused tokens"""

    @fx.gen
    def program():
        hmac = yield from jwk.import_hmac(redacted(HS256_JWK), "HS256")
        rsa = yield from jwk.import_public(RS256_PUBLIC_JWK, "RS256")
        header, payload, signature = HS256_TOKEN.split(".")

        forged = f"{header}.{b64('{"iss":"eve"}')}.{signature}"
        assert_reason((yield from jws.verify(forged, hmac).flip()), "SignatureVerificationFailed")

        # The token's algorithm must be the key's algorithm. An HS256 token
        # must never be checked with an RSA public key as the HMAC secret.
        assert_reason((yield from jws.verify(HS256_TOKEN, rsa).flip()), "AlgorithmNotAllowed")
        assert_reason((yield from jws.verify(RS256_TOKEN, hmac).flip()), "AlgorithmNotAllowed")

        unsecured = f"{b64('{"alg":"none"}')}.{payload}."
        assert_reason((yield from jws.verify(unsecured, hmac).flip()), "InvalidToken")

        extensions: list[dict[str, Any]] = [{"crit": ["exp"], "exp": 1}, {"b64": True}]
        for extension in extensions:
            unsupported = f"{json_b64({'alg': 'HS256', **extension})}.{payload}.{signature}"
            assert_reason((yield from jws.verify(unsupported, hmac).flip()), "InvalidToken")
            assert_reason(
                (yield from jws.sign(utf8("payload"), hmac, extension).flip()), "InvalidArgument"
            )

        assert_reason((yield from jws.verify(f"{header}.{payload}", hmac).flip()), "InvalidToken")
        for invalid in (f"{signature}=", f"{signature[:-1]}l"):
            assert_reason(
                (yield from jws.verify(f"{header}.{payload}.{invalid}", hmac).flip()),
                "InvalidToken",
            )
        assert_reason((yield from jws.verify("", hmac).flip()), "InvalidToken")

    return program.pipe(fx.provide(layer))


@testing.effect
def test_rejects_a_resolved_key_whose_algorithm_differs_from_the_tokens():
    """rejects a resolved key whose algorithm differs from the token's"""

    @fx.gen
    def program():
        private_key = yield from jwk.import_private(redacted(RS256_JWK), "RS256")
        public_key = yield from jwk.import_public(RS256_PUBLIC_JWK, "RS256")
        signing_input = f"{b64('{"alg":"PS256"}')}.{b64('{}')}"
        signer = yield from Signature()
        signature = yield from signer.sign(private_key.key, utf8(signing_input))
        token = f"{signing_input}.{b64(signature)}"
        key_set = layer_succeed(Jwks, JwksService(lambda _selection: fx.succeed(public_key)))

        assert_reason(
            (
                yield from jws.verify_with_key_set(token, algorithms=["PS256"])
                .pipe(fx.provide(key_set))
                .flip()
            ),
            "AlgorithmNotAllowed",
        )

    return program.pipe(fx.provide(layer))


@testing.effect
def test_resolves_the_verification_key_from_the_jwks_service_by_algorithm_and_kid():
    """resolves the verification key from the Jwks service by algorithm and kid"""
    from pyfect.jose import jwks

    @fx.gen
    def program():
        one = yield from jwk.generate_key_pair("ES256", kid="one")
        two = yield from jwk.generate_key_pair("ES256", kid="two")
        key_set = jwks.layer_local({"keys": [one.public_key, two.public_key]})
        signing_key = yield from jwk.import_private(two.private_key, "ES256")
        token = yield from jws.sign(utf8("payload"), signing_key)

        verified = yield from jws.verify_with_key_set(token, algorithms=["ES256"]).pipe(
            fx.provide(key_set)
        )
        assert text(verified.payload) == "payload"
        assert verified.key.kid == "two"
        assert verified.key.jwk == two.public_key

        # The allowlist is enforced before any key lookup.
        assert_reason(
            (
                yield from jws.verify_with_key_set(token, algorithms=["RS256", "EdDSA"])
                .pipe(fx.provide(key_set))
                .flip()
            ),
            "AlgorithmNotAllowed",
        )
        # Symmetric tokens never resolve through a public key set, even when
        # an untyped caller allows them.
        hmac = yield from jwk.import_hmac(redacted(HS256_JWK), "HS512")
        symmetric = yield from jws.sign(utf8("payload"), hmac)
        allowed = cast("list[jwk.AsymmetricAlgorithm]", ["HS512"])
        assert_reason(
            (
                yield from jws.verify_with_key_set(symmetric, algorithms=allowed)
                .pipe(fx.provide(key_set))
                .flip()
            ),
            "AlgorithmNotAllowed",
        )

    return program.pipe(fx.provide(layer))


def _chain(error: BaseException) -> str:
    """Everything an inspection would show: the error, its reason and every
    cause and context below it."""
    parts: list[str] = []
    seen: BaseException | None = error
    while seen is not None:
        parts.extend((repr(seen), str(seen), repr(getattr(seen, "reason", None))))
        seen = seen.__cause__ or seen.__context__
    return "\n".join(parts)


@testing.effect
def test_never_exposes_crypto_backend_diagnostics():
    """never exposes crypto backend diagnostics"""
    marker = "backend-secret-marker"
    failure = fx.fail(
        CryptoError(
            module="Mac",
            method="verify",
            reason=InvalidArgument(description=marker, cause=Exception(marker)),
        )
    )
    failing = layer_succeed(
        Mac,
        MacService(
            generate_key=lambda _algorithm: failure,
            sign=lambda _key, _data: failure,
            verify=lambda _key, _signature, _data: failure,
        ),
    )

    @fx.gen
    def program():
        key = yield from jwk.import_hmac(redacted(HS256_JWK), "HS256")
        operations: list[fx.Effect[object, JoseError, Mac]] = [
            jws.verify(HS256_TOKEN, key),
            jws.sign(utf8("payload"), key),
        ]
        for operation in operations:
            error = yield from operation.pipe(fx.provide(failing)).flip()
            assert isinstance(error, JoseError)
            assert error.cause is None
            assert marker not in _chain(error)

    return program.pipe(fx.provide(layer))
