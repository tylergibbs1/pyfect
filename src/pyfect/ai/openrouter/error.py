"""The metadata an OpenRouter error carries under ``"openrouter"``
(Effect's ``OpenRouterError``): the error code, type and request id, with
the ``x-ratelimit-*`` headers for a rate limit."""

from __future__ import annotations

from typing import TypedDict


class OpenRouterErrorMetadata(TypedDict):
    errorCode: str | int | float | None
    errorType: str | None
    requestId: str | None


class OpenRouterRateLimitMetadata(OpenRouterErrorMetadata):
    limit: str | None
    remaining: int | float | None
    resetRequests: str | None
    resetTokens: str | None


__all__ = ["OpenRouterErrorMetadata", "OpenRouterRateLimitMetadata"]
