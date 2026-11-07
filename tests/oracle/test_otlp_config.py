"""Ports of Effect's ``OtlpConfig.test.ts`` (``Otlp.layerFromConfig``).

Each test's docstring is the Effect test title.
"""

from __future__ import annotations

from typing import Any

import pyfect as fx
from pyfect import config_provider, layer, metric, testing
from pyfect.layer import Layer
from pyfect.observability import otlp, otlp_serialization

from ._otlp import Collector, client_layer, collector


def _test_layer(env: dict[str, str]) -> tuple[Collector, Layer[Any]]:
    seen, http = collector()
    built = (
        otlp.layer_from_config(logger_merge_with_existing=False)
        .pipe(layer.provide(otlp_serialization.layer_json))
        .pipe(layer.provide_merge(client_layer(http)))
        .pipe(layer.provide_merge(config_provider.layer(config_provider.from_env(env))))
    )
    return seen, built


def _find_metric(body: Any, name: str) -> Any:
    for resource_metrics in body["resourceMetrics"]:
        for scope_metrics in resource_metrics["scopeMetrics"]:
            for found in scope_metrics["metrics"]:
                if found["name"] == name:
                    return found
    return None


@testing.effect
def test_configures_exporters_from_otel_environment_variables():
    """Otlp.layerFromConfig configures exporters from OTEL environment variables"""
    seen, built = _test_layer(
        {
            "OTEL_SERVICE_NAME": "otel-config-test",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.example",
            "OTEL_EXPORTER_OTLP_HEADERS": (
                "x-shared=shared,authorization=Basic%20dXNlcjpwYXNzd29yZA=="
            ),
            "OTEL_EXPORTER_OTLP_LOGS_ENDPOINT": "http://logs.example/custom",
            "OTEL_EXPORTER_OTLP_LOGS_HEADERS": "x-signal=logs",
            "OTEL_LOGS_EXPORTER": "console, OTLP",
            "OTEL_METRICS_EXPORTER": " otlp ",
            "OTEL_TRACES_EXPORTER": "otlp",
            "OTEL_BLRP_MAX_EXPORT_BATCH_SIZE": "1",
            "OTEL_BSP_MAX_EXPORT_BATCH_SIZE": "1",
            "OTEL_METRIC_EXPORT_INTERVAL": "1000",
            "OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE": "delta",
        }
    )

    @fx.gen
    def program():
        yield from fx.log("configured log")
        yield from metric.counter("otel_config_counter").update(1)
        yield from fx.void.with_span("configured-span")
        yield from testing.adjust(1)

        by_url = {request.url: request for request in seen.requests}
        log_request = by_url["http://logs.example/custom"]
        assert log_request.headers.get("x-signal") == "logs"
        assert log_request.headers.get("x-shared") is None
        assert log_request.headers.get("authorization") is None

        metric_request = by_url["http://collector.example/v1/metrics"]
        assert metric_request.headers.get("x-shared") == "shared"
        assert metric_request.headers.get("authorization") == "Basic dXNlcjpwYXNzd29yZA=="
        body = seen.json()[seen.requests.index(metric_request)]
        assert _find_metric(body, "otel_config_counter")["sum"]["aggregationTemporality"] == 1

        trace_request = by_url["http://collector.example/v1/traces"]
        assert trace_request.headers.get("x-shared") == "shared"
        assert trace_request.headers.get("authorization") == "Basic dXNlcjpwYXNzd29yZA=="

    yield from program.pipe(layer.provide(built))


@testing.effect
def test_does_not_install_exporters_when_otel_sdk_disabled_is_true():
    """Otlp.layerFromConfig does not install exporters when OTEL_SDK_DISABLED is true"""
    seen, built = _test_layer(
        {
            "OTEL_SDK_DISABLED": "true",
            "OTEL_SERVICE_NAME": "otel-config-test",
            "OTEL_EXPORTER_OTLP_ENDPOINT": "http://collector.example",
            "OTEL_LOGS_EXPORTER": "otlp",
            "OTEL_METRICS_EXPORTER": "otlp",
            "OTEL_TRACES_EXPORTER": "otlp",
            "OTEL_BLRP_MAX_EXPORT_BATCH_SIZE": "1",
            "OTEL_BSP_MAX_EXPORT_BATCH_SIZE": "1",
            "OTEL_METRIC_EXPORT_INTERVAL": "1000",
        }
    )

    @fx.gen
    def program():
        yield from fx.log("disabled log")
        yield from metric.counter("otel_disabled_counter").update(1)
        yield from fx.void.with_span("disabled-span")
        yield from testing.adjust(1)
        assert seen.requests == []

    yield from program.pipe(layer.provide(built))
