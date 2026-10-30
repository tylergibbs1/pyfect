"""The client of an OpenAI-compatible Chat Completions and Embeddings API
(Effect's ``OpenAiClient`` in ``@effect/ai-openai-compat``).

``layer(api_key=..., api_url=...)`` provides ``OpenAiClient`` over the
``HttpClient`` service; requests carry the key as a bearer token and the
optional ``openai-organization`` / ``openai-project`` headers (redacted in
errors and spans)::

    client = yield from OpenAiClient()
    completion, response = yield from client.create_response(
        {"model": "llama-3.3-70b", "messages": [{"role": "user", "content": "Hi"}]}
    )

Every failure is an ``AiError``. ``create_response_stream`` streams the
completion's chunks until ``[DONE]``; an event that is not a chunk arrives
as an ``UnknownEvent``.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Never

import pyfect as fx
from pyfect import byte_size
from pyfect import layer as L
from pyfect import stream as St
from pyfect._core import Effect
from pyfect._json_text import parse as parse_json_text
from pyfect.ai import _openai_errors as OE
from pyfect.ai import _provider as P
from pyfect.ai.ai_error import AiError
from pyfect.ai.openai_compat import _schema as W
from pyfect.ai.openai_compat.config import ClientTransform, OpenAiConfig
from pyfect.byte_size import ByteSize
from pyfect.config import Config, ConfigError
from pyfect.context import Tag
from pyfect.encoding import sse
from pyfect.http import request as http_request
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value
from pyfect.result import Err, Ok, Result
from pyfect.stream import Stream

ChatCompletion = W.ChatCompletion
EmbeddingResponse = W.EmbeddingResponse
StreamEvent = W.StreamEvent
UnknownEvent = W.UnknownEvent

DEFAULT_API_URL = "https://api.openai.com/v1"
ERRORS = OE.error_mapper(OE.COMPAT)
_redacted = P.with_redacted_headers(OE.COMPAT.secret_headers)

type Payload = Mapping[str, Any]
"""A Chat Completions or Embeddings request body."""


@dataclass(frozen=True)
class Service:
    """The client: the configured ``HttpClient`` and its calls."""

    http_client: HttpClientService[HttpClientError]
    create_response: Callable[
        [Payload], Effect[tuple[W.ChatCompletion, HttpClientResponse], AiError]
    ]
    create_response_stream: Callable[
        [Payload], Effect[tuple[HttpClientResponse, Stream[W.StreamEvent, AiError]], AiError]
    ]
    create_embedding: Callable[[Payload], Effect[W.EmbeddingResponse, AiError]]
    max_response_bytes: ByteSize = P.DEFAULT_MAX_RESPONSE_BYTES


class OpenAiClient(Tag[Service], key="@effect/ai-openai-compat/OpenAiClient"):
    """The OpenAI-compatible client."""


def _event(event: sse.Event) -> Result[W.StreamEvent, None]:
    if event.data == "[DONE]":
        return Ok("[DONE]")
    try:
        parsed = parse_json_text(event.data)
    except ValueError:
        return Err(None)
    return Ok(P.obj(parsed) if W.is_chunk(parsed) else W.UnknownEvent(parsed))  # pyright: ignore[reportReturnType]


def _events(response: HttpClientResponse) -> Stream[W.StreamEvent, AiError]:
    events: Stream[Any, Any] = (
        P.sse_events(response).filter_map(_event).take_until(lambda event: event == "[DONE]")
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
    """A client over the ``HttpClient`` service. Requests go to ``api_url``
    (``https://api.openai.com/v1``); ``transform_client`` changes the
    underlying client (and so does an ``OpenAiConfig``, per call). A
    response body, or a streamed tool call's arguments, larger than
    ``max_response_bytes`` (256 MiB) fails the call."""
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
        mapped = base.map_request(prepare)
        http_client = mapped if transform_client is None else transform_client(mapped)
        limited = P.limit_responses(http_client, limit)

        def send(path: str, payload: Payload) -> Effect[HttpClientResponse, HttpClientError]:
            request = http_request.post(path).body_json_unsafe(payload)
            return P.resolve_client(OpenAiConfig, limited).flat_map(
                lambda client: client.filter_status_ok().execute(request)
            )

        def create_response(
            payload: Payload,
        ) -> Effect[tuple[W.ChatCompletion, HttpClientResponse], AiError]:
            sent: Effect[Any, Any] = send("/chat/completions", payload).flat_map(
                lambda response: response.json.flat_map(W.decode_completion).map(
                    lambda body: (body, response)
                )
            )
            return sent.catch_all(ERRORS.catch("createResponse")).pipe(_redacted)

        def create_response_stream(
            payload: Payload,
        ) -> Effect[tuple[HttpClientResponse, Stream[W.StreamEvent, AiError]], AiError]:
            body = {**payload, "stream": True, "stream_options": {"include_usage": True}}
            sent: Effect[Any, Any] = send("/chat/completions", body).map(
                lambda response: (response, _events(response))
            )
            return sent.catch_all(ERRORS.catch("createResponseStream")).pipe(_redacted)

        def create_embedding(payload: Payload) -> Effect[W.EmbeddingResponse, AiError]:
            sent: Effect[Any, Any] = send("/embeddings", payload).flat_map(
                lambda response: response.json.flat_map(W.decode_embedding)
            )
            return sent.catch_all(ERRORS.catch("createEmbedding")).pipe(_redacted)

        return Service(
            http_client, create_response, create_response_stream, create_embedding, limit
        )

    return HttpClient().map(build)


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
    """``OpenAiClient`` with its options read from ``Config``."""
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


__all__ = [
    "DEFAULT_API_URL",
    "ERRORS",
    "ChatCompletion",
    "EmbeddingResponse",
    "OpenAiClient",
    "Payload",
    "Service",
    "StreamEvent",
    "UnknownEvent",
    "layer",
    "layer_config",
    "make",
]
