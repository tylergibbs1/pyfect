"""JSON Web Tokens (Effect's ``effect/jose/Jwt``): claims described by a
schema, signed as a JWS or encrypted as a JWE::

    token = yield from jwt.sign(Claims, {"sub": "user_1", "role": "admin"}, key)
    verified = yield from jwt.verify(Claims, token, key, issuer="https://issuer.example")

Verifying checks the registered claims (``iss``, ``sub``, ``aud``,
``exp``, ``nbf``, ``iat``, ``jti``) before the application schema decodes
the claims: each must have its registered type, and the options say which
are required and what they must be. ``exp`` and ``nbf`` are always checked
against the ``Clock``, within ``clock_tolerance``; ``max_token_age``
bounds the age ``iat`` gives.
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Literal, Never, NotRequired, TypedDict, Unpack, cast, overload

from pyfect import schema as S
from pyfect._core import Effect
from pyfect._json_text import Json, stringify
from pyfect.clock import current_time_millis
from pyfect.crypto.aead import Aead
from pyfect.crypto.mac import Mac
from pyfect.crypto.secure_random import SecureRandom
from pyfect.crypto.signature import Signature
from pyfect.duration import Input as DurationInput
from pyfect.effect import gen, succeed
from pyfect.jose import jwe, jws
from pyfect.jose._compact import (
    Header,
    JsonObject,
    Token,
    fail,
    invalid_token,
    millis,
    parse_json_object,
    utf8,
)
from pyfect.jose.jose_error import Claim, ClaimFailure, ClaimValidationFailed, JoseError
from pyfect.jose.jwk import (
    AsymmetricAlgorithm,
    DirKey,
    HmacKey,
    PrivateKey,
    PublicKey,
    SigningKey,
    VerificationKey,
)
from pyfect.jose.jwks import Jwks
from pyfect.redacted import Redacted
from pyfect.schema import SchemaError
from pyfect.schema._exact import Exact, as_codec


class RegisteredClaims(TypedDict):
    """RFC 7519's registered claims, as their types require."""

    iss: NotRequired[str]
    sub: NotRequired[str]
    aud: NotRequired[str | Sequence[str]]
    exp: NotRequired[float]
    nbf: NotRequired[float]
    iat: NotRequired[float]
    jti: NotRequired[str]


_CLAIM_SCHEMAS: dict[RegisteredClaim, S.Codec[Any, Any, Never, Never]] = {
    "iss": S.String,
    "sub": S.String,
    "aud": S.Union(S.String, S.Array(S.String)),
    "exp": S.Finite,
    "nbf": S.Finite,
    "iat": S.Finite,
    "jti": S.String,
}

RegisteredClaimsSchema = S.Struct(RegisteredClaims, exp=S.Finite, nbf=S.Finite, iat=S.Finite)

type RegisteredClaim = Literal["iss", "sub", "aud", "exp", "nbf", "iat", "jti"]
type JwtError = JoseError | SchemaError

# Each claim is checked on its own so the failure can name it.
_REGISTERED_CLAIM_GUARDS: tuple[tuple[RegisteredClaim, Callable[[object], bool]], ...] = tuple(
    (name, S.is_(schema)) for name, schema in _CLAIM_SCHEMAS.items()
)


@dataclass(frozen=True, slots=True)
class Verified[A, H = jws.ProtectedHeader]:
    claims: A
    registered_claims: RegisteredClaims
    protected_header: H


@dataclass(frozen=True, slots=True)
class VerifiedWithKey[A]:
    """``verify_with_key_set``'s result: the claims and the key that verified them."""

    claims: A
    registered_claims: RegisteredClaims
    protected_header: jws.ProtectedHeader
    key: PublicKey


@dataclass(frozen=True, slots=True)
class Decrypted[A]:
    claims: A
    registered_claims: RegisteredClaims
    protected_header: jwe.ProtectedHeader
    key: DirKey


@dataclass(frozen=True, slots=True)
class Unverified:
    protected_header: jws.ProtectedHeader
    claims: JsonObject


@dataclass(frozen=True, slots=True)
class _Policy:
    issuer: str | Sequence[str] | None
    audience: str | Sequence[str] | None
    subject: str | None
    typ: str | None
    clock_tolerance: float
    max_token_age: float | None
    required_claims: Sequence[RegisteredClaim]


class VerifyOptions(TypedDict, total=False):
    """The claims policy, as keyword arguments. ``issuer`` and ``audience`` accept any of several
    values; ``typ`` compares media types as RFC 7515 does (``"JWT"`` is
    ``application/jwt``); ``clock_tolerance`` widens the time checks;
    ``max_token_age`` requires ``iat`` and bounds the token's age."""

    issuer: str | Sequence[str]
    audience: str | Sequence[str]
    subject: str
    typ: str
    clock_tolerance: DurationInput
    max_token_age: DurationInput
    required_claims: Sequence[RegisteredClaim]


def _claim_validation_failed(claim: Claim, reason: ClaimFailure) -> Effect[Never, JoseError]:
    return fail(ClaimValidationFailed(claim, reason))


def _read_policy(options: VerifyOptions) -> Effect[_Policy, JoseError]:
    """Durations are read before any cryptography, in seconds."""
    clock_tolerance = options.get("clock_tolerance")
    max_token_age = options.get("max_token_age")

    @gen
    def body():
        tolerance = (
            0.0
            if clock_tolerance is None
            else (yield from millis("clockTolerance", clock_tolerance))
        )
        max_age = (
            None if max_token_age is None else (yield from millis("maxTokenAge", max_token_age))
        )
        return _Policy(
            issuer=options.get("issuer"),
            audience=options.get("audience"),
            subject=options.get("subject"),
            typ=options.get("typ"),
            clock_tolerance=tolerance / 1000,
            max_token_age=None if max_age is None else max_age / 1000,
            required_claims=options.get("required_claims", ()),
        )

    return body


def _to_list(value: str | Sequence[str]) -> Sequence[str]:
    return [value] if isinstance(value, str) else value


def _media_type(value: str) -> str:
    lowered = value.lower()
    return lowered if "/" in lowered else f"application/{lowered}"


def _check_identity(  # noqa: PLR0911
    registered: Mapping[str, Any], header: Mapping[str, object], policy: _Policy
) -> Effect[None, JoseError]:
    for name in policy.required_claims:
        if name not in registered:
            return _claim_validation_failed(name, "missing")
    iss, sub, aud = registered.get("iss"), registered.get("sub"), registered.get("aud")
    if policy.issuer is not None:
        if iss is None:
            return _claim_validation_failed("iss", "missing")
        if iss not in _to_list(policy.issuer):
            return _claim_validation_failed("iss", "mismatch")
    if policy.subject is not None:
        if sub is None:
            return _claim_validation_failed("sub", "missing")
        if sub != policy.subject:
            return _claim_validation_failed("sub", "mismatch")
    if policy.audience is not None:
        if aud is None:
            return _claim_validation_failed("aud", "missing")
        audiences = _to_list(cast("str | Sequence[str]", aud))
        if not any(audience in audiences for audience in _to_list(policy.audience)):
            return _claim_validation_failed("aud", "mismatch")
    typ = header.get("typ")
    if policy.typ is not None and (
        not isinstance(typ, str) or _media_type(typ) != _media_type(policy.typ)
    ):
        return _claim_validation_failed("typ", "mismatch")
    return succeed(None)


def _check_times(
    registered: Mapping[str, Any], policy: _Policy, now_millis: float
) -> Effect[None, JoseError]:
    now = math.floor(now_millis / 1000)
    tolerance = policy.clock_tolerance
    exp, nbf, iat = registered.get("exp"), registered.get("nbf"), registered.get("iat")
    if exp is not None and exp <= now - tolerance:
        return _claim_validation_failed("exp", "expired")
    if nbf is not None and nbf > now + tolerance:
        return _claim_validation_failed("nbf", "notYetValid")
    if policy.max_token_age is not None:
        if iat is None:
            return _claim_validation_failed("iat", "missing")
        if iat > now + tolerance:
            return _claim_validation_failed("iat", "future")
        if now - iat - tolerance > policy.max_token_age:
            return _claim_validation_failed("iat", "tooOld")
    return succeed(None)


def _check_claims(
    claims: JsonObject, header: Mapping[str, object], policy: _Policy
) -> Effect[RegisteredClaims, JoseError]:
    @gen
    def body():
        registered: dict[str, Any] = {}
        for name, is_valid in _REGISTERED_CLAIM_GUARDS:
            if name not in claims:
                continue
            if not is_valid(claims[name]):
                return (yield from _claim_validation_failed(name, "invalid"))
            registered[name] = claims[name]
        yield from _check_identity(registered, header, policy)
        now = yield from current_time_millis()
        yield from _check_times(registered, policy, now)
        return cast("RegisteredClaims", registered)

    return body


def _decode_claims[A, R](
    schema: S.Codec[A, Any, R, Any], payload: bytes, header: Mapping[str, object], policy: _Policy
) -> Effect[tuple[A, RegisteredClaims], JwtError, R]:
    @gen
    def body():
        claims = parse_json_object(payload)
        if claims is None:
            return (yield from invalid_token("The JWT payload is not a JSON object"))
        registered = yield from _check_claims(claims, header, policy)
        decoded = yield from S.decode_unknown_effect(schema)(claims)
        return decoded, registered

    return body


_is_registered_claims = S.is_(RegisteredClaimsSchema)
_decode_claims_json = S.decode_unknown_effect(
    S.JsonObject.check(S.make_filter(_is_registered_claims))
)


def _encode_claims[A, R](schema: Exact[A, Any, R], claims: A) -> Effect[bytes, SchemaError, R]:
    @gen
    def body():
        encoded = yield from S.encode_effect(as_codec(schema))(claims)
        json = yield from _decode_claims_json(encoded)
        return utf8(stringify(cast("Json", json)))

    return body


@overload
def sign[A, R](
    schema: Exact[A, Any, R], claims: A, key: HmacKey, header: Header | None = None
) -> Effect[Redacted[str], JwtError, R | Mac]: ...
@overload
def sign[A, R](
    schema: Exact[A, Any, R], claims: A, key: PrivateKey, header: Header | None = None
) -> Effect[Redacted[str], JwtError, R | Signature]: ...
@overload
def sign[A, R](
    schema: Exact[A, Any, R], claims: A, key: SigningKey, header: Header | None = None
) -> Effect[Redacted[str], JwtError, R | Mac | Signature]: ...
def sign(
    schema: Exact[Any, Any, Any], claims: Any, key: SigningKey, header: Header | None = None
) -> Effect[Redacted[str], JwtError, Any]:
    """The claims, encoded by ``schema``, as a signed JWT. ``claims`` has the
    schema's Type, and their encoding must be a JSON object whose registered
    claims have their types."""
    return _encode_claims(schema, claims).flat_map(lambda payload: jws.sign(payload, key, header))


@overload
def verify[A, R](
    schema: S.Codec[A, Any, R, Any], token: Token, key: HmacKey, **options: Unpack[VerifyOptions]
) -> Effect[Verified[A], JwtError, R | Mac]: ...
@overload
def verify[A, R](
    schema: S.Codec[A, Any, R, Any], token: Token, key: PublicKey, **options: Unpack[VerifyOptions]
) -> Effect[Verified[A], JwtError, R | Signature]: ...
@overload
def verify[A, R](
    schema: S.Codec[A, Any, R, Any],
    token: Token,
    key: VerificationKey,
    **options: Unpack[VerifyOptions],
) -> Effect[Verified[A], JwtError, R | Mac | Signature]: ...
def verify(
    schema: S.Codec[Any, Any, Any, Any],
    token: Token,
    key: VerificationKey,
    **options: Unpack[VerifyOptions],
) -> Effect[Verified[Any], JwtError, Any]:
    """The claims of a JWT signed with ``key``, checked against ``options``
    and decoded by ``schema``."""

    @gen
    def body():
        policy = yield from _read_policy(options)
        verified = yield from jws.verify(token, key)
        claims, registered = yield from _decode_claims(
            schema,
            verified.payload,
            cast("Mapping[str, object]", verified.protected_header),
            policy,
        )
        return Verified(claims, registered, verified.protected_header)

    return body


def verify_with_key_set[A, R](
    schema: S.Codec[A, Any, R, Any],
    token: Token,
    *,
    algorithms: Sequence[AsymmetricAlgorithm],
    **options: Unpack[VerifyOptions],
) -> Effect[VerifiedWithKey[A], JwtError, R | Jwks | Signature]:
    """``verify`` with the ``Jwks`` key the header selects, for an ``alg`` in
    ``algorithms``."""

    @gen
    def body():
        policy = yield from _read_policy(options)
        verified = yield from jws.verify_with_key_set(token, algorithms=algorithms)
        claims, registered = yield from _decode_claims(
            schema,
            verified.payload,
            cast("Mapping[str, object]", verified.protected_header),
            policy,
        )
        return VerifiedWithKey(claims, registered, verified.protected_header, verified.key)

    return body


def encrypt[A, R](
    schema: Exact[A, Any, R], claims: A, key: DirKey, header: Header | None = None
) -> Effect[Redacted[str], JwtError, R | Aead | SecureRandom]:
    """The claims, encoded by ``schema``, as an encrypted JWT. ``claims`` has
    the schema's Type."""
    return _encode_claims(schema, claims).flat_map(
        lambda payload: jwe.encrypt(payload, key, header)
    )


@overload
def decrypt[A, R](
    schema: S.Codec[A, Any, R, Any], token: Token, key: DirKey, **options: Unpack[VerifyOptions]
) -> Effect[Decrypted[A], JwtError, R | Aead]: ...
@overload
def decrypt[A, R, E = Never, R2 = Never](
    schema: S.Codec[A, Any, R, Any],
    token: Token,
    key: Callable[[jwe.ProtectedHeader], Effect[DirKey, E, R2]],
    **options: Unpack[VerifyOptions],
) -> Effect[Decrypted[A], JwtError | E, R | Aead | R2]: ...
def decrypt(
    schema: S.Codec[Any, Any, Any, Any],
    token: Token,
    key: DirKey | Callable[[jwe.ProtectedHeader], Effect[DirKey, Any, Any]],
    **options: Unpack[VerifyOptions],
) -> Effect[Decrypted[Any], Any, Any]:
    """The claims of an encrypted JWT, checked against ``options`` and
    decoded by ``schema``."""

    @gen
    def body():
        policy = yield from _read_policy(options)
        decrypted = yield from jwe.decrypt(token, key)
        claims, registered = yield from _decode_claims(
            schema,
            decrypted.plaintext,
            cast("Mapping[str, object]", decrypted.protected_header),
            policy,
        )
        return Decrypted(claims, registered, decrypted.protected_header, decrypted.key)

    return body


def decode_unverified(token: Token) -> Effect[Unverified, JoseError]:
    """A signed JWT's header and claims, without verifying anything."""

    @gen
    def body():
        parsed = yield from jws.parse(token)
        claims = parse_json_object(parsed.payload)
        if claims is None:
            return (yield from invalid_token("The JWT payload is not a JSON object"))
        return Unverified(parsed.protected_header, claims)

    return body


__all__ = [
    "Decrypted",
    "JoseError",
    "JwtError",
    "RegisteredClaim",
    "RegisteredClaims",
    "RegisteredClaimsSchema",
    "Unverified",
    "Verified",
    "VerifiedWithKey",
    "VerifyOptions",
    "decode_unverified",
    "decrypt",
    "encrypt",
    "sign",
    "verify",
    "verify_with_key_set",
]
