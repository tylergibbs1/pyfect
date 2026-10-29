"""The Anthropic details an ``AiError`` reason carries under its
``metadata["anthropic"]`` (Effect's ``AnthropicError``): the error type
and request id of the provider's response, and for a rate limit the
``anthropic-ratelimit-*`` headers. A field is ``None`` when Anthropic
did not send it.
"""

from __future__ import annotations

from typing import TypedDict


class AnthropicErrorMetadata(TypedDict):
    errorType: str | None
    requestId: str | None


class AnthropicRateLimitMetadata(AnthropicErrorMetadata):
    requestsLimit: int | float | None
    requestsRemaining: int | float | None
    requestsReset: str | None
    tokensLimit: int | float | None
    tokensRemaining: int | float | None
    tokensReset: str | None


__all__ = ["AnthropicErrorMetadata", "AnthropicRateLimitMetadata"]
