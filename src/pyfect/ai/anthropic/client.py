"""The Anthropic Messages API client (Effect's ``AnthropicClient``).

``layer(api_key=...)`` provides ``AnthropicClient`` over the ``HttpClient``
service; its requests carry the ``x-api-key`` (redacted in errors and
spans) and ``anthropic-version`` headers::

    client = yield from AnthropicClient()
    message, response = yield from client.create_message(
        {"model": "claude-sonnet-5-5", "max_tokens": 1024, "messages": [...]}
    )

Every failure is an ``AiError``: a status maps to its reason (a 429 to a
``RateLimitError`` with its ``Retry-After``), a malformed body to an
``InvalidResponseError``. ``create_message_stream`` streams the events of
a message until ``message_stop``.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Never, Protocol, TypedDict

import pyfect as fx
from pyfect import byte_size
from pyfect import layer as L
from pyfect import schema as S
from pyfect import stream as St
from pyfect._core import Effect
from pyfect.ai import _provider as P
from pyfect.ai.ai_error import AiError
from pyfect.ai.anthropic import _schema as W
from pyfect.ai.anthropic._errors import ERRORS, SECRET_HEADERS, map_client_error
from pyfect.ai.anthropic.config import AnthropicConfig, ClientTransform
from pyfect.byte_size import ByteSize
from pyfect.config import Config, ConfigError
from pyfect.context import Tag
from pyfect.http import body as http_body
from pyfect.http import request as http_request
from pyfect.http.client import HttpClient, HttpClientService, transform_response
from pyfect.http.error import HttpClientError, StatusCodeError
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value
from pyfect.stream import Stream

MessageStreamEvent = W.MessageStreamEvent
Message = W.Message

DEFAULT_API_URL = "https://api.anthropic.com"
DEFAULT_API_VERSION = "2023-06-01"
_redacted = P.with_redacted_headers(SECRET_HEADERS)
_decode_json = S.decode_unknown_effect(S.UnknownFromJsonString)


class MessageParams(TypedDict, total=False):
    """Request headers of a Messages call."""

    anthropic_beta: str
    anthropic_version: str


type Payload = Mapping[str, Any]
"""A Messages request body (Anthropic's ``BetaCreateMessageParams``)."""


class CreateMessage(Protocol):
    def __call__(
        self, payload: Payload, params: MessageParams | None = None, /
    ) -> Effect[tuple[W.Message, HttpClientResponse], AiError]: ...


class CreateMessageStream(Protocol):
    def __call__(
        self, payload: Payload, params: MessageParams | None = None, /
    ) -> Effect[tuple[HttpClientResponse, Stream[W.MessageStreamEvent, AiError]], AiError]: ...


@dataclass(frozen=True)
class Service:
    """The client: the configured ``HttpClient`` and the Messages calls."""

    http_client: HttpClientService[HttpClientError]
    create_message: CreateMessage
    create_message_stream: CreateMessageStream
    max_response_bytes: ByteSize = P.DEFAULT_MAX_RESPONSE_BYTES


class AnthropicClient(Tag[Service], key="@effect/ai-anthropic/AnthropicClient"):
    """The Anthropic client."""


def _headers(params: MessageParams | None, api_version: str | None) -> dict[str, str]:
    headers: dict[str, str] = {}
    beta = (params or {}).get("anthropic_beta")
    if beta is not None:
        headers["anthropic-beta"] = beta
    version = (params or {}).get("anthropic_version", api_version)
    if version is not None:
        headers["anthropic-version"] = version
    return headers


def _status_error(response: HttpClientResponse, description: str) -> HttpClientError:
    return HttpClientError(
        StatusCodeError(request=response.request, response=response, description=description)
    )


def _gateway_check(
    sending: Effect[HttpClientResponse, HttpClientError],
) -> Effect[HttpClientResponse, HttpClientError]:
    """A 4xx Messages response without Anthropic's envelope fails with its
    text, so the status mapping handles a gateway's error."""

    def check(response: HttpClientResponse) -> Effect[HttpClientResponse, HttpClientError]:
        status = response.status
        if (
            status < 400
            or status >= 500
            or not response.request.url.endswith("/v1/messages?beta=true")
        ):
            return fx.succeed(response)

        def decide(body: Any) -> Effect[HttpClientResponse, HttpClientError]:
            if body is not None and W.is_error_response(body.value):
                return fx.succeed(response)
            return response.text.or_else_succeed(lambda _: "Unexpected status code").flat_map(
                lambda text: fx.fail(_status_error(response, text))
            )

        return response.json.option().flat_map(decide)

    return sending.flat_map(check)


def _unexpected_status(response: HttpClientResponse) -> Effect[Never, HttpClientError]:
    return (
        response.json.map(lambda body: body if isinstance(body, str) else P.dumps(body))
        .or_else_succeed(lambda _: "Unexpected status code")
        .flat_map(lambda description: fx.fail(_status_error(response, description)))
    )


def _message_events(response: HttpClientResponse) -> Stream[W.MessageStreamEvent, AiError]:
    events: Stream[Any, Any] = (
        P.sse_events(response)
        .map_effect(lambda event: _decode_json(event.data).flat_map(W.decode_event))
        .take_until(lambda event: event["type"] == "message_stop")
        .filter(lambda event: event["type"] != "ping")
    )
    handle = ERRORS.catch("createMessageStream")
    return events.catch_all(lambda error: St.from_effect(handle(error)))


def make(
    *,
    api_key: Redacted[str] | None = None,
    api_url: str | None = None,
    api_version: str | None = None,
    transform_client: ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> Effect[Service, Never, HttpClient]:
    """An Anthropic client over the ``HttpClient`` service. Requests go to
    ``api_url`` (``https://api.anthropic.com``) with ``api_key`` as
    ``x-api-key`` (none when omitted, for proxies) and ``api_version`` as
    ``anthropic-version`` (``2023-06-01``); ``transform_client`` changes
    the underlying client (and so does an ``AnthropicConfig``, per call).
    A response body, or a streamed tool call's parameters, larger than
    ``max_response_bytes`` (256 MiB) fails the call."""
    version = api_version or DEFAULT_API_VERSION
    limit = P.response_limit(max_response_bytes)

    def prepare(request: http_request.HttpClientRequest) -> http_request.HttpClientRequest:
        request = request.prepend_url(api_url or DEFAULT_API_URL)
        if api_key is not None:
            request = request.set_header("x-api-key", redacted_value(api_key))
        return request.set_header("anthropic-version", version).accept_json()

    def build(base: HttpClientService[HttpClientError]) -> Service:
        mapped = base.map_request(prepare)
        http_client = mapped if transform_client is None else transform_client(mapped)
        limited = P.limit_responses(http_client, limit)
        generated = limited.pipe(transform_response(_gateway_check))
        client_ok = limited.filter_status_ok()

        def resolved() -> Effect[HttpClientService[HttpClientError]]:
            return P.resolve_client(AnthropicConfig, generated)

        def on_response(response: HttpClientResponse) -> Effect[Any, Any]:
            status = response.status
            if 200 <= status < 300:
                return response.json.flat_map(W.decode_message).map(lambda body: (body, response))
            if 400 <= status < 500:
                return response.json.flat_map(
                    lambda body: S.decode_unknown_effect(W.ERROR_RESPONSE)(body).flat_map(
                        lambda _: map_client_error(body, response, "createMessage")  # pyright: ignore[reportArgumentType]
                    )
                )
            return _unexpected_status(response)

        def create_message(
            payload: Payload, params: MessageParams | None = None
        ) -> Effect[tuple[W.Message, HttpClientResponse], AiError]:
            request = http_request.post(
                "/v1/messages?beta=true", headers=_headers(params, None)
            ).body_json_unsafe(payload)
            sent: Effect[Any, Any] = resolved().flat_map(
                lambda client: client.execute(request).flat_map(on_response)
            )
            return sent.catch_all(ERRORS.catch("createMessage")).pipe(_redacted)

        def create_message_stream(
            payload: Payload, params: MessageParams | None = None
        ) -> Effect[tuple[HttpClientResponse, Stream[W.MessageStreamEvent, AiError]], AiError]:
            body = http_body.json_unsafe({**payload, "stream": True})
            request = http_request.post(
                "/v1/messages", headers=_headers(params, version), body=body
            )
            sent: Effect[Any, Any] = client_ok.execute(request).map(
                lambda response: (response, _message_events(response))
            )
            return sent.catch_all(ERRORS.catch("createMessageStream")).pipe(_redacted)

        return Service(http_client, create_message, create_message_stream, limit)

    return HttpClient().map(build)


def layer(
    *,
    api_key: Redacted[str] | None = None,
    api_url: str | None = None,
    api_version: str | None = None,
    transform_client: ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> L.Layer[AnthropicClient, Never, HttpClient]:
    """``AnthropicClient`` from these options (see ``make``)."""
    return L.effect(
        AnthropicClient,
        make(
            api_key=api_key,
            api_url=api_url,
            api_version=api_version,
            transform_client=transform_client,
            max_response_bytes=max_response_bytes,
        ),
    )


def layer_config(
    *,
    api_key: Config[Redacted[str]] | Config[Redacted[str] | None] | None = None,
    api_url: Config[str] | None = None,
    api_version: Config[str] | None = None,
    transform_client: ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> L.Layer[AnthropicClient, ConfigError, HttpClient]:
    """``AnthropicClient`` with its options read from ``Config``."""
    built: Effect[Service, ConfigError, HttpClient] = fx.all(
        P.optional_config(api_key), P.optional_config(api_url), P.optional_config(api_version)
    ).flat_map(
        lambda values: make(
            api_key=values[0],
            api_url=values[1],
            api_version=values[2],
            transform_client=transform_client,
            max_response_bytes=max_response_bytes,
        )
    )
    return L.effect(AnthropicClient, built)


__all__ = [
    "DEFAULT_API_URL",
    "DEFAULT_API_VERSION",
    "AnthropicClient",
    "Message",
    "MessageParams",
    "MessageStreamEvent",
    "Payload",
    "Service",
    "layer",
    "layer_config",
    "make",
]
