"""A mocked ``HttpClient`` for the AI provider ports: it records each
request and answers with recorded JSON or Server-Sent Events, as Effect's
provider tests do with ``HttpClient.makeWith``. No test reaches a real
API."""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, cast

import pyfect as fx
from pyfect.http import client as http_client
from pyfect.http import response as http_response
from pyfect.http.body import Bytes
from pyfect.http.error import HttpClientError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.layer import Layer
from pyfect.tracer import NativeSpan, SpanRequest, Tracer

type Handler = Callable[[HttpClientRequest], fx.Effect[HttpClientResponse, HttpClientError]]


def json_response(
    request: HttpClientRequest,
    body: object,
    *,
    status: int = 200,
    headers: Mapping[str, str] | None = None,
) -> HttpClientResponse:
    return http_response.make(
        request,
        json.dumps(body),
        status=status,
        headers={"content-type": "application/json", **(headers or {})},
    )


def sse_body(events: Sequence[object], *, event: str | None = None) -> str:
    """Each event as JSON ``data`` (``"[DONE]"`` as is)."""
    name = "" if event is None else f"event: {event}\n"
    return "".join(f"{name}data: {e if e == '[DONE]' else json.dumps(e)}\n\n" for e in events)


def sse_response(
    request: HttpClientRequest,
    events: Sequence[object],
    *,
    event: str | None = None,
    status: int = 200,
) -> HttpClientResponse:
    return http_response.make(
        request,
        sse_body(events, event=event),
        status=status,
        headers={"content-type": "text/event-stream"},
    )


def text_response(
    request: HttpClientRequest, body: str, *, status: int = 200, content_type: str = "text/plain"
) -> HttpClientResponse:
    return http_response.make(request, body, status=status, headers={"content-type": content_type})


def body_json(request: HttpClientRequest) -> Any:
    body = request.body
    assert isinstance(body, Bytes)
    return json.loads(body.body)


@dataclass
class MockHttp:
    """Answers each request with ``handler`` and keeps the requests."""

    handler: Handler
    requests: list[HttpClientRequest] = field(default_factory=list[HttpClientRequest])

    @property
    def layer(self) -> Layer[http_client.HttpClient]:
        def handle(request: HttpClientRequest) -> fx.Effect[HttpClientResponse, HttpClientError]:
            self.requests.append(request)
            return self.handler(request)

        return http_client.layer_test(handle)

    @property
    def bodies(self) -> list[Any]:
        return [body_json(request) for request in self.requests]


def mock_json(
    body: object, *, status: int = 200, headers: Mapping[str, str] | None = None
) -> MockHttp:
    return MockHttp(
        lambda request: fx.succeed(json_response(request, body, status=status, headers=headers))
    )


def mock_sse(events: Sequence[object], *, event: str | None = None) -> MockHttp:
    return MockHttp(lambda request: fx.succeed(sse_response(request, events, event=event)))


def mock_raw_sse(body: str) -> MockHttp:
    return MockHttp(
        lambda request: fx.succeed(text_response(request, body, content_type="text/event-stream"))
    )


def unexpected() -> MockHttp:
    return MockHttp(lambda _: fx.die(RuntimeError("unexpected request")))


def recording_tracer() -> tuple[Tracer, list[NativeSpan]]:
    spans: list[NativeSpan] = []

    def make(request: SpanRequest) -> NativeSpan:
        span = NativeSpan(request)
        spans.append(span)
        return span

    return Tracer(make), spans


def span_named(spans: Sequence[NativeSpan], name: str) -> NativeSpan:
    return next(span for span in spans if span.name == name)


def meta(metadata: object, *path: str) -> Any:
    """The value at ``path`` in provider metadata, ``None`` when absent."""
    value: Any = metadata
    for key in path:
        value = cast("dict[str, Any]", value).get(key) if isinstance(value, dict) else None
    return value
