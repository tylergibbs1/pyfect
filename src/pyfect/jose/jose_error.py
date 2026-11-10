"""The ``JoseError`` every ``pyfect.jose`` module fails with (Effect's
``effect/jose/JoseError``).

``reason`` says what went wrong. Crypto failures become ``InvalidKey``
without the crypto error's detail, so a token's verifier never learns why
a backend rejected a key. Match a reason with ``catch_reason``::

    jws.verify(token, key).pipe(
        fx.catch_reason(JoseError, SignatureVerificationFailed, lambda _r, _e: fx.succeed(None))
    )
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import ClassVar, Literal

from pyfect.errors import TaggedError

type ReasonTag = Literal[
    "InvalidToken",
    "InvalidKey",
    "InvalidArgument",
    "AlgorithmNotAllowed",
    "SignatureVerificationFailed",
    "DecryptionFailed",
    "KeyNotFound",
    "AmbiguousKey",
    "KeySetUnavailable",
    "ClaimValidationFailed",
]

type Claim = Literal["iss", "sub", "aud", "exp", "nbf", "iat", "jti", "typ"]
type ClaimFailure = Literal[
    "invalid", "missing", "mismatch", "expired", "notYetValid", "tooOld", "future"
]


class JoseErrorReason(TaggedError):
    """What every reason has: its tag and a message."""

    tag: ClassVar[ReasonTag]

    @property
    def message(self) -> str:
        raise NotImplementedError


@dataclass(eq=False)
class InvalidToken(JoseErrorReason):
    """A token that is not a well-formed compact serialization."""

    description: str

    tag: ClassVar[ReasonTag] = "InvalidToken"

    @property
    def message(self) -> str:
        return self.description


@dataclass(eq=False)
class InvalidKey(JoseErrorReason):
    """Key material or metadata rejected, or a crypto operation on the key
    that failed."""

    description: str
    cause: object = None

    tag: ClassVar[ReasonTag] = "InvalidKey"

    @property
    def message(self) -> str:
        return self.description


@dataclass(eq=False)
class InvalidArgument(JoseErrorReason):
    """An option or header rejected before any cryptography."""

    description: str
    cause: object = None

    tag: ClassVar[ReasonTag] = "InvalidArgument"

    @property
    def message(self) -> str:
        return self.description


@dataclass(eq=False)
class AlgorithmNotAllowed(JoseErrorReason):
    """The token's ``alg`` is not the key's, or not in the allowlist."""

    tag: ClassVar[ReasonTag] = "AlgorithmNotAllowed"

    @property
    def message(self) -> str:
        return "The token algorithm is not allowed"


@dataclass(eq=False)
class SignatureVerificationFailed(JoseErrorReason):
    tag: ClassVar[ReasonTag] = "SignatureVerificationFailed"

    @property
    def message(self) -> str:
        return "Could not verify the signature"


@dataclass(eq=False)
class DecryptionFailed(JoseErrorReason):
    tag: ClassVar[ReasonTag] = "DecryptionFailed"

    @property
    def message(self) -> str:
        return "Could not decrypt the token"


@dataclass(eq=False)
class KeyNotFound(JoseErrorReason):
    tag: ClassVar[ReasonTag] = "KeyNotFound"

    @property
    def message(self) -> str:
        return "No key matches the algorithm and key id"


@dataclass(eq=False)
class AmbiguousKey(JoseErrorReason):
    tag: ClassVar[ReasonTag] = "AmbiguousKey"

    @property
    def message(self) -> str:
        return "More than one key matches the algorithm and key id"


@dataclass(eq=False)
class KeySetUnavailable(JoseErrorReason):
    """A remote key set that could not be fetched, read or trusted."""

    description: str
    cause: object = None

    tag: ClassVar[ReasonTag] = "KeySetUnavailable"

    @property
    def message(self) -> str:
        return self.description


@dataclass(eq=False)
class ClaimValidationFailed(JoseErrorReason):
    """A registered claim that failed the verification policy."""

    claim: Claim
    reason: ClaimFailure

    tag: ClassVar[ReasonTag] = "ClaimValidationFailed"

    @property
    def message(self) -> str:
        return f"The {self.claim} claim failed validation: {self.reason}"


type AnyReason = (
    InvalidToken
    | InvalidKey
    | InvalidArgument
    | AlgorithmNotAllowed
    | SignatureVerificationFailed
    | DecryptionFailed
    | KeyNotFound
    | AmbiguousKey
    | KeySetUnavailable
    | ClaimValidationFailed
)


@dataclass(eq=False)
class JoseError(TaggedError):
    """A ``pyfect.jose`` operation failed; the message and ``cause`` are the
    reason's."""

    reason: AnyReason

    tag: ClassVar[Literal["JoseError"]] = "JoseError"

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
        return self.reason.message


def is_jose_error(u: object) -> bool:
    return isinstance(u, JoseError)


def is_jose_error_reason(u: object) -> bool:
    return isinstance(u, JoseErrorReason)


__all__ = [
    "AlgorithmNotAllowed",
    "AmbiguousKey",
    "AnyReason",
    "Claim",
    "ClaimFailure",
    "ClaimValidationFailed",
    "DecryptionFailed",
    "InvalidArgument",
    "InvalidKey",
    "InvalidToken",
    "JoseError",
    "JoseErrorReason",
    "KeyNotFound",
    "KeySetUnavailable",
    "ReasonTag",
    "SignatureVerificationFailed",
    "is_jose_error",
    "is_jose_error_reason",
]
