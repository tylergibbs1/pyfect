"""Keys derived from an identity's root secret (Effect's
``eventlog/internal/identityRootSecretDerivation.ts``): SHA-256 of a
versioned, domain-separated label, a zero byte and the secret gives the
AES-GCM key and the Ed25519 seed."""

from __future__ import annotations

import hashlib
import weakref
from collections.abc import Callable
from dataclasses import dataclass

from pyfect._core import Effect
from pyfect._js import text_encode
from pyfect.effect import sync
from pyfect.eventlog._identity import IdentityService
from pyfect.redacted import Redacted
from pyfect.redacted import make as redacted
from pyfect.redacted import value as reveal

ED25519_PUBLIC_KEY_LENGTH = 32
ED25519_PKCS8_SEED_PREFIX = bytes.fromhex("302e020100300506032b657004220420")
ENCRYPTION_DERIVATION_LABEL_V1 = "effect/eventlog/identity/v1/encryption"
SIGNING_DERIVATION_LABEL_V1 = "effect/eventlog/identity/v1/signing"


@dataclass(frozen=True, slots=True)
class IdentityRootSecretMaterial:
    """The AES-GCM key bytes and the Ed25519 key pair (the private key as PKCS#8
    bytes) of an identity."""

    encryption_key_material: bytes
    signing_public_key: bytes
    signing_private_key: Redacted[bytes]


def derive_secret_bytes(root_secret: bytes, label: str) -> bytes:
    return hashlib.sha256(text_encode(label) + b"\x00" + root_secret).digest()


def derive_identity_root_secret_material(root_secret: bytes) -> IdentityRootSecretMaterial:
    from pyfect.eventlog import _crypto

    encryption_key = derive_secret_bytes(root_secret, ENCRYPTION_DERIVATION_LABEL_V1)
    seed = derive_secret_bytes(root_secret, SIGNING_DERIVATION_LABEL_V1)
    public_key = _crypto.ed25519_public_key(seed)
    return IdentityRootSecretMaterial(
        encryption_key, public_key, redacted(ED25519_PKCS8_SEED_PREFIX + seed)
    )


type GetMaterial = Callable[[IdentityService], Effect[IdentityRootSecretMaterial]]


def make_get_identity_root_secret_material() -> GetMaterial:
    """The material of an identity, derived once per identity instance."""
    cache: weakref.WeakKeyDictionary[IdentityService, IdentityRootSecretMaterial] = (
        weakref.WeakKeyDictionary()
    )

    def get(identity: IdentityService) -> IdentityRootSecretMaterial:
        found = cache.get(identity)
        if found is None:
            found = cache[identity] = derive_identity_root_secret_material(
                reveal(identity.private_key)
            )
        return found

    return lambda identity: sync(lambda: get(identity))


__all__ = [
    "ENCRYPTION_DERIVATION_LABEL_V1",
    "SIGNING_DERIVATION_LABEL_V1",
    "IdentityRootSecretMaterial",
    "derive_identity_root_secret_material",
    "derive_secret_bytes",
    "make_get_identity_root_secret_material",
]
