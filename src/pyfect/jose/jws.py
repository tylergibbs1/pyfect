"""Compact JSON Web Signatures (Effect's ``effect/jose/Jws``)::

    token = yield from jws.sign(b"hello", signing_key, {"typ": "text"})
    verified = yield from jws.verify(token, verification_key)

``verify`` accepts only the key's own algorithm. ``verify_with_key_set``
takes the key from the ``Jwks`` service, for the asymmetric algorithms
listed. The ``crit`` and ``b64`` header parameters are refused.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict, overload

from pyfect import schema as S
from pyfect._binary_codecs import base64_url_encode
from pyfect._core import Effect
from pyfect._some import Some
from pyfect.crypto.mac import Mac
from pyfect.crypto.signature import Signature
from pyfect.effect import gen, succeed
from pyfect.jose._compact import (
    Header,
    Token,
    crypto_failure,
    decode_header,
    decode_segment,
    encode_header,
    fail,
    invalid_argument,
    invalid_token,
    split,
    utf8,
)
from pyfect.jose.jose_error import AlgorithmNotAllowed, JoseError, SignatureVerificationFailed
from pyfect.jose.jwk import (
    ASYMMETRIC_ALGORITHMS,
    Algorithm,
    AlgorithmSchema,
    AsymmetricAlgorithm,
    HmacKey,
    PrivateKey,
    PublicKey,
    SigningKey,
    VerificationKey,
)
from pyfect.jose.jwks import Jwks, Selection
from pyfect.redacted import Redacted
from pyfect.redacted import make as redacted

_UNSUPPORTED = ("crit", "b64")


class ProtectedHeader(TypedDict):
    """A verified token's header; other members are any JSON."""

    alg: Algorithm
    kid: NotRequired[str]
    typ: NotRequired[str]
    cty: NotRequired[str]


ProtectedHeaderSchema = S.StructWithRest(
    S.Struct(ProtectedHeader, alg=AlgorithmSchema), S.Record(S.String, S.Json)
)


@dataclass(frozen=True, slots=True)
class Verified:
    protected_header: ProtectedHeader
    payload: bytes


@dataclass(frozen=True, slots=True)
class VerifiedWithKey:
    """``verify_with_key_set``'s result: the verified token and its key."""

    protected_header: ProtectedHeader
    payload: bytes
    key: PublicKey


@dataclass(frozen=True, slots=True)
class Parsed:
    protected_header: ProtectedHeader
    payload: bytes
    signature: bytes
    signing_input: bytes


_decode_protected_header_option = S.decode_unknown_option(ProtectedHeaderSchema)


def _decode_protected_header(input: object) -> ProtectedHeader | None:
    decoded = _decode_protected_header_option(input)
    return decoded.value if isinstance(decoded, Some) else None


def parse(token: Token) -> Effect[Parsed, JoseError]:
    """A token's parts, unverified."""

    @gen
    def body():
        header, payload, signature = yield from split(token, 3)
        protected_header = yield from decode_header(header, _decode_protected_header, _UNSUPPORTED)
        payload_bytes = decode_segment(payload)
        signature_bytes = decode_segment(signature)
        if payload_bytes is None or signature_bytes is None:
            return (yield from invalid_token("The payload or signature is not base64url"))
        return Parsed(protected_header, payload_bytes, signature_bytes, utf8(f"{header}.{payload}"))

    return body


_sign_failure = crypto_failure("Could not sign with the key")
_verify_failure = crypto_failure("Could not verify with the key")


def _algorithm_not_allowed() -> Effect[Any, JoseError]:
    return fail(AlgorithmNotAllowed())


def _authenticated(parsed: Parsed, valid: bool) -> Effect[Verified, JoseError]:
    if valid:
        return succeed(Verified(parsed.protected_header, parsed.payload))
    return fail(SignatureVerificationFailed())


def _verify_signature(parsed: Parsed, key: PublicKey) -> Effect[Verified, JoseError, Signature]:
    return (
        Signature()
        .flat_map(lambda service: service.verify(key.key, parsed.signature, parsed.signing_input))
        .map_error(_verify_failure)
        .flat_map(lambda valid: _authenticated(parsed, valid))
    )


@overload
def sign(
    payload: bytes, key: HmacKey, header: Header | None = None
) -> Effect[Redacted[str], JoseError, Mac]: ...
@overload
def sign(
    payload: bytes, key: PrivateKey, header: Header | None = None
) -> Effect[Redacted[str], JoseError, Signature]: ...
@overload
def sign(
    payload: bytes, key: SigningKey, header: Header | None = None
) -> Effect[Redacted[str], JoseError, Mac | Signature]: ...
def sign(
    payload: bytes, key: SigningKey, header: Header | None = None
) -> Effect[Redacted[str], JoseError, Any]:
    """A compact JWS of ``payload``; each key needs only its own service."""

    @gen
    def body():
        protected_header = yield from encode_header(
            {"alg": key.algorithm}, key.kid, header, _UNSUPPORTED
        )
        signing_input = f"{protected_header}.{base64_url_encode(payload)}"
        data = utf8(signing_input)
        if isinstance(key, HmacKey):
            mac = yield from Mac()
            signature = yield from mac.sign(key.key, data).map_error(_sign_failure)
        else:
            signer = yield from Signature()
            signature = yield from signer.sign(key.key, data).map_error(_sign_failure)
        return redacted(f"{signing_input}.{base64_url_encode(signature)}")

    return body


@overload
def verify(token: Token, key: HmacKey) -> Effect[Verified, JoseError, Mac]: ...
@overload
def verify(token: Token, key: PublicKey) -> Effect[Verified, JoseError, Signature]: ...
@overload
def verify(token: Token, key: VerificationKey) -> Effect[Verified, JoseError, Mac | Signature]: ...
def verify(token: Token, key: VerificationKey) -> Effect[Verified, JoseError, Any]:
    """The verified header and payload, when the token's ``alg`` is the
    key's and the signature is valid."""

    @gen
    def body():
        parsed = yield from parse(token)
        if parsed.protected_header["alg"] != key.algorithm:
            return (yield from _algorithm_not_allowed())
        if isinstance(key, PublicKey):
            return (yield from _verify_signature(parsed, key))
        mac = yield from Mac()
        valid = yield from mac.verify(key.key, parsed.signature, parsed.signing_input).map_error(
            _verify_failure
        )
        return (yield from _authenticated(parsed, valid))

    return body


def verify_with_key_set(
    token: Token, *, algorithms: Sequence[AsymmetricAlgorithm]
) -> Effect[VerifiedWithKey, JoseError, Jwks | Signature]:
    """Verify with the ``Jwks`` key the header selects, for an ``alg`` in
    ``algorithms`` (which must not be empty)."""

    @gen
    def body():
        if len(algorithms) == 0:
            return (yield from invalid_argument("algorithms must not be empty"))
        parsed = yield from parse(token)
        alg = parsed.protected_header["alg"]
        if alg not in ASYMMETRIC_ALGORITHMS or alg not in algorithms:
            return (yield from _algorithm_not_allowed())
        algorithm = alg
        jwks = yield from Jwks()
        key = yield from jwks.resolve(
            Selection(algorithm, parsed.protected_header.get("kid"), parsed.protected_header)
        )
        if key.algorithm != algorithm:
            return (yield from _algorithm_not_allowed())
        verified = yield from _verify_signature(parsed, key)
        return VerifiedWithKey(verified.protected_header, verified.payload, key)

    return body


__all__ = [
    "Header",
    "JoseError",
    "Parsed",
    "ProtectedHeader",
    "ProtectedHeaderSchema",
    "Verified",
    "VerifiedWithKey",
    "parse",
    "sign",
    "verify",
    "verify_with_key_set",
]
