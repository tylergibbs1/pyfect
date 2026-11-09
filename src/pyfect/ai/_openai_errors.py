"""The mapping of a failed OpenAI-style request to an ``AiError`` (Effect's
``internal/errors.ts`` in ``@effect/ai-openai-compat``). A ``Dialect``
holds what an OpenAI-style provider varies: the metadata key, how its
error body reads and what counts as an exhausted quota."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Never, NotRequired, TypedDict, cast

import pyfect as fx
from pyfect import clock
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai.ai_error import (
    AiError,
    AnyReason,
    AuthenticationError,
    HttpContext,
    InternalProviderError,
    InvalidRequestError,
    QuotaExhaustedError,
    RateLimitError,
    UnknownError,
    build_error_description,
)
from pyfect.http.error import StatusCodeError


class ErrorMetadata(TypedDict):
    """What a provider's error body and headers say about a failure."""

    errorCode: str | None
    errorType: str | None
    requestId: str | None


class RateLimitMetadata(ErrorMetadata):
    limit: str | None
    remaining: int | float | None
    resetRequests: str | None
    resetTokens: str | None


class _ErrorDetail(TypedDict):
    message: str
    type: NotRequired[str | None]
    status: NotRequired[str | None]
    param: NotRequired[str | None]
    code: NotRequired[str | int | float | None]


class ErrorBody(TypedDict):
    error: _ErrorDetail


_match_error_body = P.wire_match(S.Struct(ErrorBody), ErrorBody)


def is_error_body(json: object) -> bool:
    return _match_error_body(json) is not None


@dataclass(frozen=True)
class BodyInfo:
    message: str | None = None
    code: str | None = None
    type: str | None = None


def _code(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    return str(value)


def compat_body(json: object) -> BodyInfo:
    """The error body of an OpenAI-compatible server: an object, or the
    first of a non-empty array of them; its type is lower-cased and falls
    back to ``status``."""
    items = cast("list[object]", json) if isinstance(json, list) else [json]
    if not items or not all(is_error_body(item) for item in items):
        return BodyInfo()
    error = P.obj(P.obj(items[0]).get("error"))
    kind = error.get("type")
    if kind is None:
        kind = error.get("status")
    return BodyInfo(
        error["message"], _code(error.get("code")), None if kind is None else str(kind).lower()
    )


def compat_quota(metadata: ErrorMetadata) -> bool:
    kind = metadata["errorType"] or ""
    return (
        metadata["errorCode"] == "insufficient_quota"
        or kind == "insufficient_quota"
        or "quota" in kind
        or "exhausted" in kind
    )


def _status_body(reason: StatusCodeError) -> Effect[str | None]:
    """The failed response's text; when it cannot be read, its description
    if that is JSON."""
    description = reason.description
    fallback = description if description and description.startswith("{") else None
    return reason.response.text.or_else_succeed(lambda _: fallback)


@dataclass(frozen=True)
class Dialect:
    module: str
    metadata_key: str
    read_body: Callable[[object], BodyInfo]
    is_quota: Callable[[ErrorMetadata], bool]
    secret_headers: tuple[str, ...]
    """The headers carrying credentials: never shown, never sent across
    origins."""
    status_body: Callable[[StatusCodeError], Effect[str | None]] = _status_body
    """The body a failed response's error shows."""
    quota_statuses: frozenset[int] = frozenset()
    """Statuses that always mean an exhausted quota (OpenAI's 402)."""


COMPAT = Dialect(
    "OpenAiClient",
    "openai-compat",
    compat_body,
    compat_quota,
    ("authorization", "openai-organization", "openai-project"),
)


def parse_rate_limit_headers(headers: Mapping[str, str], now: float) -> tuple[Any, dict[str, Any]]:
    """The ``Retry-After`` delay and the ``x-ratelimit-*`` metadata."""
    return P.retry_after(headers.get("retry-after"), now), {
        "limit": headers.get("x-ratelimit-limit-requests"),
        "remaining": P.parse_number(headers.get("x-ratelimit-remaining-requests")),
        "resetRequests": headers.get("x-ratelimit-reset-requests"),
        "resetTokens": headers.get("x-ratelimit-reset-tokens"),
    }


def map_status_code_to_reason(  # noqa: PLR0911
    dialect: Dialect,
    *,
    status: int,
    now: float,
    headers: Mapping[str, str],
    message: str | None,
    metadata: ErrorMetadata,
    http: HttpContext,
) -> AnyReason:
    """The reason for a failed status (Effect's ``mapStatusCodeToReason``);
    ``now`` is the time in epoch milliseconds."""
    description = build_error_description(
        status=status,
        message=message,
        method=http["request"]["method"],
        url=http["request"]["url"],
        error_code=metadata["errorCode"],
        error_type=metadata["errorType"],
        request_id=metadata["requestId"],
        body=http.get("body"),
    )
    meta: dict[str, Any] = {dialect.metadata_key: {**metadata}}
    if status in dialect.quota_statuses:
        return QuotaExhaustedError(metadata=meta, http=http)
    match status:
        case 400 | 404 | 409 | 422:
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
            if dialect.is_quota(metadata):
                return QuotaExhaustedError(metadata=meta, http=http)
            delay, limits = parse_rate_limit_headers(headers, now)
            rate: dict[str, Any] = {dialect.metadata_key: {**metadata, **limits}}
            return RateLimitError(retry_after=delay, metadata=rate, http=http)
        case _ if status >= 500:
            return InternalProviderError(
                description=P.or_default(message, "Server error"), metadata=meta, http=http
            )
        case _:
            return UnknownError(description=message, metadata=meta, http=http)


def status_code_mapper(
    dialect: Dialect,
) -> Callable[[StatusCodeError, str], Effect[Never, AiError]]:
    def map_status(reason: StatusCodeError, method: str) -> Effect[Never, AiError]:
        response = reason.response

        def build(body: str | None, now: float) -> Effect[Never, AiError]:
            info = dialect.read_body(P.parse_json(body))
            metadata: ErrorMetadata = {
                "errorCode": info.code,
                "errorType": info.type,
                "requestId": response.headers.get("x-request-id"),
            }
            mapped = map_status_code_to_reason(
                dialect,
                status=response.status,
                now=now,
                headers=response.headers,
                message=info.message,
                metadata=metadata,
                http=P.http_context(
                    reason.request, response, body, secret_headers=dialect.secret_headers
                ),
            )
            return fx.fail(AiError(module=dialect.module, method=method, reason=mapped))

        return dialect.status_body(reason).flat_map(
            lambda body: clock.current_time_millis().flat_map(lambda now: build(body, now))
        )

    return map_status


def error_mapper(dialect: Dialect) -> P.ErrorMapper:
    return P.ErrorMapper(dialect.module, status_code_mapper(dialect))
