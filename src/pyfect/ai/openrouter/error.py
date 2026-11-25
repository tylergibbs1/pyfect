"""The metadata an OpenRouter error carries under ``"openrouter"``
(Effect's ``OpenRouterError``): the error code, type and request id, with
the ``x-ratelimit-*`` headers for a rate limit."""

from __future__ import annotations

from typing import TypedDict


class OpenRouterErrorMetadata(TypedDict):
    """OpenRouter details on an ``AiError``: the error code, type and request id."""

    errorCode: str | int | float | None
    errorType: str | None
    requestId: str | None


class OpenRouterRateLimitMetadata(OpenRouterErrorMetadata):
    """OpenRouter rate limit details: the limit, what remains and when it resets."""

    limit: str | None
    remaining: int | float | None
    resetRequests: str | None
    resetTokens: str | None


__all__ = ["OpenRouterErrorMetadata", "OpenRouterRateLimitMetadata"]
