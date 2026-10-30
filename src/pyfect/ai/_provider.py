"""The HTTP plumbing the AI providers share (each Effect provider package's
``internal/errors.ts``): request and response details for errors and
parts, the mapping of an ``HttpClientError`` to an ``AiError``, numbers
and ``Retry-After`` read from headers, and the SSE events of a response.
"""

from __future__ import annotations

import json
import math
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import timedelta
from typing import Any, Never, cast

import pyfect as fx
from pyfect import byte_size
from pyfect import schema as S
from pyfect._core import Effect
from pyfect._js import or_default
from pyfect._json_text import parse as parse_json_text
from pyfect.ai.ai_error import (
    AiError,
    HttpContext,
    HttpRequestDetails,
    HttpResponseDetails,
    InvalidOutputError,
    InvalidResponseError,
    NetworkError,
)
from pyfect.byte_size import ByteSize, mebibytes
from pyfect.context import Tag
from pyfect.encoding import sse
from pyfect.http import headers as H
from pyfect.http.client import HttpClientService, transform_response
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
from pyfect.http.response import HttpClientResponse, with_body_limit
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


DEFAULT_MAX_RESPONSE_BYTES: ByteSize = mebibytes(256)
"""The largest response body (or streamed tool call's parameters) a
provider client reads by default: room for a large embedding batch, but
not for a server that never stops sending."""

MAX_ERROR_BODY_BYTES: ByteSize = mebibytes(1)
"""The most of a failed response's body read into its ``AiError``."""


def response_limit(max_response_bytes: byte_size.Input | None) -> ByteSize:
    """``max_response_bytes`` parsed (the default when ``None``); raises
    ``ValueError`` when it is not a positive byte size."""
    if max_response_bytes is None:
        return DEFAULT_MAX_RESPONSE_BYTES
    size = byte_size.from_input_unsafe(max_response_bytes)
    if byte_size.is_zero(size):
        raise ValueError("max_response_bytes must be positive")
    return size


def _plain_headers(headers: H.Headers, secret_headers: Sequence[str]) -> dict[str, str]:
    names = (*current_redacted_names(), *secret_headers)
    return {k: str(v) for k, v in headers.redact(names).items()}


def request_details(
    request: HttpClientRequest, *, secret_headers: Sequence[str]
) -> HttpRequestDetails:
    """The request as an error or a response part shows it, its secret
    headers redacted: the current redacted names and the provider's
    ``secret_headers``, which are named here because a response part is
    built after the client's redaction scope has ended."""
    details: HttpRequestDetails = {
        "method": request.method,
        "url": request.url,
        "urlParams": [(k, str(v)) for k, v in request.url_params],
        "headers": _plain_headers(request.headers, secret_headers),
    }
    if request.hash is not None:
        details["hash"] = request.hash
    return details


def response_details(response: HttpClientResponse) -> HttpResponseDetails:
    return {"status": response.status, "headers": _plain_headers(response.headers, ())}


def http_context(
    request: HttpClientRequest,
    response: HttpClientResponse | None = None,
    body: str | None = None,
    *,
    secret_headers: Sequence[str],
) -> HttpContext:
    context: HttpContext = {"request": request_details(request, secret_headers=secret_headers)}
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
        return parse_json_text(text)
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


def limit_responses(
    client: HttpClientService[HttpClientError], max_bytes: ByteSize
) -> HttpClientService[HttpClientError]:
    """``client`` reading each response body under a limit: ``max_bytes``
    for a success, ``MAX_ERROR_BODY_BYTES`` for a failure (its body goes
    into an ``AiError``). Every provider request goes through it."""

    def limit(response: HttpClientResponse) -> HttpClientResponse:
        ok = 200 <= response.status < 300
        return with_body_limit(response, max_bytes if ok else MAX_ERROR_BODY_BYTES)

    return client.pipe(transform_response(lambda sending: sending.map(limit)))


def status_body(reason: StatusCodeError) -> Effect[str | None]:
    """The body of a failed response: its description when that is JSON,
    else the response's text."""
    description = reason.description
    if description and description.startswith("{"):
        return fx.succeed(description)
    return reason.response.text.option().map(
        lambda text: text.value if text is not None and text.value else description
    )


class TextBuffer:
    """Text built from streamed deltas (a tool call's parameters), in
    linear time and at most ``max_chars`` characters."""

    __slots__ = ("_max_chars", "_parts", "_size")

    def __init__(self, initial: str, max_chars: int) -> None:
        self._parts = [initial] if initial else []
        self._size = len(initial)
        self._max_chars = max_chars

    def add(self, delta: str) -> bool:
        """Append ``delta``; ``False`` (and nothing kept) past the limit."""
        if self._size + len(delta) > self._max_chars:
            return False
        self._parts.append(delta)
        self._size += len(delta)
        return True

    @property
    def empty(self) -> bool:
        return self._size == 0

    def text(self) -> str:
        if len(self._parts) > 1:
            self._parts = ["".join(self._parts)]
        return self._parts[0] if self._parts else ""


def too_large(module: str, method: str, max_chars: int) -> AiError:
    description = f"Streamed tool call parameters exceed {max_chars} characters"
    return AiError(module=module, method=method, reason=InvalidOutputError(description=description))


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
