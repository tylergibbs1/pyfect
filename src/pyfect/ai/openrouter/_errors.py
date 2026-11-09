"""The mapping of a failed OpenRouter request to an ``AiError`` (Effect's
``internal/errors.ts`` in ``@effect/ai-openrouter``): a documented error
status of the generated client (its decoded body), or a status error
whose body may hold OpenRouter's ``{"error": {...}}`` envelope, under the
``openrouter`` metadata key. A 429 whose code or type is
``insufficient_quota`` is an exhausted quota; 529 is an overloaded API."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Never, NotRequired, TypedDict, cast

import pyfect as fx
from pyfect import clock
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.ai import _openai_errors as OE
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
from pyfect.ai.openrouter.error import OpenRouterErrorMetadata
from pyfect.ai.openrouter.generated.client import OpenRouterClientError
from pyfect.http.error import StatusCodeError

MODULE = "OpenRouterClient"
SECRET_HEADERS = ("authorization",)


class _ErrorDetail(TypedDict):
    message: str
    type: NotRequired[str | None]
    code: NotRequired[str | int | float | None]


class OpenRouterErrorBody(TypedDict):
    error: _ErrorDetail


_decode_body = P.wire_parser_option(
    S.Struct(
        OpenRouterErrorBody,
        error=S.Struct(
            _ErrorDetail,
            type=S.NullOr(S.String),
            code=S.NullOr(S.Union(S.String, S.Finite)),
        ),
    ),
    OpenRouterErrorBody,
)


def map_status_code_to_reason(  # noqa: PLR0911
    *,
    status: int,
    now: float,
    headers: Mapping[str, str],
    message: str | None,
    metadata: OpenRouterErrorMetadata,
    http: HttpContext,
) -> AnyReason:
    """The reason for a failed status (Effect's ``mapStatusCodeToReason``);
    ``now`` is the time in epoch milliseconds."""
    code = metadata["errorCode"]
    description = build_error_description(
        status=status,
        message=message,
        method=http["request"]["method"],
        url=http["request"]["url"],
        error_code=cast("str | int | None", code),
        error_type=metadata["errorType"],
        request_id=metadata["requestId"],
        body=http.get("body"),
    )
    meta: dict[str, Any] = {"openrouter": {**metadata}}
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
            if "insufficient_quota" in (code, metadata["errorType"]):
                return QuotaExhaustedError(metadata=meta, http=http)
            delay, limits = OE.parse_rate_limit_headers(headers, now)
            rate: dict[str, Any] = {"openrouter": {**metadata, **limits}}
            return RateLimitError(retry_after=delay, metadata=rate, http=http)
        case 529:
            return InternalProviderError(
                description=P.or_default(message, "OpenRouter API is overloaded"),
                metadata=meta,
                http=http,
            )
        case _ if status >= 500:
            return InternalProviderError(
                description=P.or_default(message, "Server error"), metadata=meta, http=http
            )
        case _:
            return UnknownError(description=message, metadata=meta, http=http)


def _fail(method: str, reason: AnyReason) -> Effect[Never, AiError]:
    return fx.fail(AiError(module=MODULE, method=method, reason=reason))


def _map_status(reason: StatusCodeError, method: str) -> Effect[Never, AiError]:
    response = reason.response

    def build(body: str | None, now: float) -> Effect[Never, AiError]:
        decoded = _decode_body(P.parse_json(body))
        error = None if decoded is None else decoded["error"]
        metadata: OpenRouterErrorMetadata = {
            "errorCode": None if error is None else error.get("code"),
            "errorType": None if error is None else error.get("type"),
            "requestId": response.headers.get("x-request-id"),
        }
        mapped = map_status_code_to_reason(
            status=response.status,
            now=now,
            headers=response.headers,
            message=None if error is None else error["message"],
            metadata=metadata,
            http=P.http_context(reason.request, response, body, secret_headers=SECRET_HEADERS),
        )
        return _fail(method, mapped)

    return P.status_body(reason).flat_map(
        lambda body: clock.current_time_millis().flat_map(lambda now: build(body, now))
    )


ERRORS = P.ErrorMapper(MODULE, _map_status)


def map_client_error(error: OpenRouterClientError, method: str) -> Effect[Never, AiError]:
    """A documented error status of the generated client: its decoded body
    is OpenRouter's error envelope."""
    cause: Mapping[str, Any] = error.cause
    detail: Mapping[str, Any] = cause["error"]
    response = error.response
    metadata: OpenRouterErrorMetadata = {
        "errorCode": detail.get("code"),
        "errorType": detail.get("type"),
        "requestId": response.headers.get("x-request-id"),
    }
    http = P.http_context(error.request, response, P.dumps(cause), secret_headers=SECRET_HEADERS)

    def build(now: float) -> Effect[Never, AiError]:
        reason = map_status_code_to_reason(
            status=response.status,
            now=now,
            headers=response.headers,
            message=detail["message"],
            metadata=metadata,
            http=http,
        )
        return _fail(method, reason)

    return clock.current_time_millis().flat_map(build)


def catch(method: str) -> Callable[[object], Effect[Never, AiError]]:
    """A handler for every failure of a request: a documented error status,
    client, schema and SSE errors become ``AiError``."""
    handle = ERRORS.catch(method)

    def run(error: object) -> Effect[Never, AiError]:
        if isinstance(error, OpenRouterClientError):
            return map_client_error(error, method)
        return handle(error)

    return run
