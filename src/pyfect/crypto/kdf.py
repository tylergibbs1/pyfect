"""Key derivation as a service (Effect's ``effect/crypto/Kdf``)::

    kdf = yield from Kdf()
    okm = yield from kdf.derive(hkdf_sha256, secret, salt=salt, info=b"ctx", length=32)
    hashed = yield from kdf.derive(argon2id(), password, salt=salt, length=32)

HKDF and PBKDF2 run on the ``WebCrypto`` reference; Argon2id needs
``native.layer_kdf`` (``layer_web_crypto`` fails it with ``Unsupported``).
Arguments are checked before Web Crypto sees them.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal, Never, Protocol

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.crypto import _web
from pyfect.crypto._key import Binary
from pyfect.crypto.crypto_error import CryptoError, InvalidArgument, Unsupported
from pyfect.crypto.digest import Algorithm as DigestAlgorithm
from pyfect.crypto.digest import name_suffix, sha1, sha256, sha384, sha512
from pyfect.crypto.web_crypto import Crypto, Params, SubtleCrypto, WebCrypto
from pyfect.effect import suspend
from pyfect.layer import Layer
from pyfect.layer import effect as layer_effect


@dataclass(frozen=True, kw_only=True)
class Hkdf:
    name: str
    hash: DigestAlgorithm

    tag: ClassVar[Literal["Hkdf"]] = "Hkdf"


@dataclass(frozen=True, kw_only=True)
class Pbkdf2:
    name: str
    hash: DigestAlgorithm
    iterations: int

    tag: ClassVar[Literal["Pbkdf2"]] = "Pbkdf2"


@dataclass(frozen=True, kw_only=True)
class Argon2id:
    """Argon2id costs: ``memory`` in KiB, ``passes`` and ``parallelism``
    (lanes)."""

    name: Literal["argon2id"] = "argon2id"
    memory: int = 65_536
    passes: int = 3
    parallelism: int = 4

    tag: ClassVar[Literal["Argon2id"]] = "Argon2id"


type Algorithm = Hkdf | Pbkdf2 | Argon2id


def hkdf(hash: DigestAlgorithm) -> Hkdf:
    return Hkdf(name=f"hkdf{name_suffix(hash)}", hash=hash)


def pbkdf2(*, hash: DigestAlgorithm, iterations: int) -> Pbkdf2:
    return Pbkdf2(name=f"pbkdf2{name_suffix(hash)}", hash=hash, iterations=iterations)


hkdf_sha1 = hkdf(sha1)
hkdf_sha256 = hkdf(sha256)
hkdf_sha384 = hkdf(sha384)
hkdf_sha512 = hkdf(sha512)
pbkdf2_sha256 = pbkdf2(hash=sha256, iterations=600_000)
"""PBKDF2-HMAC-SHA256 at OWASP's 600,000 iterations."""


def argon2id(*, memory: int = 65_536, passes: int = 3, parallelism: int = 4) -> Argon2id:
    """Argon2id; the defaults are RFC 9106's second recommended setting
    (64 MiB, 3 passes, 4 lanes)."""
    return Argon2id(memory=memory, passes=passes, parallelism=parallelism)


class KdfService(Protocol):
    def derive(
        self,
        algorithm: Algorithm,
        secret: Binary,
        *,
        salt: Binary,
        length: int,
        info: Binary | None = None,
    ) -> Effect[bytes, CryptoError]:
        """``length`` bytes derived from ``secret``; ``info`` only for HKDF."""
        ...


class Kdf(Tag[KdfService], key="effect/crypto/Kdf"):
    """Key derivation."""


def _invalid_argument(description: str) -> Effect[Never, CryptoError]:
    return _web.fail("Kdf", "derive", InvalidArgument(description=description))


def _is_integer_in(n: object, low: int, high: int) -> bool:
    return isinstance(n, int) and not isinstance(n, bool) and low <= n <= high


def check_arguments(  # noqa: PLR0911
    algorithm: Algorithm, length: int, info: Binary | None
) -> Effect[Never, CryptoError] | None:
    """Checked before Web Crypto, which takes a 32-bit bit length that some
    backends wrap instead of rejecting."""
    if not isinstance(algorithm, Hkdf) and info is not None:
        return _invalid_argument("info only applies to HKDF")
    if isinstance(algorithm, Argon2id):
        return None
    if algorithm.hash.name == "MD5":
        return _invalid_argument(f"{algorithm.tag} needs a SHA hash, not MD5")
    if isinstance(algorithm, Hkdf):
        max_length = 255 * algorithm.hash.output_length
        if _is_integer_in(length, 1, max_length):
            return None
        return _invalid_argument(
            f"length must be between 1 and {max_length} bytes for {algorithm.name}"
        )
    if not _is_integer_in(algorithm.iterations, 1, 0x7FFF_FFFF):
        return _invalid_argument("iterations must be between 1 and 2^31 - 1")
    if _is_integer_in(length, 1, 0x1FFF_FFFF):
        return None
    return _invalid_argument("length must be between 1 and 2^29 - 1 bytes")


def _params(algorithm: Hkdf | Pbkdf2, salt: bytes, info: bytes | None) -> Params:
    if isinstance(algorithm, Hkdf):
        return Params(name="HKDF", hash=algorithm.hash.name, salt=salt, info=info or b"")
    return Params(
        name="PBKDF2", hash=algorithm.hash.name, salt=salt, iterations=algorithm.iterations
    )


class _WebCryptoKdf:
    __slots__ = ("_crypto",)

    def __init__(self, crypto: Crypto) -> None:
        self._crypto = crypto

    def derive(
        self,
        algorithm: Algorithm,
        secret: Binary,
        *,
        salt: Binary,
        length: int,
        info: Binary | None = None,
    ) -> Effect[bytes, CryptoError]:
        def go() -> Effect[bytes, CryptoError]:
            failure = check_arguments(algorithm, length, info)
            if failure is not None:
                return failure
            if isinstance(algorithm, Argon2id):
                return _web.fail(
                    "Kdf",
                    "derive",
                    Unsupported(description="Kdf.layerWebCrypto does not provide argon2id"),
                )
            name = "HKDF" if isinstance(algorithm, Hkdf) else "PBKDF2"
            params = _params(algorithm, bytes(salt), None if info is None else bytes(info))

            def run(subtle: SubtleCrypto) -> bytes:
                handle = subtle.import_key("raw", bytes(secret), name, False, ["deriveBits"])
                return bytes(subtle.derive_bits(params, handle, length * 8))

            return _web.run("Kdf", "derive", algorithm.name, self._crypto, run)

        return suspend(go)


def _service(crypto: Crypto) -> KdfService:
    return _WebCryptoKdf(crypto)


layer_web_crypto: Layer[Kdf] = layer_effect(Kdf, WebCrypto().map(_service))
"""HKDF and PBKDF2 on the ``WebCrypto`` reference."""

__all__ = [
    "Algorithm",
    "Argon2id",
    "CryptoError",
    "Hkdf",
    "Kdf",
    "KdfService",
    "Pbkdf2",
    "argon2id",
    "check_arguments",
    "hkdf",
    "hkdf_sha1",
    "hkdf_sha256",
    "hkdf_sha384",
    "hkdf_sha512",
    "layer_web_crypto",
    "pbkdf2",
    "pbkdf2_sha256",
]
