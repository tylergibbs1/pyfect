"""Unauthenticated AES encryption as a service (Effect's
``effect/crypto/Cipher``)::

    cipher = yield from Cipher()
    encrypted = yield from cipher.encrypt(key, data, iv=iv)

AES-CTR counts with the whole 128-bit block and never fails to decrypt;
AES-CBC pads with PKCS#7 and fails every bad padding or length with the
same ``DecryptionFailed`` (distinguishable failures would be a padding
oracle). Prefer ``aead``: nothing here detects tampering.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Never, Protocol, final

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.crypto import _key, _web
from pyfect.crypto._key import Binary, KeyBase
from pyfect.crypto.crypto_error import CryptoError, DecryptionFailed, InvalidArgument
from pyfect.crypto.secure_random import SecureRandom, SecureRandomService
from pyfect.crypto.web_crypto import Crypto, CryptoKey, Params, SubtleCrypto, WebCrypto
from pyfect.effect import gen, suspend
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect

type Method = Literal["encrypt", "decrypt"]


@dataclass(frozen=True, kw_only=True)
class Algorithm:
    name: Literal["aes128Ctr", "aes256Ctr", "aes128Cbc", "aes256Cbc"]
    mode: Literal["AES-CTR", "AES-CBC"]
    key_length: Literal[16, 32]


aes128_ctr = Algorithm(name="aes128Ctr", mode="AES-CTR", key_length=16)
aes256_ctr = Algorithm(name="aes256Ctr", mode="AES-CTR", key_length=32)
aes128_cbc = Algorithm(name="aes128Cbc", mode="AES-CBC", key_length=16)
aes256_cbc = Algorithm(name="aes256Cbc", mode="AES-CBC", key_length=32)


@final
class Key[A: Algorithm = Algorithm](KeyBase[A]):
    """An AES key for ``algorithm``."""

    __slots__ = ()
    label: ClassVar[str] = "Cipher.Key"


def is_key(u: object) -> bool:
    return isinstance(u, Key)


class CipherService(Protocol):
    def generate_key[A: Algorithm](self, algorithm: A) -> Effect[Key[A], CryptoError]:
        """A key of random bytes from ``SecureRandom``."""
        ...

    def encrypt(
        self, key: Key[Any], plaintext: Binary, *, iv: Binary
    ) -> Effect[bytes, CryptoError]:
        """The ciphertext of ``plaintext`` under ``key`` and the 16-byte ``iv``."""
        ...

    def decrypt(
        self, key: Key[Any], ciphertext: Binary, *, iv: Binary
    ) -> Effect[bytes, CryptoError]:
        """The plaintext; AES-CBC fails a bad padding or length with
        ``DecryptionFailed``, AES-CTR never fails."""
        ...


class Cipher(Tag[CipherService], key="effect/crypto/Cipher"):
    """AES-CTR and AES-CBC encryption."""


_BLOCK_LENGTH = 16


def _params(algorithm: Algorithm, iv: bytes) -> Params:
    if algorithm.mode == "AES-CTR":
        return Params(name="AES-CTR", counter=iv, length=128)
    return Params(name="AES-CBC", iv=iv)


class _WebCryptoCipher:
    __slots__ = ("_crypto", "_crypto_key_for", "_random")

    def __init__(self, random: SecureRandomService, crypto: Crypto) -> None:
        self._random = random
        self._crypto = crypto
        self._crypto_key_for = _key.make_cache(
            lambda subtle, data, algorithm: subtle.import_key(
                "raw", data, algorithm.mode, False, ["encrypt", "decrypt"]
            )
        )

    def generate_key[A: Algorithm](self, algorithm: A) -> Effect[Key[A], CryptoError]:
        return self._random.random_bytes(algorithm.key_length).map(
            lambda data: Key(algorithm, data)
        )

    def _run(
        self, method: Method, key: Key[Any], data: Binary, iv: Binary
    ) -> Effect[bytes, CryptoError]:
        def go() -> Effect[bytes, CryptoError]:
            iv_now, data_now = bytes(iv), bytes(data)
            if len(iv_now) != _BLOCK_LENGTH:
                return _web.fail(
                    "Cipher",
                    method,
                    InvalidArgument(description="IVs must contain exactly 16 bytes"),
                )
            # Checked here, so a bad length is not reported unlike bad padding.
            cbc = key.algorithm.mode == "AES-CBC"
            if method == "decrypt" and cbc and (not data_now or len(data_now) % _BLOCK_LENGTH):
                return _web.fail("Cipher", method, DecryptionFailed())

            def run(subtle: SubtleCrypto) -> bytes:
                crypto_key = self._crypto_key_for(subtle, key)
                operation = subtle.encrypt if method == "encrypt" else subtle.decrypt
                return bytes(operation(_params(key.algorithm, iv_now), crypto_key, data_now))

            return _web.run(
                "Cipher",
                method,
                key.algorithm.name,
                self._crypto,
                run,
                lambda cause: _web.web_crypto_error(
                    "Cipher",
                    method,
                    key.algorithm.name,
                    cause,
                    DecryptionFailed if method == "decrypt" and cbc else None,
                ),
            )

        return suspend(go)

    def encrypt(
        self, key: Key[Any], plaintext: Binary, *, iv: Binary
    ) -> Effect[bytes, CryptoError]:
        return self._run("encrypt", key, plaintext, iv)

    def decrypt(
        self, key: Key[Any], ciphertext: Binary, *, iv: Binary
    ) -> Effect[bytes, CryptoError]:
        return self._run("decrypt", key, ciphertext, iv)


@gen
def _build():
    random = yield from SecureRandom()
    crypto = yield from WebCrypto()
    service: CipherService = _WebCryptoCipher(random, crypto)
    return service


layer_web_crypto: Layer[Cipher, Never, SecureRandom] = layer_effect(Cipher, _build)
"""AES-CTR and AES-CBC on the ``WebCrypto`` reference."""


def key[A: Algorithm](algorithm: A, data: Binary) -> Effect[Key[A], CryptoError]:
    """A key holding a copy of ``data``, which must be the algorithm's key
    length."""
    return _key.from_bytes(
        lambda copied: Key(algorithm, copied),
        "Cipher",
        "key",
        data,
        _key.check_key_length(algorithm.name, algorithm.key_length),
    )


def from_crypto_key[A: Algorithm](
    algorithm: A, crypto_key: CryptoKey
) -> Effect[Key[A], CryptoError]:
    """A key backed by a ``CryptoKey`` of the algorithm's mode and size,
    with both the ``encrypt`` and ``decrypt`` usages."""
    return _key.from_crypto_key(
        Key,
        "Cipher",
        "fromCryptoKey",
        algorithm,
        crypto_key,
        _key.ExpectedCryptoKey(
            type="secret",
            name=algorithm.mode,
            usages=("encrypt", "decrypt"),
            usage_policy="all",
            check=_key.check_aes_length(algorithm.mode, algorithm.key_length),
        ),
    )


def to_bytes(key: Key[Any]) -> Effect[bytes, CryptoError]:
    """A copy of the key's bytes; ``NotExtractable`` for a non-extractable
    ``CryptoKey``."""
    return _key.to_bytes("Cipher", key, _key.export_raw)


__all__ = [
    "Algorithm",
    "Cipher",
    "CipherService",
    "CryptoError",
    "Key",
    "aes128_cbc",
    "aes128_ctr",
    "aes256_cbc",
    "aes256_ctr",
    "from_crypto_key",
    "is_key",
    "key",
    "layer_web_crypto",
    "to_bytes",
]
