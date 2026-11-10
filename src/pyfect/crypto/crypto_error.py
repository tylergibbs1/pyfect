"""The ``CryptoError`` every ``pyfect.crypto`` module fails with (Effect's
``effect/crypto/CryptoError``).

``module`` and ``method`` name the operation (``"Aead"``, ``"decrypt"``);
``reason`` says what went wrong: ``InvalidArgument``, ``InvalidKey``,
``DecryptionFailed``, ``Unsupported`` or ``NotExtractable``. Match a
reason with ``catch_reason``::

    aead.decrypt(key, data, nonce=nonce).pipe(
        fx.catch_reason(CryptoError, DecryptionFailed, lambda _r, _e: fx.succeed(None))
    )

Map the error before it reaches a client: sending crypto failure detail
to clients is how oracles leak.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from pyfect.errors import TaggedError

type ReasonTag = Literal[
    "InvalidArgument", "InvalidKey", "DecryptionFailed", "Unsupported", "NotExtractable"
]


class CryptoErrorReason(TaggedError):
    """What every reason has: its tag and a message."""

    tag: ClassVar[ReasonTag]

    @property
    def message(self) -> str:
        raise NotImplementedError


@dataclass(eq=False)
class InvalidArgument(CryptoErrorReason):
    """An argument rejected before the key or data is used: a wrong nonce
    length, an out-of-range iteration count, ``info`` for a derivation
    other than HKDF."""

    description: str
    cause: object = None

    tag: ClassVar[ReasonTag] = "InvalidArgument"

    @property
    def message(self) -> str:
        return self.description


@dataclass(eq=False)
class InvalidKey(CryptoErrorReason):
    """Rejected key material: a wrong raw length, malformed DER, PEM or
    JWK, a ``CryptoKey`` that does not match the typed key, or a peer key
    that gives an all-zero shared secret."""

    description: str
    cause: object = None

    tag: ClassVar[ReasonTag] = "InvalidKey"

    @property
    def message(self) -> str:
        return self.description


@dataclass(eq=False)
class DecryptionFailed(CryptoErrorReason):
    """A decryption or unwrap failed its integrity check, or a CBC
    ciphertext had bad padding or length. It is the same for every cause and
    carries none, so a tampered tag cannot be told from bad padding."""

    tag: ClassVar[ReasonTag] = "DecryptionFailed"

    @property
    def message(self) -> str:
        return "Could not decrypt the data"


@dataclass(eq=False)
class Unsupported(CryptoErrorReason):
    """An algorithm or key a layer does not provide: Argon2id under
    ``kdf.layer_web_crypto``, a ``CryptoKey`` a layer cannot use."""

    description: str
    cause: object = None

    tag: ClassVar[ReasonTag] = "Unsupported"

    @property
    def message(self) -> str:
        return self.description


@dataclass(eq=False)
class NotExtractable(CryptoErrorReason):
    """Exporting or wrapping a ``CryptoKey`` created non-extractable."""

    description: str
    cause: object = None

    tag: ClassVar[ReasonTag] = "NotExtractable"

    @property
    def message(self) -> str:
        return self.description


type AnyReason = InvalidArgument | InvalidKey | DecryptionFailed | Unsupported | NotExtractable


@dataclass(eq=False)
class CryptoError(TaggedError):
    """A ``pyfect.crypto`` operation failed. The message reads
    ``"Aead.decrypt: <reason message>"``; ``cause`` is the reason's."""

    module: str
    method: str
    reason: AnyReason

    tag: ClassVar[Literal["CryptoError"]] = "CryptoError"

    def __post_init__(self) -> None:
        cause = getattr(self.reason, "cause", None)
        if isinstance(cause, BaseException):
            self.__cause__ = cause

    @property
    def cause(self) -> object:
        """The reason's cause, when it has one."""
        return getattr(self.reason, "cause", None)

    @property
    def message(self) -> str:
        return f"{self.module}.{self.method}: {self.reason.message}"


def is_crypto_error(u: object) -> bool:
    return isinstance(u, CryptoError)


def is_crypto_error_reason(u: object) -> bool:
    return isinstance(u, CryptoErrorReason)


__all__ = [
    "AnyReason",
    "CryptoError",
    "CryptoErrorReason",
    "DecryptionFailed",
    "InvalidArgument",
    "InvalidKey",
    "NotExtractable",
    "ReasonTag",
    "Unsupported",
    "is_crypto_error",
    "is_crypto_error_reason",
]
