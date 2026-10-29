"""Anthropic's mapping of failed requests to ``AiError`` (Effect's
``internal/errors.ts``)."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Never

import pyfect as fx
from pyfect import clock
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai.ai_error import (
    AiError,
    AnyReason,
    AuthenticationError,
    HttpContext,
    InternalProviderError,
    InvalidRequestError,
    RateLimitError,
    UnknownError,
    build_error_description,
)
from pyfect.ai.anthropic import _schema as W
from pyfect.ai.anthropic.error import AnthropicErrorMetadata
from pyfect.http.error import StatusCodeError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse

MODULE = "AnthropicClient"


def parse_rate_limit_headers(
    headers: Mapping[str, str], now_millis: float
) -> tuple[Any, dict[str, Any]]:
    """The ``Retry-After`` delay and the ``anthropic-ratelimit-*`` values."""
    return P.retry_after(headers.get("retry-after"), now_millis), {
        "requestsLimit": P.parse_number(headers.get("anthropic-ratelimit-requests-limit")),
        "requestsRemaining": P.parse_number(headers.get("anthropic-ratelimit-requests-remaining")),
        "requestsReset": headers.get("anthropic-ratelimit-requests-reset"),
        "tokensLimit": P.parse_number(headers.get("anthropic-ratelimit-tokens-limit")),
        "tokensRemaining": P.parse_number(headers.get("anthropic-ratelimit-tokens-remaining")),
        "tokensReset": headers.get("anthropic-ratelimit-tokens-reset"),
    }


def map_status_code_to_reason(  # noqa: PLR0911
    *,
    status: int,
    now: float,
    headers: Mapping[str, str],
    message: str | None,
    metadata: AnthropicErrorMetadata,
    http: HttpContext,
) -> AnyReason:
    """The reason for a failed status (Effect's ``mapStatusCodeToReason``);
    ``now`` is the time in epoch milliseconds."""
    description = build_error_description(
        status=status,
        message=message,
        method=http["request"]["method"],
        url=http["request"]["url"],
        error_type=metadata["errorType"],
        request_id=metadata["requestId"],
        body=http.get("body"),
    )
    meta: dict[str, Any] = {"anthropic": {**metadata}}
    match status:
        case 400 | 404 | 422:
            return InvalidRequestError(description=description, metadata=meta, http=http)
        case 401:
            return AuthenticationError(
                kind="InvalidKey", description=description, metadata=meta, http=http
            )
        case 403:
            return AuthenticationError(
                kind="InsufficientPermissions", description=description, metadata=meta, http=http
            )
        case 429:
            delay, limits = parse_rate_limit_headers(headers, now)
            rate: dict[str, Any] = {**metadata, **limits}
            return RateLimitError(retry_after=delay, metadata={"anthropic": rate}, http=http)
        case 529:
            return InternalProviderError(
                description=P.or_default(message, "Anthropic API is overloaded"),
                metadata=meta,
                http=http,
            )
        case _ if status >= 500:
            return InternalProviderError(
                description=P.or_default(message, "Server error"), metadata=meta, http=http
            )
        case _:
            return UnknownError(description=message, metadata=meta, http=http)


def _fail(
    *,
    request: HttpClientRequest,
    response: HttpClientResponse,
    method: str,
    body: str | None,
    message: str | None,
    metadata: AnthropicErrorMetadata,
) -> Effect[Never, AiError]:
    def build(now: float) -> Effect[Never, AiError]:
        reason = map_status_code_to_reason(
            status=response.status,
            now=now,
            headers=response.headers,
            message=message,
            metadata=metadata,
            http=P.http_context(request, response, body),
        )
        return fx.fail(AiError(module=MODULE, method=method, reason=reason))

    return clock.now().flat_map(lambda seconds: build(seconds * 1000))


def map_client_error(
    error: W.ErrorResponse, response: HttpClientResponse, method: str
) -> Effect[Never, AiError]:
    """A 4xx response carrying Anthropic's error envelope."""
    metadata: AnthropicErrorMetadata = {
        "errorType": error["error"]["type"],
        "requestId": error["request_id"],
    }
    return _fail(
        request=response.request,
        response=response,
        method=method,
        body=P.dumps(error),
        message=error["error"]["message"],
        metadata=metadata,
    )


def map_status_code_error(reason: StatusCodeError, method: str) -> Effect[Never, AiError]:
    """A failed status without (or with) Anthropic's envelope."""
    response = reason.response

    def build(body: str | None) -> Effect[Never, AiError]:
        decoded = W.error_body(P.parse_json(body))
        message = None if decoded is None else decoded["error"]["message"]
        error_type = None if decoded is None else decoded["error"]["type"]
        metadata: AnthropicErrorMetadata = {
            "errorType": error_type,
            "requestId": response.headers.get("request-id"),
        }
        return _fail(
            request=reason.request,
            response=response,
            method=method,
            body=body,
            message=message,
            metadata=metadata,
        )

    return P.status_body(reason).flat_map(build)


ERRORS = P.ErrorMapper(MODULE, map_status_code_error)
