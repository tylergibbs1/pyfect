"""The OpenRouter client (Effect's ``OpenRouterClient``): chat completions,
streamed chat completions and alpha decisions over the ``HttpClient``
service, with the generated client of every operation as ``client``.

``layer(api_key=...)`` provides ``OpenRouterClient``; requests go to
``api_url`` (``https://openrouter.ai/api/v1``) with the key as a bearer
token (redacted in errors and spans) and the optional ``HTTP-Referer`` /
``X-Title`` site ranking headers::

    client = yield from OpenRouterClient()
    completion, response = yield from client.create_chat_completion(
        {"model": "openai/gpt-4o-mini", "messages": [{"role": "user", "content": "Hi"}]}
    )

Every failure is an ``AiError``. Decisions go to ``/alpha/decisions``
next to the versioned API (a trailing ``/v1`` of ``api_url`` is dropped).
An ``OpenRouterConfig`` transform applies to the generated client's
operations and to decisions, not to streamed chat completions.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Never, Self, final

import pyfect as fx
from pyfect import byte_size
from pyfect import layer as L
from pyfect import stream as St
from pyfect._core import Effect
from pyfect._json_text import parse as parse_json_text
from pyfect._service_copy import replaced
from pyfect.ai import _provider as P
from pyfect.ai.ai_error import AiError, InvalidRequestError
from pyfect.ai.openrouter import _errors as Errors
from pyfect.ai.openrouter import generated as G
from pyfect.ai.openrouter import schema as W
from pyfect.ai.openrouter.config import ClientTransform, OpenRouterConfig
from pyfect.ai.openrouter.generated import client as generated_client
from pyfect.ai.openrouter.generated import types as GT
from pyfect.byte_size import ByteSize
from pyfect.config import Config, ConfigError
from pyfect.context import Tag
from pyfect.encoding import sse
from pyfect.http import request as http_request
from pyfect.http.body import HttpBodyError
from pyfect.http.client import HttpClient, HttpClientService
from pyfect.http.error import HttpClientError
from pyfect.http.response import HttpClientResponse
from pyfect.redacted import Redacted
from pyfect.redacted import value as redacted_value
from pyfect.result import Err, Ok, Result
from pyfect.stream import Stream

DEFAULT_API_URL = "https://openrouter.ai/api/v1"

type ChatRequest = GT.ChatRequest
type ChatResult = GT.ChatResult
type ChatStreamChunk = GT.ChatStreamChunk
"""A streamed chat completion chunk (Effect's
``ChatStreamingResponseChunkData``); it may carry an ``error``."""

type ChatCompletion = Effect[tuple[GT.ChatResult, HttpClientResponse], AiError]
type ChatCompletionStream = Effect[
    tuple[HttpClientResponse, Stream[GT.ChatStreamChunk, AiError]], AiError
]
type Decisions = Effect[tuple[W.DecisionsResponse, HttpClientResponse], AiError]


@final
class Service:
    """The client: the generated client of every operation and the calls
    the models make. ``make`` builds it; ``Service(client,
    create_decisions, ...)`` makes one of three functions (a test double,
    say).

    Every failure is an ``AiError``: an error status maps to its reason (a
    429 to a ``RateLimitError``), an unreadable or malformed body to an
    ``InvalidOutputError`` or ``InvalidResponseError``, a transport failure
    to a ``NetworkError``."""

    __slots__ = (
        "_create_chat_completion",
        "_create_chat_completion_stream",
        "_create_decisions",
        "client",
        "max_response_bytes",
    )

    client: generated_client.OpenRouterClient
    max_response_bytes: ByteSize

    def __replace__(self, **changes: Any) -> Self:
        """A copy with ``changes`` to the constructor's arguments (``copy.replace``)."""
        return replaced(self, changes)

    def __init__(
        self,
        client: generated_client.OpenRouterClient,
        create_decisions: Callable[[W.DecisionsRequest], Decisions],
        create_chat_completion: Callable[[GT.ChatRequest], ChatCompletion],
        create_chat_completion_stream: Callable[[GT.ChatRequest], ChatCompletionStream],
        max_response_bytes: ByteSize = P.DEFAULT_MAX_RESPONSE_BYTES,
    ) -> None:
        self.client = client
        self._create_decisions = create_decisions
        self._create_chat_completion = create_chat_completion
        self._create_chat_completion_stream = create_chat_completion_stream
        self.max_response_bytes = max_response_bytes

    def create_decisions(self, options: W.DecisionsRequest) -> Decisions:
        """Answer decision questions: ``POST /alpha/decisions`` (next to the
        versioned API) with ``options``, through an ``OpenRouterConfig``'s
        transform. The decoded decisions and the HTTP response; a body that
        cannot be encoded fails with an ``InvalidRequestError`` ``AiError``,
        the rest as the class says."""
        return self._create_decisions(options)

    def create_chat_completion(self, options: GT.ChatRequest) -> ChatCompletion:
        """Create a chat completion through the generated client (and an
        ``OpenRouterConfig``'s transform). The decoded result and the HTTP
        response; fails with an ``AiError`` (see the class)."""
        return self._create_chat_completion(options)

    def create_chat_completion_stream(self, options: GT.ChatRequest) -> ChatCompletionStream:
        """Create a chat completion as server-sent events: ``POST
        /chat/completions`` with ``"stream": true`` and usage included, not
        through an ``OpenRouterConfig``. The HTTP response and the chunks
        until ``[DONE]`` (a chunk may carry an ``error``); data that is not
        a chunk fails the stream with an ``InvalidResponseError``. The call
        and the stream fail with an ``AiError`` (see the class)."""
        return self._create_chat_completion_stream(options)


class OpenRouterClient(Tag[Service], key="@effect/ai-openrouter/OpenRouterClient"):
    """The OpenRouter client."""


_redacted = P.with_redacted_headers(Errors.SECRET_HEADERS)
_decode_chunk = P.wire_parser(G.ChatStreamChunk, GT.ChatStreamChunk)
_decode_decisions = P.wire_parser(W.DECISIONS_RESPONSE, W.DecisionsResponse)


def _chunk(event: sse.Event) -> Effect[Result[GT.ChatStreamChunk, None], Any]:
    """A chunk, or ``Err`` at ``[DONE]``; data that is not JSON fails as
    a schema error would."""
    if event.data == "[DONE]":
        return fx.succeed(Err(None))
    try:
        parsed = parse_json_text(event.data)
    except ValueError:
        parsed = event.data
    return _decode_chunk(parsed).map(Ok)


def _chunks(response: HttpClientResponse) -> Stream[GT.ChatStreamChunk, AiError]:
    handle = Errors.catch("createChatCompletionStream")
    events: Stream[Any, Any] = (
        P.sse_events(response).map_effect(_chunk).take_while_filter(lambda found: found)
    )
    return events.catch_all(lambda error: St.from_effect(handle(error)))


def _strip_version(url: str) -> str:
    return re.sub(r"/v1/?$", "", url)


def make(
    *,
    api_key: Redacted[str] | None = None,
    api_url: str | None = None,
    site_referrer: str | None = None,
    site_title: str | None = None,
    transform_client: P.ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> Effect[Service, Never, HttpClient]:
    """A client over the ``HttpClient`` service. ``transform_client``
    changes the underlying client; a response body, or a streamed tool
    call's arguments, larger than ``max_response_bytes`` (256 MiB) fails
    the call."""
    limit = P.response_limit(max_response_bytes)
    url = P.or_default(api_url, DEFAULT_API_URL)

    def build(base: HttpClientService[HttpClientError]) -> Service:
        def http_client_at(base_url: str) -> HttpClientService[HttpClientError]:
            def prepare(request: http_request.HttpClientRequest) -> http_request.HttpClientRequest:
                request = request.prepend_url(base_url)
                if api_key is not None:
                    request = request.bearer_token(redacted_value(api_key))
                if site_referrer:
                    request = request.set_header("HTTP-Referer", site_referrer)
                if site_title:
                    request = request.set_header("X-Title", site_title)
                return request.accept_json()

            mapped = base.map_request(prepare)
            client = mapped if transform_client is None else transform_client(mapped)
            return P.limit_responses(client, limit)

        http_client = http_client_at(url)
        decisions_client = http_client_at(_strip_version(url))

        def create_decisions(payload: W.DecisionsRequest) -> Decisions:
            def send(
                client: HttpClientService[HttpClientError],
            ) -> Effect[tuple[W.DecisionsResponse, HttpClientResponse], Any]:
                request = (
                    http_request.post("/alpha/decisions")
                    .body_json(payload)
                    .map_error(_invalid_request)
                )
                return request.flat_map(
                    lambda built: (
                        client.filter_status_ok()
                        .execute(built)
                        .flat_map(
                            lambda response: response.json.flat_map(_decode_decisions).map(
                                lambda body: (body, response)
                            )
                        )
                    )
                )

            sent = P.resolve_client(OpenRouterConfig, decisions_client).flat_map(send)
            return sent.catch_all(Errors.catch("createDecisions")).pipe(_redacted)

        def resolve(
            client: HttpClientService[HttpClientError],
        ) -> Effect[HttpClientService[HttpClientError]]:
            return P.resolve_client(OpenRouterConfig, client)

        generated = generated_client.make(http_client, transform_client=resolve)

        def create_chat_completion(payload: GT.ChatRequest) -> ChatCompletion:
            sent = generated.send_chat_completion_request(payload=payload, include_response=True)
            caught: ChatCompletion = sent.catch_all(Errors.catch("createChatCompletion"))
            return caught.pipe(_redacted)

        def create_chat_completion_stream(payload: GT.ChatRequest) -> ChatCompletionStream:
            body = {**payload, "stream": True, "stream_options": {"include_usage": True}}
            request = http_request.post("/chat/completions").body_json_unsafe(body)
            sent: Effect[Any, Any] = (
                http_client.filter_status_ok()
                .execute(request)
                .map(lambda response: (response, _chunks(response)))
            )
            return sent.catch_all(Errors.catch("createChatCompletionStream")).pipe(_redacted)

        return Service(
            generated,
            create_decisions,
            create_chat_completion,
            create_chat_completion_stream,
            limit,
        )

    return HttpClient().map(build)


def _invalid_request(error: HttpBodyError) -> AiError:
    description = f"HttpBodyError: {error.cause}"
    return AiError(
        module=Errors.MODULE,
        method="createDecisions",
        reason=InvalidRequestError(description=description),
    )


def layer(
    *,
    api_key: Redacted[str] | None = None,
    api_url: str | None = None,
    site_referrer: str | None = None,
    site_title: str | None = None,
    transform_client: P.ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> L.Layer[OpenRouterClient, Never, HttpClient]:
    """``OpenRouterClient`` from these options (see ``make``)."""
    return L.effect(
        OpenRouterClient,
        make(
            api_key=api_key,
            api_url=api_url,
            site_referrer=site_referrer,
            site_title=site_title,
            transform_client=transform_client,
            max_response_bytes=max_response_bytes,
        ),
    )


def layer_config(
    *,
    api_key: Config[Redacted[str]] | Config[Redacted[str] | None] | None = None,
    api_url: Config[str] | None = None,
    site_referrer: Config[str] | None = None,
    site_title: Config[str] | None = None,
    transform_client: P.ClientTransform | None = None,
    max_response_bytes: byte_size.Input | None = None,
) -> L.Layer[OpenRouterClient, ConfigError, HttpClient]:
    """``OpenRouterClient`` with the options given as ``Config`` read from
    it (the others are absent)."""
    built: Effect[Service, ConfigError, HttpClient] = fx.all(
        P.optional_config(api_key),
        P.optional_config(api_url),
        P.optional_config(site_referrer),
        P.optional_config(site_title),
    ).flat_map(
        lambda values: make(
            api_key=values[0],
            api_url=values[1],
            site_referrer=values[2],
            site_title=values[3],
            transform_client=transform_client,
            max_response_bytes=max_response_bytes,
        )
    )
    return L.effect(OpenRouterClient, built)


__all__ = [
    "DEFAULT_API_URL",
    "ChatCompletion",
    "ChatCompletionStream",
    "ChatRequest",
    "ChatResult",
    "ChatStreamChunk",
    "ClientTransform",
    "Decisions",
    "OpenRouterClient",
    "Service",
    "layer",
    "layer_config",
    "make",
]
