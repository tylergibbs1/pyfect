"""The errors of ``CircuitBreaker``."""

from __future__ import annotations

from pyfect import schema as S
from pyfect.duration import Seconds
from pyfect.persistence._seconds import SECONDS_FROM_MILLIS


class CircuitOpen(S.TaggedError, identifier="effect/persistence/CircuitBreaker/CircuitOpen"):
    """``key``'s circuit is open; it lets a probe through after
    ``retry_after``."""

    key: str
    retry_after: Seconds = S.field(SECONDS_FROM_MILLIS, key="retryAfter")

    @property
    def message(self) -> str:
        return "Circuit open"


class CircuitHalfOpen(
    S.TaggedError, identifier="effect/persistence/CircuitBreaker/CircuitHalfOpen"
):
    """``key``'s circuit is half-open and its probe is running."""

    key: str

    @property
    def message(self) -> str:
        return "Circuit half-open"


class CircuitBreakerStoreError(
    S.TaggedError, identifier="effect/persistence/CircuitBreaker/CircuitBreakerStoreError"
):
    """The store could not be reached; ``cause`` is why."""

    message: str
    cause: BaseException | None = S.field(S.Union(S.Null, S.Defect()), default=None)


type CircuitBreakerErrorReason = CircuitOpen | CircuitHalfOpen | CircuitBreakerStoreError

CIRCUIT_BREAKER_ERROR_REASON = S.Union(CircuitOpen, CircuitHalfOpen, CircuitBreakerStoreError)
"""The schema of every reason."""


class CircuitBreakerError(
    S.TaggedError, identifier="~effect/persistence/CircuitBreaker/CircuitBreakerError"
):
    """A call the breaker rejected, or a store failure; ``reason`` says
    which. Its message is the reason's, and its ``cause`` (and
    ``__cause__``) the reason's cause."""

    reason: CircuitBreakerErrorReason = S.field(CIRCUIT_BREAKER_ERROR_REASON)

    def __post_init__(self) -> None:
        self.__cause__ = self.cause

    @property
    def cause(self) -> BaseException | None:
        return self.reason.cause if isinstance(self.reason, CircuitBreakerStoreError) else None

    @property
    def message(self) -> str:
        return self.reason.message
