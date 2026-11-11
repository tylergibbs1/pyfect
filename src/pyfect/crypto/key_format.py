"""Reading and writing keys in standard formats (Effect's
``effect/crypto/KeyFormat``)::

    public_key = yield from decode_public(pem(spki), signature.ecdsa_p256, pem_text)
    jwk_dict = yield from encode(jwk, private_key)

Public keys: ``spki`` and ``jwk``. Private keys: ``pkcs8`` and ``jwk``,
and read-only ``pkcs1`` (RSA) and ``sec1`` (EC). Secret keys: ``jwk``
only. ``pem(format)`` wraps a DER format in a PEM block with the format's
label. A format's roles and directions are in its type, so writing a
secret key as SPKI is a type error. A JWK's ``kty``, ``crv`` and ``alg``
must match the algorithm; ``use``, ``key_ops`` and ``ext`` are dropped
before importing. Reading uses the ``WebCrypto`` reference.
"""

from __future__ import annotations

import base64
import re
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Final, Generic, Literal, Never, TypeVar, cast, overload

from pyfect._binary_codecs import base64_decode, base64_url_decode, base64_url_encode
from pyfect._core import Effect
from pyfect.crypto import _asymmetric, _der, _key, _web, aead, cipher, key_agreement, key_wrap, mac
from pyfect.crypto import signature as signature_module
from pyfect.crypto._asymmetric import Curve, Family
from pyfect.crypto._key import KeyBase, material
from pyfect.crypto.crypto_error import CryptoError, Unsupported
from pyfect.crypto.key_wrap import SecretAlgorithm, SecretKey
from pyfect.crypto.web_crypto import CryptoKey, JsonWebKey, SubtleCrypto
from pyfect.effect import succeed, suspend
from pyfect.result import Err

type Role = Literal["public", "private", "secret"]
type Direction = Literal["decode", "encode"]
type FormatTag = Literal["spki", "pkcs8", "jwk", "pkcs1", "sec1"]

R_contra = TypeVar("R_contra", contravariant=True)
D_contra = TypeVar("D_contra", contravariant=True)
# Invariant: it is read and written, and inferred from the format alone, so
# PEM text cannot be given bytes.
FormatData = TypeVar("FormatData")


@dataclass(frozen=True, slots=True)
class Format(Generic[R_contra, D_contra, FormatData]):
    """A key format: the roles it holds and the directions it goes in are
    type parameters, ``FormatData`` is what it reads and writes."""

    tag: FormatTag
    pem: bool = False


spki: Format[Literal["public"], Direction, bytes] = Format("spki")
pkcs8: Format[Literal["private"], Direction, bytes] = Format("pkcs8")
jwk: Format[Role, Direction, JsonWebKey] = Format("jwk")
pkcs1: Format[Literal["private"], Literal["decode"], bytes] = Format("pkcs1")
"""RSA private keys (RFC 8017), read only."""
sec1: Format[Literal["private"], Literal["decode"], bytes] = Format("sec1")
"""EC private keys (RFC 5915), read only; they must include the public point."""


def pem[R, D](format: Format[R, D, bytes]) -> Format[R, D, str]:
    """``format`` as a PEM block."""
    return Format(format.tag, pem=True)


type AsymmetricAlgorithm = signature_module.Algorithm | key_agreement.Algorithm | key_wrap.RsaOaep
type PublicKey = (
    signature_module.PublicKey[Any] | key_agreement.PublicKey[Any] | key_wrap.PublicKey[Any]
)
type PrivateKey = (
    signature_module.PrivateKey[Any] | key_agreement.PrivateKey[Any] | key_wrap.PrivateKey[Any]
)
type Key = PublicKey | PrivateKey | SecretKey


def _invalid_key(method: str, description: str) -> Effect[Never, CryptoError]:
    return _web.invalid_key("KeyFormat", method, description)


def _unsupported(method: str, description: str) -> Effect[Never, CryptoError]:
    return _web.fail("KeyFormat", method, Unsupported(description=description))


def _family_of(algorithm: object) -> Family | None:
    match algorithm:
        case (
            signature_module.Ed25519()
            | signature_module.Ecdsa()
            | signature_module.RsaPss()
            | signature_module.RsaPkcs1v15()
        ):
            return signature_module.family
        case key_agreement.X25519() | key_agreement.Ecdh():
            return key_agreement.family
        case key_wrap.RsaOaep():
            return key_wrap.family
        case _:
            return None


_LABELS: Final[dict[FormatTag, str]] = {
    "spki": "PUBLIC KEY",
    "pkcs8": "PRIVATE KEY",
    "pkcs1": "RSA PRIVATE KEY",
    "sec1": "EC PRIVATE KEY",
    "jwk": "",
}

_PEM_PATTERN = re.compile(
    r"-----BEGIN ([A-Z0-9 ]+)-----\r?\n([A-Za-z0-9+/=\r\n]+)-----END ([A-Z0-9 ]+)-----"
)


def _from_pem(label: str, text: str) -> bytes | str:
    match = _PEM_PATTERN.fullmatch(text.strip())
    if match is None or match[1] != label or match[3] != label:
        return f"Expected exactly one PEM block labelled {label}"
    decoded = base64_decode(re.sub(r"\r?\n", "", match[2]))
    if isinstance(decoded, Err):
        return f"The {label} PEM block is not valid base64"
    return decoded.value


def _to_pem(label: str, der: bytes) -> str:
    encoded = base64.b64encode(der).decode()
    lines = [encoded[i : i + 64] for i in range(0, len(encoded), 64)]
    joined = "\n".join(lines)
    return f"-----BEGIN {label}-----\n{joined}\n-----END {label}-----\n"


# AlgorithmIdentifier for rsaEncryption (1.2.840.113549.1.1.1) with NULL
# parameters, the OIDs of id-ecPublicKey and the NIST curves.
_RSA_ENCRYPTION = bytes([48, 13, 6, 9, 42, 134, 72, 134, 247, 13, 1, 1, 1, 5, 0])
_EC_PUBLIC_KEY = bytes([6, 7, 42, 134, 72, 206, 61, 2, 1])
_CURVE_OIDS: Final[dict[Curve, bytes]] = {
    "P-256": bytes([6, 8, 42, 134, 72, 206, 61, 3, 1, 7]),
    "P-384": bytes([6, 5, 43, 129, 4, 0, 34]),
    "P-521": bytes([6, 5, 43, 129, 4, 0, 35]),
}
_VERSION_0 = bytes([2, 1, 0])


def _ec_algorithm(curve: Curve) -> bytes:
    return _der.encode(_der.SEQUENCE, _EC_PUBLIC_KEY, _CURVE_OIDS[curve])


@dataclass(frozen=True, slots=True)
class _Problem:
    reason: Literal["InvalidKey", "Unsupported"]
    description: str


_MISSING_POINT = _Problem(
    "Unsupported",
    "EC private keys must include the public point, which Safari cannot import without",
)


def _pkcs1_to_pkcs8(pkcs1_der: bytes) -> bytes | _Problem:
    # RFC 8017 appendix A.1.2 inside an RFC 5208 PrivateKeyInfo.
    if _der.read_only(pkcs1_der, _der.SEQUENCE) is None:
        return _Problem("InvalidKey", "Malformed PKCS#1 RSAPrivateKey")
    return _der.encode(
        _der.SEQUENCE, _VERSION_0, _RSA_ENCRYPTION, _der.encode(_der.OCTET_STRING, pkcs1_der)
    )


def _sec1_to_pkcs8(sec1_der: bytes, curve: Curve) -> bytes | _Problem:
    # RFC 5915: ECPrivateKey ::= SEQUENCE { version 1, privateKey OCTET
    # STRING, [0] parameters OPTIONAL, [1] publicKey OPTIONAL }. PKCS#8
    # carries the curve in its AlgorithmIdentifier, so [0] is dropped.
    malformed = _Problem("InvalidKey", "Malformed SEC1 ECPrivateKey")
    outer = _der.read_only(sec1_der, _der.SEQUENCE)
    fields = None if outer is None else _der.children(sec1_der, outer)
    if fields is None or len(fields) < 2:
        return malformed
    version, private_key, *rest = fields
    if version.tag != _der.INTEGER or private_key.tag != _der.OCTET_STRING:
        return malformed
    params = next((field for field in rest if field.tag == 0xA0), None)
    point = next((field for field in rest if field.tag == 0xA1), None)
    if params is not None:
        oid = _der.read(sec1_der, params.start, params.end)
        if oid is None or oid.tag != _der.OBJECT_IDENTIFIER or oid.end != params.end:
            return malformed
        if _der.slice_of(sec1_der, oid) != _CURVE_OIDS[curve]:
            return _Problem("InvalidKey", f"Expected a {curve} key")
    if point is None:
        return _MISSING_POINT
    ec_private_key = _der.encode(
        _der.SEQUENCE,
        _der.slice_of(sec1_der, version),
        _der.slice_of(sec1_der, private_key),
        _der.slice_of(sec1_der, point),
    )
    return _der.encode(
        _der.SEQUENCE,
        _VERSION_0,
        _ec_algorithm(curve),
        _der.encode(_der.OCTET_STRING, ec_private_key),
    )


def _check_ec_pkcs8(pkcs8_der: bytes, curve: Curve) -> _Problem | None:
    # Checks the algorithm before classifying a missing EC public point;
    # other malformed DER is left to the import.
    outer = _der.read_only(pkcs8_der, _der.SEQUENCE)
    fields = None if outer is None else _der.children(pkcs8_der, outer)
    if fields is None or len(fields) < 3:
        return None
    if _der.slice_of(pkcs8_der, fields[1]) != _ec_algorithm(curve):
        return _Problem("InvalidKey", f"Expected a {curve} EC private key")
    octets = fields[2]
    if octets.tag != _der.OCTET_STRING:
        return None
    inner = _der.read(pkcs8_der, octets.start, octets.end)
    if inner is None or inner.tag != _der.SEQUENCE:
        return None
    ec_fields = _der.children(pkcs8_der, inner)
    if ec_fields is None:
        return None
    return None if any(field.tag == 0xA1 for field in ec_fields) else _MISSING_POINT


@dataclass(frozen=True, slots=True)
class _Jose:
    kty: str
    crv: str | None
    algs: Sequence[str]


_ECDH_ALGS: Final = ("ECDH-ES", "ECDH-ES+A128KW", "ECDH-ES+A192KW", "ECDH-ES+A256KW")

_SECRET_ALGS: Final[dict[str, str]] = {
    "aes128Gcm": "A128GCM",
    "aes256Gcm": "A256GCM",
    "chacha20Poly1305": "C20P",
    "xchacha20Poly1305": "XC20P",
    "aes128Ctr": "A128CTR",
    "aes256Ctr": "A256CTR",
    "aes128Cbc": "A128CBC",
    "aes256Cbc": "A256CBC",
    "hmacSha1": "HS1",
    "hmacSha256": "HS256",
    "hmacSha384": "HS384",
    "hmacSha512": "HS512",
    "aes128Kw": "A128KW",
    "aes256Kw": "A256KW",
}


def _hash_bits(hash_name: str) -> str:
    return hash_name[4:]


def _jose_of(algorithm: AsymmetricAlgorithm | SecretAlgorithm) -> _Jose:  # noqa: PLR0911
    match algorithm:
        case signature_module.Ed25519():
            return _Jose("OKP", "Ed25519", ("EdDSA", "Ed25519"))
        case key_agreement.X25519():
            return _Jose("OKP", "X25519", _ECDH_ALGS)
        case signature_module.Ecdsa():
            return _Jose("EC", algorithm.named_curve, (f"ES{_hash_bits(algorithm.hash.name)}",))
        case key_agreement.Ecdh():
            return _Jose("EC", algorithm.named_curve, _ECDH_ALGS)
        case signature_module.RsaPss():
            return _Jose("RSA", None, (f"PS{_hash_bits(algorithm.hash.name)}",))
        case signature_module.RsaPkcs1v15():
            return _Jose("RSA", None, (f"RS{_hash_bits(algorithm.hash.name)}",))
        case key_wrap.RsaOaep():
            alg = (
                "RSA-OAEP"
                if algorithm.hash.name == "SHA-1"
                else f"RSA-OAEP-{_hash_bits(algorithm.hash.name)}"
            )
            return _Jose("RSA", None, (alg,))
        case _:
            return _Jose("oct", None, (_SECRET_ALGS[algorithm.name],))


_PUBLIC_MEMBERS: Final = ("kty", "crv", "x", "y", "n", "e")
_PRIVATE_MEMBERS: Final = (*_PUBLIC_MEMBERS, "d", "p", "q", "dp", "dq", "qi")


def _pick(data: Mapping[str, object], members: Sequence[str]) -> JsonWebKey:
    return cast("JsonWebKey", {member: data[member] for member in members if member in data})


def _check_jwk(  # noqa: PLR0911
    data: object, algorithm: AsymmetricAlgorithm | SecretAlgorithm, role: Role
) -> JsonWebKey | str:
    """Checks the algorithm and role, then drops JOSE metadata that could
    reject an otherwise valid import (``use``, ``key_ops``, ``ext``)."""
    if not isinstance(data, Mapping):
        return "Expected a JWK object"
    jwk_data = cast("Mapping[str, object]", data)
    expected = _jose_of(algorithm)
    kty, crv, alg = jwk_data.get("kty"), jwk_data.get("crv"), jwk_data.get("alg")
    if kty is not None and kty != expected.kty:
        return f"Expected a JWK with kty {expected.kty}, not {kty}"
    if crv is not None and crv != expected.crv:
        if expected.crv is None:
            return f"Expected a JWK without crv, not {crv}"
        return f"Expected a JWK with crv {expected.crv}, not {crv}"
    if alg is not None and alg not in expected.algs:
        return f"Expected a JWK with alg {' or '.join(expected.algs)}, not {alg}"
    match role:
        case "public":
            if jwk_data.get("d") is not None:
                return "A public JWK cannot contain d"
            return _pick({**jwk_data, "kty": expected.kty}, _PUBLIC_MEMBERS)
        case "private":
            if not isinstance(jwk_data.get("d"), str):
                return "A private JWK must contain d"
            return _pick({**jwk_data, "kty": expected.kty}, _PRIVATE_MEMBERS)
        case "secret":
            k = jwk_data.get("k")
            if not isinstance(k, str):
                return "A secret JWK must contain k"
            return {"kty": "oct", "k": k}


def _decode_asymmetric(
    method: str,
    role: Literal["public", "private"],
    format: Format[Any, Any, Any],
    algorithm: AsymmetricAlgorithm,
    data: object,
) -> Effect[Any, CryptoError]:
    def go() -> Effect[Any, CryptoError]:  # noqa: PLR0911, PLR0912
        family = _family_of(algorithm)
        if family is None:
            return _invalid_key(method, "Expected an asymmetric algorithm")
        spec = family.spec_of(algorithm)
        input_format: Literal["spki", "pkcs8", "jwk"]
        input_data: bytes | JsonWebKey
        if format.tag == "jwk":
            checked = _check_jwk(data, algorithm, role)
            if isinstance(checked, str):
                return _invalid_key(method, checked)
            input_format, input_data = "jwk", checked
        else:
            if format.pem:
                if not isinstance(data, str):
                    return _invalid_key(method, "Expected PEM text")
                decoded = _from_pem(_LABELS[format.tag], data)
                if isinstance(decoded, str):
                    return _invalid_key(method, decoded)
                der = decoded
            else:
                if not _key.is_bytes(data):
                    return _invalid_key(method, "Expected DER bytes")
                der = bytes(cast("bytes", data))
            converted: bytes | _Problem = der
            curve: Curve | None = (
                algorithm.named_curve
                if isinstance(algorithm, (signature_module.Ecdsa, key_agreement.Ecdh))
                else None
            )
            if format.tag == "pkcs1":
                converted = (
                    _pkcs1_to_pkcs8(der)
                    if spec.public_format == "spki"
                    else _Problem("InvalidKey", "PKCS#1 holds RSA private keys only")
                )
            elif format.tag == "sec1":
                converted = (
                    _sec1_to_pkcs8(der, curve)
                    if curve is not None
                    else _Problem("InvalidKey", "SEC1 holds EC private keys only")
                )
            elif format.tag == "pkcs8" and curve is not None:
                converted = _check_ec_pkcs8(der, curve) or der
            if isinstance(converted, _Problem):
                if converted.reason == "Unsupported":
                    return _unsupported(method, converted.description)
                return _invalid_key(method, converted.description)
            input_format = "spki" if format.tag == "spki" else "pkcs8"
            input_data = converted

        def run(subtle: SubtleCrypto) -> KeyBase[Any]:
            usages = spec.private_usages if role == "private" else spec.public_usages
            crypto_key = subtle.import_key(
                input_format, input_data, spec.import_params, True, list(usages)
            )
            build = family.private_key if role == "private" else family.public_key
            return build(
                _key.imported_algorithm(algorithm, crypto_key),
                _asymmetric.export_key(subtle, crypto_key, spec, role),
            )

        return _web.run_with_reference("KeyFormat", method, algorithm.name, run)

    return suspend(go)


@overload
def decode_public[A: signature_module.Algorithm, Data](
    format: Format[Literal["public"], Literal["decode"], Data], algorithm: A, data: Data
) -> Effect[signature_module.PublicKey[A], CryptoError]: ...
@overload
def decode_public[A: key_agreement.Algorithm, Data](
    format: Format[Literal["public"], Literal["decode"], Data], algorithm: A, data: Data
) -> Effect[key_agreement.PublicKey[A], CryptoError]: ...
@overload
def decode_public[A: key_wrap.RsaOaep, Data](
    format: Format[Literal["public"], Literal["decode"], Data], algorithm: A, data: Data
) -> Effect[key_wrap.PublicKey[A], CryptoError]: ...
@overload
def decode_public[Data](
    format: Format[Literal["public"], Literal["decode"], Data],
    algorithm: AsymmetricAlgorithm,
    data: Data,
) -> Effect[PublicKey, CryptoError]: ...
def decode_public(
    format: Format[Any, Any, Any], algorithm: AsymmetricAlgorithm, data: object
) -> Effect[Any, CryptoError]:
    """A public key from SPKI or a JWK, checked by importing it."""
    return _decode_asymmetric("decodePublic", "public", format, algorithm, data)


@overload
def decode_private[A: signature_module.Algorithm, Data](
    format: Format[Literal["private"], Literal["decode"], Data], algorithm: A, data: Data
) -> Effect[signature_module.PrivateKey[A], CryptoError]: ...
@overload
def decode_private[A: key_agreement.Algorithm, Data](
    format: Format[Literal["private"], Literal["decode"], Data], algorithm: A, data: Data
) -> Effect[key_agreement.PrivateKey[A], CryptoError]: ...
@overload
def decode_private[A: key_wrap.RsaOaep, Data](
    format: Format[Literal["private"], Literal["decode"], Data], algorithm: A, data: Data
) -> Effect[key_wrap.PrivateKey[A], CryptoError]: ...
@overload
def decode_private[Data](
    format: Format[Literal["private"], Literal["decode"], Data],
    algorithm: AsymmetricAlgorithm,
    data: Data,
) -> Effect[PrivateKey, CryptoError]: ...
def decode_private(
    format: Format[Any, Any, Any], algorithm: AsymmetricAlgorithm, data: object
) -> Effect[Any, CryptoError]:
    """A private key from PKCS#8, PKCS#1, SEC1 or a JWK, checked by
    importing it."""
    return _decode_asymmetric("decodePrivate", "private", format, algorithm, data)


@overload
def decode_secret[A: aead.Algorithm, Data](
    format: Format[Literal["secret"], Literal["decode"], Data], algorithm: A, data: Data
) -> Effect[aead.Key[A], CryptoError]: ...
@overload
def decode_secret[A: cipher.Algorithm, Data](
    format: Format[Literal["secret"], Literal["decode"], Data], algorithm: A, data: Data
) -> Effect[cipher.Key[A], CryptoError]: ...
@overload
def decode_secret[A: mac.Algorithm, Data](
    format: Format[Literal["secret"], Literal["decode"], Data], algorithm: A, data: Data
) -> Effect[mac.Key[A], CryptoError]: ...
@overload
def decode_secret[A: key_wrap.AesKw, Data](
    format: Format[Literal["secret"], Literal["decode"], Data], algorithm: A, data: Data
) -> Effect[key_wrap.Key[A], CryptoError]: ...
def decode_secret(
    format: Format[Any, Any, Any], algorithm: SecretAlgorithm, data: object
) -> Effect[Any, CryptoError]:
    """A secret key from a JWK's ``k``."""

    def go() -> Effect[Any, CryptoError]:
        if format.tag != "jwk":
            return _invalid_key("decodeSecret", "Secret keys are only read from JWK")
        checked = _check_jwk(data, algorithm, "secret")
        if isinstance(checked, str):
            return _invalid_key("decodeSecret", checked)
        decoded = base64_url_decode(checked.get("k", ""))
        if isinstance(decoded, Err):
            return _invalid_key("decodeSecret", "The JWK k member is not valid base64url")
        return key_wrap.secret_key(algorithm, decoded.value).catch_all(
            _web.rehome("KeyFormat", "decodeSecret")
        )

    return suspend(go)


def _encode_asymmetric(
    format: Format[Any, Any, Any], key: PublicKey | PrivateKey, family: Family
) -> Effect[bytes | JsonWebKey, CryptoError]:
    def go() -> Effect[bytes | JsonWebKey, CryptoError]:
        spec = family.spec_of(key.algorithm)
        role: Literal["private", "public"] = "private" if family.is_private_key(key) else "public"
        stored = material(key)
        if isinstance(stored, CryptoKey) and not stored.extractable:
            return _web.not_extractable("KeyFormat", "encode")
        target: Literal["jwk", "spki", "pkcs8"] = (
            "jwk" if format.tag == "jwk" else "spki" if format.tag == "spki" else "pkcs8"
        )
        if isinstance(stored, bytes):
            # RSA keys and EC private keys are stored in the format asked for.
            if target == "pkcs8" and role == "private" and spec.seed_prefix is None:
                return succeed(stored)
            if target == "spki" and role == "public" and spec.public_format == "spki":
                return succeed(stored)

        def run(subtle: SubtleCrypto) -> bytes | JsonWebKey:
            if isinstance(stored, CryptoKey):
                crypto_key = stored
            elif role == "private":
                crypto_key = _asymmetric.import_private(subtle, stored, spec, True)
            else:
                crypto_key = _asymmetric.import_public(subtle, stored, spec)
            if target == "jwk":
                exported = subtle.export_key("jwk", crypto_key)
                return _pick(
                    cast("Mapping[str, object]", exported),
                    _PRIVATE_MEMBERS if role == "private" else _PUBLIC_MEMBERS,
                )
            return bytes(subtle.export_key(target, crypto_key))

        return _web.run_with_reference("KeyFormat", "encode", key.algorithm.name, run)

    return suspend(go)


@overload
def encode[Data](
    format: Format[Literal["public"], Literal["encode"], Data], key: PublicKey
) -> Effect[Data, CryptoError]: ...
@overload
def encode[Data](
    format: Format[Literal["private"], Literal["encode"], Data], key: PrivateKey
) -> Effect[Data, CryptoError]: ...
@overload
def encode[Data](
    format: Format[Literal["secret"], Literal["encode"], Data], key: SecretKey
) -> Effect[Data, CryptoError]: ...
def encode(format: Format[Any, Any, Any], key: Key) -> Effect[Any, CryptoError]:
    """``key`` in ``format``; ``NotExtractable`` for a non-extractable
    ``CryptoKey``."""
    family = _family_of(key.algorithm)
    encoded: Effect[bytes | JsonWebKey, CryptoError]
    if family is not None:
        encoded = _encode_asymmetric(format, cast("PublicKey | PrivateKey", key), family)
    elif format.tag != "jwk":
        encoded = _invalid_key("encode", "Secret keys are only written as JWK")
    else:
        encoded = (
            key_wrap.secret_to_bytes(cast("SecretKey", key))
            .catch_all(_web.rehome("KeyFormat", "encode"))
            .map(lambda data: JsonWebKey(kty="oct", k=base64_url_encode(data)))
        )
    if format.pem:
        return encoded.map(lambda der: _to_pem(_LABELS[format.tag], cast("bytes", der)))
    return encoded


__all__ = [
    "AsymmetricAlgorithm",
    "CryptoError",
    "Direction",
    "Format",
    "JsonWebKey",
    "Key",
    "PrivateKey",
    "PublicKey",
    "Role",
    "SecretAlgorithm",
    "SecretKey",
    "decode_private",
    "decode_public",
    "decode_secret",
    "encode",
    "jwk",
    "pem",
    "pkcs1",
    "pkcs8",
    "sec1",
    "spki",
]
