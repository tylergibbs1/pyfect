"""The Web Crypto API the ``layer_web_crypto`` layers run on (Effect's
``effect/crypto/WebCrypto``).

``WebCrypto`` is a reference holding a ``Crypto``: ``get_random_values``
and a ``subtle`` (``SubtleCrypto``), as JavaScript's ``globalThis.crypto``.
Its default, ``host``, is pyfect's own: ``os.urandom``, ``hashlib`` and,
for keys, the ``cryptography`` package (the ``crypto`` extra), with Web
Crypto's key formats, usages and errors. ``layer(crypto)`` swaps it, for
a hardware-backed implementation or a test double.

A ``SubtleCrypto`` method fails by raising ``DOMException`` with Web
Crypto's ``name`` (``"DataError"``, ``"InvalidAccessError"``,
``"NotSupportedError"``, ``"OperationError"``); anything else it raises
is a defect.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import Literal, Never, Protocol, TypedDict, overload

from pyfect.context import Reference
from pyfect.layer import Layer
from pyfect.layer import succeed as layer_succeed

type KeyType = Literal["private", "public", "secret"]
type KeyUsage = Literal[
    "encrypt", "decrypt", "sign", "verify", "deriveKey", "deriveBits", "wrapKey", "unwrapKey"
]
type BinaryFormat = Literal["raw", "spki", "pkcs8"]
type KeyFormat = Literal["raw", "spki", "pkcs8", "jwk"]


class DOMException(Exception):
    """A Web Crypto failure; ``name`` is its kind (``"DataError"``,
    ``"OperationError"``, ...)."""

    def __init__(self, message: str = "", name: str = "Error") -> None:
        super().__init__(message)
        self.name = name


class OtherPrime(TypedDict, total=False):
    r: str
    d: str
    t: str


class JsonWebKey(TypedDict, total=False):
    """A JSON Web Key as Web Crypto reads and writes it (RFC 7517)."""

    alg: str
    crv: str
    d: str
    dp: str
    dq: str
    e: str
    ext: bool
    k: str
    key_ops: list[str]
    kty: str
    n: str
    oth: list[OtherPrime]
    p: str
    q: str
    qi: str
    use: str
    x: str
    y: str


@dataclass(frozen=True, kw_only=True)
class KeyAlgorithm:
    """A ``CryptoKey``'s algorithm: its ``name`` and the members the name
    has (an AES ``length`` in bits, an HMAC or RSA ``hash``, an EC
    ``named_curve``, an RSA ``modulus_length`` and ``public_exponent``)."""

    name: str
    length: int | None = None
    hash: str | None = None
    named_curve: str | None = None
    modulus_length: int | None = None
    public_exponent: bytes | None = None


class CryptoKey:
    """A key held by a ``SubtleCrypto``. ``handle`` is that implementation's
    own representation; nothing else reads it."""

    __slots__ = ("algorithm", "extractable", "handle", "type", "usages")

    def __init__(
        self,
        *,
        algorithm: KeyAlgorithm,
        extractable: bool,
        type: KeyType,
        usages: Sequence[KeyUsage],
        handle: object = None,
    ) -> None:
        self.algorithm = algorithm
        self.extractable = extractable
        self.type: KeyType = type
        self.usages: tuple[KeyUsage, ...] = tuple(usages)
        self.handle = handle

    def __repr__(self) -> str:
        return (
            f"CryptoKey(type={self.type!r}, algorithm={self.algorithm.name!r}, "
            f"extractable={self.extractable}, usages={list(self.usages)!r})"
        )


@dataclass(frozen=True, slots=True)
class CryptoKeyPair:
    private_key: CryptoKey
    public_key: CryptoKey


@dataclass(frozen=True, kw_only=True)
class Params:
    """An algorithm and its parameters, as Web Crypto's algorithm
    dictionaries: ``Params(name="AES-GCM", iv=nonce)``. A method also takes
    the bare name."""

    name: str
    hash: str | None = None
    named_curve: str | None = None
    length: int | None = None
    iv: bytes | None = None
    additional_data: bytes | None = None
    tag_length: int | None = None
    counter: bytes | None = None
    salt: bytes | None = None
    info: bytes | None = None
    iterations: int | None = None
    salt_length: int | None = None
    public: CryptoKey | None = None
    modulus_length: int | None = None
    public_exponent: bytes | None = None
    label: bytes | None = None


type AlgorithmIdentifier = str | Params


class SubtleCrypto(Protocol):
    """Web Crypto's ``SubtleCrypto``, synchronous."""

    def digest(self, algorithm: AlgorithmIdentifier, data: bytes) -> bytes: ...

    def import_key(
        self,
        format: KeyFormat,
        key_data: bytes | JsonWebKey,
        algorithm: AlgorithmIdentifier,
        extractable: bool,
        usages: Sequence[KeyUsage],
    ) -> CryptoKey: ...

    @overload
    def export_key(self, format: BinaryFormat, key: CryptoKey) -> bytes: ...
    @overload
    def export_key(self, format: Literal["jwk"], key: CryptoKey) -> JsonWebKey: ...
    def export_key(self, format: KeyFormat, key: CryptoKey) -> bytes | JsonWebKey: ...

    def generate_key(
        self, algorithm: AlgorithmIdentifier, extractable: bool, usages: Sequence[KeyUsage]
    ) -> CryptoKey | CryptoKeyPair: ...

    def encrypt(self, algorithm: AlgorithmIdentifier, key: CryptoKey, data: bytes) -> bytes: ...

    def decrypt(self, algorithm: AlgorithmIdentifier, key: CryptoKey, data: bytes) -> bytes: ...

    def sign(self, algorithm: AlgorithmIdentifier, key: CryptoKey, data: bytes) -> bytes: ...

    def verify(
        self, algorithm: AlgorithmIdentifier, key: CryptoKey, signature: bytes, data: bytes
    ) -> bool: ...

    def derive_bits(
        self, algorithm: AlgorithmIdentifier, base_key: CryptoKey, length: int | None
    ) -> bytes: ...

    def wrap_key(
        self,
        format: KeyFormat,
        key: CryptoKey,
        wrapping_key: CryptoKey,
        wrap_algorithm: AlgorithmIdentifier,
    ) -> bytes: ...

    def unwrap_key(  # noqa: PLR0917
        self,
        format: KeyFormat,
        wrapped_key: bytes,
        unwrapping_key: CryptoKey,
        unwrap_algorithm: AlgorithmIdentifier,
        unwrapped_key_algorithm: AlgorithmIdentifier,
        extractable: bool,
        usages: Sequence[KeyUsage],
    ) -> CryptoKey: ...


class Crypto(Protocol):
    """JavaScript's ``globalThis.crypto``: ``subtle`` is ``None`` where
    there is none (as in a browser's insecure context)."""

    @property
    def subtle(self) -> SubtleCrypto | None: ...

    def get_random_values(self, array: memoryview, /) -> memoryview:
        """Fill ``array`` with secure random bytes and return it. At most
        65,536 bytes per call, as in Web Crypto."""
        ...


def _host() -> Crypto:
    from pyfect.crypto._subtle import host

    return host


class WebCrypto(Reference[Crypto], key="effect/crypto/WebCrypto"):
    """The ``Crypto`` the ``layer_web_crypto`` layers run on; ``host`` by
    default."""

    @classmethod
    def default(cls) -> Crypto:
        return _host()


def layer(crypto: Crypto) -> Layer[Never]:
    """Run the ``layer_web_crypto`` layers built under it on ``crypto``."""
    return layer_succeed(WebCrypto, crypto)


__all__ = [
    "AlgorithmIdentifier",
    "BinaryFormat",
    "Crypto",
    "CryptoKey",
    "CryptoKeyPair",
    "DOMException",
    "JsonWebKey",
    "KeyAlgorithm",
    "KeyFormat",
    "KeyType",
    "KeyUsage",
    "OtherPrime",
    "Params",
    "SubtleCrypto",
    "WebCrypto",
    "layer",
]
