"""Keys derived from an identity's root secret (Effect's
``eventlog/internal/identityRootSecretDerivation.ts``): SHA-256 of a
versioned, domain-separated label, a zero byte and the secret gives the
AES-256-GCM key and the Ed25519 seed. The derivations run on the
``pyfect.crypto`` services, as Effect's run on ``effect/crypto``."""

from __future__ import annotations

import weakref
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never

from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.crypto import aead, digest, key_format, secure_random, signature
from pyfect.crypto import web_crypto as web
from pyfect.effect import gen, succeed, suspend
from pyfect.eventlog._identity import IdentityService
from pyfect.layer import Layer, merge, provide_merge
from pyfect.layer import provide as provide_layer
from pyfect.redacted import Redacted
from pyfect.redacted import make as redacted
from pyfect.redacted import value as reveal

ENCRYPTION_DERIVATION_LABEL_V1 = "effect/eventlog/identity/v1/encryption"
SIGNING_DERIVATION_LABEL_V1 = "effect/eventlog/identity/v1/signing"


@dataclass(frozen=True, slots=True)
class EncryptionKey:
    """The AES-256-GCM key bytes of an identity and the key made of them."""

    encryption_key_material: bytes
    encryption_key: aead.Key[aead.AesGcm]


@dataclass(frozen=True, slots=True)
class SigningKey:
    """The Ed25519 key pair of an identity, the private key as PKCS#8 bytes."""

    signing_public_key: bytes
    signing_private_key: Redacted[bytes]


@dataclass(frozen=True, slots=True)
class IdentityRootSecretMaterial:
    """Every key derived from an identity's root secret."""

    encryption_key_material: bytes
    encryption_key: aead.Key[aead.AesGcm]
    signing_public_key: bytes
    signing_private_key: Redacted[bytes]


def derive_secret_bytes(root_secret: bytes, label: str) -> Effect[bytes, Never, digest.Digest]:
    """SHA-256(label || 0x00 || root secret)."""
    return digest.Digest().flat_map(
        lambda service: service.digest(digest.sha256, text_encode(label) + b"\x00" + root_secret)
    )


def derive_encryption_key(root_secret: bytes) -> Effect[EncryptionKey, Never, digest.Digest]:
    """The AES-256-GCM key that encrypts an identity's entries."""
    return derive_secret_bytes(root_secret, ENCRYPTION_DERIVATION_LABEL_V1).flat_map(
        lambda material: (
            aead.key(aead.aes256_gcm, material)
            .or_die()
            .map(lambda key: EncryptionKey(material, key))
        )
    )


def _derive_signing_key(
    root_secret: bytes,
) -> Effect[SigningKey, Never, digest.Digest | signature.Signature]:
    @gen
    def derive():
        service = yield from signature.Signature()
        seed = yield from derive_secret_bytes(root_secret, SIGNING_DERIVATION_LABEL_V1)
        private_key = yield from signature.private_key(signature.ed25519, seed)
        public_key = yield from service.public_key_of(private_key).flat_map(signature.to_bytes)
        pkcs8 = yield from key_format.encode(key_format.pkcs8, private_key)
        return SigningKey(public_key, redacted(pkcs8))

    return derive.or_die()


def derive_identity_root_secret_material(
    root_secret: bytes,
) -> Effect[IdentityRootSecretMaterial, Never, digest.Digest | signature.Signature]:
    return derive_encryption_key(root_secret).zip_with(
        _derive_signing_key(root_secret),
        lambda encryption, signing: IdentityRootSecretMaterial(
            encryption.encryption_key_material,
            encryption.encryption_key,
            signing.signing_public_key,
            signing.signing_private_key,
        ),
    )


def cached_by_identity[A, R](
    derive: Callable[[bytes], Effect[A, Never, R]],
) -> Callable[[IdentityService], Effect[A, Never, R]]:
    """``derive`` of an identity's root secret, memoized per identity
    instance."""
    cache: weakref.WeakKeyDictionary[IdentityService, A] = weakref.WeakKeyDictionary()

    def get(identity: IdentityService) -> Effect[A, Never, R]:
        def go() -> Effect[A, Never, R]:
            if identity in cache:
                return succeed(cache[identity])
            return derive(reveal(identity.private_key)).tap(
                lambda derived: succeed(cache.__setitem__(identity, derived))
            )

        return suspend(go)

    return get


_layer_web_crypto: Layer[digest.Digest | signature.Signature] = merge(
    digest.layer_web_crypto, signature.layer_web_crypto
).pipe(provide_layer(secure_random.layer_web_crypto))

type GetMaterial = Callable[[IdentityService], Effect[IdentityRootSecretMaterial]]


def make_get_identity_root_secret_material(crypto: web.Crypto | None = None) -> GetMaterial:
    """The material of an identity on the Web Crypto layers, derived once per
    identity instance: on ``crypto`` when given, else on the ``WebCrypto``
    reference."""
    layer: Layer[Any] = (
        _layer_web_crypto
        if crypto is None
        else _layer_web_crypto.pipe(provide_merge(web.layer(crypto)))
    )
    # ``local`` keeps enclosing Web Crypto layers, built on another
    # ``Crypto``, from being reused.
    provided = provide_layer(layer, local=crypto is not None)
    return cached_by_identity(
        lambda root_secret: derive_identity_root_secret_material(root_secret).pipe(provided)
    )


__all__ = [
    "ENCRYPTION_DERIVATION_LABEL_V1",
    "SIGNING_DERIVATION_LABEL_V1",
    "EncryptionKey",
    "GetMaterial",
    "IdentityRootSecretMaterial",
    "SigningKey",
    "cached_by_identity",
    "derive_encryption_key",
    "derive_identity_root_secret_material",
    "derive_secret_bytes",
    "make_get_identity_root_secret_material",
]
