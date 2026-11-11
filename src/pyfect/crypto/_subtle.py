"""``web_crypto.host``: Web Crypto's ``SubtleCrypto`` on ``hashlib``, ``hmac``
and the ``cryptography`` package, with Web Crypto's key formats, usage
rules and error names. ``cryptography`` (the ``crypto`` extra) is imported
by the first operation that needs it, so digests work without it."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import hashlib
import hmac
import os
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal, cast, overload

from pyfect._binary_codecs import base64_url_decode, base64_url_encode
from pyfect._js import text_encode
from pyfect._json_text import parse, stringify
from pyfect.crypto.web_crypto import (
    AlgorithmIdentifier,
    BinaryFormat,
    CryptoKey,
    CryptoKeyPair,
    DOMException,
    JsonWebKey,
    KeyAlgorithm,
    KeyFormat,
    KeyType,
    KeyUsage,
    Params,
)
from pyfect.result import Ok


def _data_error(message: str = "Invalid key data") -> DOMException:
    return DOMException(message, "DataError")


def _operation_error(message: str = "The operation failed") -> DOMException:
    return DOMException(message, "OperationError")


def _access_error(message: str) -> DOMException:
    return DOMException(message, "InvalidAccessError")


def _syntax_error(message: str) -> DOMException:
    return DOMException(message, "SyntaxError")


def _not_supported(message: str) -> DOMException:
    return DOMException(message, "NotSupportedError")


# --- algorithms ---------------------------------------------------------------------

_NAMES: Final = {
    name.upper(): name
    for name in (
        "AES-GCM",
        "AES-CBC",
        "AES-CTR",
        "AES-KW",
        "HMAC",
        "HKDF",
        "PBKDF2",
        "ECDSA",
        "ECDH",
        "Ed25519",
        "X25519",
        "RSA-PSS",
        "RSASSA-PKCS1-v1_5",
        "RSA-OAEP",
        "SHA-1",
        "SHA-256",
        "SHA-384",
        "SHA-512",
    )
}

_AES: Final = frozenset({"AES-GCM", "AES-CBC", "AES-CTR", "AES-KW"})
_RSA: Final = frozenset({"RSA-PSS", "RSASSA-PKCS1-v1_5", "RSA-OAEP"})
_EC: Final = frozenset({"ECDSA", "ECDH"})
_OKP: Final = frozenset({"Ed25519", "X25519"})
_CURVES: Final = {"P-256": 32, "P-384": 48, "P-521": 66}
_HASHES: Final = {"SHA-1": "sha1", "SHA-256": "sha256", "SHA-384": "sha384", "SHA-512": "sha512"}
_BLOCK_BITS: Final = {"SHA-1": 512, "SHA-256": 512, "SHA-384": 1024, "SHA-512": 1024}

_SECRET_USAGES: Final[dict[str, frozenset[KeyUsage]]] = {
    "AES-GCM": frozenset({"encrypt", "decrypt", "wrapKey", "unwrapKey"}),
    "AES-CBC": frozenset({"encrypt", "decrypt", "wrapKey", "unwrapKey"}),
    "AES-CTR": frozenset({"encrypt", "decrypt", "wrapKey", "unwrapKey"}),
    "AES-KW": frozenset({"wrapKey", "unwrapKey"}),
    "HMAC": frozenset({"sign", "verify"}),
    "HKDF": frozenset({"deriveKey", "deriveBits"}),
    "PBKDF2": frozenset({"deriveKey", "deriveBits"}),
}
_PAIR_USAGES: Final[dict[str, tuple[frozenset[KeyUsage], frozenset[KeyUsage]]]] = {
    "ECDSA": (frozenset({"sign"}), frozenset({"verify"})),
    "Ed25519": (frozenset({"sign"}), frozenset({"verify"})),
    "RSA-PSS": (frozenset({"sign"}), frozenset({"verify"})),
    "RSASSA-PKCS1-v1_5": (frozenset({"sign"}), frozenset({"verify"})),
    "ECDH": (frozenset({"deriveKey", "deriveBits"}), frozenset()),
    "X25519": (frozenset({"deriveKey", "deriveBits"}), frozenset()),
    "RSA-OAEP": (frozenset({"decrypt", "unwrapKey"}), frozenset({"encrypt", "wrapKey"})),
}


def _params(algorithm: AlgorithmIdentifier) -> Params:
    raw = Params(name=algorithm) if isinstance(algorithm, str) else algorithm
    name = _NAMES.get(raw.name.upper())
    if name is None:
        raise _not_supported(f"Unrecognized algorithm name: {raw.name}")
    if raw.hash is not None:
        hash_name = _NAMES.get(raw.hash.upper())
        if hash_name not in _HASHES:
            raise _not_supported(f"Unrecognized hash: {raw.hash}")
        if hash_name != raw.hash or name != raw.name:
            return _replace(raw, name=name, hash=hash_name)
    return raw if name == raw.name else _replace(raw, name=name)


def _replace(params: Params, **changes: Any) -> Params:
    from dataclasses import replace

    return replace(params, **changes)


def _require_hash(params: Params) -> str:
    if params.hash is None:
        raise DOMException(f"{params.name} needs a hash", "TypeError")
    return params.hash


def _require_curve(params: Params) -> str:
    if params.named_curve not in _CURVES:
        raise _not_supported(f"Unsupported named curve: {params.named_curve}")
    return params.named_curve


def _check_usages(name: str, type: KeyType, usages: Sequence[KeyUsage]) -> None:
    allowed = (
        _SECRET_USAGES[name]
        if type == "secret"
        else _PAIR_USAGES[name][0 if type == "private" else 1]
    )
    if any(usage not in allowed for usage in usages):
        raise _syntax_error(f"Unsupported key usage for a {name} {type} key")
    if type != "public" and not usages:
        raise _syntax_error("Usages cannot be empty when creating a key")


def _check_operation(key: CryptoKey, params: Params, usage: KeyUsage) -> None:
    if key.algorithm.name != params.name:
        raise _access_error(f"The key is a {key.algorithm.name} key, not {params.name}")
    if usage not in key.usages:
        raise _access_error(f"The key does not allow {usage}")


# --- the cryptography objects -------------------------------------------------------


def _hash(name: str) -> Any:
    from pyfect.crypto._lib import hashes

    return {
        "SHA-1": hashes.SHA1,
        "SHA-256": hashes.SHA256,
        "SHA-384": hashes.SHA384,
        "SHA-512": hashes.SHA512,
    }[name]()


def _curve(name: str) -> Any:
    from pyfect.crypto._lib import ec

    return {"P-256": ec.SECP256R1, "P-384": ec.SECP384R1, "P-521": ec.SECP521R1}[name]()


def _curve_name(key: Any) -> str | None:
    return {"secp256r1": "P-256", "secp384r1": "P-384", "secp521r1": "P-521"}.get(key.curve.name)


@dataclass(frozen=True, slots=True)
class _Asymmetric:
    """A key pair member: the ``cryptography`` key object."""

    key: Any


def _secret_bytes(key: CryptoKey) -> bytes:
    handle = key.handle
    if not isinstance(handle, bytes):
        raise _access_error("Expected a secret key")
    return handle


def _asymmetric(key: CryptoKey) -> Any:
    handle = key.handle
    if not isinstance(handle, _Asymmetric):
        raise _access_error("Expected an asymmetric key")
    return handle.key


def _int_bytes(value: int, size: int | None = None) -> bytes:
    length = size if size is not None else max(1, (value.bit_length() + 7) // 8)
    return value.to_bytes(length)


def _b64(data: bytes) -> str:
    return base64_url_encode(data)


def _unb64(text: object) -> bytes:
    if not isinstance(text, str):
        raise _data_error("Expected a base64url string")
    decoded = base64_url_decode(text)
    if not isinstance(decoded, Ok):
        raise _data_error("Invalid base64url data")
    return decoded.value


def _unb64_int(text: object) -> int:
    return int.from_bytes(_unb64(text))


# --- import ---------------------------------------------------------------------------


def _import_secret(params: Params, data: bytes) -> tuple[bytes, KeyAlgorithm]:
    name = params.name
    if name in _AES:
        if len(data) not in (16, 24, 32):
            raise _data_error(f"AES keys must be 128, 192 or 256 bits, not {len(data) * 8}")
        return data, KeyAlgorithm(name=name, length=len(data) * 8)
    if name == "HMAC":
        hash_name = _require_hash(params)
        if not data:
            raise _data_error("HMAC keys cannot be empty")
        if params.length is not None and params.length != len(data) * 8:
            raise _data_error("The HMAC key length does not match")
        return data, KeyAlgorithm(name=name, hash=hash_name, length=len(data) * 8)
    return data, KeyAlgorithm(name=name)


def _rsa_algorithm(params: Params, public: Any) -> KeyAlgorithm:
    numbers = public.public_numbers()
    return KeyAlgorithm(
        name=params.name,
        hash=_require_hash(params),
        modulus_length=public.key_size,
        public_exponent=_int_bytes(numbers.e),
    )


def _algorithm_of(params: Params, key: Any) -> KeyAlgorithm:
    """The ``KeyAlgorithm`` of an imported asymmetric key, checking that it
    is a key of ``params``."""
    from pyfect.crypto._lib import ec, ed25519, rsa, x25519

    name = params.name
    if name in _EC:
        curve = _require_curve(params)
        if not isinstance(key, (ec.EllipticCurvePrivateKey, ec.EllipticCurvePublicKey)):
            raise _data_error(f"Expected an EC key for {name}")
        if _curve_name(key) != curve:
            raise _data_error(f"Expected a {curve} key")
        return KeyAlgorithm(name=name, named_curve=curve)
    if name == "Ed25519":
        if not isinstance(key, (ed25519.Ed25519PrivateKey, ed25519.Ed25519PublicKey)):
            raise _data_error("Expected an Ed25519 key")
        return KeyAlgorithm(name=name)
    if name == "X25519":
        if not isinstance(key, (x25519.X25519PrivateKey, x25519.X25519PublicKey)):
            raise _data_error("Expected an X25519 key")
        return KeyAlgorithm(name=name)
    if not isinstance(key, (rsa.RSAPrivateKey, rsa.RSAPublicKey)):
        raise _data_error(f"Expected an RSA key for {name}")
    public = key.public_key() if isinstance(key, rsa.RSAPrivateKey) else key
    return _rsa_algorithm(params, public)


def _import_raw_public(params: Params, data: bytes) -> Any:
    from pyfect.crypto._lib import ec, ed25519, x25519

    try:
        if params.name in _EC:
            return ec.EllipticCurvePublicKey.from_encoded_point(
                _curve(_require_curve(params)), data
            )
        if params.name == "Ed25519":
            return ed25519.Ed25519PublicKey.from_public_bytes(data)
        return x25519.X25519PublicKey.from_public_bytes(data)
    except ValueError as error:
        raise _data_error() from error


def _import_jwk(params: Params, jwk: JsonWebKey, extractable: bool) -> tuple[KeyType, object]:  # noqa: PLR0911, PLR0912
    from pyfect.crypto._lib import ec, ed25519, rsa, x25519

    if jwk.get("ext") is False and extractable:
        raise _data_error("The JWK is not extractable")
    name = params.name
    kty = jwk.get("kty")
    try:
        if name in _SECRET_USAGES:
            if kty != "oct" or "k" not in jwk:
                raise _data_error("Expected an oct JWK with k")
            return "secret", _unb64(jwk["k"])
        if name in _EC:
            if kty != "EC" or jwk.get("crv") != _require_curve(params):
                raise _data_error(f"Expected an EC JWK on {params.named_curve}")
            size = _CURVES[_require_curve(params)]
            x, y = _unb64(jwk.get("x")), _unb64(jwk.get("y"))
            if len(x) != size or len(y) != size:
                raise _data_error("Invalid EC coordinates")
            public = ec.EllipticCurvePublicNumbers(
                int.from_bytes(x), int.from_bytes(y), _curve(params.named_curve or "")
            )
            if "d" in jwk:
                d = _unb64(jwk["d"])
                if len(d) != size:
                    raise _data_error("Invalid EC private key")
                return "private", ec.EllipticCurvePrivateNumbers(
                    int.from_bytes(d), public
                ).private_key()
            return "public", public.public_key()
        if name in _OKP:
            if kty != "OKP" or jwk.get("crv") != name:
                raise _data_error(f"Expected an OKP JWK on {name}")
            x = _unb64(jwk.get("x"))
            private_class: Any = (
                ed25519.Ed25519PrivateKey if name == "Ed25519" else x25519.X25519PrivateKey
            )
            public_class: Any = (
                ed25519.Ed25519PublicKey if name == "Ed25519" else x25519.X25519PublicKey
            )
            if "d" in jwk:
                private = private_class.from_private_bytes(_unb64(jwk["d"]))
                if _raw_public(private.public_key()) != x:
                    raise _data_error("The JWK x does not match d")
                return "private", private
            return "public", public_class.from_public_bytes(x)
        if kty != "RSA":
            raise _data_error("Expected an RSA JWK")
        public_numbers = rsa.RSAPublicNumbers(_unb64_int(jwk.get("e")), _unb64_int(jwk.get("n")))
        if "d" not in jwk:
            return "public", public_numbers.public_key()
        if "oth" in jwk:
            raise _not_supported("Multi-prime RSA keys are not supported")
        members = [jwk.get(member) for member in ("p", "q", "dp", "dq", "qi")]
        if any(member is None for member in members):
            raise _data_error("An RSA private JWK needs p, q, dp, dq and qi")
        p, q, dp, dq, qi = (_unb64_int(member) for member in members)
        return "private", rsa.RSAPrivateNumbers(
            p, q, _unb64_int(jwk["d"]), dp, dq, qi, public_numbers
        ).private_key()
    except ValueError as error:
        raise _data_error() from error


def _raw_public(key: Any) -> bytes:
    from pyfect.crypto._lib import serialization

    return key.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


# --- export ---------------------------------------------------------------------------


def _export_jwk(key: CryptoKey) -> JsonWebKey:
    from pyfect.crypto._lib import ec, rsa

    name = key.algorithm.name
    if key.type == "secret":
        jwk: JsonWebKey = {"kty": "oct", "k": _b64(_secret_bytes(key))}
    elif name in _EC:
        handle = _asymmetric(key)
        size = _CURVES[key.algorithm.named_curve or ""]
        public = handle.public_key() if isinstance(handle, ec.EllipticCurvePrivateKey) else handle
        numbers = public.public_numbers()
        jwk = {
            "kty": "EC",
            "crv": key.algorithm.named_curve or "",
            "x": _b64(_int_bytes(numbers.x, size)),
            "y": _b64(_int_bytes(numbers.y, size)),
        }
        if isinstance(handle, ec.EllipticCurvePrivateKey):
            jwk["d"] = _b64(_int_bytes(handle.private_numbers().private_value, size))
    elif name in _OKP:
        handle = _asymmetric(key)
        if key.type == "private":
            from pyfect.crypto._lib import serialization

            jwk = {
                "kty": "OKP",
                "crv": name,
                "x": _b64(_raw_public(handle.public_key())),
                "d": _b64(
                    handle.private_bytes(
                        serialization.Encoding.Raw,
                        serialization.PrivateFormat.Raw,
                        serialization.NoEncryption(),
                    )
                ),
            }
        else:
            jwk = {"kty": "OKP", "crv": name, "x": _b64(_raw_public(handle))}
    else:
        handle = _asymmetric(key)
        public = handle.public_key() if isinstance(handle, rsa.RSAPrivateKey) else handle
        numbers = public.public_numbers()
        jwk = {"kty": "RSA", "n": _b64(_int_bytes(numbers.n)), "e": _b64(_int_bytes(numbers.e))}
        if isinstance(handle, rsa.RSAPrivateKey):
            private = handle.private_numbers()
            jwk.update(
                {
                    "d": _b64(_int_bytes(private.d)),
                    "p": _b64(_int_bytes(private.p)),
                    "q": _b64(_int_bytes(private.q)),
                    "dp": _b64(_int_bytes(private.dmp1)),
                    "dq": _b64(_int_bytes(private.dmq1)),
                    "qi": _b64(_int_bytes(private.iqmp)),
                }
            )
    jwk["key_ops"] = [*key.usages]
    jwk["ext"] = key.extractable
    return jwk


def _export_binary(format: BinaryFormat, key: CryptoKey) -> bytes:
    from pyfect.crypto._lib import serialization

    if format == "raw":
        if key.type == "secret":
            return _secret_bytes(key)
        if key.type == "public" and key.algorithm.name in _EC:
            return _asymmetric(key).public_bytes(
                serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint
            )
        if key.type == "public" and key.algorithm.name in _OKP:
            return _raw_public(_asymmetric(key))
        raise _access_error(f"A {key.algorithm.name} {key.type} key has no raw form")
    if format == "spki":
        if key.type != "public":
            raise _access_error("Only public keys export as SPKI")
        return _asymmetric(key).public_bytes(
            serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo
        )
    if key.type != "private":
        raise _access_error("Only private keys export as PKCS#8")
    return _asymmetric(key).private_bytes(
        serialization.Encoding.DER,
        serialization.PrivateFormat.PKCS8,
        serialization.NoEncryption(),
    )


# --- the implementation -----------------------------------------------------------------


class HostSubtle:
    """``SubtleCrypto`` on ``hashlib``, ``hmac`` and ``cryptography``."""

    def digest(self, algorithm: AlgorithmIdentifier, data: bytes) -> bytes:
        params = _params(algorithm)
        if params.name not in _HASHES:
            raise _not_supported(f"{params.name} is not a digest")
        return hashlib.new(_HASHES[params.name], data).digest()

    def import_key(  # noqa: PLR0912
        self,
        format: KeyFormat,
        key_data: bytes | JsonWebKey,
        algorithm: AlgorithmIdentifier,
        extractable: bool,
        usages: Sequence[KeyUsage],
    ) -> CryptoKey:
        params = _params(algorithm)
        name = params.name
        if name in _HASHES:
            raise _not_supported(f"{name} is not a key algorithm")
        if name in ("HKDF", "PBKDF2"):
            if format != "raw":
                raise _not_supported(f"{name} keys are only imported raw")
            if extractable:
                raise _syntax_error(f"{name} keys cannot be extractable")
        if format == "jwk":
            if not isinstance(key_data, dict):
                raise DOMException("Expected a JWK object", "TypeError")
            type, handle = _import_jwk(params, key_data, extractable)
            if type == "secret":
                data, key_algorithm = _import_secret(params, cast("bytes", handle))
                _check_usages(name, type, usages)
                return CryptoKey(
                    algorithm=key_algorithm,
                    extractable=extractable,
                    type=type,
                    usages=usages,
                    handle=data,
                )
            _check_usages(name, type, usages)
            return CryptoKey(
                algorithm=_algorithm_of(params, handle),
                extractable=extractable,
                type=type,
                usages=usages,
                handle=_Asymmetric(handle),
            )
        if isinstance(key_data, dict):
            raise DOMException("Expected key bytes", "TypeError")
        data = bytes(key_data)
        if name in _SECRET_USAGES:
            if format != "raw":
                raise _not_supported(f"{name} keys are imported raw or as JWK")
            _check_usages(name, "secret", usages)
            data, key_algorithm = _import_secret(params, data)
            return CryptoKey(
                algorithm=key_algorithm,
                extractable=extractable,
                type="secret",
                usages=usages,
                handle=data,
            )
        from pyfect.crypto._lib import serialization

        if format == "raw":
            if name in _RSA:
                raise _not_supported("RSA keys have no raw form")
            handle = _import_raw_public(params, data)
            type: KeyType = "public"
        elif format == "spki":
            try:
                handle = serialization.load_der_public_key(data)
            except (ValueError, TypeError) as error:
                raise _data_error() from error
            type = "public"
        else:
            try:
                handle = serialization.load_der_private_key(data, None)
            except (ValueError, TypeError) as error:
                raise _data_error() from error
            type = "private"
        _check_usages(name, type, usages)
        return CryptoKey(
            algorithm=_algorithm_of(params, handle),
            extractable=True if type == "public" else extractable,
            type=type,
            usages=usages,
            handle=_Asymmetric(handle),
        )

    @overload
    def export_key(self, format: BinaryFormat, key: CryptoKey) -> bytes: ...
    @overload
    def export_key(self, format: Literal["jwk"], key: CryptoKey) -> JsonWebKey: ...
    def export_key(self, format: KeyFormat, key: CryptoKey) -> bytes | JsonWebKey:
        if not key.extractable:
            raise _access_error("The key is not extractable")
        if key.algorithm.name in ("HKDF", "PBKDF2"):
            raise _not_supported(f"{key.algorithm.name} keys cannot be exported")
        if format == "jwk":
            return _export_jwk(key)
        return _export_binary(format, key)

    def generate_key(  # noqa: PLR0912
        self, algorithm: AlgorithmIdentifier, extractable: bool, usages: Sequence[KeyUsage]
    ) -> CryptoKey | CryptoKeyPair:
        params = _params(algorithm)
        name = params.name
        if name in _AES or name == "HMAC":
            _check_usages(name, "secret", usages)
            if name == "HMAC":
                bits = params.length or _BLOCK_BITS[_require_hash(params)]
            else:
                bits = params.length or 0
                if bits not in (128, 192, 256):
                    raise _operation_error("AES keys are 128, 192 or 256 bits")
            if bits <= 0 or bits % 8:
                raise _operation_error("Unsupported key length")
            data, key_algorithm = _import_secret(params, os.urandom(bits // 8))
            return CryptoKey(
                algorithm=key_algorithm,
                extractable=extractable,
                type="secret",
                usages=usages,
                handle=data,
            )
        if name not in _PAIR_USAGES:
            raise _not_supported(f"{name} keys cannot be generated")
        private_usages, public_usages = _PAIR_USAGES[name]
        if any(usage not in private_usages | public_usages for usage in usages):
            raise _syntax_error(f"Unsupported key usage for {name}")
        from pyfect.crypto._lib import ec, ed25519, rsa, x25519

        private: Any
        if name in _EC:
            private = ec.generate_private_key(_curve(_require_curve(params)))
        elif name == "Ed25519":
            private = ed25519.Ed25519PrivateKey.generate()
        elif name == "X25519":
            private = x25519.X25519PrivateKey.generate()
        else:
            _require_hash(params)
            exponent = int.from_bytes(params.public_exponent or b"\x01\x00\x01")
            try:
                private = rsa.generate_private_key(exponent, params.modulus_length or 0)
            except ValueError as error:
                raise _operation_error(str(error)) from error
        own: list[KeyUsage] = [usage for usage in usages if usage in private_usages]
        if not own:
            raise _syntax_error("Usages cannot be empty when creating a key")
        key_algorithm = _algorithm_of(params, private)
        return CryptoKeyPair(
            private_key=CryptoKey(
                algorithm=key_algorithm,
                extractable=extractable,
                type="private",
                usages=own,
                handle=_Asymmetric(private),
            ),
            public_key=CryptoKey(
                algorithm=key_algorithm,
                extractable=True,
                type="public",
                usages=[usage for usage in usages if usage in public_usages],
                handle=_Asymmetric(private.public_key()),
            ),
        )

    def encrypt(self, algorithm: AlgorithmIdentifier, key: CryptoKey, data: bytes) -> bytes:
        params = _params(algorithm)
        _check_operation(key, params, "encrypt")
        return self._encrypt(params, key, bytes(data))

    def decrypt(self, algorithm: AlgorithmIdentifier, key: CryptoKey, data: bytes) -> bytes:
        params = _params(algorithm)
        _check_operation(key, params, "decrypt")
        return self._decrypt(params, key, bytes(data))

    def _encrypt(self, params: Params, key: CryptoKey, data: bytes) -> bytes:
        name = params.name
        if name == "RSA-OAEP":
            return _oaep(params, key, data, encrypt=True)
        secret = _secret_bytes(key)
        if name == "AES-GCM":
            return _gcm(params, secret, data, encrypt=True)
        return _aes_mode(params, secret)(data, True)

    def _decrypt(self, params: Params, key: CryptoKey, data: bytes) -> bytes:
        name = params.name
        if name == "RSA-OAEP":
            return _oaep(params, key, data, encrypt=False)
        secret = _secret_bytes(key)
        if name == "AES-GCM":
            return _gcm(params, secret, data, encrypt=False)
        return _aes_mode(params, secret)(data, False)

    def sign(self, algorithm: AlgorithmIdentifier, key: CryptoKey, data: bytes) -> bytes:
        params = _params(algorithm)
        _check_operation(key, params, "sign")
        data = bytes(data)
        if params.name == "HMAC":
            return hmac.new(_secret_bytes(key), data, _HASHES[key.algorithm.hash or ""]).digest()
        return _sign(params, key, data)

    def verify(
        self, algorithm: AlgorithmIdentifier, key: CryptoKey, signature: bytes, data: bytes
    ) -> bool:
        params = _params(algorithm)
        _check_operation(key, params, "verify")
        data, signature = bytes(data), bytes(signature)
        if params.name == "HMAC":
            expected = hmac.new(_secret_bytes(key), data, _HASHES[key.algorithm.hash or ""])
            return hmac.compare_digest(expected.digest(), signature)
        return _verify(params, key, signature, data)

    def derive_bits(  # noqa: PLR0912
        self, algorithm: AlgorithmIdentifier, base_key: CryptoKey, length: int | None
    ) -> bytes:
        params = _params(algorithm)
        _check_operation(base_key, params, "deriveBits")
        name = params.name
        if name in ("ECDH", "X25519"):
            public = params.public
            if public is None:
                raise DOMException("deriveBits needs the public key", "TypeError")
            if public.type != "public" or public.algorithm.name != name:
                raise _access_error(f"Expected a {name} public key")
            if public.algorithm.named_curve != base_key.algorithm.named_curve:
                raise _access_error("The keys are on different curves")
            private = _asymmetric(base_key)
            try:
                if name == "ECDH":
                    from pyfect.crypto._lib import ec

                    secret = private.exchange(ec.ECDH(), _asymmetric(public))
                else:
                    secret = private.exchange(_asymmetric(public))
            except ValueError as error:
                raise _operation_error("Could not derive the shared secret") from error
            if length is None:
                return secret
            if length > len(secret) * 8:
                raise _operation_error("The length is longer than the shared secret")
            return _truncate(secret, length)
        if length is None or length <= 0 or length % 8:
            raise _operation_error("The length must be a positive multiple of 8")
        secret = _secret_bytes(base_key)
        try:
            if name == "HKDF":
                from pyfect.crypto._lib import HKDF

                return HKDF(
                    _hash(_require_hash(params)),
                    length // 8,
                    params.salt if params.salt is not None else b"",
                    params.info if params.info is not None else b"",
                ).derive(secret)
            if name == "PBKDF2":
                from pyfect.crypto._lib import PBKDF2HMAC

                if not params.iterations:
                    raise _operation_error("PBKDF2 needs at least one iteration")
                return PBKDF2HMAC(
                    _hash(_require_hash(params)),
                    length // 8,
                    params.salt if params.salt is not None else b"",
                    params.iterations,
                ).derive(secret)
        except ValueError as error:
            raise _operation_error(str(error)) from error
        raise _not_supported(f"{name} does not derive bits")

    def wrap_key(
        self,
        format: KeyFormat,
        key: CryptoKey,
        wrapping_key: CryptoKey,
        wrap_algorithm: AlgorithmIdentifier,
    ) -> bytes:
        params = _params(wrap_algorithm)
        _check_operation(wrapping_key, params, "wrapKey")
        exported = self.export_key(format, key) if format != "jwk" else None
        data = (
            exported
            if exported is not None
            else text_encode(stringify(self.export_key("jwk", key)))
        )
        if params.name == "AES-KW":
            from pyfect.crypto._lib import aes_key_wrap

            if len(data) % 8 or len(data) < 16:
                raise _operation_error("AES-KW wraps a multiple of 8 bytes, at least 16")
            return aes_key_wrap(_secret_bytes(wrapping_key), data)
        return self._encrypt(params, wrapping_key, data)

    def unwrap_key(  # noqa: PLR0917
        self,
        format: KeyFormat,
        wrapped_key: bytes,
        unwrapping_key: CryptoKey,
        unwrap_algorithm: AlgorithmIdentifier,
        unwrapped_key_algorithm: AlgorithmIdentifier,
        extractable: bool,
        usages: Sequence[KeyUsage],
    ) -> CryptoKey:
        params = _params(unwrap_algorithm)
        _check_operation(unwrapping_key, params, "unwrapKey")
        if params.name == "AES-KW":
            from pyfect.crypto._lib import InvalidUnwrap, aes_key_unwrap

            try:
                data = aes_key_unwrap(_secret_bytes(unwrapping_key), bytes(wrapped_key))
            except (InvalidUnwrap, ValueError) as error:
                raise _operation_error() from error
        else:
            data = self._decrypt(params, unwrapping_key, bytes(wrapped_key))
        if format == "jwk":
            try:
                jwk = parse(data)
            except ValueError as error:
                raise _data_error() from error
            if not isinstance(jwk, dict):
                raise _data_error()
            return self.import_key(
                "jwk", cast("JsonWebKey", jwk), unwrapped_key_algorithm, extractable, usages
            )
        return self.import_key(format, data, unwrapped_key_algorithm, extractable, usages)


def _truncate(data: bytes, bits: int) -> bytes:
    out = bytearray(data[: (bits + 7) // 8])
    if bits % 8:
        out[-1] &= 0xFF << (8 - bits % 8) & 0xFF
    return bytes(out)


def _gcm(params: Params, secret: bytes, data: bytes, *, encrypt: bool) -> bytes:
    from pyfect.crypto._lib import AESGCM, InvalidTag

    if params.tag_length not in (None, 128):
        raise _not_supported("Only 128-bit AES-GCM tags are supported")
    iv = params.iv or b""
    aad = params.additional_data
    try:
        if encrypt:
            return AESGCM(secret).encrypt(iv, data, aad)
        return AESGCM(secret).decrypt(iv, data, aad)
    except (InvalidTag, ValueError) as error:
        raise _operation_error() from error


def _aes_mode(params: Params, secret: bytes) -> Callable[[bytes, bool], bytes]:
    from pyfect.crypto._lib import PKCS7, Cipher, algorithms, modes

    if params.name == "AES-CBC":
        iv = params.iv or b""
        if len(iv) != 16:
            raise _operation_error("AES-CBC IVs are 16 bytes")

        def cbc(data: bytes, encrypt: bool) -> bytes:
            cipher = Cipher(algorithms.AES(secret), modes.CBC(iv))
            if encrypt:
                padder = PKCS7(128).padder()
                worker = cipher.encryptor()
                return worker.update(padder.update(data) + padder.finalize()) + worker.finalize()
            if not data or len(data) % 16:
                raise _operation_error()
            worker = cipher.decryptor()
            unpadder = PKCS7(128).unpadder()
            try:
                padded = worker.update(data) + worker.finalize()
                return unpadder.update(padded) + unpadder.finalize()
            except ValueError as error:
                raise _operation_error() from error

        return cbc
    if params.name == "AES-CTR":
        counter = params.counter or b""
        if len(counter) != 16:
            raise _operation_error("AES-CTR counters are 16 bytes")
        if params.length != 128:
            raise _not_supported("Only a 128-bit AES-CTR counter is supported")

        def ctr(data: bytes, _encrypt: bool) -> bytes:
            worker = Cipher(algorithms.AES(secret), modes.CTR(counter)).encryptor()
            return worker.update(data) + worker.finalize()

        return ctr
    raise _not_supported(f"{params.name} does not encrypt")


def _oaep(params: Params, key: CryptoKey, data: bytes, *, encrypt: bool) -> bytes:
    from pyfect.crypto._lib import padding

    hash_algorithm = _hash(key.algorithm.hash or "")
    oaep = padding.OAEP(
        mgf=padding.MGF1(hash_algorithm), algorithm=hash_algorithm, label=params.label or None
    )
    try:
        handle = _asymmetric(key)
        return handle.encrypt(data, oaep) if encrypt else handle.decrypt(data, oaep)
    except ValueError as error:
        raise _operation_error() from error


def _sign(params: Params, key: CryptoKey, data: bytes) -> bytes:
    from pyfect.crypto._lib import ec, padding, utils

    handle = _asymmetric(key)
    if key.type != "private":
        raise _access_error("Signing needs a private key")
    name = params.name
    try:
        if name == "Ed25519":
            return handle.sign(data)
        if name == "ECDSA":
            der = handle.sign(data, ec.ECDSA(_hash(_require_hash(params))))
            r, s = utils.decode_dss_signature(der)
            size = _CURVES[key.algorithm.named_curve or ""]
            return _int_bytes(r, size) + _int_bytes(s, size)
        hash_algorithm = _hash(key.algorithm.hash or "")
        if name == "RSA-PSS":
            return handle.sign(
                data,
                padding.PSS(mgf=padding.MGF1(hash_algorithm), salt_length=params.salt_length or 0),
                hash_algorithm,
            )
        return handle.sign(data, padding.PKCS1v15(), hash_algorithm)
    except ValueError as error:
        raise _operation_error(str(error)) from error


def _verify(params: Params, key: CryptoKey, signature: bytes, data: bytes) -> bool:
    from pyfect.crypto._lib import InvalidSignature, ec, padding, utils

    handle = _asymmetric(key)
    if key.type != "public":
        raise _access_error("Verifying needs a public key")
    name = params.name
    try:
        if name == "Ed25519":
            handle.verify(signature, data)
        elif name == "ECDSA":
            size = _CURVES[key.algorithm.named_curve or ""]
            if len(signature) != 2 * size:
                return False
            r, s = int.from_bytes(signature[:size]), int.from_bytes(signature[size:])
            handle.verify(
                utils.encode_dss_signature(r, s), data, ec.ECDSA(_hash(_require_hash(params)))
            )
        else:
            hash_algorithm = _hash(key.algorithm.hash or "")
            pad: Any = (
                padding.PSS(mgf=padding.MGF1(hash_algorithm), salt_length=params.salt_length or 0)
                if name == "RSA-PSS"
                else padding.PKCS1v15()
            )
            handle.verify(signature, data, pad, hash_algorithm)
    except (InvalidSignature, ValueError):
        return False
    return True


class HostCrypto:
    """``web_crypto.host``: ``os.urandom`` and ``HostSubtle``."""

    __slots__ = ("_subtle",)

    def __init__(self) -> None:
        self._subtle = HostSubtle()

    @property
    def subtle(self) -> HostSubtle:
        return self._subtle

    def get_random_values(self, array: memoryview, /) -> memoryview:
        if array.nbytes > 65_536:
            raise DOMException(
                f"The ArrayBufferView's byte length ({array.nbytes}) exceeds 65536",
                "QuotaExceededError",
            )
        array.cast("B")[:] = os.urandom(array.nbytes)
        return array


host: Final = HostCrypto()
"""pyfect's ``Crypto``, the ``WebCrypto`` reference's default."""

__all__ = ["HostCrypto", "HostSubtle", "host"]
