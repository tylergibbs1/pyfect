"""What the key-pair families share (Effect's
``crypto/internal/asymmetric.ts``): how each algorithm imports and exports
on Web Crypto, and generating, deriving and exporting key pairs.

Stored forms: an Ed25519 or X25519 private key is its 32-byte seed and its
public key the raw 32 bytes; an EC public key is the uncompressed SEC1
point and its private key PKCS#8; RSA keys are SPKI and PKCS#8."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Final, Literal

from pyfect._core import Effect
from pyfect.crypto import _key, _web
from pyfect.crypto._key import KeyBase, material
from pyfect.crypto.crypto_error import CryptoError, InvalidKey, Unsupported
from pyfect.crypto.secure_random import SecureRandomService
from pyfect.crypto.web_crypto import (
    Crypto,
    CryptoKey,
    CryptoKeyPair,
    JsonWebKey,
    KeyAlgorithm,
    KeyUsage,
    Params,
    SubtleCrypto,
)
from pyfect.effect import succeed, suspend

type Role = Literal["private", "public"]
type Curve = Literal["P-256", "P-384", "P-521"]

COORDINATE_SIZES: Final[dict[Curve, int]] = {"P-256": 32, "P-384": 48, "P-521": 66}


@dataclass(frozen=True, slots=True)
class Spec:
    """How an algorithm runs on Web Crypto."""

    name: str
    import_params: Params
    private_usages: Sequence[KeyUsage]
    public_usages: Sequence[KeyUsage]
    seed_prefix: bytes | None
    public_format: Literal["raw", "spki"]
    check: Callable[[KeyAlgorithm], str | None] | None = None


@dataclass(frozen=True, slots=True)
class Family:
    """A key-pair family: its module name, specs and key classes."""

    module: str
    spec_of: Callable[[Any], Spec]
    private_key: Callable[[Any, _key.Material], KeyBase[Any]]
    public_key: Callable[[Any, _key.Material], KeyBase[Any]]
    is_private_key: Callable[[object], bool]


def _seed_prefix(oid: int) -> bytes:
    # RFC 8410: the PKCS#8 encoding of a 32-byte Ed25519 or X25519 private
    # key is this prefix, ending in the algorithm's OID byte, then the key.
    return bytes([48, 46, 2, 1, 0, 48, 5, 6, 3, 43, 101, oid, 4, 34, 4, 32])


ED25519_PREFIX: Final = _seed_prefix(112)
X25519_PREFIX: Final = _seed_prefix(110)
SEED_LENGTH: Final = 32


def check_seed_length(name: str, role: Role) -> Callable[[bytes], str | None]:
    def check(data: bytes) -> str | None:
        if len(data) == SEED_LENGTH:
            return None
        if role == "private" and len(data) == 64:
            return (
                f"Expected the 32-byte {name} seed, not the 64-byte seed‖public key form: "
                "pass its first 32 bytes"
            )
        return f"Expected a {SEED_LENGTH}-byte {name} {role} key, not {len(data)} bytes"

    return check


def check_point(curve: Curve) -> Callable[[bytes], str | None]:
    def check(data: bytes) -> str | None:
        length = 1 + 2 * COORDINATE_SIZES[curve]
        if len(data) != length:
            return f"Expected a {length}-byte uncompressed {curve} point, not {len(data)} bytes"
        return (
            None if data[0] == 4 else f"Expected an uncompressed {curve} point, starting with 0x04"
        )

    return check


def check_named_curve(curve: Curve) -> Callable[[KeyAlgorithm], str | None]:
    def check(algorithm: KeyAlgorithm) -> str | None:
        named = algorithm.named_curve
        return None if named == curve else f"Expected a {curve} key, not {named}"

    return check


def check_hash(hash: str) -> Callable[[KeyAlgorithm], str | None]:
    def check(algorithm: KeyAlgorithm) -> str | None:
        key_hash = algorithm.hash
        return None if key_hash == hash else f"Expected a key for {hash}, not {key_hash}"

    return check


def rsa_generate_params(spec: Spec, modulus_length: int) -> Params:
    return Params(
        name=spec.import_params.name,
        hash=spec.import_params.hash,
        modulus_length=modulus_length,
        public_exponent=bytes([1, 0, 1]),
    )


def from_crypto_key(
    family: Family, method: str, algorithm: Any, role: Role, crypto_key: CryptoKey
) -> Effect[Any, CryptoError]:
    spec = family.spec_of(algorithm)
    build = family.private_key if role == "private" else family.public_key
    return _key.from_crypto_key(
        build,
        family.module,
        method,
        algorithm,
        crypto_key,
        _key.ExpectedCryptoKey(
            type=role,
            name=spec.name,
            usages=spec.private_usages if role == "private" else spec.public_usages,
            usage_policy="all",
            check=spec.check,
        ),
    )


def import_private(subtle: SubtleCrypto, data: bytes, spec: Spec, extractable: bool) -> CryptoKey:
    pkcs8 = data if spec.seed_prefix is None else spec.seed_prefix + data
    return subtle.import_key("pkcs8", pkcs8, spec.import_params, extractable, spec.private_usages)


def import_public(subtle: SubtleCrypto, data: bytes, spec: Spec) -> CryptoKey:
    return subtle.import_key(spec.public_format, data, spec.import_params, True, spec.public_usages)


def _export_private(subtle: SubtleCrypto, crypto_key: CryptoKey, spec: Spec) -> bytes:
    pkcs8 = bytes(subtle.export_key("pkcs8", crypto_key))
    prefix = spec.seed_prefix
    if prefix is None:
        return pkcs8
    if len(pkcs8) != len(prefix) + SEED_LENGTH or not pkcs8.startswith(prefix):
        raise _web.Failure(
            Unsupported(
                description=f"{spec.name} private key was exported in an unexpected PKCS#8 form"
            )
        )
    return pkcs8[len(prefix) :]


def _export_public(subtle: SubtleCrypto, crypto_key: CryptoKey, spec: Spec) -> bytes:
    return bytes(subtle.export_key(spec.public_format, crypto_key))


def export_key(subtle: SubtleCrypto, crypto_key: CryptoKey, spec: Spec, role: Role) -> bytes:
    if role == "private":
        return _export_private(subtle, crypto_key, spec)
    return _export_public(subtle, crypto_key, spec)


def to_bytes(family: Family, key: KeyBase[Any]) -> Effect[bytes, CryptoError]:
    role: Role = "private" if family.is_private_key(key) else "public"
    return _key.to_bytes(
        family.module,
        key,
        lambda subtle, crypto_key: export_key(
            subtle, crypto_key, family.spec_of(key.algorithm), role
        ),
    )


@dataclass(frozen=True, slots=True)
class Caches:
    private_key: Callable[[SubtleCrypto, KeyBase[Any]], CryptoKey]
    public_key: Callable[[SubtleCrypto, KeyBase[Any]], CryptoKey]


def make_caches(family: Family) -> Caches:
    return Caches(
        private_key=_key.make_cache(
            lambda subtle, data, algorithm: import_private(
                subtle, data, family.spec_of(algorithm), False
            )
        ),
        public_key=_key.make_cache(
            lambda subtle, data, algorithm: import_public(subtle, data, family.spec_of(algorithm))
        ),
    )


_PRIVATE_MEMBERS: Final = frozenset(
    {"d", "p", "q", "dp", "dq", "qi", "oth", "key_ops", "ext", "alg"}
)


def _public_of(subtle: SubtleCrypto, private_key: CryptoKey, spec: Spec) -> bytes:
    exported = subtle.export_key("jwk", private_key)
    public: JsonWebKey = {
        k: v  # pyright: ignore[reportAssignmentType]
        for k, v in exported.items()
        if k not in _PRIVATE_MEMBERS
    }
    imported = subtle.import_key("jwk", public, spec.import_params, True, spec.public_usages)
    return _export_public(subtle, imported, spec)


def generate_key_pair(  # noqa: PLR0917
    family: Family,
    crypto: Crypto | None,
    random: SecureRandomService,
    algorithm: Any,
    params: Params,
    pair: Callable[[Any, Any], object],
) -> Effect[Any, CryptoError]:
    """A pair of byte-backed keys. Ed25519 and X25519 seeds come from
    ``SecureRandom``; the others from Web Crypto's ``generate_key``."""
    spec = family.spec_of(algorithm)

    def generate(subtle: SubtleCrypto, seed: bytes | None) -> tuple[bytes, bytes]:
        if seed is not None:
            private_key = import_private(subtle, seed, spec, True)
            return seed, _public_of(subtle, private_key, spec)
        usages: list[KeyUsage] = list(dict.fromkeys([*spec.private_usages, *spec.public_usages]))
        generated = subtle.generate_key(params, True, usages)
        if not isinstance(generated, CryptoKeyPair):
            raise TypeError("generate_key gave a single key for a key pair algorithm")
        return (
            _export_private(subtle, generated.private_key, spec),
            _export_public(subtle, generated.public_key, spec),
        )

    seed_effect: Effect[bytes | None] = (
        succeed(None) if spec.seed_prefix is None else random.random_bytes(SEED_LENGTH)
    )
    return seed_effect.flat_map(
        lambda seed: _web.run(
            family.module,
            "generateKeyPair",
            algorithm.name,
            crypto,
            lambda subtle: generate(subtle, seed),
        ).map(
            lambda keys: pair(
                family.private_key(algorithm, keys[0]), family.public_key(algorithm, keys[1])
            )
        )
    )


def public_key_of(
    family: Family, crypto: Crypto | None, private_key: KeyBase[Any]
) -> Effect[Any, CryptoError]:
    def go() -> Effect[Any, CryptoError]:
        stored = material(private_key)
        if isinstance(stored, CryptoKey) and not stored.extractable:
            return _web.not_extractable(family.module, "publicKeyOf")
        spec = family.spec_of(private_key.algorithm)

        def run(subtle: SubtleCrypto) -> bytes:
            handle = (
                stored
                if isinstance(stored, CryptoKey)
                else import_private(subtle, stored, spec, True)
            )
            return _public_of(subtle, handle, spec)

        return _web.run(family.module, "publicKeyOf", private_key.algorithm.name, crypto, run).map(
            lambda data: family.public_key(private_key.algorithm, data)
        )

    return suspend(go)


def public_key_error(
    module: str, method: str, public_key: KeyBase[Any], cause: Exception
) -> CryptoError:
    if isinstance(material(public_key), bytes) and _web.is_type_error(cause):
        return CryptoError(
            module=module,
            method=method,
            reason=InvalidKey(description="Invalid public key", cause=cause),
        )
    return _web.web_crypto_error(module, method, public_key.algorithm.name, cause)
