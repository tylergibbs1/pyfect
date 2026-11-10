"""Cryptography as services (Effect's ``effect/crypto``).

Each family is a service with its own opaque keys: ``secure_random``
(random bytes, integers, UUIDs, ULIDs), ``digest``, ``mac`` (HMAC),
``aead`` (AES-GCM, ChaCha20-Poly1305), ``cipher`` (AES-CTR / CBC), ``kdf``
(HKDF, PBKDF2, Argon2id), ``signature`` (Ed25519, ECDSA, RSA),
``key_agreement`` (X25519, ECDH) and ``key_wrap`` (AES-KW, RSA-OAEP).
``key_format`` reads and writes keys as SPKI, PKCS#8, JWK and PEM. Every
failure is a ``crypto_error.CryptoError``.

The ``layer_web_crypto`` layers run on the ``web_crypto.WebCrypto``
reference; ``native`` adds the host's own implementations (Argon2id,
ChaCha20-Poly1305) and ``native.layer`` provides every family. Keys need
the ``crypto`` extra: ``uv add "pyfect-dev[crypto]"``.
"""

from pyfect.crypto import (
    aead,
    cipher,
    crypto_error,
    digest,
    kdf,
    key_agreement,
    key_format,
    key_wrap,
    mac,
    native,
    secure_random,
    signature,
    web_crypto,
)

__all__ = [
    "aead",
    "cipher",
    "crypto_error",
    "digest",
    "kdf",
    "key_agreement",
    "key_format",
    "key_wrap",
    "mac",
    "native",
    "secure_random",
    "signature",
    "web_crypto",
]
