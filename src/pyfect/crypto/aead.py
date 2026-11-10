"""Authenticated encryption as a service (Effect's ``effect/crypto/Aead``)::

    aead = yield from Aead()
    key = yield from aead.generate_key(aes256_gcm)
    sealed = yield from aead.encrypt(key, plaintext, nonce=nonce, aad=header)
    opened = yield from aead.decrypt(key, sealed, nonce=nonce, aad=header)

The ciphertext ends with its 16-byte tag. Every argument is checked when
the effect runs, before any work; a decryption that fails for any reason
(tag, AAD, ciphertext, a too-short input) fails with the same
``DecryptionFailed``. AES-GCM runs on the ``WebCrypto`` reference;
ChaCha20-Poly1305 (``cryptography``) and XChaCha20-Poly1305 (``PyNaCl``,
both in the ``crypto`` extra) run in the process. Never reuse a nonce with
a key.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, ClassVar, Literal, Never, Protocol, final

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.crypto import _key, _web
from pyfect.crypto._key import Binary, KeyBase, material
from pyfect.crypto.crypto_error import (
    AnyReason,
    CryptoError,
    DecryptionFailed,
    InvalidArgument,
    InvalidKey,
)
from pyfect.crypto.secure_random import SecureRandom, SecureRandomService
from pyfect.crypto.web_crypto import Crypto, CryptoKey, Params, SubtleCrypto, WebCrypto
from pyfect.effect import gen, succeed, suspend, sync
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect

type Name = Literal["aes128Gcm", "aes256Gcm", "chacha20Poly1305", "xchacha20Poly1305"]
type Method = Literal["encrypt", "decrypt"]


@dataclass(frozen=True, slots=True)
class Implementation:
    """An in-process AEAD: ``encrypt(key, nonce, plaintext, aad)`` gives the
    ciphertext and tag; ``decrypt`` gives the plaintext, or ``None`` when the
    tag does not match."""

    encrypt: Callable[[bytes, bytes, bytes, bytes], bytes]
    decrypt: Callable[[bytes, bytes, bytes, bytes], bytes | None]


@dataclass(frozen=True, kw_only=True)
class Algorithm:
    name: Name
    key_length: Literal[16, 32]
    nonce_length: Literal[12, 24]
    implementation: Implementation | None = field(default=None, compare=False)


@dataclass(frozen=True, kw_only=True)
class AesGcm(Algorithm):
    """AES-GCM, which runs on Web Crypto and may be backed by a ``CryptoKey``."""


aes128_gcm = AesGcm(name="aes128Gcm", key_length=16, nonce_length=12)
aes256_gcm = AesGcm(name="aes256Gcm", key_length=32, nonce_length=12)


def _chacha20_poly1305() -> Implementation:
    def cipher(key: bytes) -> Any:
        from pyfect.crypto._lib import ChaCha20Poly1305

        return ChaCha20Poly1305(key)

    def decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes | None:
        from pyfect.crypto._lib import InvalidTag

        try:
            return cipher(key).decrypt(nonce, ciphertext, aad)
        except InvalidTag:
            return None

    return Implementation(
        encrypt=lambda key, nonce, plaintext, aad: cipher(key).encrypt(nonce, plaintext, aad),
        decrypt=decrypt,
    )


def _xchacha20_poly1305() -> Implementation:
    def bindings() -> Any:
        from pyfect.crypto._lib import nacl_bindings

        return nacl_bindings

    def encrypt(key: bytes, nonce: bytes, plaintext: bytes, aad: bytes) -> bytes:
        return bindings().crypto_aead_xchacha20poly1305_ietf_encrypt(plaintext, aad, nonce, key)

    def decrypt(key: bytes, nonce: bytes, ciphertext: bytes, aad: bytes) -> bytes | None:
        from pyfect.crypto._lib import NaclCryptoError

        try:
            return bindings().crypto_aead_xchacha20poly1305_ietf_decrypt(
                ciphertext, aad, nonce, key
            )
        except NaclCryptoError:
            return None

    return Implementation(encrypt=encrypt, decrypt=decrypt)


chacha20_poly1305 = Algorithm(
    name="chacha20Poly1305",
    key_length=32,
    nonce_length=12,
    implementation=_chacha20_poly1305(),
)
xchacha20_poly1305 = Algorithm(
    name="xchacha20Poly1305",
    key_length=32,
    nonce_length=24,
    implementation=_xchacha20_poly1305(),
)


@final
class Key[A: Algorithm = Algorithm](KeyBase[A]):
    """An AEAD key for ``algorithm``."""

    __slots__ = ()
    label: ClassVar[str] = "Aead.Key"


def is_key(u: object) -> bool:
    return isinstance(u, Key)


class AeadService(Protocol):
    def generate_key[A: Algorithm](self, algorithm: A) -> Effect[Key[A], CryptoError]:
        """A key of random bytes from ``SecureRandom``."""
        ...

    def encrypt(
        self, key: Key[Any], plaintext: Binary, *, nonce: Binary, aad: Binary | None = None
    ) -> Effect[bytes, CryptoError]:
        """The ciphertext followed by its 16-byte tag."""
        ...

    def decrypt(
        self, key: Key[Any], ciphertext: Binary, *, nonce: Binary, aad: Binary | None = None
    ) -> Effect[bytes, CryptoError]:
        """The plaintext; ``DecryptionFailed`` for any authentication failure."""
        ...


class Aead(Tag[AeadService], key="effect/crypto/Aead"):
    """Authenticated encryption."""


def _fail(method: Method, reason: AnyReason) -> Effect[Never, CryptoError]:
    return _web.fail("Aead", method, reason)


def _decryption_failed() -> Effect[Never, CryptoError]:
    return _fail("decrypt", DecryptionFailed())


# GCM limits the plaintext to 2^39 - 256 bits.
_MAX_GCM_PLAINTEXT = 2**36 - 32
_TAG_LENGTH = 16


def _check_arguments(
    method: Method, key: Key[Any], data: bytes, nonce: bytes
) -> Effect[Never, CryptoError] | None:
    """Every check runs before any work, so an implementation only raises
    on a bug, and Web Crypto's ``OperationError`` only means a failed tag."""
    algorithm = key.algorithm
    if len(nonce) != algorithm.nonce_length:
        return _fail(
            method,
            InvalidArgument(
                description=(
                    f"{algorithm.name} nonces must contain exactly {algorithm.nonce_length} bytes"
                )
            ),
        )
    if method == "encrypt":
        if algorithm.implementation is None and len(data) > _MAX_GCM_PLAINTEXT:
            return _fail(
                method,
                InvalidArgument(description="AES-GCM plaintext cannot exceed 2^36 - 32 bytes"),
            )
    elif len(data) < _TAG_LENGTH:
        return _decryption_failed()
    return None


def _run_implementation(  # noqa: PLR0917
    method: Method,
    implementation: Implementation,
    key: Key[Any],
    data: bytes,
    nonce: bytes,
    aad: bytes | None,
) -> Effect[bytes, CryptoError]:
    stored = material(key)
    if not isinstance(stored, bytes):
        return _fail(method, InvalidKey(description=f"{key.algorithm.name} keys must hold bytes"))
    associated = b"" if aad is None else bytes(aad)
    if method == "encrypt":
        return sync(lambda: bytes(implementation.encrypt(stored, nonce, data, associated)))

    def go() -> Effect[bytes, CryptoError]:
        plaintext = implementation.decrypt(stored, nonce, data, associated)
        return _decryption_failed() if plaintext is None else succeed(bytes(plaintext))

    return suspend(go)


class _WebCryptoAead:
    __slots__ = ("_crypto", "_crypto_key_for", "_implementations", "_random")

    def __init__(
        self,
        random: SecureRandomService,
        crypto: Crypto,
        implementations: dict[Name, Implementation] | None,
    ) -> None:
        self._random = random
        self._crypto = crypto
        self._implementations = implementations
        self._crypto_key_for = _key.make_cache(
            lambda subtle, data, _algorithm: subtle.import_key(
                "raw", data, "AES-GCM", False, ["encrypt", "decrypt"]
            )
        )

    def generate_key[A: Algorithm](self, algorithm: A) -> Effect[Key[A], CryptoError]:
        return self._random.random_bytes(algorithm.key_length).map(
            lambda data: Key(algorithm, data)
        )

    def _implementation_for(self, key: Key[Any]) -> Implementation | None:
        # A supplied implementation runs only for byte-backed keys, so
        # CryptoKeys stay on ``crypto.subtle``.
        supplied = (
            None if self._implementations is None else self._implementations.get(key.algorithm.name)
        )
        if supplied is not None and isinstance(material(key), bytes):
            return supplied
        return key.algorithm.implementation

    def _gcm(
        self, method: Method, key: Key[Any], data: bytes, nonce: bytes, aad: bytes | None
    ) -> Effect[bytes, CryptoError]:
        params = Params(
            name="AES-GCM",
            iv=nonce,
            tag_length=128,
            additional_data=None if aad is None else bytes(aad),
        )

        def run(subtle: SubtleCrypto) -> bytes:
            crypto_key = self._crypto_key_for(subtle, key)
            operation = subtle.encrypt if method == "encrypt" else subtle.decrypt
            return bytes(operation(params, crypto_key, data))

        return _web.run(
            "Aead",
            method,
            key.algorithm.name,
            self._crypto,
            run,
            lambda cause: _web.web_crypto_error(
                "Aead",
                method,
                key.algorithm.name,
                cause,
                DecryptionFailed if method == "decrypt" else None,
            ),
        )

    def _run(
        self, method: Method, key: Key[Any], data: Binary, nonce: Binary, aad: Binary | None
    ) -> Effect[bytes, CryptoError]:
        def go() -> Effect[bytes, CryptoError]:
            # Read when the effect runs: it may run later than it is built.
            nonce_now, data_now = bytes(nonce), bytes(data)
            aad_now = None if aad is None else bytes(aad)
            failure = _check_arguments(method, key, data_now, nonce_now)
            if failure is not None:
                return failure
            implementation = self._implementation_for(key)
            if implementation is None:
                return self._gcm(method, key, data_now, nonce_now, aad_now)
            return _run_implementation(method, implementation, key, data_now, nonce_now, aad_now)

        return suspend(go)

    def encrypt(
        self, key: Key[Any], plaintext: Binary, *, nonce: Binary, aad: Binary | None = None
    ) -> Effect[bytes, CryptoError]:
        return self._run("encrypt", key, plaintext, nonce, aad)

    def decrypt(
        self, key: Key[Any], ciphertext: Binary, *, nonce: Binary, aad: Binary | None = None
    ) -> Effect[bytes, CryptoError]:
        return self._run("decrypt", key, ciphertext, nonce, aad)


def layer_web_crypto_with(
    *, implementations: dict[Name, Implementation] | None = None
) -> Layer[Aead, Never, SecureRandom]:
    """``layer_web_crypto``, running ``implementations`` (by algorithm name)
    for byte-backed keys; ``CryptoKey``-backed keys stay on ``subtle``."""

    @gen
    def build():
        random = yield from SecureRandom()
        crypto = yield from WebCrypto()
        service: AeadService = _WebCryptoAead(random, crypto, implementations)
        return service

    return layer_effect(Aead, build)


layer_web_crypto: Layer[Aead, Never, SecureRandom] = layer_web_crypto_with()
"""AES-GCM on the ``WebCrypto`` reference, ChaCha in the process."""


def key[A: Algorithm](algorithm: A, data: Binary) -> Effect[Key[A], CryptoError]:
    """A key holding a copy of ``data``, which must be the algorithm's key
    length."""
    return _key.from_bytes(
        lambda copied: Key(algorithm, copied),
        "Aead",
        "key",
        data,
        _key.check_key_length(algorithm.name, algorithm.key_length),
    )


def from_crypto_key[A: AesGcm](algorithm: A, crypto_key: CryptoKey) -> Effect[Key[A], CryptoError]:
    """A key backed by an AES-GCM ``CryptoKey`` of the algorithm's size,
    with both the ``encrypt`` and ``decrypt`` usages."""
    if algorithm.implementation is not None:
        return _web.invalid_key(
            "Aead", "fromCryptoKey", f"{algorithm.name} keys cannot be CryptoKeys"
        )
    return _key.from_crypto_key(
        Key,
        "Aead",
        "fromCryptoKey",
        algorithm,
        crypto_key,
        _key.ExpectedCryptoKey(
            type="secret",
            name="AES-GCM",
            usages=("encrypt", "decrypt"),
            usage_policy="all",
            check=_key.check_aes_length("AES-GCM", algorithm.key_length),
        ),
    )


def to_bytes(key: Key[Any]) -> Effect[bytes, CryptoError]:
    """A copy of the key's bytes; ``NotExtractable`` for a non-extractable
    ``CryptoKey``."""
    return _key.to_bytes("Aead", key, _key.export_raw)


__all__ = [
    "Aead",
    "AeadService",
    "AesGcm",
    "Algorithm",
    "CryptoError",
    "Implementation",
    "Key",
    "Name",
    "aes128_gcm",
    "aes256_gcm",
    "chacha20_poly1305",
    "from_crypto_key",
    "is_key",
    "key",
    "layer_web_crypto",
    "layer_web_crypto_with",
    "to_bytes",
    "xchacha20_poly1305",
]
