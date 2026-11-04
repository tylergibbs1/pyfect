"""Ports of Effect's ``packages/ai/openai/test/OpenAiClient.test.ts``. Each
docstring is the Effect test title (with its ``describe``). Responses are
recorded JSON or Server-Sent Events answered by a mocked ``HttpClient``;
WebSocket mode talks to an in-memory server (Effect's
``vitest-websocket-mock``).

Omitted: ``OpenAiClientGenerated / sets Bearer token from apiKey``,
``prepends custom apiUrl`` and ``applies OpenAiConfig transformClient after
options transformClient``: the generated client of every OpenAPI operation
is not ported (``OpenAiClient`` covers the Responses, embeddings and
decisions calls the models use). ``OpenAiDecisionModel.test.ts`` is ported in
``test_ai_openai_decision_model.py``."""

from __future__ import annotations

# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false
# pyright: reportUnknownMemberType=false, reportUnknownLambdaType=false
import json
from collections.abc import Callable
from datetime import timedelta
from typing import Any, cast

import pytest

import pyfect as fx
from pyfect import config, config_provider, testing
from pyfect import layer as L
from pyfect import stream as St
from pyfect.ai import ai_error as E
from pyfect.ai import chat
from pyfect.ai.openai import _errors, client, language_model
from pyfect.ai.openai import config as openai_config
from pyfect.deferred import Deferred
from pyfect.exit import Success
from pyfect.http import error as http_error
from pyfect.http import request as http_request
from pyfect.http import response as http_response
from pyfect.http.request import HttpClientRequest
from pyfect.queue import Queue
from pyfect.redacted import make as redact
from pyfect.socket import WebSocketConstructor
from pyfect.socket._web_socket import WebSocketClientOptions

from ._ai_http import MockHttp, mock_json, sse_body, unexpected
from ._graphql import FakeWebSocket

_TEST: client.CreateResponse = {"model": "gpt-4o", "input": "test"}


def response_body(**overrides: Any) -> dict[str, Any]:
    """Effect's ``makeResponseBody``."""
    return {
        "id": "resp_test123",
        "object": "response",
        "created_at": 1,
        "model": "gpt-4o-mini",
        "status": "completed",
        "output": [],
        "metadata": None,
        "temperature": None,
        "top_p": None,
        "tools": [],
        "tool_choice": "auto",
        "error": None,
        "incomplete_details": None,
        "instructions": None,
        "parallel_tool_calls": False,
        **overrides,
    }


def mock_sse(events: list[Any], *, trailer: str = "", keep_open: bool = False) -> MockHttp:
    body = sse_body(events) + trailer

    def respond(request: HttpClientRequest) -> Any:
        content = body.encode()
        if keep_open:
            data: Any = St.succeed(content).concat(St.never)
            return fx.succeed(
                http_response.make(request, data, headers={"content-type": "text/event-stream"})
            )
        return fx.succeed(
            http_response.make(request, body, headers={"content-type": "text/event-stream"})
        )

    return MockHttp(respond)


def _run(
    use: Callable[[client.Service], fx.Effect[Any, Any, Any]],
    mock: MockHttp | None = None,
    **options: Any,
) -> fx.Effect[Any, Any, Any]:
    mock = mock or mock_json(response_body())
    settings: dict[str, Any] = {"api_key": redact("test-key"), **options}
    layer = client.layer(**settings)
    return client.OpenAiClient().flat_map(use).pipe(fx.provide(layer)).pipe(fx.provide(mock.layer))


def _create(mock: MockHttp | None = None, **options: Any) -> fx.Effect[Any, Any, Any]:
    return _run(lambda c: c.create_response(_TEST), mock, **options)


def _error(mock: MockHttp) -> fx.Effect[E.AiError, Any, Any]:
    return _run(lambda c: c.create_response(_TEST).flip(), mock)


def _stream(mock: MockHttp) -> fx.Effect[list[Any], Any, Any]:
    return _run(
        lambda c: c.create_response_stream(_TEST).flat_map(lambda sent: sent[1].run_collect()),
        mock,
    )


def _stream_error(mock: MockHttp) -> fx.Effect[E.AiError, Any, Any]:
    return _run(
        lambda c: c.create_response_stream(_TEST).flat_map(lambda sent: sent[1].run_drain()).flip(),
        mock,
    )


# make -------------------------------------------------------------------------------------


@testing.effect
def test_bearer_token():
    """make / sets Bearer token from apiKey"""
    mock = mock_json(response_body())
    yield from _create(mock, api_key=redact("sk-test-12345"))
    assert mock.requests[0].headers["authorization"] == "Bearer sk-test-12345"


@testing.effect
def test_default_url():
    """make / prepends default URL"""
    mock = mock_json(response_body())
    yield from _create(mock)
    assert mock.requests[0].url.startswith("https://api.openai.com/v1")


@testing.effect
def test_custom_api_url():
    """make / uses custom apiUrl when provided"""
    mock = mock_json(response_body())
    yield from _create(mock, api_url="https://custom.api.com/v2")
    assert mock.requests[0].url.startswith("https://custom.api.com/v2")


@testing.effect
def test_organization_header():
    """make / sets OpenAI-Organization header when organizationId provided"""
    mock = mock_json(response_body())
    yield from _create(mock, organization_id=redact("org-12345"))
    assert mock.requests[0].headers["openai-organization"] == "org-12345"


@testing.effect
def test_project_header():
    """make / sets OpenAI-Project header when projectId provided"""
    mock = mock_json(response_body())
    yield from _create(mock, project_id=redact("proj-67890"))
    assert mock.requests[0].headers["openai-project"] == "proj-67890"


@testing.effect
def test_transform_client():
    """make / applies transformClient option"""
    applied: list[bool] = []

    def transform(c: Any) -> Any:
        applied.append(True)
        return c

    yield from _create(transform_client=transform)
    assert applied


@testing.effect
def test_client_field():
    """make / exposes transformed HttpClient via client field"""
    mock = mock_json(response_body())
    yield from _run(
        lambda c: c.http_client.execute(http_request.get("/responses")),
        mock,
        transform_client=lambda c: c.map_request(
            lambda r: r.set_header("x-client-field", "enabled")
        ),
    )
    request = mock.requests[0]
    assert request.url.startswith("https://api.openai.com/v1")
    assert request.headers["authorization"] == "Bearer test-key"
    assert request.headers["x-client-field"] == "enabled"


@testing.effect
def test_config_transform_after_options():
    """make / applies OpenAiConfig transformClient after options transformClient"""
    applied: list[str] = []

    def options_transform(c: Any) -> Any:
        applied.append("options")
        return c.map_request(lambda r: r.set_header("x-openai-transform", "options"))

    def config_transform(c: Any) -> Any:
        applied.append("config")
        return c.map_request(lambda r: r.set_header("x-openai-transform", "config"))

    mock = mock_json(response_body())
    yield from _run(
        lambda c: c.create_response(_TEST).pipe(
            openai_config.with_client_transform(config_transform)
        ),
        mock,
        transform_client=options_transform,
    )
    assert set(applied) == {"options", "config"}
    assert mock.requests[0].headers["x-openai-transform"] == "config"


# layer ------------------------------------------------------------------------------------


@testing.effect
def test_layer_service():
    """layer / creates working service"""
    found = yield from _run(lambda c: fx.succeed(c.http_client))
    assert found is not None


@testing.effect
def test_layer_config():
    """layer / layerConfig loads from Config"""
    mock = mock_json(response_body())
    provider = config_provider.from_env(
        {"MY_API_KEY": "sk-config-key", "MY_API_URL": "https://config.api.com/v1"}
    )
    layer = client.layer_config(
        api_key=config.redacted("MY_API_KEY"), api_url=config.string("MY_API_URL")
    )
    yield from (
        client.OpenAiClient()
        .flat_map(lambda c: c.create_response(_TEST))
        .pipe(fx.provide(layer))
        .pipe(fx.provide(mock.layer))
        .pipe(fx.provide(config_provider.layer(provider)))
    )
    assert mock.requests[0].headers["authorization"] == "Bearer sk-config-key"
    assert mock.requests[0].url.startswith("https://config.api.com/v1")


# request behavior -------------------------------------------------------------------------


@testing.effect
def test_redacts_headers():
    """request behavior / redacts OpenAI-specific headers in AI error context"""
    mock = mock_json({"error": {"message": "Bad request"}}, status=400)
    error = yield from _run(
        lambda c: c.create_response(_TEST).flip(),
        mock,
        organization_id=redact("org-secret"),
        project_id=redact("proj-secret"),
    )
    reason = error.reason
    assert isinstance(reason, E.InvalidRequestError)
    assert reason.http is not None
    headers = reason.http["request"]["headers"]
    assert headers["authorization"] == "<redacted>"
    assert headers["openai-organization"] == "<redacted>"
    assert headers["openai-project"] == "<redacted>"


# error mapping ----------------------------------------------------------------------------


@testing.effect
def test_transport_error():
    """error mapping / maps TransportError to NetworkError reason"""

    def refuse(request: HttpClientRequest) -> Any:
        return fx.fail(
            http_error.HttpClientError(
                http_error.TransportError(request=request, cause=ConnectionRefusedError())
            )
        )

    error = yield from _error(MockHttp(refuse))
    assert isinstance(error, E.AiError)
    assert error.module == "OpenAiClient"
    assert error.method == "createResponse"
    assert isinstance(error.reason, E.NetworkError)


@testing.effect
def test_400():
    """error mapping / maps 400 status to InvalidRequestError reason"""
    error = yield from _error(mock_json({"error": {"message": "Bad request"}}, status=400))
    assert isinstance(error, E.AiError)
    assert error.module == "OpenAiClient"
    assert error.method == "createResponse"
    assert isinstance(error.reason, E.InvalidRequestError)


@testing.effect
def test_401():
    """error mapping / maps 401 status to AuthenticationError reason"""
    body = {
        "error": {
            "message": "Invalid API key",
            "type": "invalid_request_error",
            "code": "invalid_api_key",
        }
    }
    error = yield from _error(mock_json(body, status=401, headers={"x-request-id": "req_openai"}))
    reason = error.reason
    assert isinstance(reason, E.AuthenticationError)
    assert reason.kind == "InvalidKey"
    assert reason.description == (
        "Invalid API key (POST https://api.openai.com/v1/responses) "
        "[code: invalid_api_key] [requestId: req_openai]"
    )
    assert "Invalid API key" in reason.message


def test_fallback_body_truncated():
    """error mapping / preserves and truncates a fallback HTTP response"""
    body = "a" * 200 + "b"
    reason = _errors.map_status_code_to_reason(
        now=0,
        status=400,
        headers={},
        message=None,
        metadata={"errorCode": None, "errorType": None, "requestId": None},
        http={
            "request": {
                "method": "POST",
                "url": "https://api.openai.com/v1/responses",
                "urlParams": [],
                "headers": {},
            },
            "body": body,
        },
    )
    assert isinstance(reason, E.InvalidRequestError)
    assert reason.description == (
        f"HTTP 400 (POST https://api.openai.com/v1/responses) Response: {'a' * 200}..."
    )


@testing.effect
def test_403():
    """error mapping / maps 403 status to AuthenticationError with InsufficientPermissions"""
    error = yield from _error(mock_json({"error": {"message": "Access denied"}}, status=403))
    reason = error.reason
    assert isinstance(reason, E.AuthenticationError)
    assert reason.kind == "InsufficientPermissions"
    assert "Access denied" in (reason.description or "")
    assert "Access denied" in reason.message


_RATE_LIMITED = {
    "error": {"message": "Rate limit exceeded", "type": "rate_limit_error", "code": None}
}


@testing.effect
def test_429():
    """error mapping / maps 429 status to RateLimitError reason"""
    error = yield from _error(mock_json(_RATE_LIMITED, status=429))
    assert isinstance(error.reason, E.RateLimitError)
    assert error.is_retryable


@pytest.mark.parametrize(
    ("header", "expected"),
    [
        ("-5", None),
        ("Infinity", None),
        ("Thu, 01 Jan 1970 00:00:30 GMT", timedelta(seconds=30)),
    ],
    ids=[
        "ignores a negative Retry-After",
        "ignores a non-finite Retry-After",
        "honors an HTTP-date Retry-After",
    ],
)
@testing.effect
def test_retry_after(header: str, expected: timedelta | None):
    """error mapping / $name (ignores a negative Retry-After, ignores a non-finite
    Retry-After, honors an HTTP-date Retry-After)"""
    error = yield from _error(mock_json(_RATE_LIMITED, status=429, headers={"retry-after": header}))
    reason = error.reason
    assert isinstance(reason, E.RateLimitError)
    assert reason.retry_after == expected


@testing.effect
def test_insufficient_quota():
    """error mapping / maps 429 with insufficient_quota code to QuotaExhaustedError"""
    body = {
        "error": {
            "message": "You exceeded your current quota",
            "type": "insufficient_quota",
            "code": "insufficient_quota",
        }
    }
    error = yield from _error(mock_json(body, status=429))
    assert isinstance(error.reason, E.QuotaExhaustedError)
    assert not error.is_retryable


@testing.effect
def test_402_compatible():
    """error mapping / maps OpenAI-compatible 402 errors to QuotaExhaustedError"""
    body = {"error": "Your balance is too low", "code": "billing_insufficient_balance"}
    error = yield from _error(mock_json(body, status=402))
    assert isinstance(error.reason, E.QuotaExhaustedError)
    assert not error.is_retryable


@testing.effect
def test_insufficient_balance_compatible():
    """error mapping / maps OpenAI-compatible insufficient balance errors to QuotaExhaustedError"""
    body = {"error": "Your balance is too low", "code": "billing_insufficient_balance"}
    error = yield from _error(mock_json(body, status=429))
    assert isinstance(error.reason, E.QuotaExhaustedError)
    assert not error.is_retryable


def test_map_status_insufficient_quota():
    """error mapping / mapStatusCodeToReason detects insufficient_quota as QuotaExhaustedError"""
    reason = _errors.map_status_code_to_reason(
        now=0,
        status=429,
        headers={},
        message="You exceeded your current quota",
        metadata={
            "errorCode": "insufficient_quota",
            "errorType": "insufficient_quota",
            "requestId": None,
        },
        http={
            "request": {
                "method": "POST",
                "url": "https://api.openai.com",
                "urlParams": [],
                "headers": {},
            }
        },
    )
    assert isinstance(reason, E.QuotaExhaustedError)


def test_error_body_decodes():
    """error mapping / OpenAiErrorBody decodes error with type and code"""
    body = {
        "error": {
            "message": "You exceeded your current quota",
            "type": "insufficient_quota",
            "code": "insufficient_quota",
        }
    }
    decoded = fx.run_sync(_errors.decode_error_body(body).or_die())
    assert decoded["error"]["message"] == "You exceeded your current quota"
    assert decoded["error"].get("type") == "insufficient_quota"
    assert decoded["error"].get("code") == "insufficient_quota"


@testing.effect
def test_5xx():
    """error mapping / maps 5xx status to InternalProviderError reason"""
    error = yield from _error(
        mock_json({"error": {"message": "Internal server error"}}, status=500)
    )
    assert isinstance(error.reason, E.InternalProviderError)
    assert error.is_retryable


@testing.effect
def test_malformed_envelope():
    """error mapping / maps a malformed successful response envelope to a non-retryable InvalidResponseError reason"""  # noqa: E501
    error = yield from _error(mock_json({"invalid": "response"}))
    assert error.method == "createResponse"
    assert isinstance(error.reason, E.InvalidResponseError)
    assert not error.is_retryable


# createEmbedding --------------------------------------------------------------------------


@testing.effect
def test_embedding_400():
    """createEmbedding / maps 400 error to AiError"""
    error = yield from _run(
        lambda c: c.create_embedding({"model": "invalid-model", "input": "test"}).flip(),
        mock_json({"error": {"message": "Invalid model"}}, status=400),
    )
    assert error.method == "createEmbedding"
    assert isinstance(error.reason, E.InvalidRequestError)


@testing.effect
def test_embedding_429():
    """createEmbedding / maps 429 error to RateLimitError"""
    error = yield from _run(
        lambda c: c.create_embedding({"model": "text-embedding-ada-002", "input": "test"}).flip(),
        mock_json({"error": {"message": "Rate limit exceeded"}}, status=429),
    )
    assert isinstance(error.reason, E.RateLimitError)


# createResponseStream ---------------------------------------------------------------------


@testing.effect
def test_completed_before_done():
    """createResponseStream / emits response.completed before [DONE] in the same SSE chunk"""
    completed = {
        "type": "response.completed",
        "sequence_number": 1,
        "response": response_body(status="completed"),
    }
    events = yield from _stream(mock_sse([completed], trailer="data: [DONE]\n\n"))
    assert [event["type"] for event in events] == ["response.completed"]


@testing.live
def test_sse_terminates_at_failed():
    """createResponseStream / terminates an SSE stream at response.failed"""
    failed = {
        "type": "response.failed",
        "sequence_number": 1,
        "response": response_body(status="failed"),
    }
    result = yield from _stream(mock_sse([failed], keep_open=True)).timeout_option(0.1)
    assert result is not None


@testing.effect
def test_keepalive_events():
    """createResponseStream / accepts keepalive stream events"""
    events = yield from _stream(
        mock_sse(
            [
                {
                    "type": "response.created",
                    "sequence_number": 1,
                    "response": response_body(id="resp_stream", status="in_progress"),
                },
                {"type": "keepalive", "sequence_number": 2},
                {
                    "type": "response.completed",
                    "sequence_number": 3,
                    "response": response_body(id="resp_stream"),
                },
            ]
        )
    )
    assert len(events) == 3
    assert events[1] == {"type": "keepalive", "sequence_number": 2}
    assert events[2]["type"] == "response.completed"
    assert events[2]["response"]["id"] == "resp_stream"


@testing.effect
def test_events_without_sequence_numbers():
    """createResponseStream / accepts response stream events without sequence numbers"""
    reasoning = {"output_index": 0, "item_id": "rs_tmp_123", "content_index": 0}
    sent = [
        {"type": "response.created", "response": response_body(status="in_progress")},
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "id": "msg_123",
                "type": "message",
                "role": "assistant",
                "status": "in_progress",
                "content": [],
            },
        },
        {
            "type": "response.content_part.added",
            **reasoning,
            "part": {"type": "reasoning_text", "text": ""},
        },
        {
            "type": "response.output_text.delta",
            "output_index": 0,
            "item_id": "msg_123",
            "content_index": 0,
            "delta": "hello",
            "sequence_number": 4,
        },
        {"type": "response.reasoning_text.delta", **reasoning, "delta": "thinking..."},
        {"type": "response.reasoning_text.done", **reasoning, "text": "thinking..."},
        {
            "type": "response.content_part.done",
            **reasoning,
            "part": {"type": "reasoning_text", "text": "thinking..."},
        },
        {"type": "response.completed", "response": response_body()},
    ]
    events = yield from _stream(mock_sse(sent))
    assert [event["type"] for event in events] == [event["type"] for event in sent]
    assert events[0] == {
        "type": "response.created",
        "response": {
            "id": "resp_test123",
            "object": "response",
            "model": "gpt-4o-mini",
            "created_at": 1,
            "output": [],
            "error": None,
            "incomplete_details": None,
        },
    }
    assert events[3] == sent[3]
    assert [events[2], events[4], events[5], events[6]] == [sent[2], sent[4], sent[5], sent[6]]


@testing.effect
def test_malformed_stream_event():
    """createResponseStream / maps a malformed stream event to a non-retryable InvalidResponseError"""  # noqa: E501
    bad = {
        "type": "response.output_text.delta",
        "output_index": "zero",
        "item_id": "msg_123",
        "content_index": 0,
        "delta": "hello",
    }
    error = yield from _stream_error(mock_sse([bad]))
    assert isinstance(error.reason, E.InvalidResponseError)
    assert not error.is_retryable


@testing.effect
def test_oversized_sse_event():
    """createResponseStream / maps an oversized SSE event to a non-retryable InvalidResponseError"""
    error = yield from _stream_error(mock_sse([], trailer="data: " + "x" * (10 * 1024 * 1024 + 1)))
    assert isinstance(error.reason, E.InvalidResponseError)
    assert not error.is_retryable


@testing.effect
def test_http_error_before_stream():
    """createResponseStream / maps HTTP error before stream starts"""
    error = yield from _stream_error(mock_json({"error": {"message": "Server error"}}, status=500))
    assert isinstance(error, E.AiError)
    assert isinstance(error.reason, E.InternalProviderError)


# WebSocket mode ---------------------------------------------------------------------------


class WsServer:
    """One in-memory WebSocket server: every connection's messages arrive
    on ``messages``, and ``send`` answers on the newest connection."""

    def __init__(self) -> None:
        self.messages: Queue[dict[str, Any]] = Queue()
        self.sockets: list[FakeWebSocket] = []
        self.urls: list[tuple[str, WebSocketClientOptions]] = []

        def construct(url: str, options: WebSocketClientOptions) -> FakeWebSocket:
            ws = FakeWebSocket(self.messages, Deferred())
            self.sockets.append(ws)
            self.urls.append((url, options))
            return ws

        self.layer = L.succeed(WebSocketConstructor, construct)

    @property
    def next_create(self) -> fx.Effect[dict[str, Any]]:
        def checked(message: dict[str, Any]) -> dict[str, Any]:
            assert message["type"] == "response.create"
            return message

        return self.messages.take().map(checked)

    def send(self, *events: dict[str, Any]) -> fx.Effect[None]:
        from pyfect.socket._web_socket import WebSocketEvent

        def run() -> None:
            for event in events:
                self.sockets[-1].dispatch("message", WebSocketEvent(data=json.dumps(event)))

        return fx.sync(run)

    def close(self) -> None:
        for ws in self.sockets:
            ws.server_close(1000)


def ws_completed(id: str, item_id: str, text: str) -> list[dict[str, Any]]:
    """Effect's ``sendWebSocketCompleted``."""
    response = {
        "id": id,
        "object": "response",
        "model": "gpt-4o-mini",
        "created_at": 1,
        "output": [],
        "error": None,
        "incomplete_details": None,
    }
    return [
        {"type": "response.created", "response": response},
        {
            "type": "response.output_item.added",
            "output_index": 0,
            "item": {
                "id": item_id,
                "type": "message",
                "role": "assistant",
                "status": "in_progress",
                "content": [],
            },
        },
        {
            "type": "response.output_text.delta",
            "item_id": item_id,
            "output_index": 0,
            "content_index": 0,
            "delta": text,
        },
        {
            "type": "response.output_item.done",
            "output_index": 0,
            "item": {
                "id": item_id,
                "type": "message",
                "role": "assistant",
                "status": "completed",
                "content": [{"type": "output_text", "text": text, "annotations": []}],
            },
        },
        {"type": "response.completed", "response": response},
    ]


def ws_reasoning_completed(
    id: str, item_id: str, summary: str, encrypted: str
) -> list[dict[str, Any]]:
    """Effect's ``sendWebSocketReasoningCompleted``."""
    response = {
        "id": id,
        "object": "response",
        "model": "o3-mini",
        "created_at": 1,
        "output": [],
        "error": None,
        "incomplete_details": None,
    }
    part = {"type": "summary_text", "text": summary}
    at = {"output_index": 0, "item_id": item_id, "summary_index": 0}
    return [
        {"type": "response.created", "sequence_number": 1, "response": response},
        {
            "type": "response.output_item.added",
            "sequence_number": 2,
            "output_index": 0,
            "item": {
                "type": "reasoning",
                "id": item_id,
                "summary": [],
                "encrypted_content": None,
            },
        },
        {"type": "response.reasoning_summary_part.added", "sequence_number": 3, **at, "part": part},
        {
            "type": "response.reasoning_summary_text.delta",
            "sequence_number": 4,
            **at,
            "delta": summary,
        },
        {"type": "response.reasoning_summary_part.done", "sequence_number": 5, **at, "part": part},
        {
            "type": "response.output_item.done",
            "sequence_number": 6,
            "output_index": 0,
            "item": {
                "type": "reasoning",
                "id": item_id,
                "summary": [part],
                "encrypted_content": encrypted,
            },
        },
        {"type": "response.completed", "sequence_number": 7, "response": response},
    ]


def user_input(text: str) -> dict[str, Any]:
    return {"role": "user", "content": [{"type": "input_text", "text": text}]}


def assistant_input(id: str, text: str) -> dict[str, Any]:
    return {
        "id": id,
        "type": "message",
        "role": "assistant",
        "status": "completed",
        "content": [{"type": "output_text", "text": text, "annotations": [], "logprobs": []}],
    }


def web_socket_mode(
    server: WsServer, effect: fx.Effect[Any, Any, Any], api_url: str
) -> fx.Effect[Any, Any, Any]:
    return (
        effect.pipe(client.with_web_socket_mode)
        .pipe(fx.provide(client.layer(api_key=redact("sk-test"), api_url=api_url)))
        .pipe(fx.provide(server.layer))
        .pipe(fx.provide(unexpected().layer))
    )


def ws_turn(
    server: WsServer, payload: dict[str, Any], respond: Callable[[dict[str, Any]], Any]
) -> fx.Effect[Any, Any, Any]:
    """Stream one response while the server answers its request."""

    def body(c: client.Service) -> Any:
        stream = c.create_response_stream(cast("client.CreateResponse", payload)).flat_map(
            lambda sent: sent[1].run_collect()
        )
        answer = server.next_create.flat_map(respond)
        return fx.all(stream.exit(), answer, concurrency="unbounded").map(lambda r: r[0])

    return client.OpenAiClient().flat_map(body)


@testing.live
def test_ws_terminates_at_failed():
    """createResponseStream / terminates a WebSocket stream at response.failed"""
    server = WsServer()
    failed = {
        "type": "response.failed",
        "sequence_number": 1,
        "response": response_body(status="failed"),
    }
    turn = ws_turn(server, dict(_TEST), lambda _: server.send(failed))
    result = yield from web_socket_mode(server, turn, "https://api.openai.com/v1").timeout_option(1)
    assert result is not None
    assert isinstance(result.value, Success)
    assert server.urls[0][0] == "wss://api.openai.com/v1/responses"
    headers = server.urls[0][1].headers or {}
    assert headers["authorization"] == "Bearer sk-test"


@testing.live
def test_ws_replaces_after_error_events():
    """createResponseStream / replaces the WebSocket after non-retryable error events"""
    server = WsServer()
    errors = [
        {"type": "error", "code": "invalid_request_error", "message": "bad", "param": None},
        {"error": {"message": "gRPC error: permission denied", "type": "api_error"}},
        {"error": {"message": "bad request", "type": "invalid_request_error"}},
    ]

    def drive() -> Any:
        exits = []
        for index, error in enumerate(errors):
            exits.append(
                (
                    yield from ws_turn(
                        server,
                        {"model": "gpt-4o", "input": f"turn {index}"},
                        lambda _, error=error: server.send(error),
                    )
                )
            )
        last = yield from ws_turn(
            server,
            {"model": "gpt-4o", "input": "fourth"},
            lambda _: server.send(*ws_completed("resp_4", "msg_4", "ok")),
        )
        return exits, last

    exits, last = yield from web_socket_mode(
        server, fx.gen(drive), "https://socket-errors.test/v1"
    ).timeout(5)
    assert all(not isinstance(exit, Success) for exit in exits)
    third = exits[2].cause.find_error().value
    assert isinstance(third.reason, E.InvalidRequestError)
    assert isinstance(last, Success)
    assert len(server.sockets) == 4


def chat_over_ws(
    server: WsServer, model: str, prompts: list[str], api_url: str
) -> fx.Effect[Any, Any, Any]:
    def drive() -> Any:
        session = yield from chat.empty
        for prompt in prompts:
            yield from session.stream_text(prompt=prompt).run_drain()

    return (
        fx.gen(drive)
        .pipe(client.with_web_socket_mode)
        .pipe(fx.provide(language_model.model(model, {"store": True}).layer))
        .pipe(fx.provide(client.layer(api_key=redact("sk-test"), api_url=api_url)))
        .pipe(fx.provide(server.layer))
        .pipe(fx.provide(unexpected().layer))
    )


NOT_FOUND = {
    "error": {"message": "gRPC error: Response with id=resp_1 not found", "type": "api_error"}
}


@testing.live
def test_ws_xai_not_found_retry():
    """createResponseStream / retries an untagged xAI response-not-found error with the full prompt"""  # noqa: E501
    server = WsServer()

    def respond() -> Any:
        first = yield from server.next_create
        assert "previous_response_id" not in first
        assert first["input"] == [user_input("hello")]
        yield from server.send(*ws_completed("resp_1", "msg_1", "ok"))

        incremental = yield from server.next_create
        assert incremental["previous_response_id"] == "resp_1"
        assert incremental["input"] == [user_input("again")]
        yield from server.send(NOT_FOUND)

        retried = yield from server.next_create
        assert "previous_response_id" not in retried
        assert retried["input"] == [
            user_input("hello"),
            assistant_input("msg_1", "ok"),
            user_input("again"),
        ]
        yield from server.send(*ws_completed("resp_2", "msg_2", "retried"))

        later = yield from server.next_create
        assert later["previous_response_id"] == "resp_2"
        assert later["input"] == [user_input("later")]
        yield from server.send(*ws_completed("resp_3", "msg_3", "later"))

    drive = chat_over_ws(
        server, "gpt-4o-mini", ["hello", "again", "later"], "https://previous-response.test/v1"
    )
    yield from fx.all(drive, fx.gen(respond), concurrency="unbounded").timeout(5)


@testing.live
def test_ws_encrypted_reasoning_retry():
    """createResponseStream / round-trips streamed encrypted reasoning in a full-prompt retry"""
    server = WsServer()
    requests: list[dict[str, Any]] = []

    def respond() -> Any:
        requests.append((yield from server.next_create))
        yield from server.send(
            *ws_reasoning_completed("resp_1", "rs_1", "thinking", "encrypted-reasoning")
        )
        requests.append((yield from server.next_create))
        yield from server.send(NOT_FOUND)
        requests.append((yield from server.next_create))
        yield from server.send(*ws_completed("resp_2", "msg_2", "done"))

    drive = chat_over_ws(
        server, "o3-mini", ["think", "continue"], "https://reasoning-recovery.test/v1"
    )
    yield from fx.all(drive, fx.gen(respond), concurrency="unbounded").timeout(5)
    reasoning = next(item for item in requests[2]["input"] if item.get("type") == "reasoning")
    assert requests[0].get("include") == ["reasoning.encrypted_content"]
    assert reasoning == {
        "type": "reasoning",
        "id": "rs_1",
        "summary": [{"type": "summary_text", "text": "thinking"}],
        "encrypted_content": "encrypted-reasoning",
    }
