"""HMAC as a service (Effect's ``effect/crypto/Mac``)::

    mac = yield from Mac()
    key = yield from mac_module.key(hmac_sha256, secret)
    tag = yield from mac.sign(key, data)
    ok = yield from mac.verify(key, tag, data)

``verify`` compares in constant time and is ``False`` for a tag of
another length. A ``Key`` shows only its algorithm, equals only itself,
and gives its bytes back through ``to_bytes``.
"""

from __future__ import annotations

import hmac as std_hmac
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Never, final

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.crypto import _key, _web
from pyfect.crypto._key import Binary, KeyBase, material
from pyfect.crypto.crypto_error import CryptoError
from pyfect.crypto.digest import Algorithm as DigestAlgorithm
from pyfect.crypto.digest import Name as DigestName
from pyfect.crypto.digest import sha1, sha256, sha384, sha512
from pyfect.crypto.secure_random import SecureRandom
from pyfect.crypto.web_crypto import CryptoKey, KeyAlgorithm, Params, SubtleCrypto, WebCrypto
from pyfect.effect import gen, sync
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect


@dataclass(frozen=True, kw_only=True)
class Algorithm:
    name: Literal["hmacSha1", "hmacSha256", "hmacSha384", "hmacSha512"]
    hash: DigestAlgorithm


hmac_sha1 = Algorithm(name="hmacSha1", hash=sha1)
hmac_sha256 = Algorithm(name="hmacSha256", hash=sha256)
hmac_sha384 = Algorithm(name="hmacSha384", hash=sha384)
hmac_sha512 = Algorithm(name="hmacSha512", hash=sha512)


@final
class Key[A: Algorithm = Algorithm](KeyBase[A]):
    """An HMAC key for ``algorithm``."""

    __slots__ = ()
    label: ClassVar[str] = "Mac.Key"


def is_key(u: object) -> bool:
    return isinstance(u, Key)


# Generated keys have the hash's block size, as Web Crypto generates them.
_BLOCK_SIZES: dict[DigestName, int] = {
    "MD5": 64,
    "SHA-1": 64,
    "SHA-256": 64,
    "SHA-384": 128,
    "SHA-512": 128,
}


@dataclass(frozen=True, slots=True, kw_only=True)
class MacService:
    generate_key: Callable[[Algorithm], Effect[Key[Any], CryptoError]]
    sign: Callable[[Key[Any], Binary], Effect[bytes, CryptoError]]
    verify: Callable[[Key[Any], Binary, Binary], Effect[bool, CryptoError]]


class Mac(Tag[MacService], key="effect/crypto/Mac"):
    """HMAC signing and verification."""


type Hmac = Callable[[DigestName, bytes, bytes], bytes]
"""``hmac(hash_name, key, data)``: an in-process HMAC."""


def _import_params(algorithm: Algorithm) -> Params:
    return Params(name="HMAC", hash=algorithm.hash.name)


def layer_web_crypto_with(*, hmac: Hmac | None = None) -> Layer[Mac, Never, SecureRandom]:
    """``layer_web_crypto``, computing a byte-backed key's tags with
    ``hmac`` when given; ``CryptoKey``-backed keys stay on ``subtle``."""

    @gen
    def build():
        random = yield from SecureRandom()
        crypto = yield from WebCrypto()
        crypto_key_for = _key.make_cache(
            lambda subtle, data, algorithm: subtle.import_key(
                "raw", data, _import_params(algorithm), False, ["sign", "verify"]
            )
        )

        def tag_of(key: Key[Any]) -> Callable[[Binary], bytes] | None:
            stored = material(key)
            compute = hmac
            if compute is None or not isinstance(stored, bytes):
                return None
            return lambda data: bytes(compute(key.algorithm.hash.name, stored, bytes(data)))

        def generate_key(algorithm: Algorithm) -> Effect[Key[Any], CryptoError]:
            return random.random_bytes(_BLOCK_SIZES[algorithm.hash.name]).map(
                lambda data: Key(algorithm, data)
            )

        def sign(key: Key[Any], data: Binary) -> Effect[bytes, CryptoError]:
            compute = tag_of(key)
            if compute is not None:
                return sync(lambda: compute(data))

            def run(subtle: SubtleCrypto) -> bytes:
                return bytes(subtle.sign("HMAC", crypto_key_for(subtle, key), bytes(data)))

            return _web.run("Mac", "sign", key.algorithm.name, crypto, run)

        # Both paths compare tags in constant time and reject other lengths.
        def verify(key: Key[Any], tag: Binary, data: Binary) -> Effect[bool, CryptoError]:
            compute = tag_of(key)
            if compute is not None:
                return sync(lambda: timing_safe_equal(compute(data), tag))

            def run(subtle: SubtleCrypto) -> bool:
                return subtle.verify("HMAC", crypto_key_for(subtle, key), bytes(tag), bytes(data))

            return _web.run("Mac", "verify", key.algorithm.name, crypto, run)

        return MacService(generate_key=generate_key, sign=sign, verify=verify)

    return layer_effect(Mac, build)


layer_web_crypto: Layer[Mac, Never, SecureRandom] = layer_web_crypto_with()
"""HMAC on the ``WebCrypto`` reference; keys generated from ``SecureRandom``."""


def key[A: Algorithm](algorithm: A, data: Binary) -> Effect[Key[A], CryptoError]:
    """A key holding a copy of ``data``, which cannot be empty."""
    return _key.from_bytes(
        lambda copied: Key(algorithm, copied),
        "Mac",
        "key",
        data,
        lambda copied: "An HMAC key cannot be empty" if not copied else None,
    )


def from_crypto_key[A: Algorithm](
    algorithm: A, crypto_key: CryptoKey
) -> Effect[Key[A], CryptoError]:
    """A key backed by an HMAC ``CryptoKey`` for ``algorithm``'s hash, with
    both the ``sign`` and ``verify`` usages."""

    def check(key_algorithm: KeyAlgorithm) -> str | None:
        hash_name = key_algorithm.hash
        if hash_name == algorithm.hash.name:
            return None
        return f"Expected an HMAC key for {algorithm.hash.name}, not {hash_name}"

    return _key.from_crypto_key(
        Key,
        "Mac",
        "fromCryptoKey",
        algorithm,
        crypto_key,
        _key.ExpectedCryptoKey(
            type="secret", name="HMAC", usages=("sign", "verify"), usage_policy="all", check=check
        ),
    )


def to_bytes(key: Key[Any]) -> Effect[bytes, CryptoError]:
    """A copy of the key's bytes; ``NotExtractable`` for a non-extractable
    ``CryptoKey``."""
    return _key.to_bytes("Mac", key, _key.export_raw)


def timing_safe_equal(a: Binary, b: Binary) -> bool:
    """Whether ``a`` and ``b`` are equal, compared in constant time;
    ``False`` for different lengths."""
    left, right = bytes(a), bytes(b)
    if len(left) != len(right):
        return False
    return std_hmac.compare_digest(left, right)


__all__ = [
    "Algorithm",
    "CryptoError",
    "Hmac",
    "Key",
    "Mac",
    "MacService",
    "from_crypto_key",
    "hmac_sha1",
    "hmac_sha256",
    "hmac_sha384",
    "hmac_sha512",
    "is_key",
    "key",
    "layer_web_crypto",
    "layer_web_crypto_with",
    "timing_safe_equal",
    "to_bytes",
]
