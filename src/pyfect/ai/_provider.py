"""The HTTP plumbing the AI providers share (each Effect provider package's
``internal/errors.ts``): request and response details for errors and
parts, the mapping of an ``HttpClientError`` to an ``AiError``, numbers
and ``Retry-After`` read from headers, and the SSE events of a response.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, Never, cast

import pyfect as fx
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._js import or_default
from pyfect.ai.ai_error import (
    AiError,
    HttpContext,
    HttpRequestDetails,
    HttpResponseDetails,
    InvalidOutputError,
    InvalidResponseError,
    NetworkError,
)
from pyfect.context import Tag
from pyfect.encoding import sse
from pyfect.http import headers as H
from pyfect.http.client import HttpClientService
from pyfect.http.error import (
    DecodeError,
    EmptyBodyError,
    EncodeError,
    HttpClientError,
    InvalidUrlError,
    StatusCodeError,
    TransportError,
)
from pyfect.http.headers import CurrentRedactedNames, current_redacted_names
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.result import Ok
from pyfect.stream import Stream

type JsonObject = dict[str, Any]
"""A JSON object read from or sent to a provider."""


def obj(value: object) -> JsonObject:
    """``value`` when it is a JSON object, else an empty one."""
    return cast("JsonObject", value) if isinstance(value, dict) else {}


def arr(value: object) -> list[Any]:
    """``value`` when it is a JSON array, else an empty one."""
    return cast("list[Any]", value) if isinstance(value, list) else []


def _plain_headers(headers: H.Headers) -> dict[str, str]:
    return {k: str(v) for k, v in headers.redact(current_redacted_names()).items()}


def request_details(request: HttpClientRequest) -> HttpRequestDetails:
    """The request as an error or a response part shows it, its secret
    headers redacted."""
    details: HttpRequestDetails = {
        "method": request.method,
        "url": request.url,
        "urlParams": [(k, str(v)) for k, v in request.url_params],
        "headers": _plain_headers(request.headers),
    }
    if request.hash is not None:
        details["hash"] = request.hash
    return details


def response_details(response: HttpClientResponse) -> HttpResponseDetails:
    return {"status": response.status, "headers": _plain_headers(response.headers)}


def http_context(
    request: HttpClientRequest,
    response: HttpClientResponse | None = None,
    body: str | None = None,
) -> HttpContext:
    context: HttpContext = {"request": request_details(request)}
    if response is not None:
        context["response"] = response_details(response)
    if body is not None:
        context["body"] = body
    return context


def parse_number(raw: str | None) -> int | float | None:
    """A header's number (Effect's ``Number.parse``), ``None`` when absent
    or not a number."""
    if raw is None or raw.strip() == "":
        return None
    try:
        value = float(raw)
    except ValueError:
        return None
    if math.isnan(value) or math.isinf(value):
        return None
    return int(value) if value.is_integer() else value


def retry_after(raw: str | None, now_millis: float) -> timedelta | None:
    """The delay a ``Retry-After`` header asks for; an invalid one is
    absent."""
    if raw is None:
        return None
    parsed = H.parse_retry_after(raw)
    if not isinstance(parsed, Ok):
        return None
    return timedelta(seconds=H.retry_after_delay(parsed.value, now_millis))


def parse_json(text: str | None) -> object:
    """``text`` as JSON, or ``None``."""
    if text is None:
        return None
    try:
        return json.loads(text)
    except ValueError:
        return None


def dumps(value: object) -> str:
    """JSON as JavaScript's ``JSON.stringify`` writes it."""
    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def with_redacted_headers[A, E, R](
    names: tuple[str, ...],
) -> Callable[[Effect[A, E, R]], Effect[A, E, R]]:
    """Run an effect with ``names`` added to the redacted header names."""
    return lambda effect: effect.update_service(
        CurrentRedactedNames, lambda current: (*current, *names)
    )


@dataclass(frozen=True)
class ErrorMapper:
    """A provider's mapping of client failures to ``AiError``: its
    ``module`` name and the mapping of a status-code failure."""

    module: str
    status: Callable[[StatusCodeError, str], Effect[Never, AiError]]

    def error(self, method: str, reason: Any) -> AiError:
        return AiError(module=self.module, method=method, reason=reason)

    def schema_error(self, error: S.SchemaError, method: str) -> AiError:
        return self.error(method, InvalidResponseError.from_schema_error(error))

    def sse_error(self, error: sse.SseError, method: str) -> AiError:
        return self.error(method, InvalidResponseError(description=error.message))

    def http_error(self, error: HttpClientError, method: str) -> Effect[Never, AiError]:
        reason = error.reason
        match reason:
            case TransportError() | EncodeError() | InvalidUrlError():
                return fx.fail(self.error(method, NetworkError.from_request_error(reason)))
            case StatusCodeError():
                return self.status(reason, method)
            case DecodeError():
                description = or_default(reason.description, "Failed to decode response")
                return fx.fail(self.error(method, InvalidOutputError(description=description)))
            case EmptyBodyError():
                description = or_default(reason.description, "Response body was empty")
                return fx.fail(self.error(method, InvalidOutputError(description=description)))

    def catch(self, method: str) -> Callable[[object], Effect[Never, AiError]]:
        """A handler for every failure of a request: client and schema
        errors become ``AiError``, an ``AiError`` passes through."""

        def handle(error: object) -> Effect[Never, AiError]:
            if isinstance(error, HttpClientError):
                return self.http_error(error, method)
            if isinstance(error, S.SchemaError):
                return fx.fail(self.schema_error(error, method))
            if isinstance(error, sse.SseError):
                return fx.fail(self.sse_error(error, method))
            if isinstance(error, sse.Retry):
                return fx.die(RuntimeError(f"Unexpected SSE retry directive: {error!r}"))
            return fx.fail(error)  # pyright: ignore[reportReturnType]

        return handle


def status_body(reason: StatusCodeError) -> Effect[str | None]:
    """The body of a failed response: its description when that is JSON,
    else the response's text."""
    description = reason.description
    if description and description.startswith("{"):
        return fx.succeed(description)
    return reason.response.text.option().map(
        lambda text: text.value if text is not None and text.value else description
    )


def header(headers: Mapping[str, str], name: str) -> str | None:
    return headers.get(name)


def sse_events(
    response: HttpClientResponse,
) -> Stream[sse.Event, HttpClientError | sse.Retry | sse.SseError]:
    """The response body read as Server-Sent Events."""
    return response.stream.decode_text().pipe_through_channel(sse.decode())


type ClientTransform = Callable[
    [HttpClientService[HttpClientError]], HttpClientService[HttpClientError]
]
"""A change to a provider's HTTP client."""


@dataclass(frozen=True)
class ClientConfig:
    """A provider's per-request client overrides (Effect's
    ``AnthropicConfig`` / ``OpenAiConfig`` services)."""

    transform_client: ClientTransform | None = None


def client_config(tag: type[Tag[ClientConfig]]) -> Effect[ClientConfig | None]:
    """The provided ``tag`` service, else ``None``."""
    return fx.service_option(tag).map(lambda found: None if found is None else found.value)


def resolve_client(
    tag: type[Tag[ClientConfig]], client: HttpClientService[HttpClientError]
) -> Effect[HttpClientService[HttpClientError]]:
    """``client`` through the provided ``tag`` service's transform."""
    return client_config(tag).map(
        lambda config: (
            client
            if config is None or config.transform_client is None
            else config.transform_client(client)
        )
    )


class WithClientTransform:
    """Run an effect with ``tag``'s ``transform_client`` set. Use with
    ``.pipe``."""

    __slots__ = ("tag", "transform")

    def __init__(self, tag: type[Tag[ClientConfig]], transform: ClientTransform) -> None:
        self.tag = tag
        self.transform = transform

    def __call__[A, E, R](self, effect: Effect[A, E, R]) -> Effect[A, E, R]:
        def run(config: ClientConfig | None) -> Effect[A, E, R]:
            service = replace(config or ClientConfig(), transform_client=self.transform)
            return effect.pipe(fx.provide_service(self.tag, service))

        return client_config(self.tag).flat_map(run)


class WithConfigOverride[C: Mapping[str, Any]]:
    """Run an effect with ``overrides`` merged over the provided ``tag``
    config. Use with ``.pipe``."""

    __slots__ = ("overrides", "tag")

    def __init__(self, tag: type[Tag[C]], overrides: C) -> None:
        self.tag = tag
        self.overrides = overrides

    def __call__[A, E, R](self, effect: Effect[A, E, R]) -> Effect[A, E, R]:
        def run(found: Any) -> Effect[A, E, R]:
            current: Mapping[str, Any] = {} if found is None else found.value
            merged = cast("C", {**current, **self.overrides})
            return effect.pipe(fx.provide_service(self.tag, merged))

        return fx.service_option(self.tag).flat_map(run)


def current_config[C: Mapping[str, Any]](
    tag: type[Tag[C]], *defaults: Mapping[str, Any] | None
) -> Effect[C]:
    """``defaults`` merged left to right, then the provided ``tag`` config."""

    def merge(found: Any) -> C:
        merged: dict[str, Any] = {}
        for config in (*defaults, None if found is None else found.value):
            if config is not None:
                merged.update(config)
        return cast("C", merged)

    return fx.service_option(tag).map(merge)


def optional_config[A](config: Effect[A, Any] | None) -> Effect[A | None, Any]:
    """A ``Config`` value, or ``None`` when it was not given."""
    return fx.succeed(None) if config is None else config
