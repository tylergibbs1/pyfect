"""Ports of Effect's ``jose/Jwt.test.ts``."""

from __future__ import annotations

import json
import math
import sys
from typing import Literal, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect import testing
from pyfect.duration import Input as DurationInput
from pyfect.jose import jwe, jwk, jwks, jwt
from pyfect.jose.jose_error import ClaimValidationFailed
from pyfect.redacted import make as redacted
from pyfect.redacted import value as reveal
from pyfect.schema import SchemaError

from ._jose import (
    HS256_JWK,
    HS256_TOKEN,
    NODE,
    SECRET,
    SECRET_JWK,
    assert_reason,
    b64,
    layer,
    reference_decrypt,
    unb64,
    utf8,
)

RootClaimsDict = TypedDict("RootClaimsDict", {"iss": str, "http://example.com/is_root": bool})
RootClaims = S.Struct(RootClaimsDict)


def claim_failure(error: object) -> tuple[str, str]:
    reason = assert_reason(error, "ClaimValidationFailed").reason
    assert isinstance(reason, ClaimValidationFailed)
    return reason.claim, reason.reason


@testing.effect
def test_verifies_the_rfc_7515_a1_token_as_a_jwt_against_the_clock():
    """verifies the RFC 7515 A.1 token as a JWT against the clock"""

    @fx.gen
    def program():
        key = yield from jwk.import_hmac(redacted(HS256_JWK), "HS256")

        yield from testing.set_time(1300819379_000)
        verified = yield from jwt.verify(RootClaims, HS256_TOKEN, key, issuer="joe", typ="JWT")
        assert verified.claims == {"iss": "joe", "http://example.com/is_root": True}
        assert verified.registered_claims == {"iss": "joe", "exp": 1300819380}
        assert verified.protected_header["alg"] == "HS256"

        # ``exp`` is exclusive: the token is invalid from the expiry second on.
        yield from testing.set_time(1300819380_000)
        expired = yield from jwt.verify(RootClaims, HS256_TOKEN, key).flip()
        assert claim_failure(expired) == ("exp", "expired")

        yield from jwt.verify(RootClaims, HS256_TOKEN, key, clock_tolerance="5 seconds")

        # No options means signature and present temporal claims only.
        yield from testing.set_time(0)
        yield from jwt.verify(RootClaims, HS256_TOKEN, key)

    return program.pipe(fx.provide(layer))


class ClaimsDict(TypedDict):
    sub: str
    role: Literal["admin", "member"]
    quota: float


Claims = S.Struct(ClaimsDict, quota=S.FiniteFromString)


@testing.effect
def test_encodes_claims_through_the_schema_before_signing_and_decodes_them_after_verification():
    """encodes claims through the schema before signing and decodes them after verification"""

    @fx.gen
    def program():
        key = yield from jwk.import_hmac(redacted({**SECRET_JWK, "kid": "k1"}), "HS256")
        token = yield from jwt.sign(
            Claims, {"sub": "user_1", "role": "member", "quota": 3}, key, {"typ": "JWT"}
        )

        header, payload, _ = reveal(token).split(".")
        assert json.loads(unb64(payload)) == {"sub": "user_1", "role": "member", "quota": "3"}
        assert json.loads(unb64(header)) == {"alg": "HS256", "kid": "k1", "typ": "JWT"}

        verified = yield from jwt.verify(Claims, token, key, subject="user_1", typ="JWT")
        assert verified.claims == {"sub": "user_1", "role": "member", "quota": 3}
        assert verified.registered_claims == {"sub": "user_1"}

        unverified = yield from jwt.decode_unverified(token)
        assert unverified.claims == {"sub": "user_1", "role": "member", "quota": "3"}
        assert unverified.protected_header.get("kid") == "k1"

        # Application schema failures surface as SchemaError, after authentication.
        guest: str = NODE["jwt"]["guest"]
        assert isinstance((yield from jwt.verify(Claims, guest, key).flip()), SchemaError)

    return program.pipe(fx.provide(layer))


@testing.effect
def test_encrypts_schema_encoded_claims_and_decrypts_encrypted_jwts_interoperably():
    """encrypts schema-encoded claims and decrypts encrypted JWTs interoperably"""

    @fx.gen
    def program():
        key = yield from jwk.import_dir(redacted({**SECRET_JWK, "kid": "enc-1"}))
        token = yield from jwt.encrypt(
            Claims, {"sub": "user_1", "role": "member", "quota": 3}, key, {"typ": "JWT"}
        )

        their_header, plaintext = reference_decrypt(reveal(token), SECRET)
        assert json.loads(plaintext) == {"sub": "user_1", "role": "member", "quota": "3"}
        assert their_header == {"alg": "dir", "enc": "A256GCM", "kid": "enc-1", "typ": "JWT"}

        encrypted: str = NODE["jwt"]["encrypted"]

        def resolve(header: jwe.ProtectedHeader) -> fx.Effect[jwk.DirKey]:
            assert header.get("kid") == "enc-1"
            return fx.succeed(key)

        decrypted = yield from jwt.decrypt(Claims, encrypted, resolve, subject="user_2", typ="JWT")
        assert decrypted.claims == {"sub": "user_2", "role": "admin", "quota": 4}
        assert decrypted.protected_header == {
            "alg": "dir",
            "enc": "A256GCM",
            "kid": "enc-1",
            "typ": "JWT",
        }
        assert decrypted.key is key

    return program.pipe(fx.provide(layer))


NOW = 1604416038


@testing.effect
def test_validates_registered_claims_against_the_verification_policy():
    """validates registered claims against the verification policy"""

    @fx.gen
    def program():
        yield from testing.set_time(NOW * 1000)
        key = yield from jwk.import_hmac(redacted(SECRET_JWK), "HS256")
        registered: jwt.RegisteredClaims = {
            "iss": "https://issuer.example",
            "sub": "user_1",
            "aud": ["api", "web"],
            "exp": NOW + 10,
            "nbf": NOW - 10,
            "iat": NOW - 20,
        }
        token = yield from jwt.sign(jwt.RegisteredClaimsSchema, registered, key, {"typ": "at+jwt"})

        accepted = yield from jwt.verify(
            jwt.RegisteredClaimsSchema,
            token,
            key,
            issuer=["https://other.example", "https://issuer.example"],
            audience="web",
            subject="user_1",
            typ="application/at+jwt",
            max_token_age="30 seconds",
            required_claims=["iss", "aud", "exp", "iat"],
        )
        assert accepted.registered_claims == registered

        failures: list[tuple[jwt.VerifyOptions, tuple[str, str]]] = [
            ({"issuer": "https://other.example"}, ("iss", "mismatch")),
            ({"audience": ["mobile"]}, ("aud", "mismatch")),
            ({"subject": "user_2"}, ("sub", "mismatch")),
            ({"typ": "JWT"}, ("typ", "mismatch")),
            ({"required_claims": ["jti"]}, ("jti", "missing")),
            ({"max_token_age": "10 seconds"}, ("iat", "tooOld")),
        ]
        for options, expected in failures:
            error = yield from jwt.verify(jwt.RegisteredClaimsSchema, token, key, **options).flip()
            assert claim_failure(error) == expected

        # Inputs that ``Duration`` would read as zero are rejected: NaN in any
        # form, non-finite components, and components that overflow.
        tolerances: list[DurationInput] = [
            math.nan,
            (math.nan, 0),
            {"seconds": math.nan},
            {"seconds": math.inf, "minutes": -math.inf},
            {"milliseconds": math.inf, "nanoseconds": -math.inf},
            {"seconds": sys.float_info.max, "minutes": -sys.float_info.max},
        ]
        for clock_tolerance in tolerances:
            assert_reason(
                (
                    yield from jwt.verify(
                        jwt.RegisteredClaimsSchema, token, key, clock_tolerance=clock_tolerance
                    ).flip()
                ),
                "InvalidArgument",
            )

        yield from testing.set_time((NOW - 11) * 1000)
        early = yield from jwt.verify(jwt.RegisteredClaimsSchema, token, key).flip()
        assert claim_failure(early) == ("nbf", "notYetValid")
        yield from jwt.verify(jwt.RegisteredClaimsSchema, token, key, clock_tolerance=1000)

        # Registered claims with the wrong shape are rejected before any schema.
        malformed: str = NODE["jwt"]["malformed"]
        invalid = yield from jwt.verify(jwt.RegisteredClaimsSchema, malformed, key).flip()
        assert claim_failure(invalid) == ("exp", "invalid")

    return program.pipe(fx.provide(layer))


class ApplicationClaimsDict(TypedDict):
    role: str


@testing.effect
def test_authenticates_and_checks_encrypted_jwt_claims_before_decoding_the_application_schema():
    """authenticates and checks encrypted JWT claims before decoding the application schema"""
    decoded = False

    def admin(claims: ApplicationClaimsDict) -> bool:
        nonlocal decoded
        decoded = True
        return claims["role"] == "admin"

    application_claims = S.Struct(ApplicationClaimsDict).check(S.make_filter(admin))

    @fx.gen
    def program():
        yield from testing.set_time(NOW * 1000)
        key = yield from jwk.import_dir(redacted(SECRET_JWK))
        token = yield from jwe.encrypt(utf8(json.dumps({"role": "member", "exp": NOW})), key)
        parts = reveal(token).split(".")
        tag = bytearray(unb64(parts[4]))
        tag[0] ^= 1
        parts[4] = b64(bytes(tag))

        assert_reason(
            (yield from jwt.decrypt(application_claims, ".".join(parts), key).flip()),
            "DecryptionFailed",
        )
        expired = yield from jwt.decrypt(application_claims, token, key).flip()
        assert claim_failure(expired) == ("exp", "expired")
        assert not decoded

        member = yield from jwe.encrypt(utf8('{"role":"member"}'), key)
        error = yield from jwt.decrypt(application_claims, member, key).flip()
        assert isinstance(error, SchemaError)
        assert decoded

    return program.pipe(fx.provide(layer))


@testing.effect
def test_verifies_with_a_key_resolved_from_the_jwks_service():
    """verifies with a key resolved from the Jwks service"""

    @fx.gen
    def program():
        pair = yield from jwk.generate_key_pair("EdDSA", kid="ed")
        signing_key = yield from jwk.import_private(pair.private_key, "EdDSA")
        token = yield from jwt.sign(
            Claims, {"sub": "user_1", "role": "admin", "quota": 1}, signing_key
        )

        verified = yield from jwt.verify_with_key_set(
            Claims, token, algorithms=["EdDSA"], subject="user_1"
        ).pipe(fx.provide(jwks.layer_local({"keys": [pair.public_key]})))
        assert verified.claims == {"sub": "user_1", "role": "admin", "quota": 1}
        assert verified.key.kid == "ed"

    return program.pipe(fx.provide(layer))
