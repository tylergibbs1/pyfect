"""Reuse cases for ``pyfect.observability``: each run posts to its own
recording collector and checks what arrived."""

# pyright: reportUnknownLambdaType=false, reportUnknownMemberType=false
# pyright: reportUnknownVariableType=false, reportUnknownArgumentType=false

from __future__ import annotations

import itertools
from collections.abc import Callable
from typing import Any

from oracle._otlp import Collector, client_layer, collector

import pyfect as fx
from layer_cases._case import AnyEffect, AnyLayer, Case
from pyfect import config_provider, metric
from pyfect import layer as L
from pyfect.http import body as http_body
from pyfect.http import router
from pyfect.http.client import HttpClient
from pyfect.observability import (
    otlp,
    otlp_exporter,
    otlp_logger,
    otlp_metrics,
    otlp_proxy,
    otlp_serialization,
    otlp_tracer,
)
from pyfect.observability.otlp_serialization import OtlpSerialization

_runs = itertools.count(1)
_URL = "http://localhost:4318"
_ENV = {
    "OTEL_SERVICE_NAME": "reuse",
    "OTEL_EXPORTER_OTLP_ENDPOINT": _URL,
    "OTEL_LOGS_EXPORTER": "otlp",
    "OTEL_METRICS_EXPORTER": "otlp",
    "OTEL_TRACES_EXPORTER": "otlp",
}


def _emit_and_flush(seen: Collector, signals: tuple[str, ...]) -> AnyEffect:
    run = next(_runs)

    @fx.gen
    def body():
        yield from fx.log_info(f"run {run}")
        yield from metric.counter(f"reuse_{run}").update(1)
        yield from fx.void.with_span(f"run {run}")
        yield from (yield from otlp_exporter.Flusher()).flush
        posted = sorted({url.rsplit("/", 1)[-1] for url in seen.urls})
        assert posted == sorted(signals), posted

    return body


def _exports(
    signals: tuple[str, ...], *, serialized: bool = True, env: bool = False
) -> Callable[[AnyLayer], AnyEffect]:
    """A whole run: the layer value, a fresh collector, then one log, metric
    and span flushed; only ``signals`` reach the collector."""

    def run(value: AnyLayer) -> AnyEffect:
        seen, http = collector()
        provided = value
        if serialized:
            provided = provided.pipe(L.provide(otlp_serialization.layer_json))
        if env:
            provided = provided.pipe(
                L.provide(config_provider.layer(config_provider.from_env(_ENV)))
            )
        provided = provided.pipe(L.provide_merge(client_layer(http)))
        return (
            _emit_and_flush(seen, signals)
            .pipe(fx.provide(provided))
            .pipe(fx.provide_service(metric.MetricRegistry, {}))
        )

    return run


def _serializes() -> AnyEffect:
    def check(service: Any) -> None:
        body = service.traces(
            {
                "resourceSpans": [
                    {"resource": {"attributes": [], "droppedAttributesCount": 0}, "scopeSpans": []}
                ]
            }
        )
        assert isinstance(body, http_body.Bytes) and body.body, body

    return OtlpSerialization().map(check)


def _proxies(value: AnyLayer) -> AnyEffect:
    """A whole run: the proxy routes over a fresh upstream, sent one export."""
    seen, upstream = collector()
    routes = value.pipe(L.provide(client_layer(upstream)))
    routes = routes.pipe(L.provide(config_provider.layer(config_provider.from_env(_ENV))))

    @fx.gen
    def body():
        http = yield from HttpClient()
        sent = yield from http.post(
            "http://localhost/v1/traces",
            body=http_body.bytes_(b"\x0a\x00", "application/x-protobuf"),
        )
        assert sent.status == 200, sent.status
        assert seen.urls == [f"{_URL}/v1/traces"], seen.urls

    return fx.scoped(body).pipe(fx.provide(router.layer_in_memory_client(routes)))


_ALL = ("logs", "metrics", "traces")

CASES: dict[str, Case] = {
    "pyfect.observability.otlp.layer": Case(
        layer=lambda: otlp.layer(base_url=_URL, resource={"service_name": "reuse"}),
        run=_exports(_ALL),
    ),
    "pyfect.observability.otlp.layer_json": Case(
        layer=lambda: otlp.layer_json(base_url=_URL, resource={"service_name": "reuse"}),
        run=_exports(_ALL, serialized=False),
    ),
    "pyfect.observability.otlp.layer_protobuf": Case(
        layer=lambda: otlp.layer_protobuf(base_url=_URL, resource={"service_name": "reuse"}),
        run=_exports(_ALL, serialized=False),
    ),
    "pyfect.observability.otlp.layer_from_config": Case(
        layer=otlp.layer_from_config, run=_exports(_ALL, env=True)
    ),
    "pyfect.observability.otlp_exporter.layer_flusher": Case(
        layer=lambda: otlp_exporter.layer_flusher,
        use=lambda: otlp_exporter.Flusher().flat_map(lambda flusher: flusher.flush),
    ),
    "pyfect.observability.otlp_logger.layer": Case(
        layer=lambda: otlp_logger.layer(url=f"{_URL}/v1/logs", resource={"service_name": "reuse"}),
        run=_exports(("logs",)),
    ),
    "pyfect.observability.otlp_logger.layer_from_config": Case(
        layer=otlp_logger.layer_from_config, run=_exports(("logs",), env=True)
    ),
    "pyfect.observability.otlp_metrics.layer": Case(
        layer=lambda: otlp_metrics.layer(
            url=f"{_URL}/v1/metrics", resource={"service_name": "reuse"}
        ),
        run=_exports(("metrics",)),
    ),
    "pyfect.observability.otlp_metrics.layer_from_config": Case(
        layer=otlp_metrics.layer_from_config, run=_exports(("metrics",), env=True)
    ),
    "pyfect.observability.otlp_tracer.layer": Case(
        layer=lambda: otlp_tracer.layer(
            url=f"{_URL}/v1/traces", resource={"service_name": "reuse"}
        ),
        run=_exports(("traces",)),
    ),
    "pyfect.observability.otlp_tracer.layer_from_config": Case(
        layer=otlp_tracer.layer_from_config, run=_exports(("traces",), env=True)
    ),
    "pyfect.observability.otlp_serialization.layer_json": Case(
        layer=lambda: otlp_serialization.layer_json, use=_serializes
    ),
    "pyfect.observability.otlp_serialization.layer_protobuf": Case(
        layer=lambda: otlp_serialization.layer_protobuf, use=_serializes
    ),
    "pyfect.observability.otlp_proxy.layer": Case(
        layer=lambda: otlp_proxy.layer(base_url=_URL), run=_proxies
    ),
    "pyfect.observability.otlp_proxy.layer_from_config": Case(
        layer=otlp_proxy.layer_from_config, run=_proxies
    ),
}
SKIPPED: dict[str, str] = {}
