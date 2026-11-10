"""Every crypto family on the host's own libraries (Effect's
``@effect/platform-node`` ``NodeCrypto``)::

    program.pipe(provide(native.layer))

Digests and HMAC run on ``hashlib`` and ``hmac``; Argon2id on
``cryptography`` (on a worker thread); ChaCha20-Poly1305 on
``cryptography``; the rest on the ``WebCrypto`` reference, whose default
is the host's. Random bytes come from ``os.urandom``.
"""

from __future__ import annotations

import hashlib
import hmac as std_hmac
from typing import Never

from pyfect._core import Effect
from pyfect.crypto import aead, cipher, digest, kdf, key_agreement, key_wrap, mac, secure_random
from pyfect.crypto import signature as signature_module
from pyfect.crypto._key import Binary
from pyfect.crypto.crypto_error import AnyReason, CryptoError, InvalidArgument, Unsupported
from pyfect.effect import die, fail, gen, suspend, sync, try_blocking
from pyfect.layer import Layer, merge, provide
from pyfect.layer import effect as layer_effect
from pyfect.layer import succeed as layer_succeed

layer_secure_random: Layer[secure_random.SecureRandom] = secure_random.layer_web_crypto
"""Random bytes from the ``WebCrypto`` reference (``os.urandom`` by default)."""

_HASH_NAMES: dict[digest.Name, str] = {
    "MD5": "md5",
    "SHA-1": "sha1",
    "SHA-256": "sha256",
    "SHA-384": "sha384",
    "SHA-512": "sha512",
}


def _hash(algorithm: digest.Algorithm, data: Binary) -> hashlib._Hash:  # pyright: ignore[reportPrivateUsage]
    return hashlib.new(_HASH_NAMES[algorithm.name], bytes(data), usedforsecurity=False)


layer_digest: Layer[digest.Digest] = layer_succeed(
    digest.Digest,
    digest.DigestService(
        digest=lambda algorithm, data: sync(lambda: _hash(algorithm, data).digest()),
        digest_hex=lambda algorithm, data: sync(lambda: _hash(algorithm, data).hexdigest()),
    ),
)
"""Digests on ``hashlib``."""


def _hmac(hash_name: digest.Name, key: bytes, data: bytes) -> bytes:
    return std_hmac.new(key, data, _HASH_NAMES[hash_name]).digest()


layer_mac: Layer[mac.Mac] = mac.layer_web_crypto_with(hmac=_hmac).pipe(provide(layer_secure_random))
"""HMAC on ``hmac`` for byte-backed keys."""


def _kdf_failure(reason: AnyReason) -> Effect[Never, CryptoError]:
    return fail(CryptoError(module="Kdf", method="derive", reason=reason))


def _argon2_unsupported(cause: object = None) -> Effect[Never, CryptoError]:
    return _kdf_failure(
        Unsupported(
            description="NodeCrypto.layerKdf does not provide argon2id on this runtime",
            cause=cause,
        )
    )


def _is_integer_in(n: object, low: int, high: int) -> bool:
    return isinstance(n, int) and not isinstance(n, bool) and low <= n <= high


def _argon2_problem(
    algorithm: kdf.Argon2id, salt: bytes, length: int, info: Binary | None
) -> str | None:
    """RFC 9106's bounds, checked before ``cryptography``, which raises on them."""
    if info is not None:
        return "info only applies to HKDF"

    def uint32(n: int) -> bool:
        return _is_integer_in(n, 1, 0xFFFF_FFFF)

    if not uint32(algorithm.passes) or not _is_integer_in(algorithm.parallelism, 1, 0xFF_FFFF):
        return "passes must be between 1 and 2^32 - 1 and parallelism between 1 and 2^24 - 1"
    if not uint32(algorithm.memory) or algorithm.memory < 8 * algorithm.parallelism:
        return "memory must be at least 8 KiB per lane and below 2^32 KiB"
    if len(salt) < 8:
        return "salt must be at least 8 bytes"
    if _is_integer_in(length, 4, 0xFFFF_FFFF):
        return None
    return "length must be between 4 and 2^32 - 1 bytes"


class _Argon2Unavailable(Exception):
    pass


def _argon2id_derive(algorithm: kdf.Argon2id, secret: bytes, salt: bytes, length: int) -> bytes:
    try:
        from pyfect.crypto._lib import Argon2id, UnsupportedAlgorithm
    except ImportError as error:
        raise _Argon2Unavailable from error
    try:
        derivation = Argon2id(
            salt=salt,
            length=length,
            iterations=algorithm.passes,
            lanes=algorithm.parallelism,
            memory_cost=algorithm.memory,
        )
    except UnsupportedAlgorithm as error:
        raise _Argon2Unavailable from error
    return derivation.derive(secret)


def _argon2id(
    algorithm: kdf.Argon2id, secret: Binary, salt: Binary, length: int, info: Binary | None
) -> Effect[bytes, CryptoError]:
    def go() -> Effect[bytes, CryptoError]:
        problem = _argon2_problem(algorithm, bytes(salt), length, info)
        if problem is not None:
            return _kdf_failure(InvalidArgument(description=problem))
        secret_now, salt_now = bytes(secret), bytes(salt)

        # Only a missing Argon2id engine is a typed failure; anything else
        # is a defect.
        def recover(cause: Exception) -> Effect[Never, CryptoError]:
            if isinstance(cause, _Argon2Unavailable):
                return _argon2_unsupported(cause.__cause__)
            return die(cause)

        def keep(cause: Exception) -> Exception:
            return cause

        return (
            try_blocking(lambda: _argon2id_derive(algorithm, secret_now, salt_now, length), keep)
            .catch_all(recover)
            .uninterruptible()
        )

    return suspend(go)


class _NativeKdf:
    __slots__ = ("_core",)

    def __init__(self, core: kdf.KdfService) -> None:
        self._core = core

    def derive(
        self,
        algorithm: kdf.Algorithm,
        secret: Binary,
        *,
        salt: Binary,
        length: int,
        info: Binary | None = None,
    ) -> Effect[bytes, CryptoError]:
        if isinstance(algorithm, kdf.Argon2id):
            return _argon2id(algorithm, secret, salt, length, info)
        return self._core.derive(algorithm, secret, salt=salt, length=length, info=info)


@gen
def _build_kdf():
    core = yield from kdf.Kdf()
    service: kdf.KdfService = _NativeKdf(core)
    return service


layer_kdf: Layer[kdf.Kdf] = layer_effect(kdf.Kdf, _build_kdf).pipe(provide(kdf.layer_web_crypto))
"""HKDF and PBKDF2 on the ``WebCrypto`` reference, Argon2id on ``cryptography``."""

_chacha = aead.chacha20_poly1305.implementation
_native_aead: dict[aead.Name, aead.Implementation] = (
    {} if _chacha is None else {"chacha20Poly1305": _chacha}
)

layer_aead: Layer[aead.Aead] = aead.layer_web_crypto_with(implementations=_native_aead).pipe(
    provide(layer_secure_random)
)
"""AES-GCM on the ``WebCrypto`` reference, ChaCha20-Poly1305 on ``cryptography``."""

layer_cipher: Layer[cipher.Cipher] = cipher.layer_web_crypto.pipe(provide(layer_secure_random))
layer_signature: Layer[signature_module.Signature] = signature_module.layer_web_crypto.pipe(
    provide(layer_secure_random)
)
layer_key_agreement: Layer[key_agreement.KeyAgreement] = key_agreement.layer_web_crypto.pipe(
    provide(layer_secure_random)
)
layer_key_wrap: Layer[key_wrap.KeyWrap] = key_wrap.layer_web_crypto.pipe(
    provide(layer_secure_random)
)

type Services = (
    secure_random.SecureRandom
    | digest.Digest
    | mac.Mac
    | kdf.Kdf
    | aead.Aead
    | cipher.Cipher
    | signature_module.Signature
    | key_agreement.KeyAgreement
    | key_wrap.KeyWrap
)

layer: Layer[Services] = merge(
    merge(layer_secure_random, layer_digest, layer_mac, layer_kdf, layer_aead),
    merge(layer_cipher, layer_signature, layer_key_agreement, layer_key_wrap),
)
"""Every crypto family."""

__all__ = [
    "Services",
    "layer",
    "layer_aead",
    "layer_cipher",
    "layer_digest",
    "layer_kdf",
    "layer_key_agreement",
    "layer_key_wrap",
    "layer_mac",
    "layer_secure_random",
    "layer_signature",
]
