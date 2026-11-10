"""JSON Web Keys for JOSE (Effect's ``effect/jose/Jwk``)::

    pair = yield from jwk.generate_key_pair("ES256", kid="k1")
    signing = yield from jwk.import_private(pair.private_key, "ES256")
    verifying = yield from jwk.import_public(pair.public_key, "ES256")

Importing checks a JWK's ``alg``, ``use`` and ``key_ops`` against the
algorithm and operation it is imported for, refuses private members in a
public JWK and RSA moduli below 2048 bits. Private and secret JWKs travel
as ``Redacted``. ``thumbprint`` is RFC 7638's (``thumbprint_uri`` RFC 9278's).
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Never, NotRequired, TypedDict, cast

from pyfect import schema as S
from pyfect._binary_codecs import base64_url_encode
from pyfect._core import Effect
from pyfect._json_text import stringify
from pyfect.crypto import aead, digest, key_format, mac, signature
from pyfect.crypto.digest import Digest
from pyfect.crypto.secure_random import SecureRandom
from pyfect.crypto.signature import Signature
from pyfect.crypto.web_crypto import JsonWebKey
from pyfect.effect import gen, succeed
from pyfect.jose._compact import (
    crypto_failure,
    decode_segment,
    has_private_members,
    invalid_argument,
    invalid_key,
    is_canonical_segment,
    public_key_failure,
    utf8,
)
from pyfect.jose.jose_error import JoseError
from pyfect.redacted import Redacted
from pyfect.redacted import make as redacted
from pyfect.redacted import value as reveal

type AsymmetricAlgorithm = Literal[
    "RS256", "RS384", "RS512", "PS256", "PS384", "PS512", "ES256", "ES384", "ES512", "EdDSA"
]
type HmacAlgorithm = Literal["HS256", "HS384", "HS512"]
type Algorithm = HmacAlgorithm | AsymmetricAlgorithm
type SecretAlgorithm = HmacAlgorithm | Literal["dir"]

ASYMMETRIC_ALGORITHMS: tuple[AsymmetricAlgorithm, ...] = (
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
ALGORITHMS: tuple[Algorithm, ...] = ("HS256", "HS384", "HS512", *ASYMMETRIC_ALGORITHMS)

AsymmetricAlgorithmSchema = S.Literals(*ASYMMETRIC_ALGORITHMS)
AlgorithmSchema = S.Literals(*ALGORITHMS)


class _Metadata(TypedDict):
    kid: NotRequired[str]
    alg: NotRequired[str]
    use: NotRequired[str]
    key_ops: NotRequired[Sequence[str]]


class _NoPrivateMembers(TypedDict):
    d: NotRequired[Never]
    p: NotRequired[Never]
    q: NotRequired[Never]
    dp: NotRequired[Never]
    dq: NotRequired[Never]
    qi: NotRequired[Never]
    oth: NotRequired[Never]
    k: NotRequired[Never]


class RsaPublicJwk(_Metadata, _NoPrivateMembers):
    kty: Literal["RSA"]
    n: str
    e: str


class EcPublicJwk(_Metadata, _NoPrivateMembers):
    kty: Literal["EC"]
    crv: Literal["P-256", "P-384", "P-521"]
    x: str
    y: str


class OkpPublicJwk(_Metadata, _NoPrivateMembers):
    kty: Literal["OKP"]
    crv: Literal["Ed25519"]
    x: str


type PublicJwk = RsaPublicJwk | EcPublicJwk | OkpPublicJwk


class RsaPrivateJwk(_Metadata):
    kty: Literal["RSA"]
    n: str
    e: str
    d: str
    p: str
    q: str
    dp: str
    dq: str
    qi: str
    oth: NotRequired[Never]


class EcPrivateJwk(_Metadata):
    kty: Literal["EC"]
    crv: Literal["P-256", "P-384", "P-521"]
    x: str
    y: str
    d: str


class OkpPrivateJwk(_Metadata):
    kty: Literal["OKP"]
    crv: Literal["Ed25519"]
    x: str
    d: str


type PrivateJwk = RsaPrivateJwk | EcPrivateJwk | OkpPrivateJwk


class SecretJwk(_Metadata):
    kty: Literal["oct"]
    k: str


_base64url = S.String.check(
    S.make_filter(is_canonical_segment, expected="a canonical base64url encoded string")
)
_no_private_members = {name: S.Never for name in ("d", "p", "q", "dp", "dq", "qi", "oth", "k")}

PublicJwkSchema = S.Union(
    S.Struct(RsaPublicJwk, n=_base64url, e=_base64url, **_no_private_members),
    S.Struct(EcPublicJwk, x=_base64url, y=_base64url, **_no_private_members),
    S.Struct(OkpPublicJwk, x=_base64url, **_no_private_members),
)
PrivateJwkSchema = S.Union(
    S.Struct(
        RsaPrivateJwk,
        n=_base64url,
        e=_base64url,
        d=_base64url,
        p=_base64url,
        q=_base64url,
        dp=_base64url,
        dq=_base64url,
        qi=_base64url,
        oth=S.Never,
    ),
    S.Struct(EcPrivateJwk, x=_base64url, y=_base64url, d=_base64url),
    S.Struct(OkpPrivateJwk, x=_base64url, d=_base64url),
)
SecretJwkSchema = S.Struct(SecretJwk)

_is_public_jwk = S.is_(PublicJwkSchema)
_is_private_jwk = S.is_(PrivateJwkSchema)


@dataclass(frozen=True, slots=True)
class PublicKey:
    """An imported verification key and the public JWK it came from."""

    algorithm: AsymmetricAlgorithm
    kid: str | None
    jwk: PublicJwk
    key: signature.PublicKey[Any]

    tag: ClassVar[Literal["PublicKey"]] = "PublicKey"


@dataclass(frozen=True, slots=True)
class PrivateKey:
    algorithm: AsymmetricAlgorithm
    kid: str | None
    key: signature.PrivateKey[Any]

    tag: ClassVar[Literal["PrivateKey"]] = "PrivateKey"


@dataclass(frozen=True, slots=True)
class HmacKey:
    """An imported ``HS*`` secret (Effect's ``SecretKey<HmacAlgorithm>``)."""

    algorithm: HmacAlgorithm
    kid: str | None
    key: mac.Key[Any]

    tag: ClassVar[Literal["SecretKey"]] = "SecretKey"


@dataclass(frozen=True, slots=True)
class DirKey:
    """An imported ``dir`` (A256GCM) secret (Effect's ``SecretKey<"dir">``)."""

    algorithm: Literal["dir"]
    kid: str | None
    key: aead.Key[Any]

    tag: ClassVar[Literal["SecretKey"]] = "SecretKey"


type SecretKey = HmacKey | DirKey
type SigningKey = PrivateKey | HmacKey
type VerificationKey = PublicKey | HmacKey


@dataclass(frozen=True, slots=True)
class KeyPair:
    public_key: PublicJwk
    private_key: Redacted[PrivateJwk]


_SIGNATURE_ALGORITHMS: dict[AsymmetricAlgorithm, Callable[[int], signature.Algorithm]] = {
    "RS256": lambda bits: signature.rsa_pkcs1v15(hash=digest.sha256, modulus_length=bits),
    "RS384": lambda bits: signature.rsa_pkcs1v15(hash=digest.sha384, modulus_length=bits),
    "RS512": lambda bits: signature.rsa_pkcs1v15(hash=digest.sha512, modulus_length=bits),
    "PS256": lambda bits: signature.rsa_pss(hash=digest.sha256, modulus_length=bits),
    "PS384": lambda bits: signature.rsa_pss(hash=digest.sha384, modulus_length=bits),
    "PS512": lambda bits: signature.rsa_pss(hash=digest.sha512, modulus_length=bits),
    "ES256": lambda _bits: signature.ecdsa_p256,
    "ES384": lambda _bits: signature.ecdsa_p384,
    "ES512": lambda _bits: signature.ecdsa_p521,
    "EdDSA": lambda _bits: signature.ed25519,
}


def _signature_algorithm(
    algorithm: AsymmetricAlgorithm, modulus_length: int = 2048
) -> signature.Algorithm:
    return _SIGNATURE_ALGORITHMS[algorithm](modulus_length)


_HMAC_ALGORITHMS: dict[HmacAlgorithm, mac.Algorithm] = {
    "HS256": mac.hmac_sha256,
    "HS384": mac.hmac_sha384,
    "HS512": mac.hmac_sha512,
}


def _secret_key_length(algorithm: SecretAlgorithm) -> int:
    return 32 if algorithm == "dir" else _HMAC_ALGORITHMS[algorithm].hash.output_length


def _check_metadata(
    jwk: Mapping[str, object],
    algorithm: str,
    use: Literal["sig", "enc"],
    operations: Sequence[str],
) -> Effect[None, JoseError]:
    """``key_ops`` must allow every operation; secret keys do both."""
    alg, own_use, key_ops = jwk.get("alg"), jwk.get("use"), jwk.get("key_ops")
    if alg is not None and alg != algorithm:
        return invalid_key(f"The JWK is for {alg}, not {algorithm}")
    if own_use is not None and own_use != use:
        return invalid_key(f"The JWK use is {own_use}, not {use}")
    if key_ops is not None and not all(
        operation in cast("Sequence[str]", key_ops) for operation in operations
    ):
        return invalid_key(f"The JWK key_ops must allow {' and '.join(operations)}")
    return succeed(None)


def _check_modulus(
    key: signature.PublicKey[Any] | signature.PrivateKey[Any],
) -> Effect[None, JoseError]:
    """Checked on the imported key, whose algorithm carries the real modulus."""
    algorithm: signature.Algorithm = key.algorithm
    if (
        isinstance(algorithm, signature.RsaPss | signature.RsaPkcs1v15)
        and algorithm.modulus_length < 2048
    ):
        return invalid_key("RSA keys must have at least 2048 bits")
    return succeed(None)


def _json_web_key(jwk: Mapping[str, object]) -> JsonWebKey:
    """KeyFormat reads only the key members; JOSE metadata is checked here."""
    return cast("JsonWebKey", jwk)


def _export_jwk(
    key: signature.PrivateKey[Any] | signature.PublicKey[Any],
    algorithm: AsymmetricAlgorithm,
    kid: str | None,
) -> Effect[dict[str, object], JoseError]:
    encoded = key_format.encode(key_format.jwk, key)

    def with_metadata(jwk: JsonWebKey) -> dict[str, object]:
        out: dict[str, object] = dict(jwk)
        if kid is not None:
            out["kid"] = kid
        out["alg"] = algorithm
        out["use"] = "sig"
        return out

    return encoded.map_both(
        on_failure=crypto_failure("Could not export the key"), on_success=with_metadata
    )


def generate_key_pair(
    algorithm: AsymmetricAlgorithm, *, kid: str | None = None, modulus_length: int | None = None
) -> Effect[KeyPair, JoseError, Signature]:
    """A new key pair as JWKs; RSA moduli default to 2048 bits and must be
    at least that."""

    @gen
    def body():
        if modulus_length is not None and not (
            type(modulus_length) is int and 2048 <= modulus_length <= 2**53 - 1
        ):
            return (
                yield from invalid_argument("modulusLength must be an integer of at least 2048")
            )
        service = yield from Signature()
        pair = yield from service.generate_key_pair(
            _signature_algorithm(algorithm, modulus_length or 2048)
        ).map_error(crypto_failure(f"Could not generate a {algorithm} key pair"))
        public_jwk = yield from _export_jwk(pair.public_key, algorithm, kid)
        private_jwk = yield from _export_jwk(pair.private_key, algorithm, kid)
        return KeyPair(cast("PublicJwk", public_jwk), redacted(cast("PrivateJwk", private_jwk)))

    return body


def generate_secret(
    algorithm: SecretAlgorithm, *, kid: str | None = None
) -> Effect[Redacted[SecretJwk], Never, SecureRandom]:
    """A random secret JWK of the algorithm's key length."""

    def make(data: bytes) -> Redacted[SecretJwk]:
        jwk: SecretJwk = {
            "kty": "oct",
            "k": base64_url_encode(data),
            "alg": algorithm,
            "use": "enc" if algorithm == "dir" else "sig",
        }
        if kid is not None:
            jwk["kid"] = kid
        return redacted(jwk)

    return (
        SecureRandom()
        .flat_map(lambda random: random.random_bytes(_secret_key_length(algorithm)))
        .map(make)
    )


def import_public(jwk: PublicJwk, algorithm: AsymmetricAlgorithm) -> Effect[PublicKey, JoseError]:
    """A verification key; the JWK must allow ``verify`` for ``sig``."""

    @gen
    def body():
        data = cast("Mapping[str, object]", jwk)
        if has_private_members(data):
            return (yield from invalid_key("A public JWK cannot contain private members"))
        yield from _check_metadata(data, algorithm, "sig", ("verify",))
        if not _is_public_jwk(jwk):
            return (yield from invalid_key("Expected a public JWK with base64url key members"))
        key = yield from key_format.decode_public(
            key_format.jwk, _signature_algorithm(algorithm), _json_web_key(data)
        ).map_error(public_key_failure)
        yield from _check_modulus(key)
        return PublicKey(algorithm, jwk.get("kid"), jwk, key)

    return body


def import_private(
    input: Redacted[PrivateJwk], algorithm: AsymmetricAlgorithm
) -> Effect[PrivateKey, JoseError]:
    """A signing key; the JWK must allow ``sign`` for ``sig``."""

    @gen
    def body():
        jwk = reveal(input)
        data = cast("Mapping[str, object]", jwk)
        yield from _check_metadata(data, algorithm, "sig", ("sign",))
        if not _is_private_jwk(jwk):
            return (yield from invalid_key("Expected a private JWK with base64url key members"))
        key = yield from key_format.decode_private(
            key_format.jwk, _signature_algorithm(algorithm), _json_web_key(data)
        ).map_error(crypto_failure(f"Could not import the private JWK for {algorithm}"))
        yield from _check_modulus(key)
        return PrivateKey(algorithm, jwk.get("kid"), key)

    return body


def import_spki(
    input: bytes | str, algorithm: AsymmetricAlgorithm, *, kid: str | None = None
) -> Effect[PublicKey, JoseError]:
    """A verification key from SPKI DER bytes or PEM text."""

    @gen
    def body():
        decoded = (
            key_format.decode_public(
                key_format.pem(key_format.spki), _signature_algorithm(algorithm), input
            )
            if isinstance(input, str)
            else key_format.decode_public(key_format.spki, _signature_algorithm(algorithm), input)
        )
        key = yield from decoded.map_error(public_key_failure)
        yield from _check_modulus(key)
        jwk = yield from _export_jwk(key, algorithm, kid)
        return PublicKey(algorithm, kid, cast("PublicJwk", jwk), key)

    return body


def import_pkcs8(
    input: Redacted[bytes] | Redacted[str],
    algorithm: AsymmetricAlgorithm,
    *,
    kid: str | None = None,
) -> Effect[PrivateKey, JoseError]:
    """A signing key from PKCS#8 DER bytes or PEM text."""

    @gen
    def body():
        data: bytes | str = reveal(input)
        decoded = (
            key_format.decode_private(
                key_format.pem(key_format.pkcs8), _signature_algorithm(algorithm), data
            )
            if isinstance(data, str)
            else key_format.decode_private(key_format.pkcs8, _signature_algorithm(algorithm), data)
        )
        key = yield from decoded.map_error(
            crypto_failure(f"Could not import the PKCS#8 key for {algorithm}")
        )
        yield from _check_modulus(key)
        return PrivateKey(algorithm, kid, key)

    return body


def _secret_bytes(
    input: Redacted[SecretJwk], algorithm: SecretAlgorithm
) -> Effect[tuple[SecretJwk, bytes], JoseError]:
    @gen
    def body():
        jwk = reveal(input)
        data = cast("Mapping[str, object]", jwk)
        if algorithm == "dir":
            yield from _check_metadata(data, algorithm, "enc", ("encrypt", "decrypt"))
        else:
            yield from _check_metadata(data, algorithm, "sig", ("sign", "verify"))
        k = data.get("k")
        decoded = decode_segment(k) if data.get("kty") == "oct" and isinstance(k, str) else None
        if decoded is None:
            return (yield from invalid_key("Expected an oct JWK with a base64url k member"))
        length = _secret_key_length(algorithm)
        if algorithm == "dir" and len(decoded) != length:
            return (yield from invalid_key("dir keys must have exactly 32 bytes"))
        if algorithm != "dir" and len(decoded) < length:
            return (yield from invalid_key(f"{algorithm} keys must have at least {length} bytes"))
        return jwk, decoded

    return body


def import_hmac(input: Redacted[SecretJwk], algorithm: HmacAlgorithm) -> Effect[HmacKey, JoseError]:
    """An ``HS*`` key (Effect's ``importSecret`` for an HMAC algorithm); the
    JWK must allow ``sign`` and ``verify`` for ``sig``."""

    @gen
    def body():
        jwk, data = yield from _secret_bytes(input, algorithm)
        key = yield from mac.key(_HMAC_ALGORITHMS[algorithm], data).map_error(
            crypto_failure(f"Could not import the {algorithm} key")
        )
        return HmacKey(algorithm, jwk.get("kid"), key)

    return body


def import_dir(input: Redacted[SecretJwk]) -> Effect[DirKey, JoseError]:
    """A 32-byte ``dir`` (A256GCM) key (Effect's ``importSecret(jwk, "dir")``);
    the JWK must allow ``encrypt`` and ``decrypt`` for ``enc``."""

    @gen
    def body():
        jwk, data = yield from _secret_bytes(input, "dir")
        key = yield from aead.key(aead.aes256_gcm, data).map_error(
            crypto_failure("Could not import the dir key")
        )
        return DirKey("dir", jwk.get("kid"), key)

    return body


def import_secret(
    input: Redacted[SecretJwk], algorithm: SecretAlgorithm
) -> Effect[SecretKey, JoseError]:
    """``import_hmac`` or ``import_dir`` by ``algorithm`` (Effect's
    ``importSecret``)."""
    if algorithm == "dir":
        return import_dir(input).map(lambda key: key)
    return import_hmac(input, algorithm).map(lambda key: key)


def export_public(key: PublicKey) -> Effect[PublicJwk, JoseError]:
    return _export_jwk(key.key, key.algorithm, key.kid).map(lambda jwk: cast("PublicJwk", jwk))


def export_private(key: PrivateKey) -> Effect[Redacted[PrivateJwk], JoseError]:
    return _export_jwk(key.key, key.algorithm, key.kid).map(
        lambda jwk: redacted(cast("PrivateJwk", jwk))
    )


def export_spki(key: PublicKey) -> Effect[bytes, JoseError]:
    """The key as SPKI DER bytes."""
    return key_format.encode(key_format.spki, key.key).map_error(
        crypto_failure("Could not export the SPKI key")
    )


def export_spki_pem(key: PublicKey) -> Effect[str, JoseError]:
    """The key as SPKI PEM text (Effect's ``exportSpki(key, { format: "pem" })``)."""
    return key_format.encode(key_format.pem(key_format.spki), key.key).map_error(
        crypto_failure("Could not export the SPKI key")
    )


def export_pkcs8(key: PrivateKey) -> Effect[Redacted[bytes], JoseError]:
    """The key as PKCS#8 DER bytes."""
    return key_format.encode(key_format.pkcs8, key.key).map_both(
        on_failure=crypto_failure("Could not export the PKCS#8 key"), on_success=redacted
    )


def export_pkcs8_pem(key: PrivateKey) -> Effect[Redacted[str], JoseError]:
    """The key as PKCS#8 PEM text (Effect's ``exportPkcs8(key, { format: "pem" })``)."""
    return key_format.encode(key_format.pem(key_format.pkcs8), key.key).map_both(
        on_failure=crypto_failure("Could not export the PKCS#8 key"), on_success=redacted
    )


type ThumbprintInput = (
    PublicJwk | Redacted[PrivateJwk] | Redacted[SecretJwk] | PublicKey | PrivateKey | SecretKey
)

_THUMBPRINT_HASHES = ("SHA-256", "SHA-384", "SHA-512")


def _thumbprint_jwk(input: ThumbprintInput) -> Effect[Mapping[str, object], JoseError]:
    if isinstance(input, Redacted):
        return succeed(cast("Mapping[str, object]", reveal(input)))
    if isinstance(input, PublicKey | PrivateKey | HmacKey | DirKey):
        failure = crypto_failure("Could not export the key for a thumbprint")
        encoded = key_format.encode(key_format.jwk, input.key)
        return encoded.map_both(
            on_failure=failure, on_success=lambda jwk: cast("Mapping[str, object]", jwk)
        )
    return succeed(cast("Mapping[str, object]", input))


def _required_members(jwk: Mapping[str, object]) -> dict[str, object] | None:
    match jwk.get("kty"):
        case "RSA":
            return {"e": jwk.get("e"), "kty": "RSA", "n": jwk.get("n")}
        case "EC":
            return {"crv": jwk.get("crv"), "kty": "EC", "x": jwk.get("x"), "y": jwk.get("y")}
        case "OKP":
            return {"crv": jwk.get("crv"), "kty": "OKP", "x": jwk.get("x")}
        case "oct":
            return {"k": jwk.get("k"), "kty": "oct"}
        case _:
            return None


def thumbprint(
    input: ThumbprintInput, hash: digest.Algorithm = digest.sha256
) -> Effect[str, JoseError, Digest]:
    """RFC 7638's thumbprint: the hash of the required members, as
    base64url."""

    @gen
    def body():
        if hash.name not in _THUMBPRINT_HASHES:
            return (
                yield from invalid_argument("JWK thumbprints require SHA-256, SHA-384, or SHA-512")
            )
        jwk = yield from _thumbprint_jwk(input)
        required = _required_members(jwk)
        if required is None:
            return (yield from invalid_key("Unsupported JWK key type for a thumbprint"))
        members_ok = all(isinstance(value, str) and value for value in required.values())
        if not members_ok or (
            not is_canonical_segment(cast("str", required["k"]))
            if required["kty"] == "oct"
            else not _is_public_jwk(required)
        ):
            return (yield from invalid_key("Expected a JWK with canonical base64url key members"))
        service = yield from Digest()
        hashed = yield from service.digest(hash, utf8(stringify(required)))
        return base64_url_encode(hashed)

    return body


def thumbprint_uri(
    input: ThumbprintInput, hash: digest.Algorithm = digest.sha256
) -> Effect[str, JoseError, Digest]:
    """RFC 9278's thumbprint URI."""
    return thumbprint(input, hash).map(
        lambda value: f"urn:ietf:params:oauth:jwk-thumbprint:{hash.name.lower()}:{value}"
    )


__all__ = [
    "ALGORITHMS",
    "ASYMMETRIC_ALGORITHMS",
    "Algorithm",
    "AlgorithmSchema",
    "AsymmetricAlgorithm",
    "AsymmetricAlgorithmSchema",
    "DirKey",
    "EcPrivateJwk",
    "EcPublicJwk",
    "HmacAlgorithm",
    "HmacKey",
    "JoseError",
    "KeyPair",
    "OkpPrivateJwk",
    "OkpPublicJwk",
    "PrivateJwk",
    "PrivateJwkSchema",
    "PrivateKey",
    "PublicJwk",
    "PublicJwkSchema",
    "PublicKey",
    "RsaPrivateJwk",
    "RsaPublicJwk",
    "SecretAlgorithm",
    "SecretJwk",
    "SecretJwkSchema",
    "SecretKey",
    "SigningKey",
    "ThumbprintInput",
    "VerificationKey",
    "export_pkcs8",
    "export_pkcs8_pem",
    "export_private",
    "export_public",
    "export_spki",
    "export_spki_pem",
    "generate_key_pair",
    "generate_secret",
    "import_dir",
    "import_hmac",
    "import_pkcs8",
    "import_private",
    "import_public",
    "import_secret",
    "import_spki",
    "thumbprint",
    "thumbprint_uri",
]
