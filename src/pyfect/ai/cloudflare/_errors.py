"""The mapping of a failed Cloudflare request to an ``AiError`` (Effect's
``internal/errors.ts`` in ``@effect/ai-cloudflare``): Cloudflare's
``errors`` envelope, the ``cf-ray`` request id, 404 and 422 as invalid
requests and a failure envelope on a 2xx as a provider error."""

from __future__ import annotations

from typing import Any, Never, TypedDict

import pyfect as fx
from pyfect import clock
from pyfect import schema as S
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai.ai_error import (
    AiError,
    AnyReason,
    InternalProviderError,
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
from pyfect.http.response import HttpClientResponse

MODULE = "CloudflareClient"
METHOD = "createDecisions"
SECRET_HEADERS = ("authorization",)


class _Error(TypedDict):
    code: float
    message: str


class _ErrorBody(TypedDict):
    errors: list[_Error]


_parse_error_body = P.wire_parser_option(S.Struct(_ErrorBody), _ErrorBody)


def fail(reason: AnyReason) -> Effect[Never, AiError]:
    return fx.fail(AiError(module=MODULE, method=METHOD, reason=reason))


def map_response_error(response: HttpClientResponse) -> Effect[Never, AiError]:
    """The ``AiError`` of a failed response, or of a failure envelope."""
    request, status = response.request, response.status

    def build(body: str | None, now: float) -> Effect[Never, AiError]:
        details = _parse_error_body(P.parse_json(body))
        errors = [] if details is None else details["errors"]
        http = P.http_context(request, response, body, secret_headers=SECRET_HEADERS)
        ray_id = response.headers.get("cf-ray")
        description = build_error_description(
            status=status,
            method=request.method,
            url=request.url,
            body=body,
            message=None if details is None else "; ".join(e["message"] for e in errors),
            error_code=None if not errors else _code(errors[0]["code"]),
            request_id=ray_id,
        )
        if status == 429:
            metadata: dict[str, Any] = {"cloudflare": {"rayId": ray_id, "errors": errors}}
            delay = P.retry_after(response.headers.get("retry-after"), now)
            return fail(RateLimitError(retry_after=delay, http=http, metadata=metadata))
        if status in (404, 422):
            return fail(InvalidRequestError(description=description, http=http))
        if 200 <= status < 300:
            return fail(InternalProviderError(description=description, http=http))
        return fail(reason_from_http_status(status=status, description=description, http=http))

    body = response.text.option().map(lambda text: None if text is None else text.value)
    return body.flat_map(lambda text: clock.now().flat_map(lambda s: build(text, s * 1000)))


def _code(code: float) -> int | str:
    return int(code) if float(code).is_integer() else str(code)


def map_error(error: object) -> Effect[Never, AiError]:
    """Client and schema failures as ``AiError``; an ``AiError`` passes."""
    match error:
        case HttpClientError(reason=TransportError() | EncodeError() | InvalidUrlError() as source):
            return fail(NetworkError.from_request_error(source))
        case HttpClientError(reason=DecodeError() | EmptyBodyError() as source):
            description = source.description or "Failed to decode Cloudflare response"
            return fail(InvalidOutputError(description=description))
        case HttpClientError(reason=StatusCodeError() as source):
            return map_response_error(source.response)
        case S.SchemaError():
            return fail(InvalidResponseError.from_schema_error(error))
        case _:
            return fx.fail(error)  # pyright: ignore[reportReturnType]
