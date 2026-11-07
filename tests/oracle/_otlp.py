"""Fake collectors for the OTLP exporter ports: ``HttpClient`` services
that record what they are sent and answer as each test needs."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pyfect as fx
from pyfect import _json_text
from pyfect import layer as _layer
from pyfect.http import client, response
from pyfect.http.client import HttpClient, HttpClientError, HttpClientService
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.layer import Layer

type Answer = Callable[[HttpClientRequest], HttpClientResponse]


@dataclass
class Collector:
    """Every request a fake collector received, with its body."""

    requests: list[HttpClientRequest] = field(default_factory=list[HttpClientRequest])

    @property
    def urls(self) -> list[str]:
        return [request.url for request in self.requests]

    def bodies(self) -> list[bytes]:
        return [body_bytes(request) for request in self.requests]

    def json(self) -> list[Any]:
        return [_json_text.parse(body) for body in self.bodies()]


def body_bytes(request: HttpClientRequest) -> bytes:
    body: Any = request.body
    data = getattr(body, "body", b"")
    return data if isinstance(data, bytes) else b""


def collector(
    answer: Answer = response.make,
) -> tuple[Collector, HttpClientService[HttpClientError]]:
    """A client recording each request and answering with ``answer``."""
    seen = Collector()

    def post(
        requests: fx.Effect[HttpClientRequest, Any, Any],
    ) -> fx.Effect[HttpClientResponse, HttpClientError]:
        def record(request: HttpClientRequest) -> HttpClientResponse:
            seen.requests.append(request)
            return answer(request)

        return requests.map(record)

    return seen, client.make_with(post, fx.succeed)


def with_status(status: int) -> tuple[Collector, HttpClientService[HttpClientError]]:
    return collector(lambda request: response.make(request, status=status))


def client_layer(http: HttpClientService[HttpClientError]) -> Layer[HttpClient]:
    return _layer.succeed(HttpClient, http)
