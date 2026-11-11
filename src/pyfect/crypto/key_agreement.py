"""Key agreement as a service (Effect's ``effect/crypto/KeyAgreement``)::

    agreement = yield from KeyAgreement()
    pair = yield from agreement.generate_key_pair(x25519)
    secret = yield from agreement.derive_shared_secret(pair.private_key, peer_public_key)

X25519 and ECDH on P-256 / P-384 / P-521. A peer key off the curve, of
another algorithm, or a low-order X25519 key giving an all-zero secret
fails with ``InvalidKey``. Feed the shared secret to ``kdf`` before using
it as a key.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, ClassVar, Generic, Literal, Never, Protocol, TypeVar, final

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.crypto import _asymmetric, _key, _web
from pyfect.crypto._asymmetric import Curve, Family, Spec
from pyfect.crypto._key import Binary, KeyBase
from pyfect.crypto.crypto_error import CryptoError, InvalidKey
from pyfect.crypto.secure_random import SecureRandom, SecureRandomService
from pyfect.crypto.web_crypto import Crypto, CryptoKey, Params, SubtleCrypto, WebCrypto
from pyfect.effect import fail, gen, succeed, suspend
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect


@dataclass(frozen=True, kw_only=True)
class X25519:
    name: Literal["x25519"] = "x25519"

    tag: ClassVar[Literal["X25519"]] = "X25519"


C_co = TypeVar("C_co", bound=Curve, covariant=True, default=Curve)


@dataclass(frozen=True, kw_only=True)
class Ecdh(Generic[C_co]):
    name: Literal["ecdhP256", "ecdhP384", "ecdhP521"]
    named_curve: C_co

    tag: ClassVar[Literal["Ecdh"]] = "Ecdh"


type Algorithm = X25519 | Ecdh[Any]

x25519 = X25519()
ecdh_p256: Ecdh[Literal["P-256"]] = Ecdh(name="ecdhP256", named_curve="P-256")
ecdh_p384: Ecdh[Literal["P-384"]] = Ecdh(name="ecdhP384", named_curve="P-384")
ecdh_p521: Ecdh[Literal["P-521"]] = Ecdh(name="ecdhP521", named_curve="P-521")


@final
class PrivateKey[A: Algorithm = Algorithm](KeyBase[A]):
    """A key-agreement private key for ``algorithm``."""

    __slots__ = ()
    label: ClassVar[str] = "KeyAgreement.PrivateKey"


@final
class PublicKey[A: Algorithm = Algorithm](KeyBase[A]):
    """A key-agreement public key for ``algorithm``."""

    __slots__ = ()
    label: ClassVar[str] = "KeyAgreement.PublicKey"


@dataclass(frozen=True, slots=True)
class KeyPair[A: Algorithm = Algorithm]:
    private_key: PrivateKey[A]
    public_key: PublicKey[A]


def is_private_key(u: object) -> bool:
    return isinstance(u, PrivateKey)


def is_public_key(u: object) -> bool:
    return isinstance(u, PublicKey)


def _spec_of(algorithm: Algorithm) -> Spec:
    if isinstance(algorithm, X25519):
        return Spec(
            "X25519", Params(name="X25519"), ("deriveBits",), (), _asymmetric.X25519_PREFIX, "raw"
        )
    return Spec(
        "ECDH",
        Params(name="ECDH", named_curve=algorithm.named_curve),
        ("deriveBits",),
        (),
        None,
        "raw",
        _asymmetric.check_named_curve(algorithm.named_curve),
    )


family = Family(
    module="KeyAgreement",
    spec_of=_spec_of,
    private_key=PrivateKey,
    public_key=PublicKey,
    is_private_key=is_private_key,
)


def _shared_secret_bits(algorithm: Algorithm) -> int:
    # P-521 coordinates are 521 bits, padded to 66 bytes.
    if isinstance(algorithm, X25519):
        return 256
    return 8 * _asymmetric.COORDINATE_SIZES[algorithm.named_curve]


def _invalid_peer(description: str, cause: object = None) -> CryptoError:
    return CryptoError(
        module="KeyAgreement",
        method="deriveSharedSecret",
        reason=InvalidKey(description=description, cause=cause),
    )


class KeyAgreementService(Protocol):
    def generate_key_pair[A: Algorithm](self, algorithm: A) -> Effect[KeyPair[A], CryptoError]:
        """A new key pair for ``algorithm``."""
        ...

    def derive_shared_secret[A: Algorithm](
        self, private_key: PrivateKey[A], public_key: PublicKey[A]
    ) -> Effect[bytes, CryptoError]:
        """The secret shared with the holder of ``public_key``, as raw
        bytes for ``kdf``; ``InvalidKey`` for a peer key off the curve or a
        low-order X25519 key."""
        ...

    def public_key_of[A: Algorithm](
        self, private_key: PrivateKey[A]
    ) -> Effect[PublicKey[A], CryptoError]:
        """The public key of ``private_key``."""
        ...


class KeyAgreement(Tag[KeyAgreementService], key="effect/crypto/KeyAgreement"):
    """Shared secrets from key pairs."""


class _WebCryptoKeyAgreement:
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
            _spec_of(algorithm).import_params,
            KeyPair,
        )

    def derive_shared_secret[A: Algorithm](
        self, private_key: PrivateKey[A], public_key: PublicKey[A]
    ) -> Effect[bytes, CryptoError]:
        def go() -> Effect[bytes, CryptoError]:
            algorithm: Algorithm = private_key.algorithm
            # The types keep curves apart, but keys typed with the default
            # ``Algorithm`` can still differ at run time.
            if algorithm.name != public_key.algorithm.name:
                return fail(
                    _invalid_peer(
                        f"Expected a {algorithm.name} public key, not {public_key.algorithm.name}"
                    )
                )

            def on_error(cause: Exception) -> CryptoError:
                return _asymmetric.public_key_error(
                    "KeyAgreement", "deriveSharedSecret", public_key, cause
                )

            def import_keys(subtle: SubtleCrypto) -> tuple[CryptoKey, CryptoKey]:
                return (
                    self._caches.private_key(subtle, private_key),
                    self._caches.public_key(subtle, public_key),
                )

            spec = _spec_of(algorithm)

            # The keys are imported first, so an ``OperationError`` from
            # ``derive_bits`` can only come from the peer key.
            def derive(keys: tuple[CryptoKey, CryptoKey]) -> Effect[bytes, CryptoError]:
                return _web.run(
                    "KeyAgreement",
                    "deriveSharedSecret",
                    algorithm.name,
                    self._crypto,
                    lambda subtle: bytes(
                        subtle.derive_bits(
                            Params(name=spec.name, public=keys[1]),
                            keys[0],
                            _shared_secret_bits(algorithm),
                        )
                    ),
                    lambda cause: (
                        _invalid_peer("Invalid peer public key", cause)
                        if _web.is_operation_error(cause)
                        else on_error(cause)
                    ),
                )

            def check(secret: bytes) -> Effect[bytes, CryptoError]:
                # RFC 7748, section 6.1: an all-zero X25519 output means the
                # peer sent a low-order point, and protocols must abort.
                if isinstance(algorithm, X25519) and not any(secret):
                    return fail(_invalid_peer("X25519 shared secret must not be all zeros"))
                return succeed(secret)

            return (
                _web.run(
                    "KeyAgreement",
                    "deriveSharedSecret",
                    algorithm.name,
                    self._crypto,
                    import_keys,
                    on_error,
                )
                .flat_map(derive)
                .flat_map(check)
            )

        return suspend(go)

    def public_key_of[A: Algorithm](
        self, private_key: PrivateKey[A]
    ) -> Effect[PublicKey[A], CryptoError]:
        return _asymmetric.public_key_of(family, self._crypto, private_key)


@gen
def _build():
    random = yield from SecureRandom()
    crypto = yield from WebCrypto()
    service: KeyAgreementService = _WebCryptoKeyAgreement(random, crypto)
    return service


layer_web_crypto: Layer[KeyAgreement, Never, SecureRandom] = layer_effect(KeyAgreement, _build)
"""Key agreement on the ``WebCrypto`` reference; X25519 keys from ``SecureRandom``."""


def private_key[A: X25519](algorithm: A, data: Binary) -> Effect[PrivateKey[A], CryptoError]:
    """An X25519 private key from its 32 bytes."""
    return _key.from_bytes(
        lambda copied: PrivateKey(algorithm, copied),
        "KeyAgreement",
        "privateKey",
        data,
        _asymmetric.check_seed_length("X25519", "private"),
    )


def public_key[A: Algorithm](algorithm: A, data: Binary) -> Effect[PublicKey[A], CryptoError]:
    """An X25519 public key (32 bytes) or an uncompressed EC point."""
    check = (
        _asymmetric.check_point(algorithm.named_curve)
        if isinstance(algorithm, Ecdh)
        else _asymmetric.check_seed_length("X25519", "public")
    )
    return _key.from_bytes(
        lambda copied: PublicKey(algorithm, copied), "KeyAgreement", "publicKey", data, check
    )


def private_key_from_crypto_key[A: Algorithm](
    algorithm: A, crypto_key: CryptoKey
) -> Effect[PrivateKey[A], CryptoError]:
    return _asymmetric.from_crypto_key(
        family, "privateKeyFromCryptoKey", algorithm, "private", crypto_key
    )


def public_key_from_crypto_key[A: Algorithm](
    algorithm: A, crypto_key: CryptoKey
) -> Effect[PublicKey[A], CryptoError]:
    return _asymmetric.from_crypto_key(
        family, "publicKeyFromCryptoKey", algorithm, "public", crypto_key
    )


def to_bytes(key: PrivateKey[Any] | PublicKey[Any]) -> Effect[bytes, CryptoError]:
    return _asymmetric.to_bytes(family, key)


__all__ = [
    "X25519",
    "Algorithm",
    "CryptoError",
    "Curve",
    "Ecdh",
    "KeyAgreement",
    "KeyAgreementService",
    "KeyPair",
    "PrivateKey",
    "PublicKey",
    "ecdh_p256",
    "ecdh_p384",
    "ecdh_p521",
    "family",
    "is_private_key",
    "is_public_key",
    "layer_web_crypto",
    "private_key",
    "private_key_from_crypto_key",
    "public_key",
    "public_key_from_crypto_key",
    "to_bytes",
    "x25519",
]
