"""Digital signatures as a service (Effect's ``effect/crypto/Signature``)::

    signature = yield from Signature()
    pair = yield from signature.generate_key_pair(ed25519)
    signed = yield from signature.sign(pair.private_key, data)
    ok = yield from signature.verify(pair.public_key, signed, data)

Ed25519, ECDSA on P-256 / P-384 / P-521 (the hash bound to the curve,
signatures in raw ``r‖s`` form) and RSA-PSS / RSASSA-PKCS1-v1_5.
``verify`` is ``False`` for any problem with the signature bytes. Keys are
stored as an Ed25519 seed or raw public key, an uncompressed EC point or
EC PKCS#8, or RSA SPKI / PKCS#8; ``key_format`` reads and writes the
other forms.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, ClassVar, Generic, Literal, Never, Protocol, TypeVar, final

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.crypto import _asymmetric, _key, _web
from pyfect.crypto._asymmetric import Curve, Family, Spec
from pyfect.crypto._key import Binary, KeyBase
from pyfect.crypto.crypto_error import CryptoError, InvalidArgument
from pyfect.crypto.digest import Algorithm as DigestAlgorithm
from pyfect.crypto.digest import name_suffix, sha256, sha384, sha512
from pyfect.crypto.secure_random import SecureRandom, SecureRandomService
from pyfect.crypto.web_crypto import Crypto, CryptoKey, KeyUsage, Params, SubtleCrypto, WebCrypto
from pyfect.effect import gen
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect


@dataclass(frozen=True, kw_only=True)
class Ed25519:
    name: Literal["ed25519"] = "ed25519"

    tag: ClassVar[Literal["Ed25519"]] = "Ed25519"


C_co = TypeVar("C_co", bound=Curve, covariant=True, default=Curve)


@dataclass(frozen=True, kw_only=True)
class Ecdsa(Generic[C_co]):
    """ECDSA on ``named_curve`` with ``hash``."""

    name: Literal["ecdsaP256", "ecdsaP384", "ecdsaP521"]
    named_curve: C_co
    hash: DigestAlgorithm

    tag: ClassVar[Literal["Ecdsa"]] = "Ecdsa"


@dataclass(frozen=True, kw_only=True)
class RsaPss:
    name: str
    hash: DigestAlgorithm
    modulus_length: int
    salt_length: int

    tag: ClassVar[Literal["RsaPss"]] = "RsaPss"


@dataclass(frozen=True, kw_only=True)
class RsaPkcs1v15:
    name: str
    hash: DigestAlgorithm
    modulus_length: int

    tag: ClassVar[Literal["RsaPkcs1v15"]] = "RsaPkcs1v15"


type Algorithm = Ed25519 | Ecdsa[Any] | RsaPss | RsaPkcs1v15

ed25519 = Ed25519()
ecdsa_p256: Ecdsa[Literal["P-256"]] = Ecdsa(name="ecdsaP256", named_curve="P-256", hash=sha256)
ecdsa_p384: Ecdsa[Literal["P-384"]] = Ecdsa(name="ecdsaP384", named_curve="P-384", hash=sha384)
ecdsa_p521: Ecdsa[Literal["P-521"]] = Ecdsa(name="ecdsaP521", named_curve="P-521", hash=sha512)


def rsa_pss(
    *, hash: DigestAlgorithm, modulus_length: int, salt_length: int | None = None
) -> RsaPss:
    """RSA-PSS; the salt is the hash's length unless given."""
    return RsaPss(
        name=f"rsaPss{name_suffix(hash)}",
        hash=hash,
        modulus_length=modulus_length,
        salt_length=hash.output_length if salt_length is None else salt_length,
    )


def rsa_pkcs1v15(*, hash: DigestAlgorithm, modulus_length: int) -> RsaPkcs1v15:
    return RsaPkcs1v15(
        name=f"rsaPkcs1v15{name_suffix(hash)}", hash=hash, modulus_length=modulus_length
    )


# 3072-bit moduli follow current NIST guidance.
rsa_pss_sha256 = rsa_pss(hash=sha256, modulus_length=3072)
rsa_pss_sha384 = rsa_pss(hash=sha384, modulus_length=3072)
rsa_pss_sha512 = rsa_pss(hash=sha512, modulus_length=3072)
rsa_pkcs1v15_sha256 = rsa_pkcs1v15(hash=sha256, modulus_length=3072)
rsa_pkcs1v15_sha384 = rsa_pkcs1v15(hash=sha384, modulus_length=3072)
rsa_pkcs1v15_sha512 = rsa_pkcs1v15(hash=sha512, modulus_length=3072)


@final
class PrivateKey[A: Algorithm = Algorithm](KeyBase[A]):
    """A signing key for ``algorithm``."""

    __slots__ = ()
    label: ClassVar[str] = "Signature.PrivateKey"


@final
class PublicKey[A: Algorithm = Algorithm](KeyBase[A]):
    """A verification key for ``algorithm``."""

    __slots__ = ()
    label: ClassVar[str] = "Signature.PublicKey"


@dataclass(frozen=True, slots=True)
class KeyPair[A: Algorithm = Algorithm]:
    private_key: PrivateKey[A]
    public_key: PublicKey[A]


def is_private_key(u: object) -> bool:
    return isinstance(u, PrivateKey)


def is_public_key(u: object) -> bool:
    return isinstance(u, PublicKey)


def _spec_of(algorithm: Algorithm) -> Spec:
    private_usages: tuple[KeyUsage, ...] = ("sign",)
    public_usages: tuple[KeyUsage, ...] = ("verify",)
    match algorithm:
        case Ed25519():
            return Spec(
                "Ed25519",
                Params(name="Ed25519"),
                private_usages,
                public_usages,
                _asymmetric.ED25519_PREFIX,
                "raw",
            )
        case Ecdsa():
            return Spec(
                "ECDSA",
                Params(name="ECDSA", named_curve=algorithm.named_curve),
                private_usages,
                public_usages,
                None,
                "raw",
                _asymmetric.check_named_curve(algorithm.named_curve),
            )
        case RsaPss() | RsaPkcs1v15():
            name = "RSA-PSS" if isinstance(algorithm, RsaPss) else "RSASSA-PKCS1-v1_5"
            return Spec(
                name,
                Params(name=name, hash=algorithm.hash.name),
                private_usages,
                public_usages,
                None,
                "spki",
                _asymmetric.check_hash(algorithm.hash.name),
            )


family = Family(
    module="Signature",
    spec_of=_spec_of,
    private_key=PrivateKey,
    public_key=PublicKey,
    is_private_key=is_private_key,
)


def _sign_params(algorithm: Algorithm) -> Params:
    match algorithm:
        case Ed25519():
            return Params(name="Ed25519")
        case Ecdsa():
            return Params(name="ECDSA", hash=algorithm.hash.name)
        case RsaPss():
            return Params(name="RSA-PSS", salt_length=algorithm.salt_length)
        case RsaPkcs1v15():
            return Params(name="RSASSA-PKCS1-v1_5")


def _generate_params(algorithm: Algorithm) -> Params:
    match algorithm:
        case Ed25519():
            return Params(name="Ed25519")
        case Ecdsa():
            return Params(name="ECDSA", named_curve=algorithm.named_curve)
        case RsaPss() | RsaPkcs1v15():
            return _asymmetric.rsa_generate_params(_spec_of(algorithm), algorithm.modulus_length)


def _signature_length(algorithm: Algorithm, crypto_key: CryptoKey) -> int:
    """A signature of another length is rejected without asking Web Crypto,
    so every backend returns ``False`` for it. For RSA it is the modulus's
    size."""
    match algorithm:
        case Ed25519():
            return 64
        case Ecdsa():
            return 2 * _asymmetric.COORDINATE_SIZES[algorithm.named_curve]
        case RsaPss() | RsaPkcs1v15():
            return math.ceil((crypto_key.algorithm.modulus_length or 0) / 8)


def _check_salt_length(algorithm: Algorithm, crypto_key: CryptoKey) -> None:
    """RFC 8017, section 9.1.1: the encoded message fits the hash, the salt
    and two bytes. The modulus is known once the key is imported."""
    if not isinstance(algorithm, RsaPss):
        return
    salt = algorithm.salt_length
    problem: str | None = None
    if type(salt) is not int or not 0 <= salt <= 2**53 - 1:
        problem = "PSS salt length must be a non-negative safe integer"
    else:
        modulus_length = crypto_key.algorithm.modulus_length or 0
        if algorithm.hash.output_length + salt + 2 > math.ceil((modulus_length - 1) / 8):
            problem = (
                f"A {salt}-byte PSS salt does not fit a {modulus_length}-bit key "
                f"with {algorithm.hash.name}"
            )
    if problem is not None:
        raise _web.Failure(InvalidArgument(description=problem))


class SignatureService(Protocol):
    def generate_key_pair[A: Algorithm](self, algorithm: A) -> Effect[KeyPair[A], CryptoError]:
        """A new key pair for ``algorithm``."""
        ...

    def sign(self, private_key: PrivateKey[Any], data: Binary) -> Effect[bytes, CryptoError]:
        """The signature of ``data`` (ECDSA in raw ``r‖s`` form)."""
        ...

    def verify(
        self, public_key: PublicKey[Any], signature: Binary, data: Binary
    ) -> Effect[bool, CryptoError]:
        """Whether ``signature`` signs ``data``; ``False`` for any problem
        with the signature bytes."""
        ...

    def public_key_of[A: Algorithm](
        self, private_key: PrivateKey[A]
    ) -> Effect[PublicKey[A], CryptoError]:
        """The public key of ``private_key``."""
        ...


class Signature(Tag[SignatureService], key="effect/crypto/Signature"):
    """Signing and verification."""


class _WebCryptoSignature:
    __slots__ = ("_caches", "_crypto", "_random")

    def __init__(self, random: SecureRandomService, crypto: Crypto) -> None:
        self._random = random
        self._crypto = crypto
        self._caches = _asymmetric.make_caches(family)

    def generate_key_pair[A: Algorithm](self, algorithm: A) -> Effect[KeyPair[A], CryptoError]:
        return _asymmetric.generate_key_pair(
            family,
            self._crypto,
            self._random,
            algorithm,
            _generate_params(algorithm),
            KeyPair,
        )

    def sign(self, private_key: PrivateKey[Any], data: Binary) -> Effect[bytes, CryptoError]:
        def run(subtle: SubtleCrypto) -> bytes:
            crypto_key = self._caches.private_key(subtle, private_key)
            _check_salt_length(private_key.algorithm, crypto_key)
            return bytes(subtle.sign(_sign_params(private_key.algorithm), crypto_key, bytes(data)))

        return _web.run("Signature", "sign", private_key.algorithm.name, self._crypto, run)

    def verify(
        self, public_key: PublicKey[Any], signature: Binary, data: Binary
    ) -> Effect[bool, CryptoError]:
        def run(subtle: SubtleCrypto) -> bool:
            crypto_key = self._caches.public_key(subtle, public_key)
            _check_salt_length(public_key.algorithm, crypto_key)
            signed = bytes(signature)
            if len(signed) != _signature_length(public_key.algorithm, crypto_key):
                return False
            return subtle.verify(
                _sign_params(public_key.algorithm), crypto_key, signed, bytes(data)
            )

        return _web.run(
            "Signature",
            "verify",
            public_key.algorithm.name,
            self._crypto,
            run,
            lambda cause: _asymmetric.public_key_error("Signature", "verify", public_key, cause),
        )

    def public_key_of[A: Algorithm](
        self, private_key: PrivateKey[A]
    ) -> Effect[PublicKey[A], CryptoError]:
        return _asymmetric.public_key_of(family, self._crypto, private_key)


@gen
def _build():
    random = yield from SecureRandom()
    crypto = yield from WebCrypto()
    service: SignatureService = _WebCryptoSignature(random, crypto)
    return service


layer_web_crypto: Layer[Signature, Never, SecureRandom] = layer_effect(Signature, _build)
"""Signatures on the ``WebCrypto`` reference; Ed25519 seeds from ``SecureRandom``."""


def private_key[A: Ed25519](algorithm: A, data: Binary) -> Effect[PrivateKey[A], CryptoError]:
    """An Ed25519 private key from its 32-byte seed (not libsodium's
    64-byte ``seed‖public key`` form: pass its first 32 bytes)."""
    return _key.from_bytes(
        lambda copied: PrivateKey(algorithm, copied),
        "Signature",
        "privateKey",
        data,
        _asymmetric.check_seed_length("Ed25519", "private"),
    )


def public_key[A: Ed25519 | Ecdsa[Any]](
    algorithm: A, data: Binary
) -> Effect[PublicKey[A], CryptoError]:
    """An Ed25519 public key (32 bytes) or an uncompressed EC point. A point
    off the curve is rejected when the key is used."""
    check = (
        _asymmetric.check_point(algorithm.named_curve)
        if isinstance(algorithm, Ecdsa)
        else _asymmetric.check_seed_length("Ed25519", "public")
    )
    return _key.from_bytes(
        lambda copied: PublicKey(algorithm, copied), "Signature", "publicKey", data, check
    )


def private_key_from_crypto_key[A: Algorithm](
    algorithm: A, crypto_key: CryptoKey
) -> Effect[PrivateKey[A], CryptoError]:
    """A private key backed by a ``CryptoKey`` of the algorithm (and its
    curve or hash) with the ``sign`` usage."""
    return _asymmetric.from_crypto_key(
        family, "privateKeyFromCryptoKey", algorithm, "private", crypto_key
    )


def public_key_from_crypto_key[A: Algorithm](
    algorithm: A, crypto_key: CryptoKey
) -> Effect[PublicKey[A], CryptoError]:
    """A public key backed by a ``CryptoKey`` with the ``verify`` usage."""
    return _asymmetric.from_crypto_key(
        family, "publicKeyFromCryptoKey", algorithm, "public", crypto_key
    )


def to_bytes(key: PrivateKey[Any] | PublicKey[Any]) -> Effect[bytes, CryptoError]:
    """The key's stored form; ``NotExtractable`` for a non-extractable
    ``CryptoKey``."""
    return _asymmetric.to_bytes(family, key)


__all__ = [
    "Algorithm",
    "CryptoError",
    "Curve",
    "Ecdsa",
    "Ed25519",
    "KeyPair",
    "PrivateKey",
    "PublicKey",
    "RsaPkcs1v15",
    "RsaPss",
    "Signature",
    "SignatureService",
    "ecdsa_p256",
    "ecdsa_p384",
    "ecdsa_p521",
    "ed25519",
    "family",
    "is_private_key",
    "is_public_key",
    "layer_web_crypto",
    "private_key",
    "private_key_from_crypto_key",
    "public_key",
    "public_key_from_crypto_key",
    "rsa_pkcs1v15",
    "rsa_pkcs1v15_sha256",
    "rsa_pkcs1v15_sha384",
    "rsa_pkcs1v15_sha512",
    "rsa_pss",
    "rsa_pss_sha256",
    "rsa_pss_sha384",
    "rsa_pss_sha512",
    "to_bytes",
]
