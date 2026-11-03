"""The OpenAI client (Effect's ``OpenAiClient``): the Responses API,
embeddings and decisions over the ``HttpClient`` service, and the
Responses API's WebSocket mode.

``layer(api_key=...)`` provides ``OpenAiClient``; requests go to
``api_url`` (``https://api.openai.com/v1``) with the key as a bearer token
and the optional ``openai-organization`` / ``openai-project`` headers,
which errors and spans show redacted::

    client = yield from OpenAiClient()
    body, response = yield from client.create_response({"model": "gpt-5", "input": "Hi"})

Every failure is an ``AiError``. ``create_response_stream`` streams the
response's events until ``response.completed``, ``response.incomplete`` or
``response.failed``; an event of a type this library does not read
arrives as it came.

``with_web_socket_mode`` (or ``layer_web_socket_mode``) sends response
streams over one WebSocket connection to ``/responses`` instead, one
request at a time; it needs a ``WebSocketConstructor`` that sends headers
(``pyfect.socket.ws``). A connection left mid-response, or that answers an
error event, is replaced for the next request.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Never

import pyfect as fx
from pyfect import byte_size
from pyfect import layer as L
from pyfect import stream as St
from pyfect._core import Effect
from pyfect._json_text import parse as parse_json_text
from pyfect.ai import _provider as P
from pyfect.ai import ai_error as E
from pyfect.ai import response_id_tracker as RIT
from pyfect.ai.ai_error import AiError
from pyfect.ai.openai import _schema as W
from pyfect.ai.openai import _web_socket as WS
from pyfect.ai.openai._errors import ERRORS, OPENAI
from pyfect.ai.openai._web_socket import ResponseStream, SocketService
from pyfect.ai.openai.config import ClientTransform, OpenAiConfig
from pyfect.byte_size import ByteSize
from pyfect.config import Config, ConfigError
from pyfect.context import Context, Tag
from pyfect.encoding import sse
from pyfect.http import request as http_request
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value
from pyfect.scope import Scope
from pyfect.socket import WebSocketConstructor
from pyfect.stream import Stream

CreateResponse = W.CreateResponse
CreateEmbeddingRequest = W.CreateEmbeddingRequest
CreateDecisionsRequest = W.CreateDecisionsRequest
Response = W.Response
ResponseStreamEvent = W.ResponseStreamEvent

DEFAULT_API_URL = "https://api.openai.com/v1"
_redacted = P.with_redacted_headers(OPENAI.secret_headers)


@dataclass(frozen=True)
class Service:
    """The client: the configured ``HttpClient`` and its calls."""

    http_client: HttpClientService[HttpClientError]
    create_response: Callable[
        [W.CreateResponse], Effect[tuple[W.Response, HttpClientResponse], AiError]
    ]
    create_response_stream: Callable[[W.CreateResponse], Effect[ResponseStream, AiError]]
    create_embedding: Callable[
        [W.CreateEmbeddingRequest], Effect[W.CreateEmbeddingResponse, AiError]
    ]
    create_decisions: Callable[
        [W.CreateDecisionsRequest], Effect[W.CreateDecisionsResponse, AiError]
    ]
    max_response_bytes: ByteSize = P.DEFAULT_MAX_RESPONSE_BYTES


class OpenAiClient(Tag[Service], key="@effect/ai-openai/OpenAiClient"):
    """The OpenAI client."""


def _sse_event(event: sse.Event) -> Effect[W.ResponseStreamEvent, Any]:
    try:
        parsed = parse_json_text(event.data)
    except ValueError as error:
        return fx.fail(
            AiError(
                module="OpenAiClient",
                method="createResponseStream",
                reason=E.InvalidResponseError(description=f"Invalid JSON in stream event: {error}"),
            )
        )
    return W.decode_event(parsed)


def _events(response: HttpClientResponse) -> Stream[W.ResponseStreamEvent, AiError]:
    events: Stream[Any, Any] = (
        P.sse_events(response)
        # Some OpenAI-compatible servers end the stream with `data: [DONE]`.
        .take_while(lambda event: event.data != "[DONE]")
        .map_effect(_sse_event)
        .take_until(lambda event: event.get("type") in W.TERMINAL_EVENT_TYPES)
    )
    handle = ERRORS.catch("createResponseStream")
    return events.catch_all(lambda error: St.from_effect(handle(error)))


def make(
    *,
    api_key: Redacted[str] | None = None,
    api_url: str | None = None,
    organization_id: Redacted[str] | None = None,
    project_id: Redacted[str] | None = None,
    transform_client: ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> Effect[Service, Never, HttpClient]:
    """A client over the ``HttpClient`` service. ``transform_client``
    changes the underlying client, before a provided ``OpenAiConfig``'s
    transform. A response body larger than ``max_response_bytes``
    (256 MiB) fails the call."""
    limit = P.response_limit(max_response_bytes)

    def prepare(request: http_request.HttpClientRequest) -> http_request.HttpClientRequest:
        request = request.prepend_url(api_url or DEFAULT_API_URL)
        if api_key is not None:
            request = request.bearer_token(redacted_value(api_key))
        if organization_id is not None:
            request = request.set_header("openai-organization", redacted_value(organization_id))
        if project_id is not None:
            request = request.set_header("openai-project", redacted_value(project_id))
        return request.accept_json()

    def build(base: HttpClientService[HttpClientError]) -> Service:
        mapped = base.map_request(prepare).filter_status_ok()
        http_client = mapped if transform_client is None else transform_client(mapped)
        limited = P.limit_responses(http_client, limit)

        def send(path: str, payload: object) -> Effect[HttpClientResponse, HttpClientError]:
            request = http_request.post(path).body_json_unsafe(payload)
            return P.resolve_client(OpenAiConfig, limited).flat_map(
                lambda client: client.execute(request)
            )

        def create_response(
            payload: W.CreateResponse,
        ) -> Effect[tuple[W.Response, HttpClientResponse], AiError]:
            sent: Effect[Any, Any] = send("/responses", payload).flat_map(
                lambda response: response.json.flat_map(W.decode_response).map(
                    lambda body: (body, response)
                )
            )
            return sent.catch_all(ERRORS.catch("createResponse")).pipe(_redacted)

        def over_http(payload: W.CreateResponse) -> Effect[ResponseStream, AiError]:
            body = {**payload, "stream": True}
            sent: Effect[Any, Any] = send("/responses", body).map(
                lambda response: (response, _events(response))
            )
            return sent.catch_all(ERRORS.catch("createResponseStream")).pipe(_redacted)

        def create_response_stream(payload: W.CreateResponse) -> Effect[ResponseStream, AiError]:
            return fx.service_option(OpenAiSocket).flat_map(
                lambda socket: (
                    over_http(payload)
                    if socket is None
                    else socket.value.create_response_stream(payload)
                )
            )

        def post_json[T](
            path: str, decode: Callable[[object], Effect[T, Any]], method: str
        ) -> Callable[[Any], Effect[T, AiError]]:
            def call(payload: Any) -> Effect[T, AiError]:
                sent: Effect[Any, Any] = send(path, payload).flat_map(
                    lambda response: response.json.flat_map(decode)
                )
                return sent.catch_all(ERRORS.catch(method)).pipe(_redacted)

            return call

        return Service(
            http_client,
            create_response,
            create_response_stream,
            post_json("/embeddings", W.decode_embedding, "createEmbedding"),
            post_json("/decisions", W.decode_decisions, "createDecisions"),
            limit,
        )

    return HttpClient().map(build).pipe(_redacted)


def layer(
    *,
    api_key: Redacted[str] | None = None,
    api_url: str | None = None,
    organization_id: Redacted[str] | None = None,
    project_id: Redacted[str] | None = None,
    transform_client: ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> L.Layer[OpenAiClient, Never, HttpClient]:
    """``OpenAiClient`` from these options (see ``make``)."""
    return L.effect(
        OpenAiClient,
        make(
            api_key=api_key,
            api_url=api_url,
            organization_id=organization_id,
            project_id=project_id,
            transform_client=transform_client,
            max_response_bytes=max_response_bytes,
        ),
    )


def layer_config(
    *,
    api_key: Config[Redacted[str]] | Config[Redacted[str] | None] | None = None,
    api_url: Config[str] | None = None,
    organization_id: Config[Redacted[str]] | Config[Redacted[str] | None] | None = None,
    project_id: Config[Redacted[str]] | Config[Redacted[str] | None] | None = None,
    transform_client: ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> L.Layer[OpenAiClient, ConfigError, HttpClient]:
    """``OpenAiClient`` with the given options read from ``Config``."""
    built: Effect[Service, ConfigError, HttpClient] = fx.all(
        P.optional_config(api_key),
        P.optional_config(api_url),
        P.optional_config(organization_id),
        P.optional_config(project_id),
    ).flat_map(
        lambda values: make(
            api_key=values[0],
            api_url=values[1],
            organization_id=values[2],
            project_id=values[3],
            transform_client=transform_client,
            max_response_bytes=max_response_bytes,
        )
    )
    return L.effect(OpenAiClient, built)


# --- WebSocket mode ---------------------------------------------------------------------


class OpenAiSocket(Tag[SocketService], key="@effect/ai-openai/OpenAiClient/OpenAiSocket"):
    """WebSocket mode: while provided, response streams use it."""


type _SocketServices = OpenAiSocket | RIT.ResponseIdTracker


def _make_socket() -> Effect[
    Context[_SocketServices], Never, OpenAiClient | WebSocketConstructor | Scope
]:
    def build(client: Service) -> Effect[Context[_SocketServices], Never, Any]:
        connect = WS.make(P.resolve_client(OpenAiConfig, client.http_client))
        return connect.map(
            lambda made: Context.make(OpenAiSocket, made[0]).add(RIT.ResponseIdTracker, made[1])
        )

    return OpenAiClient().flat_map(build)


def layer_web_socket_mode() -> L.Layer[_SocketServices, Never, OpenAiClient | WebSocketConstructor]:
    """WebSocket mode for every response stream made with this layer: one
    connection at a time, reopened when it closes, with the response id
    tracker it clears. Needs a ``WebSocketConstructor`` that sends headers."""
    return L.effect_context(_make_socket())


with_web_socket_mode = L.provide(layer_web_socket_mode(), local=True)
"""Run an effect with its response streams over WebSocket mode; the
connection closes when it ends (Effect's ``withWebSocketMode``). Use with
``.pipe``: ``effect.pipe(client.with_web_socket_mode)``."""


__all__ = [
    "DEFAULT_API_URL",
    "CreateDecisionsRequest",
    "CreateEmbeddingRequest",
    "CreateResponse",
    "OpenAiClient",
    "OpenAiSocket",
    "Response",
    "ResponseStream",
    "ResponseStreamEvent",
    "Service",
    "SocketService",
    "layer",
    "layer_config",
    "layer_web_socket_mode",
    "make",
    "with_web_socket_mode",
]
