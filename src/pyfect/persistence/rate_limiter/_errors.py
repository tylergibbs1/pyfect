"""The errors of ``RateLimiter``."""

from __future__ import annotations

from pyfect import schema as S
from pyfect.duration import Seconds
from pyfect.persistence._seconds import SECONDS_FROM_MILLIS


class RateLimitExceeded(
    S.TaggedError, identifier="effect/persistence/RateLimiter/RateLimitExceeded"
):
    """A ``"fail"`` consume would go over ``limit`` for ``key``; retry
    after ``retry_after``."""

    retry_after: Seconds = S.field(SECONDS_FROM_MILLIS)
    key: str
    limit: float = S.field(S.Finite)
    remaining: float = S.field(S.Finite)

    @property
    def message(self) -> str:
        return "Rate limit exceeded"


class RateLimitStoreError(
    S.TaggedError, identifier="effect/persistence/RateLimiter/RateLimitStoreError"
):
    """The store could not be reached; ``cause`` is why."""

    message: str
    cause: BaseException | None = S.field(S.Union(S.Null, S.Defect()), default=None)


type RateLimiterErrorReason = RateLimitExceeded | RateLimitStoreError

RATE_LIMITER_ERROR_REASON = S.Union(RateLimitExceeded, RateLimitStoreError)
"""The schema of every reason."""


class RateLimiterError(
    S.TaggedError, identifier="~effect/persistence/RateLimiter/RateLimiterError"
):
    """A ``RateLimiter`` failure; ``reason`` says which kind. Its message is
    the reason's, and its ``cause`` (and ``__cause__``) the reason's
    cause."""

    reason: RateLimiterErrorReason = S.field(RATE_LIMITER_ERROR_REASON)

    def __post_init__(self) -> None:
        self.__cause__ = self.cause

    @property
    def cause(self) -> BaseException | None:
        return self.reason.cause if isinstance(self.reason, RateLimitStoreError) else None

    @property
    def message(self) -> str:
        return self.reason.message
