"""Ports of Effect's ``observability/OtlpProxy.test.ts``.

Each test's docstring is the Effect test title. ``HttpRouter.toWebHandler``
is ``router.to_web_handler``; a Web ``Request`` is a ``WebRequest``, and a
``ReadableStream`` body an async generator.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from typing import Any

import pyfect as fx
from pyfect import config_provider, layer
from pyfect.http import client, response, router
from pyfect.http.client import HttpClient, HttpClientError, HttpClientService
from pyfect.http.error import TransportError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.http.web import WebRequest
from pyfect.layer import Layer
from pyfect.observability import otlp_proxy

from ._otlp import body_bytes

type Respond = Callable[[HttpClientRequest], fx.Effect[HttpClientResponse, HttpClientError]]


def _upstream(
    respond: Respond = lambda request: fx.succeed(response.make(request)),
) -> tuple[list[HttpClientRequest], HttpClientService[HttpClientError]]:
    requests: list[HttpClientRequest] = []

    def post(
        made: fx.Effect[HttpClientRequest, Any, Any],
    ) -> fx.Effect[HttpClientResponse, HttpClientError]:
        def send(request: HttpClientRequest) -> fx.Effect[HttpClientResponse, HttpClientError]:
            requests.append(request)
            return respond(request)

        return made.flat_map(send)

    return requests, client.make_with(post, fx.succeed)


def _serve(
    proxy: Layer[Any, Any, Any], upstream: HttpClientService[HttpClientError], request: WebRequest
) -> tuple[int, dict[str, str | None], bytes]:
    async def main() -> tuple[int, dict[str, str | None], bytes]:
        made = router.to_web_handler(
            proxy.pipe(layer.provide(layer.succeed(HttpClient, upstream))), disable_logger=True
        )
        try:
            answer = await asyncio.wait_for(made.handler(request), 5)
            names = ("content-type", "retry-after", "set-cookie", "content-encoding", "x-vendor")
            return answer.status, {name: answer.get(name) for name in names}, await answer.read()
        finally:
            await made.dispose()

    return asyncio.run(main())


def _post(path: str, body: bytes, headers: dict[str, str] | None = None) -> WebRequest:
    return WebRequest(
        f"http://localhost{path}",
        method="POST",
        body=body,
        headers={"content-type": "application/x-protobuf", **(headers or {})},
    )


def test_forwards_the_body_and_allow_listed_headers_to_the_configured_signal_endpoint() -> None:
    """forwards the body and allow-listed headers to the configured signal endpoint"""
    requests, upstream = _upstream()
    status, _, _ = _serve(
        otlp_proxy.layer(
            base_url="https://otlp.example/base",
            headers={"authorization": "Bearer server"},
            prefix="/otlp",
        ),
        upstream,
        _post(
            "/otlp/v1/traces?target=https://attacker.example",
            bytes([1, 2, 3]),
            {
                "content-encoding": "gzip",
                "accept-encoding": "gzip, br",
                "authorization": "Bearer client",
                "cookie": "session=secret",
                "traceparent": "00-0af7651916cd43dd8448eb211c80319c-b7ad6b7169203331-01",
                "x-forwarded-for": "203.0.113.1",
            },
        ),
    )
    assert status == 200
    assert len(requests) == 1
    request = requests[0]
    assert request.method == "POST"
    assert request.url == "https://otlp.example/base/v1/traces"
    assert len(request.url_params) == 0
    # No client credentials, cookies or trace context, and none from the
    # proxy's own outbound span; the response is asked for uncompressed.
    assert dict(request.headers) == {
        "content-type": "application/x-protobuf",
        "content-encoding": "gzip",
        "content-length": "3",
        "accept-encoding": "identity",
        "authorization": "Bearer server",
    }
    assert body_bytes(request) == bytes([1, 2, 3])


def test_returns_the_upstream_status_and_body_with_only_content_type_and_retry_after_headers() -> (
    None
):
    """returns the upstream status and body with only content-type and retry-after headers"""
    _, upstream = _upstream(
        lambda request: fx.succeed(
            response.make(
                request,
                bytes([4, 5]),
                status=429,
                headers={
                    "content-type": "application/x-protobuf",
                    "retry-after": "5",
                    "set-cookie": "vendor=1",
                    "content-encoding": "gzip",
                    "x-vendor": "1",
                },
            )
        )
    )
    status, headers, body = _serve(
        otlp_proxy.layer(base_url="https://otlp.example"), upstream, _post("/v1/logs", bytes([1]))
    )
    assert status == 429
    assert headers == {
        "content-type": "application/x-protobuf",
        "retry-after": "5",
        "set-cookie": None,
        "content-encoding": None,
        "x-vendor": None,
    }
    assert body == bytes([4, 5])


def test_rejects_unsupported_content_types_with_415_without_contacting_upstream() -> None:
    """rejects unsupported content types with 415 without contacting upstream"""
    requests, upstream = _upstream()
    status, _, _ = _serve(
        otlp_proxy.layer(base_url="https://otlp.example"),
        upstream,
        _post("/v1/metrics", bytes([1]), {"content-type": "text/plain"}),
    )
    assert status == 415
    assert requests == []


def test_accepts_a_body_at_max_body_size_and_rejects_larger_ones_with_413() -> None:
    """accepts a body at maxBodySize and rejects larger ones with 413 without contacting upstream"""
    requests, upstream = _upstream()
    proxy = otlp_proxy.layer(base_url="https://otlp.example", max_body_size=4)
    at_limit, _, _ = _serve(
        proxy, upstream, _post("/v1/traces", bytes([1, 2, 3, 4]), {"content-length": "4"})
    )
    assert at_limit == 200
    assert len(requests) == 1
    over, _, _ = _serve(proxy, upstream, _post("/v1/traces", bytes([1, 2, 3, 4, 5])))
    assert over == 413
    assert len(requests) == 1


def test_stops_reading_early_when_content_length_understates_the_body() -> None:
    """stops reading early when content-length understates the body"""
    for content_length, expected in (("0", 400), ("1", 400), ("4", 413)):
        requests, upstream = _upstream()
        pulls = 0

        async def body() -> AsyncIterator[bytes]:
            nonlocal pulls
            while True:
                pulls += 1
                if pulls > 10:
                    return
                yield bytes([1, 2])

        status, _, _ = _serve(
            otlp_proxy.layer(base_url="https://otlp.example", max_body_size=4),
            upstream,
            WebRequest(
                "http://localhost/v1/traces",
                method="POST",
                body=body(),
                headers={
                    "content-type": "application/x-protobuf",
                    "content-length": content_length,
                },
            ),
        )
        # Overrunning the declared length is a parse error unless the body
        # is also over the limit.
        assert status == expected, f"content-length: {content_length}"
        assert requests == []
        # Reading stops once the declared length or the limit is crossed.
        assert pulls <= 4, f"content-length: {content_length}"


def test_maps_upstream_transport_failures_to_502_and_timeouts_to_504() -> None:
    """maps upstream transport failures to 502 and timeouts to 504"""
    _, failing = _upstream(lambda request: fx.fail(HttpClientError(TransportError(request))))
    failed, _, _ = _serve(
        otlp_proxy.layer(base_url="https://otlp.example"), failing, _post("/v1/traces", bytes([1]))
    )
    assert failed == 502

    _, hanging = _upstream(lambda _: fx.never)
    timed_out, _, _ = _serve(
        otlp_proxy.layer(base_url="https://otlp.example", timeout="10 millis"),
        hanging,
        _post("/v1/traces", bytes([1])),
    )
    assert timed_out == 504


def test_layer_from_config_resolves_the_upstream_endpoint_and_headers_per_signal() -> None:
    """layerFromConfig resolves the upstream endpoint and headers per signal"""
    requests, upstream = _upstream()
    provider = config_provider.from_env(
        {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.example",
            "OTEL_EXPORTER_OTLP_HEADERS": "authorization=Basic%20c2hhcmVk",
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs.example/custom",
            "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "authorization=Basic%20bG9ncw==",
        }
    )
    proxy = otlp_proxy.layer_from_config().pipe(layer.provide(config_provider.layer(provider)))
    _serve(proxy, upstream, _post("/v1/logs", bytes([1])))
    _serve(proxy, upstream, _post("/v1/metrics", bytes([1])))
    assert [(r.url, r.headers.get("authorization")) for r in requests] == [
        ("http://logs.example/custom", "Basic bG9ncw=="),
        ("http://collector.example/v1/metrics", "Basic c2hhcmVk"),
    ]
