"""Ports of Effect's ``OtlpCompression.test.ts``.

Each test's docstring is the Effect test title.
"""

from __future__ import annotations

from typing import Any, Literal

import pytest

import pyfect as fx
from pyfect import config_provider, layer, metric, testing
from pyfect.http import body as http_body
from pyfect.http import response
from pyfect.http.client import HttpClient
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.layer import Layer
from pyfect.observability import otlp, otlp_exporter, otlp_serialization

from ._otlp import Collector, collector

SIGNALS = ("logs", "metrics", "traces")
LARGE_SERVICE_NAME = "compression-service-" * 150


@fx.gen
def _emit_and_flush():
    yield from fx.log("compression log")
    yield from metric.counter("compression_counter").update(1)
    yield from fx.void.with_span("compression span")
    yield from (yield from otlp_exporter.Flusher()).flush


def _configured_layer(env: dict[str, str]) -> Layer[Any, Any, Any]:
    provider = config_provider.from_env(
        {
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://localhost:4318",
            "OTEL_LOGS_EXPORTER": "otlp",
            "OTEL_METRICS_EXPORTER": "otlp",
            "OTEL_TRACES_EXPORTER": "otlp",
            "OTEL_BLRP_SCHEDULE_DELAY": "3600000",
            "OTEL_BSP_SCHEDULE_DELAY": "3600000",
            "OTEL_METRIC_EXPORT_INTERVAL": "3600000",
            **env,
        }
    )
    return (
        otlp.layer_from_config(
            logger_merge_with_existing=False, resource={"service_name": LARGE_SERVICE_NAME}
        )
        .pipe(layer.provide(otlp_serialization.layer_json))
        .pipe(layer.provide(config_provider.layer(provider)))
    )


def _check_requests(
    seen: Collector, format: Literal["json", "protobuf"], compressed: tuple[str, ...]
) -> None:
    assert len(seen.requests) == 3
    for signal in SIGNALS:
        request = next(r for r in seen.requests if r.url.endswith("/v1/" + signal))
        assert request.headers.get("content-type") == (
            "application/json" if format == "json" else "application/x-protobuf"
        )
        expected = "gzip" if signal in compressed else None
        assert request.headers.get("content-encoding") == expected


@pytest.mark.parametrize(
    ("format", "compression"),
    [("json", None), ("json", "gzip"), ("protobuf", "gzip")],
    ids=["json default", "json gzip", "protobuf gzip"],
)
@testing.effect
def test_aggregate_layer_exports_all_signals(
    format: Literal["json", "protobuf"], compression: Literal["gzip"] | None
):
    """format + " aggregate layer exports all signals with " + (compression ?? "default") + " compression"""  # noqa: E501
    seen, http = collector()
    make = otlp.layer_json if format == "json" else otlp.layer_protobuf
    signals = make(
        base_url="http://localhost:4318",
        resource={"service_name": LARGE_SERVICE_NAME},
        compression=compression or "none",
        logger_merge_with_existing=False,
        logger_export_interval="1 hour",
        metrics_export_interval="1 hour",
        tracer_export_interval="1 hour",
    )
    checked = _emit_and_flush.and_then(
        fx.sync(lambda: _check_requests(seen, format, SIGNALS if compression == "gzip" else ()))
    )
    yield from checked.pipe(layer.provide(signals)).pipe(fx.provide_service(HttpClient, http))


@testing.effect
def test_config_uses_global_compression_unless_a_signal_overrides_it():
    """config uses global compression unless a signal overrides it"""
    seen, http = collector()
    signals = _configured_layer(
        {
            "OTEL_EXPORTER_OTLP_COMPRESSION": "gzip",
            "OTEL_EXPORTER_OTLP_LOGS_COMPRESSION": "none",
            "OTEL_EXPORTER_OTLP_TRACES_COMPRESSION": "gzip",
        }
    )
    checked = _emit_and_flush.and_then(
        fx.sync(lambda: _check_requests(seen, "json", ("metrics", "traces")))
    )
    yield from checked.pipe(layer.provide(signals)).pipe(fx.provide_service(HttpClient, http))


@testing.effect
def test_rejects_invalid_compression_config():
    """rejects invalid compression config"""
    _, http = collector()
    signals = _configured_layer({"OTEL_EXPORTER_OTLP_COMPRESSION": "brotli"})
    exit = yield from (
        fx.void.pipe(layer.provide(signals)).pipe(fx.provide_service(HttpClient, http)).exit()
    )
    assert isinstance(exit, fx.Failure)
    assert "OTEL_EXPORTER_OTLP_COMPRESSION" in exit.cause.pretty()


@testing.effect
def test_retries_reuse_the_identical_compressed_request_body():
    """retries reuse the identical compressed request body"""
    first_attempt = yield from fx.Deferred[None].make()
    attempts = [0]

    def answer(request: HttpClientRequest) -> HttpClientResponse:
        attempts[0] += 1
        if attempts[0] == 1:
            first_attempt.done_unsafe(fx.Success(None))
        status = 429 if attempts[0] == 1 else 200
        return response.make(request, status=status, headers={"retry-after": "1"})

    seen, http = collector(answer)

    @fx.gen
    def program():
        exporter = yield from otlp_exporter.make(
            label="CompressionTest",
            url="http://localhost:4318/v1/logs",
            headers=None,
            compression="gzip",
            export_interval="1 hour",
            max_batch_size=100,
            shutdown_timeout="1 second",
            body=lambda _: (http_body.text(LARGE_SERVICE_NAME, "application/json"), fx.void),
        )
        exporter.push(1)
        fiber = yield from (yield from otlp_exporter.Flusher()).flush.fork()
        yield from first_attempt.wait()
        yield from testing.adjust("1 second")
        yield from fiber.join()
        assert len(seen.requests) == 2
        assert seen.requests[0].headers.get("content-encoding") == "gzip"
        assert seen.requests[0].body is seen.requests[1].body

    yield from (
        fx.scoped(program)
        .pipe(layer.provide(otlp_exporter.layer_flusher))
        .pipe(fx.provide_service(HttpClient, http))
    )
