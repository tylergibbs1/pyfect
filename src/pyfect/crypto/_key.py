"""The opaque keys of the ``pyfect.crypto`` families (Effect's
``crypto/internal/key.ts``): each holds its algorithm and either its bytes
or a ``CryptoKey``, shows only the algorithm, and equals only itself."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import weakref
from collections.abc import Callable, Sequence
from dataclasses import dataclass, replace
from typing import Any, ClassVar, Generic, Literal, Protocol, TypeVar, cast

from pyfect._core import Effect
from pyfect._json_text import stringify
from pyfect.crypto import _web
from pyfect.crypto.crypto_error import CryptoError
from pyfect.crypto.web_crypto import CryptoKey, KeyAlgorithm, KeyType, KeyUsage, SubtleCrypto
from pyfect.effect import succeed, suspend

type Binary = bytes | bytearray | memoryview
type Material = bytes | CryptoKey


class Named(Protocol):
    @property
    def name(self) -> str: ...


# Invariant, as Effect's ``NoInfer``: a key pair's algorithm is solved from
# one key, so keys of two curves cannot meet in one call.
A = TypeVar("A", bound=Named)


class KeyBase(Generic[A]):
    """A key of one family: its ``algorithm`` and hidden material."""

    __slots__ = ("__weakref__", "_algorithm", "_material")

    label: ClassVar[str]

    def __init__(self, algorithm: A, material: Material) -> None:
        self._algorithm = algorithm
        self._material = material

    @property
    def algorithm(self) -> A:
        return self._algorithm

    def to_json(self) -> dict[str, str]:
        """``{"_id": label, "algorithm": name}``, never the key material."""
        return {"_id": self.label, "algorithm": self.algorithm.name}

    def __repr__(self) -> str:
        return stringify(self.to_json())

    __str__ = __repr__

    def __reduce__(self) -> Any:
        raise TypeError(f"{self.label} values cannot be pickled; encode them with key_format")


def material(key: KeyBase[Any]) -> Material:
    return key._material


def is_bytes(data: object) -> bool:
    return isinstance(data, (bytes, bytearray, memoryview))


def check_key_length(name: str, key_length: int) -> Callable[[bytes], str | None]:
    def check(data: bytes) -> str | None:
        if len(data) == key_length:
            return None
        return f"Expected a {key_length}-byte key for {name}, not {len(data)} bytes"

    return check


def from_bytes[K](
    build: Callable[[bytes], K],
    module: str,
    method: str,
    data: Binary,
    check: Callable[[bytes], str | None],
) -> Effect[K, CryptoError]:
    """A key from a copy of ``data``, when ``check`` finds no problem."""

    def go() -> Effect[K, CryptoError]:
        if not is_bytes(data):
            return _web.invalid_key(module, method, "Expected the key as bytes")
        copied = bytes(data)
        problem = check(copied)
        return (
            succeed(build(copied)) if problem is None else _web.invalid_key(module, method, problem)
        )

    return suspend(go)


@dataclass(frozen=True, slots=True)
class ExpectedCryptoKey:
    type: KeyType
    name: str
    usages: Sequence[KeyUsage]
    usage_policy: Literal["all", "any"]
    check: Callable[[KeyAlgorithm], str | None] | None = None


def check_aes_length(name: str, key_length: int) -> Callable[[KeyAlgorithm], str | None]:
    def check(algorithm: KeyAlgorithm) -> str | None:
        length = algorithm.length
        if length == key_length * 8:
            return None
        return f"Expected a {key_length * 8}-bit {name} key, not {length} bits"

    return check


def _check_crypto_key(crypto_key: object, expected: ExpectedCryptoKey) -> str | None:  # noqa: PLR0911
    if not isinstance(crypto_key, CryptoKey):
        return "Expected a CryptoKey"
    if crypto_key.algorithm.name != expected.name:
        return f"Expected a {expected.name} key, not {crypto_key.algorithm.name}"
    if crypto_key.type != expected.type:
        return f"Expected a {expected.type} key, not {crypto_key.type}"
    if expected.check is not None and (problem := expected.check(crypto_key.algorithm)):
        return problem
    usages = crypto_key.usages
    if expected.usage_policy == "all":
        if not all(usage in usages for usage in expected.usages):
            return (
                f"Expected a key with the usages {' and '.join(expected.usages)}, "
                f"not {', '.join(usages) or 'none'}"
            )
    elif not any(usage in usages for usage in expected.usages):
        return f"Expected a key with one of the usages {', '.join(expected.usages)}"
    return None


def imported_algorithm[A](algorithm: A, crypto_key: CryptoKey) -> A:
    """``algorithm`` with an RSA ``CryptoKey``'s real modulus length."""
    modulus_length = crypto_key.algorithm.modulus_length
    current = getattr(algorithm, "modulus_length", None)
    if current is None or modulus_length is None or current == modulus_length:
        return algorithm
    updated: A = replace(cast("Any", algorithm), modulus_length=modulus_length)
    return updated


def from_crypto_key[A, K](  # noqa: PLR0917
    build: Callable[[A, CryptoKey], K],
    module: str,
    method: str,
    algorithm: A,
    crypto_key: CryptoKey,
    expected: ExpectedCryptoKey,
) -> Effect[K, CryptoError]:
    def go() -> Effect[K, CryptoError]:
        problem = _check_crypto_key(crypto_key, expected)
        if problem is not None:
            return _web.invalid_key(module, method, problem)
        return succeed(build(imported_algorithm(algorithm, crypto_key), crypto_key))

    return suspend(go)


def export_raw(subtle: SubtleCrypto, crypto_key: CryptoKey) -> bytes:
    return bytes(subtle.export_key("raw", crypto_key))


def to_bytes(
    module: str,
    key: KeyBase[Any],
    export: Callable[[SubtleCrypto, CryptoKey], bytes],
) -> Effect[bytes, CryptoError]:
    """A copy of the key's bytes, exported from its ``CryptoKey`` if it has
    one (``NotExtractable`` when that is not extractable)."""

    def go() -> Effect[bytes, CryptoError]:
        stored = material(key)
        if isinstance(stored, bytes):
            return succeed(stored)
        if not stored.extractable:
            return _web.not_extractable(module, "toBytes")
        return _web.run_with_reference(
            module, "toBytes", key.algorithm.name, lambda subtle: export(subtle, stored)
        )

    return suspend(go)


def make_cache(
    import_key: Callable[[SubtleCrypto, bytes, Any], CryptoKey],
) -> Callable[[SubtleCrypto, KeyBase[Any]], CryptoKey]:
    """A byte-backed key's ``CryptoKey``, imported once per key."""
    cache: weakref.WeakKeyDictionary[KeyBase[Any], CryptoKey] = weakref.WeakKeyDictionary()

    def crypto_key_for(subtle: SubtleCrypto, key: KeyBase[Any]) -> CryptoKey:
        stored = material(key)
        if isinstance(stored, CryptoKey):
            return stored
        found = cache.get(key)
        if found is None:
            found = import_key(subtle, stored, key.algorithm)
            cache[key] = found
        return found

    return crypto_key_for
