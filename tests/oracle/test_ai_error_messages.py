"""Rate-limit and quota messages as Effect 4.0.6 writes them (QA
ai-workflow AI-2, AI-3)."""

from __future__ import annotations

from datetime import UTC, datetime

from pyfect import duration as fx_duration
from pyfect.ai import ai_error as E


def test_a_zero_retry_after_is_in_the_message():
    """A ``Duration`` is an object, so ``if (this.retryAfter)`` keeps zero."""
    error = E.RateLimitError(retry_after=fx_duration.zero)
    assert error.message == "Rate limit exceeded. Retry after 0"


def test_the_quota_reset_time_is_written_as_a_date_time_utc():
    reset_at = datetime(2026, 1, 2, 3, 4, 5, 6000, tzinfo=UTC)
    error = E.QuotaExhaustedError(reset_at=reset_at)
    assert error.message == (
        "Quota exhausted. Resets at DateTime.Utc(2026-01-02T03:04:05.006Z)."
        " Check your account billing and usage limits."
    )
