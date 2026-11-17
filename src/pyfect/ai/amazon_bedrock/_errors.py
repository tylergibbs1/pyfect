"""Amazon Bedrock's mapping of failed requests to ``AiError`` (Effect's
``internal/errors.ts``)."""

from __future__ import annotations

from typing import Never, TypedDict

import pyfect as fx
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai.ai_error import (
    AiError,
    AnyReason,
    AuthenticationError,
    AuthenticationKind,
    HttpContext,
    InternalProviderError,
    InvalidRequestError,
    InvalidResponseError,
    QuotaExhaustedError,
    RateLimitError,
    UnknownError,
)
from pyfect.ai.amazon_bedrock._event_stream import EventStreamError
from pyfect.http.error import StatusCodeError

MODULE = "AmazonBedrockClient"
SECRET_HEADERS = ("x-amz-security-token",)
"""The session token header, redacted wherever headers are shown."""


def make(method: str, reason: AnyReason) -> AiError:
    return AiError(module=MODULE, method=method, reason=reason)


def map_event_stream_error(error: EventStreamError, method: str) -> AiError:
    return make(method, InvalidResponseError(description=error.description))


def map_stream_exception(exception_type: str, message: str | None, method: str) -> AiError:
    """An exception frame of a ConverseStream response (a
    ``throttlingException``, ...) as the reason its REST counterpart has."""
    description = exception_type if message is None else f"{exception_type}: {message}"
    if exception_type == "throttlingException":
        return make(method, RateLimitError())
    if exception_type == "validationException":
        return make(method, InvalidRequestError(description=description))
    return make(method, InternalProviderError(description=description))


class _ErrorBody(TypedDict, total=False):
    """A Bedrock REST error body: ``{"message": ...}``, in either casing."""

    message: str
    Message: str


_error_body = P.wire_match(S.Struct(_ErrorBody), _ErrorBody)

_AUTHENTICATION_KINDS: dict[str, AuthenticationKind] = {
    "AccessDeniedException": "InsufficientPermissions",
    "ExpiredTokenException": "ExpiredKey",
    "IncompleteSignatureException": "InvalidKey",
    "InvalidSignatureException": "InvalidKey",
    "MissingAuthenticationTokenException": "MissingKey",
    "UnrecognizedClientException": "InvalidKey",
}
"""Bedrock answers 403 for a bad key, an expired session token and a model
the account may not use alike; the exception type tells them apart."""


def map_status_code_to_reason(  # noqa: PLR0911
    *,
    status: int,
    request_method: str,
    url: str,
    message: str | None,
    error_type: str | None,
    http: HttpContext,
) -> AnyReason:
    """The reason for a failed status (Effect's ``mapStatusCodeToReason``)."""
    # Sent with a 400, but the request is well formed: a quota is used up.
    if error_type == "ServiceQuotaExceededException":
        return QuotaExhaustedError(http=http)

    def describe(text: str | None) -> str | None:
        if error_type is None:
            return text
        return error_type if text is None else f"{error_type}: {text}"

    match status:
        case 400 | 404 | 422:
            summary = P.or_default(message, f"HTTP {status}")
            return InvalidRequestError(
                description=describe(f"{summary} ({request_method} {url})"), http=http
            )
        case 401 | 403:
            kind = None if error_type is None else _AUTHENTICATION_KINDS.get(error_type)
            if kind is None:
                kind = "InvalidKey" if status == 401 else "InsufficientPermissions"
            return AuthenticationError(kind=kind, description=describe(message), http=http)
        case 408 | 424:
            # ModelTimeoutException and ModelErrorException.
            return InternalProviderError(
                description=P.or_default(describe(message), "Model error"), http=http
            )
        case 429:
            return RateLimitError(http=http)
        case _ if status >= 500:
            return InternalProviderError(
                description=P.or_default(describe(message), "Server error"), http=http
            )
        case _:
            return UnknownError(description=describe(message), http=http)


def map_status_code_error(reason: StatusCodeError, method: str) -> Effect[Never, AiError]:
    response = reason.response

    def build(body: str | None) -> Effect[Never, AiError]:
        decoded = _error_body(P.parse_json(body))
        message = None if decoded is None else decoded.get("message", decoded.get("Message"))
        # AWS sends the type as `Name:http://internal.amazon.com/coral/...`.
        error_type = response.headers.get("x-amzn-errortype")
        return fx.fail(
            make(
                method,
                map_status_code_to_reason(
                    status=response.status,
                    request_method=reason.request.method,
                    url=reason.request.url,
                    message=message,
                    error_type=None if error_type is None else error_type.split(":")[0],
                    http=P.http_context(response, body),
                ),
            )
        )

    return P.status_body(reason).flat_map(build)


ERRORS = P.ErrorMapper(MODULE, map_status_code_error)
