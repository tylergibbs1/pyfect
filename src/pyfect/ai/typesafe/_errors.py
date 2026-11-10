"""The mapping of a failed TypeSafe request to an ``AiError`` (Effect's
``internal/errors.ts`` in ``@effect/ai-typesafe``): TypeSafe's
``{message, type, code}`` body, the ``x-typesafe-request-id`` header, 404
and 422 as invalid requests and ``retry-after-ms`` before ``Retry-After``."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import timedelta
from typing import Any, Never, NotRequired, TypedDict

import pyfect as fx
from pyfect import clock
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai.ai_error import (
    AiError,
    AnyReason,
    InvalidOutputError,
    InvalidRequestError,
    InvalidResponseError,
    NetworkError,
    RateLimitError,
    build_error_description,
    reason_from_http_status,
)
from pyfect.http.error import (
    DecodeError,
    EmptyBodyError,
    EncodeError,
    HttpClientError,
    InvalidUrlError,
    StatusCodeError,
    TransportError,
)

MODULE = "TypeSafeClient"
SECRET_HEADERS = ("authorization",)
_REQUEST_ID = "x-typesafe-request-id"


class _ErrorBody(TypedDict):
    message: NotRequired[str]
    type: NotRequired[str]
    code: NotRequired[str]


_parse_error_body = P.wire_parser_option(S.Struct(_ErrorBody), _ErrorBody)


def _fail(method: str, reason: AnyReason) -> Effect[Never, AiError]:
    return fx.fail(AiError(module=MODULE, method=method, reason=reason))


def _retry_after(headers: Mapping[str, str], now: float) -> timedelta | None:
    millis = P.parse_number(headers.get("retry-after-ms"))
    if millis is not None and millis >= 0:
        return timedelta(milliseconds=millis)
    return P.retry_after(headers.get("retry-after"), now)


def _status_error(source: StatusCodeError, method: str) -> Effect[Never, AiError]:
    request, response = source.request, source.response

    def build(body: str | None, now: float) -> Effect[Never, AiError]:
        details = _parse_error_body(P.parse_json(body)) or _ErrorBody()
        http = P.http_context(response, body)
        request_id = response.headers.get(_REQUEST_ID)
        status = response.status
        description = build_error_description(
            status=status,
            method=request.method,
            url=request.url,
            body=body,
            message=details.get("message"),
            error_code=details.get("code"),
            error_type=details.get("type"),
            request_id=request_id,
        )
        if status == 429:
            metadata: dict[str, Any] = {
                "typesafe": {
                    "requestId": request_id,
                    "errorCode": details.get("code"),
                    "errorType": details.get("type"),
                }
            }
            delay = _retry_after(response.headers, now)
            return _fail(method, RateLimitError(retry_after=delay, http=http, metadata=metadata))
        if status in (404, 422):
            return _fail(method, InvalidRequestError(description=description, http=http))
        reason = reason_from_http_status(status=status, description=description, http=http)
        return _fail(method, reason)

    body = response.text.or_else_succeed(lambda _: source.description)
    return body.flat_map(
        lambda text: clock.current_time_millis().flat_map(lambda now: build(text, now))
    )


def mapper(method: str) -> Callable[[object], Effect[Never, AiError]]:
    """A handler of ``method``'s failures: client and schema errors become
    ``AiError``; an ``AiError`` passes."""

    def handle(error: object) -> Effect[Never, AiError]:
        match error:
            case HttpClientError(reason=TransportError() | EncodeError() | InvalidUrlError()):
                return _fail(method, NetworkError.from_http_client_error(error))
            case HttpClientError(reason=DecodeError() | EmptyBodyError() as source):
                description = source.description or "Failed to decode TypeSafe response"
                return _fail(method, InvalidOutputError(description=description))
            case HttpClientError(reason=StatusCodeError() as source):
                return _status_error(source, method)
            case S.SchemaError():
                return _fail(method, InvalidResponseError.from_schema_error(error))
            case _:
                return fx.fail(error)  # pyright: ignore[reportReturnType]

    return handle
