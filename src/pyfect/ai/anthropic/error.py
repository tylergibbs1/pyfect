"""The Anthropic details an ``AiError`` reason carries under its
``metadata["anthropic"]`` (Effect's ``AnthropicError``): the error type
and request id of the provider's response, and for a rate limit the
``anthropic-ratelimit-*`` headers. A field is ``None`` when Anthropic
did not send it.
"""

from __future__ import annotations

from typing import TypedDict


class AnthropicErrorMetadata(TypedDict):
    """Anthropic details on an ``AiError``: the provider's error type and request id."""

    errorType: str | None
    requestId: str | None


class AnthropicRateLimitMetadata(AnthropicErrorMetadata):
    """Anthropic rate limit details: request and token limits, what remains and when they reset."""

    requestsLimit: int | float | None
    requestsRemaining: int | float | None
    requestsReset: str | None
    tokensLimit: int | float | None
    tokensRemaining: int | float | None
    tokensReset: str | None


__all__ = ["AnthropicErrorMetadata", "AnthropicRateLimitMetadata"]
