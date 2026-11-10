"""Schemas of crypto keys (Effect's ``Schema.MacKey``, ``AeadKey``,
``SignaturePublicKey``, ... and their ``FromBytes`` / ``FromFormat``
codecs). They live here, not in ``pyfect.schema``, because
``pyfect.crypto`` is built on ``pyfect.schema``::

    from pyfect.crypto import mac
    from pyfect.crypto import schema as CS

    key_config = config.schema(CS.MacKeyFromBytes(mac.hmac_sha256), "HMAC_KEY")

A declaration (``CS.MacKey(algorithm)``) accepts live keys of an algorithm
with the same operation parameters (name, hash, salt length; an RSA modulus
length only matters when generating). Keys have no JSON form, no
strategy, display redacted and compare by identity.

``...FromBytes`` decodes raw key bytes synchronously; ``...FromFormat``
decodes with ``key_format`` and is asynchronous only, so the synchronous
decoders refuse it. A ``CryptoError`` becomes an ``InvalidValue`` issue
whose ``cause`` is the error. Secret and private keys are written back only
with ``allow_encode=True`` (and never to the read-only PKCS#1 and SEC1).
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Literal, Never, TypeIs, cast

from pyfect._core import Effect
from pyfect.crypto import aead, cipher, key_agreement, key_format, key_wrap, mac, signature
from pyfect.crypto.crypto_error import CryptoError
from pyfect.crypto.web_crypto import JsonWebKey
from pyfect.duration import Seconds
from pyfect.effect import callback, fail, succeed, sync
from pyfect.exit import Exit
from pyfect.scheduler import CurrentScheduler
from pyfect.schema import (
    Bottom,
    Bytes,
    DecodeToSchema,
    String,
    Struct,
    Unknown,
    declare,
    decode_to,
)
from pyfect.schema import (
    Never as NeverSchema,
)
from pyfect.schema import ast as _ast
from pyfect.schema import transformation as T
from pyfect.schema._options import ParseOptions
from pyfect.schema.getter import Getter, forbidden
from pyfect.schema.issue import Forbidden, InvalidValue, Issue, reported
from pyfect.schema.representation import GeneratedDeclaration

type _Family = Literal["Mac", "Aead", "Cipher", "Signature", "KeyAgreement", "KeyWrap"]

_MODULES: dict[_Family, str] = {
    "Mac": "mac",
    "Aead": "aead",
    "Cipher": "cipher",
    "Signature": "signature",
    "KeyAgreement": "key_agreement",
    "KeyWrap": "key_wrap",
}


def _hash_name(algorithm: object) -> str | None:
    hash = getattr(algorithm, "hash", None)
    return None if hash is None else cast("str", hash.name)


def _salt_length(algorithm: object) -> int | None:
    return getattr(algorithm, "salt_length", None)


def _modulus_length(algorithm: object) -> int | None:
    return getattr(algorithm, "modulus_length", None)


def _algorithm_equals(self: object, that: object) -> bool:
    """The same operation parameters. An RSA modulus length only matters
    when generating, so it is ignored here as on import."""
    return self is that or (
        cast("Any", self).name == cast("Any", that).name
        and _hash_name(self) == _hash_name(that)
        and _salt_length(self) == _salt_length(that)
    )


def _snake(name: str) -> str:
    return re.sub(r"(?<=[a-z0-9])([A-Z])", r"_\1", name).lower()


def _digest_code(hash_name: str) -> str:
    return f"digest.{hash_name.lower().replace('-', '')}"


def _algorithm_code(family: _Family, algorithm: object) -> str:
    module = _MODULES[family]
    hash_name = _hash_name(algorithm)
    modulus_length = _modulus_length(algorithm)
    tag = getattr(type(algorithm), "tag", None)
    if modulus_length is None or hash_name is None or tag is None:
        code = f"{module}.{_snake(cast('Any', algorithm).name)}"
        if hash_name is None:
            return code
        return f"dataclasses.replace({code}, hash={_digest_code(hash_name)})"
    salt_length = _salt_length(algorithm)
    salt = "" if salt_length is None else f", salt_length={salt_length}"
    return (
        f"{module}.{_snake(tag)}(hash={_digest_code(hash_name)}, "
        f"modulus_length={modulus_length}{salt})"
    )


def _algorithm_payload(algorithm: object) -> dict[str, object]:
    payload: dict[str, object] = {"name": cast("Any", algorithm).name}
    hash_name = _hash_name(algorithm)
    if hash_name is not None:
        payload["hash"] = hash_name
    modulus_length = _modulus_length(algorithm)
    if modulus_length is not None:
        payload["modulusLength"] = modulus_length
    salt_length = _salt_length(algorithm)
    if salt_length is not None:
        payload["saltLength"] = salt_length
    return payload


def _declare(
    name: str, family: _Family, type_name: str, cls: type[Any], algorithm: object
) -> Bottom[Any]:
    code = _algorithm_code(family, algorithm)
    module = _MODULES[family]
    imports = [
        "from pyfect.crypto import schema as CS",
        f"from pyfect.crypto import {module}",
    ]
    if "digest." in code:
        imports.append("from pyfect.crypto import digest")
    if "dataclasses." in code:
        imports.append("import dataclasses")
    message = (
        f"Cannot serialize {family}.{type_name} values as JSON, "
        f"use CS.{name}FromFormat to read and write keys"
    )
    refuse: Getter[Never, object] = forbidden(lambda _: message)

    def guard(u: object) -> TypeIs[Any]:
        return isinstance(u, cls) and _algorithm_equals(cast("Any", u).algorithm, algorithm)

    def refused(to: _ast.AST) -> _ast.Link:
        return _ast.Link(to, T.Transformation(refuse, refuse))

    def to_codec_json(_: tuple[_ast.AST, ...]) -> _ast.Link:
        return refused(Unknown.ast)

    # Keys have no strategy: linking to ``Never`` makes derivation fail.
    def to_codec_arbitrary(_: tuple[_ast.AST, ...], __: object) -> _ast.Link:
        return refused(NeverSchema.ast)

    def to_formatter(_: tuple[object, ...]) -> Callable[[object], str]:
        return str

    def to_equivalence(_: tuple[object, ...]) -> Callable[[object, object], bool]:
        return lambda self, that: self is that

    def to_code(_: object) -> GeneratedDeclaration:
        return GeneratedDeclaration(f"CS.{name}({code})", f"{module}.{type_name}", tuple(imports))

    return declare(
        guard,
        expected=f"{family}.{type_name} for {cast('Any', algorithm).name}",
        representation={"id": f"effect/crypto/{name}", "payload": _algorithm_payload(algorithm)},
        to_code=to_code,
        to_codec_json=to_codec_json,
        to_codec_arbitrary=to_codec_arbitrary,
        to_formatter=to_formatter,
        to_equivalence=to_equivalence,
    )


def _issue(error: CryptoError, input: object, options: ParseOptions) -> Issue:
    return InvalidValue({"message": error.message, "cause": error}, reported(input, options))


def _forbidden_encode(name: str, key: object, options: ParseOptions) -> Effect[Never, Issue]:
    message = f"CS.{name} only decodes, pass allow_encode=True to encode the key"
    return fail(Forbidden({"message": message}, reported(key, options)))


def _from_bytes[K](
    name: str,
    to: Bottom[K],
    from_bytes: Callable[[bytes], Effect[K, CryptoError]],
    to_bytes: Callable[[K], Effect[bytes, CryptoError]] | None,
) -> DecodeToSchema[K, bytes]:
    def decode(data: bytes, options: ParseOptions) -> Effect[K, Issue]:
        return from_bytes(data).map_error(lambda error: _issue(error, data, options))

    def encode(key: K, options: ParseOptions) -> Effect[bytes, Issue]:
        if to_bytes is None:
            return _forbidden_encode(name, key, options)
        return to_bytes(key).map_error(lambda error: _issue(error, key, options))

    return Bytes.pipe(decode_to(to, T.transform_effect(decode=decode, encode=encode)))


_JWK: Bottom[JsonWebKey, Any] = Struct(JsonWebKey).__codec__()
"""The JWK members ``key_format`` reads and writes; others are dropped."""


def _format_data[Data](format: key_format.Format[Any, Any, Data]) -> Bottom[Data, Data]:
    if format.tag == "jwk":
        return cast("Bottom[Data, Data]", _JWK)
    return cast("Bottom[Data, Data]", String if format.pem else Bytes)


def _next_turn() -> Effect[None]:
    """Effect's ``Effect.promise(() => Promise.resolve())``: resumed by a
    timer of no delay, so a synchronous run sees it as asynchronous."""

    def wait(scheduler: Any) -> Effect[None]:
        def register(resume: Callable[[Effect[None]], None]) -> Effect[None]:
            return sync(scheduler.call_later(Seconds(0.0), lambda: resume(succeed(None))))

        return callback(register)

    return CurrentScheduler().flat_map(wait)


def _from_format[K, Data](
    name: str,
    to: Bottom[K],
    format: key_format.Format[Any, Any, Data],
    decode_key: Callable[[Data], Effect[K, CryptoError]],
    can_encode: bool,
) -> DecodeToSchema[K, Data]:
    # PKCS#1 and SEC1 are read only.
    writable = can_encode and format.tag not in {"pkcs1", "sec1"}

    def decode(data: Data, options: ParseOptions) -> Effect[K, Issue]:
        # Secret JWK decoding is synchronous, but every format schema is
        # asynchronous only.
        return _next_turn().flat_map(
            lambda _: decode_key(data).map_error(lambda error: _issue(error, data, options))
        )

    def encode(key: K, options: ParseOptions) -> Effect[Data, Issue] | Exit[Data, Issue]:
        if not writable:
            return _forbidden_encode(name, key, options)
        encoded = key_format.encode(cast("Any", format), cast("Any", key))
        return cast("Effect[Data, CryptoError]", encoded).map_error(
            lambda error: _issue(error, key, options)
        )

    return _format_data(format).pipe(
        decode_to(to, T.transform_effect(decode=decode, encode=encode))
    )


type _Decode = Literal["decode"]


# ---------------------------------------------------------------------- Mac


def MacKey[A: mac.Algorithm](algorithm: A) -> Bottom[mac.Key[A]]:
    """Live ``mac.Key`` values of ``algorithm``."""
    return _declare("MacKey", "Mac", "Key", mac.Key, algorithm)


def MacKeyFromBytes[A: mac.Algorithm](
    algorithm: A, *, allow_encode: bool = False
) -> DecodeToSchema[mac.Key[A], bytes]:
    """Raw key bytes (base64 under ``config.schema``) as a ``mac.Key``."""
    return _from_bytes(
        "MacKeyFromBytes",
        MacKey(algorithm),
        lambda data: mac.key(algorithm, data),
        mac.to_bytes if allow_encode else None,
    )


def MacKeyFromFormat[A: mac.Algorithm, Data](
    format: key_format.Format[Literal["secret"], _Decode, Data],
    algorithm: A,
    *,
    allow_encode: bool = False,
) -> DecodeToSchema[mac.Key[A], Data]:
    """A ``mac.Key`` read with ``key_format.decode_secret``."""
    return _from_format(
        "MacKeyFromFormat",
        MacKey(algorithm),
        format,
        lambda data: cast("Any", key_format.decode_secret)(format, algorithm, data),
        allow_encode,
    )


# --------------------------------------------------------------------- Aead


def AeadKey[A: aead.Algorithm](algorithm: A) -> Bottom[aead.Key[A]]:
    """Live ``aead.Key`` values of ``algorithm``."""
    return _declare("AeadKey", "Aead", "Key", aead.Key, algorithm)


def AeadKeyFromBytes[A: aead.Algorithm](
    algorithm: A, *, allow_encode: bool = False
) -> DecodeToSchema[aead.Key[A], bytes]:
    """Raw key bytes (base64 under ``config.schema``) as an ``aead.Key``."""
    return _from_bytes(
        "AeadKeyFromBytes",
        AeadKey(algorithm),
        lambda data: aead.key(algorithm, data),
        aead.to_bytes if allow_encode else None,
    )


def AeadKeyFromFormat[A: aead.Algorithm, Data](
    format: key_format.Format[Literal["secret"], _Decode, Data],
    algorithm: A,
    *,
    allow_encode: bool = False,
) -> DecodeToSchema[aead.Key[A], Data]:
    """An ``aead.Key`` read with ``key_format.decode_secret``."""
    return _from_format(
        "AeadKeyFromFormat",
        AeadKey(algorithm),
        format,
        lambda data: cast("Any", key_format.decode_secret)(format, algorithm, data),
        allow_encode,
    )


# ------------------------------------------------------------------- Cipher


def CipherKey[A: cipher.Algorithm](algorithm: A) -> Bottom[cipher.Key[A]]:
    """Live ``cipher.Key`` values of ``algorithm``."""
    return _declare("CipherKey", "Cipher", "Key", cipher.Key, algorithm)


def CipherKeyFromBytes[A: cipher.Algorithm](
    algorithm: A, *, allow_encode: bool = False
) -> DecodeToSchema[cipher.Key[A], bytes]:
    """Raw key bytes (base64 under ``config.schema``) as a ``cipher.Key``."""
    return _from_bytes(
        "CipherKeyFromBytes",
        CipherKey(algorithm),
        lambda data: cipher.key(algorithm, data),
        cipher.to_bytes if allow_encode else None,
    )


def CipherKeyFromFormat[A: cipher.Algorithm, Data](
    format: key_format.Format[Literal["secret"], _Decode, Data],
    algorithm: A,
    *,
    allow_encode: bool = False,
) -> DecodeToSchema[cipher.Key[A], Data]:
    """A ``cipher.Key`` read with ``key_format.decode_secret``."""
    return _from_format(
        "CipherKeyFromFormat",
        CipherKey(algorithm),
        format,
        lambda data: cast("Any", key_format.decode_secret)(format, algorithm, data),
        allow_encode,
    )


# ---------------------------------------------------------------- Signature


def SignaturePublicKey[A: signature.Algorithm](algorithm: A) -> Bottom[signature.PublicKey[A]]:
    """Live ``signature.PublicKey`` values of ``algorithm``."""
    return _declare("SignaturePublicKey", "Signature", "PublicKey", signature.PublicKey, algorithm)


def SignaturePublicKeyFromBytes[A: signature.Ed25519 | signature.Ecdsa[Any]](
    algorithm: A,
) -> DecodeToSchema[signature.PublicKey[A], bytes]:
    """A raw Ed25519 key or uncompressed EC point as a ``signature.PublicKey``."""
    return _from_bytes(
        "SignaturePublicKeyFromBytes",
        SignaturePublicKey(algorithm),
        lambda data: signature.public_key(algorithm, data),
        signature.to_bytes,
    )


def SignaturePublicKeyFromFormat[A: signature.Algorithm, Data](
    format: key_format.Format[Literal["public"], _Decode, Data], algorithm: A
) -> DecodeToSchema[signature.PublicKey[A], Data]:
    """A ``signature.PublicKey`` read with ``key_format.decode_public`` and
    written with ``key_format.encode``."""
    return _from_format(
        "SignaturePublicKeyFromFormat",
        SignaturePublicKey(algorithm),
        format,
        lambda data: cast("Any", key_format.decode_public)(format, algorithm, data),
        True,
    )


def SignaturePrivateKey[A: signature.Algorithm](algorithm: A) -> Bottom[signature.PrivateKey[A]]:
    """Live ``signature.PrivateKey`` values of ``algorithm``."""
    return _declare(
        "SignaturePrivateKey", "Signature", "PrivateKey", signature.PrivateKey, algorithm
    )


def SignaturePrivateKeyFromBytes[A: signature.Ed25519](
    algorithm: A, *, allow_encode: bool = False
) -> DecodeToSchema[signature.PrivateKey[A], bytes]:
    """An Ed25519 seed as a ``signature.PrivateKey``."""
    return _from_bytes(
        "SignaturePrivateKeyFromBytes",
        SignaturePrivateKey(algorithm),
        lambda data: signature.private_key(algorithm, data),
        signature.to_bytes if allow_encode else None,
    )


def SignaturePrivateKeyFromFormat[A: signature.Algorithm, Data](
    format: key_format.Format[Literal["private"], _Decode, Data],
    algorithm: A,
    *,
    allow_encode: bool = False,
) -> DecodeToSchema[signature.PrivateKey[A], Data]:
    """A ``signature.PrivateKey`` read with ``key_format.decode_private``."""
    return _from_format(
        "SignaturePrivateKeyFromFormat",
        SignaturePrivateKey(algorithm),
        format,
        lambda data: cast("Any", key_format.decode_private)(format, algorithm, data),
        allow_encode,
    )


# ------------------------------------------------------------- KeyAgreement


def KeyAgreementPublicKey[A: key_agreement.Algorithm](
    algorithm: A,
) -> Bottom[key_agreement.PublicKey[A]]:
    """Live ``key_agreement.PublicKey`` values of ``algorithm``."""
    return _declare(
        "KeyAgreementPublicKey", "KeyAgreement", "PublicKey", key_agreement.PublicKey, algorithm
    )


def KeyAgreementPublicKeyFromBytes[A: key_agreement.Algorithm](
    algorithm: A,
) -> DecodeToSchema[key_agreement.PublicKey[A], bytes]:
    """A raw X25519 key or uncompressed EC point as a ``key_agreement.PublicKey``."""
    return _from_bytes(
        "KeyAgreementPublicKeyFromBytes",
        KeyAgreementPublicKey(algorithm),
        lambda data: key_agreement.public_key(algorithm, data),
        key_agreement.to_bytes,
    )


def KeyAgreementPublicKeyFromFormat[A: key_agreement.Algorithm, Data](
    format: key_format.Format[Literal["public"], _Decode, Data], algorithm: A
) -> DecodeToSchema[key_agreement.PublicKey[A], Data]:
    """A ``key_agreement.PublicKey`` read with ``key_format.decode_public``
    and written with ``key_format.encode``."""
    return _from_format(
        "KeyAgreementPublicKeyFromFormat",
        KeyAgreementPublicKey(algorithm),
        format,
        lambda data: cast("Any", key_format.decode_public)(format, algorithm, data),
        True,
    )


def KeyAgreementPrivateKey[A: key_agreement.Algorithm](
    algorithm: A,
) -> Bottom[key_agreement.PrivateKey[A]]:
    """Live ``key_agreement.PrivateKey`` values of ``algorithm``."""
    return _declare(
        "KeyAgreementPrivateKey", "KeyAgreement", "PrivateKey", key_agreement.PrivateKey, algorithm
    )


def KeyAgreementPrivateKeyFromBytes[A: key_agreement.X25519](
    algorithm: A, *, allow_encode: bool = False
) -> DecodeToSchema[key_agreement.PrivateKey[A], bytes]:
    """An X25519 private key's 32 bytes as a ``key_agreement.PrivateKey``."""
    return _from_bytes(
        "KeyAgreementPrivateKeyFromBytes",
        KeyAgreementPrivateKey(algorithm),
        lambda data: key_agreement.private_key(algorithm, data),
        key_agreement.to_bytes if allow_encode else None,
    )


def KeyAgreementPrivateKeyFromFormat[A: key_agreement.Algorithm, Data](
    format: key_format.Format[Literal["private"], _Decode, Data],
    algorithm: A,
    *,
    allow_encode: bool = False,
) -> DecodeToSchema[key_agreement.PrivateKey[A], Data]:
    """A ``key_agreement.PrivateKey`` read with ``key_format.decode_private``."""
    return _from_format(
        "KeyAgreementPrivateKeyFromFormat",
        KeyAgreementPrivateKey(algorithm),
        format,
        lambda data: cast("Any", key_format.decode_private)(format, algorithm, data),
        allow_encode,
    )


# ------------------------------------------------------------------ KeyWrap


def KeyWrapKey[A: key_wrap.AesKw](algorithm: A) -> Bottom[key_wrap.Key[A]]:
    """Live AES-KW ``key_wrap.Key`` values of ``algorithm``."""
    return _declare("KeyWrapKey", "KeyWrap", "Key", key_wrap.Key, algorithm)


def KeyWrapKeyFromBytes[A: key_wrap.AesKw](
    algorithm: A, *, allow_encode: bool = False
) -> DecodeToSchema[key_wrap.Key[A], bytes]:
    """Raw key bytes (base64 under ``config.schema``) as a ``key_wrap.Key``."""
    return _from_bytes(
        "KeyWrapKeyFromBytes",
        KeyWrapKey(algorithm),
        lambda data: key_wrap.key(algorithm, data),
        key_wrap.to_bytes if allow_encode else None,
    )


def KeyWrapKeyFromFormat[A: key_wrap.AesKw, Data](
    format: key_format.Format[Literal["secret"], _Decode, Data],
    algorithm: A,
    *,
    allow_encode: bool = False,
) -> DecodeToSchema[key_wrap.Key[A], Data]:
    """A ``key_wrap.Key`` read with ``key_format.decode_secret``."""
    return _from_format(
        "KeyWrapKeyFromFormat",
        KeyWrapKey(algorithm),
        format,
        lambda data: cast("Any", key_format.decode_secret)(format, algorithm, data),
        allow_encode,
    )


def KeyWrapPublicKey[A: key_wrap.RsaOaep](algorithm: A) -> Bottom[key_wrap.PublicKey[A]]:
    """Live RSA-OAEP ``key_wrap.PublicKey`` values of ``algorithm``."""
    return _declare("KeyWrapPublicKey", "KeyWrap", "PublicKey", key_wrap.PublicKey, algorithm)


def KeyWrapPublicKeyFromFormat[A: key_wrap.RsaOaep, Data](
    format: key_format.Format[Literal["public"], _Decode, Data], algorithm: A
) -> DecodeToSchema[key_wrap.PublicKey[A], Data]:
    """A ``key_wrap.PublicKey`` read with ``key_format.decode_public`` and
    written with ``key_format.encode``."""
    return _from_format(
        "KeyWrapPublicKeyFromFormat",
        KeyWrapPublicKey(algorithm),
        format,
        lambda data: cast("Any", key_format.decode_public)(format, algorithm, data),
        True,
    )


def KeyWrapPrivateKey[A: key_wrap.RsaOaep](algorithm: A) -> Bottom[key_wrap.PrivateKey[A]]:
    """Live RSA-OAEP ``key_wrap.PrivateKey`` values of ``algorithm``."""
    return _declare("KeyWrapPrivateKey", "KeyWrap", "PrivateKey", key_wrap.PrivateKey, algorithm)


def KeyWrapPrivateKeyFromFormat[A: key_wrap.RsaOaep, Data](
    format: key_format.Format[Literal["private"], _Decode, Data],
    algorithm: A,
    *,
    allow_encode: bool = False,
) -> DecodeToSchema[key_wrap.PrivateKey[A], Data]:
    """A ``key_wrap.PrivateKey`` read with ``key_format.decode_private``."""
    return _from_format(
        "KeyWrapPrivateKeyFromFormat",
        KeyWrapPrivateKey(algorithm),
        format,
        lambda data: cast("Any", key_format.decode_private)(format, algorithm, data),
        allow_encode,
    )


__all__ = [
    "AeadKey",
    "AeadKeyFromBytes",
    "AeadKeyFromFormat",
    "CipherKey",
    "CipherKeyFromBytes",
    "CipherKeyFromFormat",
    "KeyAgreementPrivateKey",
    "KeyAgreementPrivateKeyFromBytes",
    "KeyAgreementPrivateKeyFromFormat",
    "KeyAgreementPublicKey",
    "KeyAgreementPublicKeyFromBytes",
    "KeyAgreementPublicKeyFromFormat",
    "KeyWrapKey",
    "KeyWrapKeyFromBytes",
    "KeyWrapKeyFromFormat",
    "KeyWrapPrivateKey",
    "KeyWrapPrivateKeyFromFormat",
    "KeyWrapPublicKey",
    "KeyWrapPublicKeyFromFormat",
    "MacKey",
    "MacKeyFromBytes",
    "MacKeyFromFormat",
    "SignaturePrivateKey",
    "SignaturePrivateKeyFromBytes",
    "SignaturePrivateKeyFromFormat",
    "SignaturePublicKey",
    "SignaturePublicKeyFromBytes",
    "SignaturePublicKeyFromFormat",
]
