"""Key wrapping as a service (Effect's ``effect/crypto/KeyWrap``)::

    key_wrap = yield from KeyWrap()
    kek = yield from key_wrap.generate_key(aes256_kw)
    wrapped = yield from key_wrap.wrap(kek, data_key)
    restored = yield from key_wrap.unwrap(kek, aead.aes256_gcm, wrapped)

AES-KW (RFC 3394) wraps with a secret key; RSA-OAEP wraps with a public
key and unwraps with the private one. Any secret key of ``mac``, ``aead``,
``cipher`` or this module can be wrapped; ``unwrap`` gives a key of the
algorithm asked for. A wrapped key that fails to unwrap fails with
``DecryptionFailed``.
"""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, ClassVar, Literal, Never, Protocol, final, overload

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.crypto import _asymmetric, _key, _web, aead, cipher, mac
from pyfect.crypto._asymmetric import Family, Spec
from pyfect.crypto._key import Binary, KeyBase, material
from pyfect.crypto.crypto_error import CryptoError, DecryptionFailed, InvalidArgument
from pyfect.crypto.digest import Algorithm as DigestAlgorithm
from pyfect.crypto.digest import name_suffix, sha1, sha256
from pyfect.crypto.secure_random import SecureRandom, SecureRandomService
from pyfect.crypto.web_crypto import Crypto, CryptoKey, Params, SubtleCrypto, WebCrypto
from pyfect.effect import gen, suspend
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect


@dataclass(frozen=True, kw_only=True)
class AesKw:
    name: Literal["aes128Kw", "aes256Kw"]
    key_length: Literal[16, 32]

    tag: ClassVar[Literal["AesKw"]] = "AesKw"


@dataclass(frozen=True, kw_only=True)
class RsaOaep:
    name: str
    hash: DigestAlgorithm
    modulus_length: int

    tag: ClassVar[Literal["RsaOaep"]] = "RsaOaep"


type Algorithm = AesKw | RsaOaep

aes128_kw = AesKw(name="aes128Kw", key_length=16)
aes256_kw = AesKw(name="aes256Kw", key_length=32)


def rsa_oaep(*, hash: DigestAlgorithm, modulus_length: int) -> RsaOaep:
    return RsaOaep(name=f"rsaOaep{name_suffix(hash)}", hash=hash, modulus_length=modulus_length)


rsa_oaep_sha256 = rsa_oaep(hash=sha256, modulus_length=3072)
rsa_oaep_sha1 = rsa_oaep(hash=sha1, modulus_length=3072)
"""RSA-OAEP with SHA-1, for protocols that require it (JWE ``RSA-OAEP``)."""


@final
class Key[A: AesKw = AesKw](KeyBase[A]):
    """An AES-KW key-encryption key."""

    __slots__ = ()
    label: ClassVar[str] = "KeyWrap.Key"


@final
class PrivateKey[A: RsaOaep = RsaOaep](KeyBase[A]):
    """An RSA-OAEP unwrapping key."""

    __slots__ = ()
    label: ClassVar[str] = "KeyWrap.PrivateKey"


@final
class PublicKey[A: RsaOaep = RsaOaep](KeyBase[A]):
    """An RSA-OAEP wrapping key."""

    __slots__ = ()
    label: ClassVar[str] = "KeyWrap.PublicKey"


@dataclass(frozen=True, slots=True)
class KeyPair[A: RsaOaep = RsaOaep]:
    private_key: PrivateKey[A]
    public_key: PublicKey[A]


type WrapKey = Key[Any] | PublicKey[Any]
type UnwrapKey = Key[Any] | PrivateKey[Any]
type SecretAlgorithm = mac.Algorithm | aead.Algorithm | cipher.Algorithm | AesKw
type SecretKey = mac.Key[Any] | aead.Key[Any] | cipher.Key[Any] | Key[Any]


def is_key(u: object) -> bool:
    return isinstance(u, Key)


def is_private_key(u: object) -> bool:
    return isinstance(u, PrivateKey)


def is_public_key(u: object) -> bool:
    return isinstance(u, PublicKey)


def _spec_of(algorithm: RsaOaep) -> Spec:
    return Spec(
        "RSA-OAEP",
        Params(name="RSA-OAEP", hash=algorithm.hash.name),
        ("decrypt",),
        ("encrypt",),
        None,
        "spki",
        _asymmetric.check_hash(algorithm.hash.name),
    )


family = Family(
    module="KeyWrap",
    spec_of=_spec_of,
    private_key=PrivateKey,
    public_key=PublicKey,
    is_private_key=is_private_key,
)


def secret_key(algorithm: SecretAlgorithm, data: Binary) -> Effect[SecretKey, CryptoError]:
    """A secret key of ``algorithm``'s family from its bytes."""
    match algorithm:
        case aead.Algorithm():
            return aead.key(algorithm, data)
        case cipher.Algorithm():
            return cipher.key(algorithm, data)
        case AesKw():
            return key(algorithm, data)
        case mac.Algorithm():
            return mac.key(algorithm, data)


def secret_to_bytes(secret: SecretKey) -> Effect[bytes, CryptoError]:
    """A secret key's bytes, through its own family."""
    match secret:
        case aead.Key():
            return aead.to_bytes(secret)
        case cipher.Key():
            return cipher.to_bytes(secret)
        case Key():
            return to_bytes(secret)
        case mac.Key():
            return mac.to_bytes(secret)


# AES-KW in Web Crypto only wraps ``CryptoKey``s, so the key bytes go
# through a temporary extractable HMAC key, which imports any non-empty
# length.
_HMAC_PARAMS = Params(name="HMAC", hash="SHA-256")
_RSA_OAEP_PARAMS = Params(name="RSA-OAEP")


def _invalid_argument(description: str) -> _web.Failure:
    return _web.Failure(InvalidArgument(description=description))


def _check_oaep_length(algorithm: RsaOaep, crypto_key: CryptoKey, length: int) -> None:
    # RFC 8017, section 7.1.1: the message fits the modulus minus two hashes
    # and two bytes.
    modulus_length = crypto_key.algorithm.modulus_length or 0
    maximum = math.ceil(modulus_length / 8) - 2 * algorithm.hash.output_length - 2
    if length > maximum:
        raise _invalid_argument(
            f"A {modulus_length}-bit RSA-OAEP key with {algorithm.hash.name} wraps at most "
            f"{maximum} bytes, not {length}"
        )


def _check_kw_length(length: int, overhead: int) -> None:
    # RFC 3394, section 2: keys are at least two 64-bit blocks, and the
    # wrapped form adds one block.
    if length % 8 != 0 or length < 16 + overhead:
        raise _invalid_argument(
            f"AES-KW needs a multiple of 8 bytes and at least {16 + overhead} bytes, not {length}"
        )


class KeyWrapService(Protocol):
    def generate_key[A: AesKw](self, algorithm: A) -> Effect[Key[A], CryptoError]: ...

    def generate_key_pair[A: RsaOaep](self, algorithm: A) -> Effect[KeyPair[A], CryptoError]: ...

    def wrap(self, wrap_key: WrapKey, key: SecretKey) -> Effect[bytes, CryptoError]: ...

    @overload
    def unwrap[A: aead.Algorithm](
        self, unwrap_key: UnwrapKey, algorithm: A, wrapped: Binary
    ) -> Effect[aead.Key[A], CryptoError]: ...
    @overload
    def unwrap[A: cipher.Algorithm](
        self, unwrap_key: UnwrapKey, algorithm: A, wrapped: Binary
    ) -> Effect[cipher.Key[A], CryptoError]: ...
    @overload
    def unwrap[A: mac.Algorithm](
        self, unwrap_key: UnwrapKey, algorithm: A, wrapped: Binary
    ) -> Effect[mac.Key[A], CryptoError]: ...
    @overload
    def unwrap[A: AesKw](
        self, unwrap_key: UnwrapKey, algorithm: A, wrapped: Binary
    ) -> Effect[Key[A], CryptoError]: ...
    def unwrap(
        self, unwrap_key: UnwrapKey, algorithm: SecretAlgorithm, wrapped: Binary
    ) -> Effect[Any, CryptoError]:
        """A key of ``algorithm`` from ``wrapped``; ``DecryptionFailed``
        when it does not unwrap."""
        ...


class KeyWrap(Tag[KeyWrapService], key="effect/crypto/KeyWrap"):
    """Wrapping secret keys under other keys."""


class _WebCryptoKeyWrap:
    __slots__ = ("_caches", "_crypto", "_kw_crypto_key", "_random")

    def __init__(self, random: SecureRandomService, crypto: Crypto) -> None:
        self._random = random
        self._crypto = crypto
        self._kw_crypto_key = _key.make_cache(
            lambda subtle, data, _algorithm: subtle.import_key(
                "raw", data, "AES-KW", False, ["wrapKey", "unwrapKey"]
            )
        )
        self._caches = _asymmetric.make_caches(family)

    def generate_key[A: AesKw](self, algorithm: A) -> Effect[Key[A], CryptoError]:
        return self._random.random_bytes(algorithm.key_length).map(
            lambda data: Key(algorithm, data)
        )

    def generate_key_pair[A: RsaOaep](self, algorithm: A) -> Effect[KeyPair[A], CryptoError]:
        return _asymmetric.generate_key_pair(
            family,
            self._crypto,
            self._random,
            algorithm,
            _asymmetric.rsa_generate_params(_spec_of(algorithm), algorithm.modulus_length),
            KeyPair,
        )

    def _wrap_bytes(self, wrap_key: WrapKey, data: bytes) -> Effect[bytes, CryptoError]:
        def run(subtle: SubtleCrypto) -> bytes:
            if isinstance(wrap_key, Key):
                _check_kw_length(len(data), 0)
                kek = self._kw_crypto_key(subtle, wrap_key)
                target = subtle.import_key("raw", data, _HMAC_PARAMS, True, ["sign"])
                return bytes(subtle.wrap_key("raw", target, kek, "AES-KW"))
            public_key = self._caches.public_key(subtle, wrap_key)
            _check_oaep_length(wrap_key.algorithm, public_key, len(data))
            if "encrypt" in public_key.usages:
                return bytes(subtle.encrypt(_RSA_OAEP_PARAMS, public_key, data))
            target = subtle.import_key("raw", data, _HMAC_PARAMS, True, ["sign"])
            return bytes(subtle.wrap_key("raw", target, public_key, _RSA_OAEP_PARAMS))

        return _web.run("KeyWrap", "wrap", wrap_key.algorithm.name, self._crypto, run)

    def _unwrap_bytes(self, unwrap_key: UnwrapKey, wrapped: bytes) -> Effect[bytes, CryptoError]:
        def run(subtle: SubtleCrypto) -> bytes:
            if isinstance(unwrap_key, Key):
                _check_kw_length(len(wrapped), 8)
                kek = self._kw_crypto_key(subtle, unwrap_key)
                target = subtle.unwrap_key(
                    "raw", wrapped, kek, "AES-KW", _HMAC_PARAMS, True, ["sign"]
                )
                return _key.export_raw(subtle, target)
            private_key = self._caches.private_key(subtle, unwrap_key)
            if "decrypt" in private_key.usages:
                return bytes(subtle.decrypt(_RSA_OAEP_PARAMS, private_key, wrapped))
            target = subtle.unwrap_key(
                "raw", wrapped, private_key, _RSA_OAEP_PARAMS, _HMAC_PARAMS, True, ["sign"]
            )
            return _key.export_raw(subtle, target)

        return _web.run(
            "KeyWrap",
            "unwrap",
            unwrap_key.algorithm.name,
            self._crypto,
            run,
            lambda cause: _web.web_crypto_error(
                "KeyWrap", "unwrap", unwrap_key.algorithm.name, cause, DecryptionFailed
            ),
        )

    def wrap(self, wrap_key: WrapKey, key: SecretKey) -> Effect[bytes, CryptoError]:
        def go() -> Effect[bytes, CryptoError]:
            stored = material(key)
            if isinstance(stored, CryptoKey) and not stored.extractable:
                return _web.not_extractable("KeyWrap", "wrap")
            return (
                secret_to_bytes(key)
                .catch_all(_web.rehome("KeyWrap", "wrap"))
                .flat_map(lambda data: self._wrap_bytes(wrap_key, data))
            )

        return suspend(go)

    @overload
    def unwrap[A: aead.Algorithm](
        self, unwrap_key: UnwrapKey, algorithm: A, wrapped: Binary
    ) -> Effect[aead.Key[A], CryptoError]: ...
    @overload
    def unwrap[A: cipher.Algorithm](
        self, unwrap_key: UnwrapKey, algorithm: A, wrapped: Binary
    ) -> Effect[cipher.Key[A], CryptoError]: ...
    @overload
    def unwrap[A: mac.Algorithm](
        self, unwrap_key: UnwrapKey, algorithm: A, wrapped: Binary
    ) -> Effect[mac.Key[A], CryptoError]: ...
    @overload
    def unwrap[A: AesKw](
        self, unwrap_key: UnwrapKey, algorithm: A, wrapped: Binary
    ) -> Effect[Key[A], CryptoError]: ...
    def unwrap(
        self, unwrap_key: UnwrapKey, algorithm: SecretAlgorithm, wrapped: Binary
    ) -> Effect[Any, CryptoError]:
        return self._unwrap_bytes(unwrap_key, bytes(wrapped)).flat_map(
            lambda data: secret_key(algorithm, data).catch_all(_web.rehome("KeyWrap", "unwrap"))
        )


@gen
def _build():
    random = yield from SecureRandom()
    crypto = yield from WebCrypto()
    service: KeyWrapService = _WebCryptoKeyWrap(random, crypto)
    return service


layer_web_crypto: Layer[KeyWrap, Never, SecureRandom] = layer_effect(KeyWrap, _build)
"""AES-KW and RSA-OAEP on the ``WebCrypto`` reference."""


def key[A: AesKw](algorithm: A, data: Binary) -> Effect[Key[A], CryptoError]:
    """An AES-KW key holding a copy of ``data``, of the algorithm's length."""
    return _key.from_bytes(
        lambda copied: Key(algorithm, copied),
        "KeyWrap",
        "key",
        data,
        _key.check_key_length(algorithm.name, algorithm.key_length),
    )


def from_crypto_key[A: AesKw](algorithm: A, crypto_key: CryptoKey) -> Effect[Key[A], CryptoError]:
    return _key.from_crypto_key(
        Key,
        "KeyWrap",
        "fromCryptoKey",
        algorithm,
        crypto_key,
        _key.ExpectedCryptoKey(
            type="secret",
            name="AES-KW",
            usages=("wrapKey", "unwrapKey"),
            usage_policy="all",
            check=_key.check_aes_length("AES-KW", algorithm.key_length),
        ),
    )


def _rsa_from_crypto_key[A: RsaOaep, K](
    method: str,
    build: Callable[[A, CryptoKey], K],
    algorithm: A,
    role: _asymmetric.Role,
    crypto_key: CryptoKey,
) -> Effect[K, CryptoError]:
    # RSA-OAEP keys need one usage the layer can use for the key's role,
    # since ``wrapKey`` and ``encrypt`` produce the same ciphertext.
    return _key.from_crypto_key(
        build,
        "KeyWrap",
        method,
        algorithm,
        crypto_key,
        _key.ExpectedCryptoKey(
            type=role,
            name="RSA-OAEP",
            usages=("decrypt", "unwrapKey") if role == "private" else ("encrypt", "wrapKey"),
            usage_policy="any",
            check=_asymmetric.check_hash(algorithm.hash.name),
        ),
    )


def private_key_from_crypto_key[A: RsaOaep](
    algorithm: A, crypto_key: CryptoKey
) -> Effect[PrivateKey[A], CryptoError]:
    return _rsa_from_crypto_key(
        "privateKeyFromCryptoKey", PrivateKey, algorithm, "private", crypto_key
    )


def public_key_from_crypto_key[A: RsaOaep](
    algorithm: A, crypto_key: CryptoKey
) -> Effect[PublicKey[A], CryptoError]:
    return _rsa_from_crypto_key(
        "publicKeyFromCryptoKey", PublicKey, algorithm, "public", crypto_key
    )


def to_bytes(key: Key[Any] | PrivateKey[Any] | PublicKey[Any]) -> Effect[bytes, CryptoError]:
    if isinstance(key, Key):
        return _key.to_bytes("KeyWrap", key, _key.export_raw)
    return _asymmetric.to_bytes(family, key)


__all__ = [
    "AesKw",
    "Algorithm",
    "CryptoError",
    "Key",
    "KeyPair",
    "KeyWrap",
    "KeyWrapService",
    "PrivateKey",
    "PublicKey",
    "RsaOaep",
    "SecretAlgorithm",
    "SecretKey",
    "UnwrapKey",
    "WrapKey",
    "aes128_kw",
    "aes256_kw",
    "family",
    "from_crypto_key",
    "is_key",
    "is_private_key",
    "is_public_key",
    "key",
    "layer_web_crypto",
    "private_key_from_crypto_key",
    "public_key_from_crypto_key",
    "rsa_oaep",
    "rsa_oaep_sha1",
    "rsa_oaep_sha256",
    "secret_key",
    "secret_to_bytes",
    "to_bytes",
]
