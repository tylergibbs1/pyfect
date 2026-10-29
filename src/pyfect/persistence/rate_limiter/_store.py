"""``RateLimiterStore``: where a ``RateLimiter`` keeps its counters.

A store works in milliseconds, as Effect's does (and its Redis scripts),
so its arithmetic is Effect's to the last bit; ``RateLimiter`` turns the
results into ``Seconds``.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal, Protocol

from pyfect._core import Effect
from pyfect.context import Tag
from pyfect.duration import Seconds
from pyfect.persistence.rate_limiter._errors import RateLimiterError

type AdaptivePhase = Literal["inactive", "cooldown", "learning", "learned"]
"""Where an adaptive key is: no 429 seen (``"inactive"``), waiting out a
``Retry-After`` (``"cooldown"``), counting what the server accepts
(``"learning"``), or pacing at the limit it learned (``"learned"``)."""


@dataclass(frozen=True, slots=True)
class AdaptiveConsumeResult:
    """Wait ``delay`` before sending; report the response with ``epoch``."""

    delay: Seconds
    epoch: int
    phase: AdaptivePhase


class RateLimiterStoreService(Protocol):
    """The counters of a ``RateLimiter``."""

    def fixed_window(
        self, *, key: str, tokens: float, refill_rate_millis: float, limit: float | None
    ) -> Effect[tuple[float, float], RateLimiterError]:
        """Add ``tokens`` to ``key``'s count, each extending its window by
        ``refill_rate_millis``, unless ``limit`` is given and would be
        passed. Gives ``(count, ttl_millis)``: the count reached (or that
        would be), and how long the window has left."""
        ...

    def token_bucket(
        self,
        *,
        key: str,
        tokens: float,
        limit: float,
        refill_rate_millis: float,
        allow_overflow: bool,
    ) -> Effect[tuple[float, float], RateLimiterError]:
        """Take ``tokens`` from ``key``'s bucket of ``limit``, refilled one
        token per ``refill_rate_millis``; the balance goes below zero only
        with ``allow_overflow``. Gives ``(remaining, elapsed_millis)``: the
        balance after the take, and the time since the last refill."""
        ...

    def adaptive_consume(
        self, *, key: str, tokens: float, fallback_limit: float, fallback_window: Seconds
    ) -> Effect[AdaptiveConsumeResult, RateLimiterError]:
        """See ``RateLimiterService.adaptive_consume``."""
        ...

    def adaptive_feedback(
        self, *, key: str, epoch: int, tokens: float, status: int, retry_after: Seconds | None
    ) -> Effect[None, RateLimiterError]:
        """See ``RateLimiterService.adaptive_feedback``."""
        ...


class RateLimiterStore(
    Tag[RateLimiterStoreService], key="effect/persistence/RateLimiter/RateLimiterStore"
):
    """Where a ``RateLimiter`` keeps its counters."""


ADAPTIVE_TTL_GRACE_MILLIS = 60_000
ADAPTIVE_MAX_WINDOW_MILLIS = 60 * 60 * 1_000


def clamp_adaptive_millis(millis: float) -> float:
    """A ``Retry-After`` or learned window, at least 1 ms and at most an
    hour."""
    if math.isnan(millis) or millis <= 0:
        return 1
    return min(millis, ADAPTIVE_MAX_WINDOW_MILLIS)
