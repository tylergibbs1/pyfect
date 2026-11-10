"""Compact JSON Web Encryption with a shared key (Effect's
``effect/jose/Jwe``): ``alg`` ``dir`` and ``enc`` ``A256GCM`` only::

    token = yield from jwe.encrypt(b"hello", dir_key, {"cty": "text/plain"})
    decrypted = yield from jwe.decrypt(token, dir_key)

``decrypt`` takes the key, or a function choosing it from the protected
header (by ``kid``), called only once the token is well formed. The
``crit`` and ``zip`` header parameters are refused.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, Never, NotRequired, TypedDict, overload

from pyfect import schema as S
from pyfect._binary_codecs import base64_url_encode
from pyfect._core import Effect
from pyfect._some import Some
from pyfect.crypto import aead
from pyfect.crypto.aead import Aead
from pyfect.crypto.crypto_error import CryptoError
from pyfect.crypto.crypto_error import DecryptionFailed as CryptoDecryptionFailed
from pyfect.crypto.secure_random import SecureRandom
from pyfect.effect import gen
from pyfect.jose._compact import (
    Header,
    Token,
    crypto_failure,
    decode_header,
    decode_segment,
    encode_header,
    invalid_token,
    split,
    utf8,
)
from pyfect.jose.jose_error import DecryptionFailed, JoseError
from pyfect.jose.jwk import DirKey
from pyfect.redacted import Redacted
from pyfect.redacted import make as redacted

_UNSUPPORTED = ("crit", "zip")
_TAG_LENGTH = 16
_NONCE_LENGTH = aead.aes256_gcm.nonce_length


class ProtectedHeader(TypedDict):
    """A decrypted token's header; other members are any JSON."""

    alg: Literal["dir"]
    enc: Literal["A256GCM"]
    kid: NotRequired[str]
    typ: NotRequired[str]
    cty: NotRequired[str]


ProtectedHeaderSchema = S.StructWithRest(S.Struct(ProtectedHeader), S.Record(S.String, S.Json))


@dataclass(frozen=True, slots=True)
class Decrypted:
    protected_header: ProtectedHeader
    plaintext: bytes
    key: DirKey


_decode_protected_header_option = S.decode_unknown_option(ProtectedHeaderSchema)


def _decode_protected_header(input: object) -> ProtectedHeader | None:
    decoded = _decode_protected_header_option(input)
    return decoded.value if isinstance(decoded, Some) else None


def encrypt(
    plaintext: bytes, key: DirKey, header: Header | None = None
) -> Effect[Redacted[str], JoseError, Aead | SecureRandom]:
    """A compact JWE of ``plaintext`` with a random IV; ``alg`` and ``enc``
    are always ``dir`` and ``A256GCM``."""

    @gen
    def body():
        protected_header = yield from encode_header(
            {"alg": "dir", "enc": "A256GCM"}, key.kid, header, _UNSUPPORTED
        )
        random = yield from SecureRandom()
        service = yield from Aead()
        nonce = yield from random.random_bytes(_NONCE_LENGTH)
        sealed = yield from service.encrypt(
            key.key, plaintext, nonce=nonce, aad=utf8(protected_header)
        ).map_error(crypto_failure("Could not encrypt with the key"))
        ciphertext = base64_url_encode(sealed[:-_TAG_LENGTH])
        tag = base64_url_encode(sealed[-_TAG_LENGTH:])
        return redacted(f"{protected_header}..{base64_url_encode(nonce)}.{ciphertext}.{tag}")

    return body


def _decryption_failure(error: CryptoError) -> JoseError:
    if isinstance(error.reason, CryptoDecryptionFailed):
        return JoseError(DecryptionFailed())
    return crypto_failure("Could not decrypt with the key")(error)


@overload
def decrypt(token: Token, key: DirKey) -> Effect[Decrypted, JoseError, Aead]: ...
@overload
def decrypt[E = Never, R = Never](
    token: Token, key: Callable[[ProtectedHeader], Effect[DirKey, E, R]]
) -> Effect[Decrypted, JoseError | E, Aead | R]: ...
@overload
def decrypt[E = Never, R = Never](
    token: Token, key: DirKey | Callable[[ProtectedHeader], Effect[DirKey, E, R]]
) -> Effect[Decrypted, JoseError | E, Aead | R]: ...
def decrypt(
    token: Token, key: DirKey | Callable[[ProtectedHeader], Effect[DirKey, Any, Any]]
) -> Effect[Decrypted, Any, Any]:
    """The plaintext and header; ``DecryptionFailed`` for a wrong key or a
    tampered token."""

    @gen
    def body():
        header, encrypted_key, iv, ciphertext, tag = yield from split(token, 5)
        if encrypted_key != "":
            return (yield from invalid_token("A dir token must have an empty encrypted key"))
        protected_header = yield from decode_header(header, _decode_protected_header, _UNSUPPORTED)
        nonce = decode_segment(iv)
        data = decode_segment(ciphertext)
        auth_tag = decode_segment(tag)
        if (
            nonce is None
            or data is None
            or auth_tag is None
            or len(nonce) != _NONCE_LENGTH
            or len(auth_tag) != _TAG_LENGTH
        ):
            return (yield from invalid_token("The IV, ciphertext, or tag is malformed"))
        resolved: DirKey = key if isinstance(key, DirKey) else (yield from key(protected_header))
        service = yield from Aead()
        plaintext = yield from service.decrypt(
            resolved.key, data + auth_tag, nonce=nonce, aad=utf8(header)
        ).map_error(_decryption_failure)
        return Decrypted(protected_header, plaintext, resolved)

    return body


__all__ = [
    "Decrypted",
    "Header",
    "JoseError",
    "ProtectedHeader",
    "ProtectedHeaderSchema",
    "decrypt",
    "encrypt",
]
