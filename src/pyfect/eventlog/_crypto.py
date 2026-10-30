"""AES-GCM and Ed25519 on the ``cryptography`` package (the extra
``pyfect[eventlog]``), where Effect uses WebCrypto. Imported by the
functions that need it, so the rest of ``pyfect.eventlog`` works without
the extra."""

from __future__ import annotations

try:
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import (
        Ed25519PrivateKey,
        Ed25519PublicKey,
    )
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM
except ImportError as error:  # pragma: no cover - depends on the environment
    raise ImportError(
        "pyfect.eventlog encryption and session auth need the cryptography package: "
        "install pyfect[eventlog]"
    ) from error


def ed25519_public_key(seed: bytes) -> bytes:
    """The raw public key of the private key ``seed``."""
    public = Ed25519PrivateKey.from_private_bytes(seed).public_key()
    return public.public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)


def ed25519_sign(pkcs8: bytes, payload: bytes) -> bytes:
    """``payload`` signed with a PKCS#8 private key; ``ValueError`` when
    the key is not an Ed25519 key."""
    key = serialization.load_der_private_key(pkcs8, None)
    if not isinstance(key, Ed25519PrivateKey):
        raise ValueError("not an Ed25519 private key")
    return key.sign(payload)


def ed25519_verify(public_key: bytes, signature: bytes, payload: bytes) -> bool:
    """Whether ``signature`` signs ``payload`` for the raw ``public_key``."""
    key = Ed25519PublicKey.from_public_bytes(public_key)
    try:
        key.verify(signature, payload)
    except InvalidSignature:
        return False
    return True


def aes_gcm_encrypt(key: bytes, iv: bytes, data: bytes, additional_data: bytes) -> bytes:
    """The ciphertext followed by its 128-bit tag, as WebCrypto's."""
    return AESGCM(key).encrypt(iv, data, additional_data)


def aes_gcm_decrypt(key: bytes, iv: bytes, data: bytes, additional_data: bytes) -> bytes:
    """The plaintext; ``cryptography.exceptions.InvalidTag`` when ``data``
    was altered or the key, iv or additional data differ."""
    return AESGCM(key).decrypt(iv, data, additional_data)


__all__ = [
    "aes_gcm_decrypt",
    "aes_gcm_encrypt",
    "ed25519_public_key",
    "ed25519_sign",
    "ed25519_verify",
]
