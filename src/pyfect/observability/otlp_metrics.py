"""Exporting metrics over OTLP/HTTP (Effect's ``OtlpMetrics``): every
export interval the registry's series are posted as OTLP metrics,
cumulative from the exporter's start or as deltas since the last
successful export."""

from __future__ import annotations

from typing import Any, Literal, Never, NotRequired, TypedDict

from pyfect import config
from pyfect import layer as _layer
from pyfect._context_effects import context as current_context
from pyfect.clock import Clock
from pyfect.duration import Duration
from pyfect.effect import Effect, gen, succeed, sync
from pyfect.http import headers as _headers
from pyfect.http.body import HttpBody
from pyfect.http.client import HttpClient
from pyfect.layer import Layer
from pyfect.metric import snapshot_unsafe
from pyfect.observability import _otlp_env as env
from pyfect.observability import otlp_exporter as exporter
from pyfect.observability._otlp_metric_points import Converter, empty_checkpoints
from pyfect.observability.otlp_exporter import Compression, Flusher
from pyfect.observability.otlp_resource import (
    Resource,
    ResourceOptions,
    from_options,
    service_name_unsafe,
)
from pyfect.observability.otlp_serialization import OtlpSerialization
from pyfect.scope import Scope

__all__ = [
    "AggregationTemporality",
    "MetricsData",
    "ResourceMetrics",
    "ScopeMetrics",
    "layer",
    "layer_from_config",
    "make",
]

type AggregationTemporality = Literal["cumulative", "delta"]
"""``"cumulative"`` (the default) reports totals since the exporter
started; ``"delta"`` reports the change since the last successful export.
Gauges report their value and summaries are always cumulative."""


class _Scope(TypedDict):
    name: str


class ScopeMetrics(TypedDict):
    scope: _Scope
    metrics: list[dict[str, Any]]
    schemaUrl: NotRequired[str]


class ResourceMetrics(TypedDict):
    resource: Resource
    scopeMetrics: list[ScopeMetrics]
    schemaUrl: NotRequired[str]


class MetricsData(TypedDict):
    """The body of a metrics export. Each metric is an OTLP ``Metric`` in
    its JSON shape (``name``, ``description``, ``unit`` and one of
    ``sum``, ``gauge``, ``histogram`` or ``summary``)."""

    resourceMetrics: list[ResourceMetrics]


def make(
    *,
    url: str,
    resource: ResourceOptions | None = None,
    headers: _headers.Input | None = None,
    compression: Compression = "none",
    export_interval: Duration | None = None,
    shutdown_timeout: Duration | None = None,
    temporality: AggregationTemporality = "cumulative",
) -> Effect[None, Never, Flusher | HttpClient | OtlpSerialization | Scope]:
    """Export the current registry's series to ``url`` every
    ``export_interval`` (10 seconds), on each flush, and for at most
    ``shutdown_timeout`` (3 seconds) when the scope closes. With
    ``"delta"`` each successful export moves the checkpoint the next one
    subtracts; an export that fails, or finishes after a later one, does
    not."""

    @gen
    def build():
        clock = yield from Clock()
        serialization = yield from OtlpSerialization()
        start_nanos = clock.now_nanos_unsafe()
        otel_resource = yield from from_options(resource)
        scope: _Scope = {"name": service_name_unsafe(otel_resource)}
        services = yield from current_context()
        delta = temporality == "delta"
        sequence = 0
        committed_sequence = -1
        committed = empty_checkpoints(start_nanos)

        def body(_items: list[Any]) -> tuple[HttpBody, Effect[None]]:
            nonlocal sequence
            snapshots = snapshot_unsafe(services)
            current_sequence = sequence
            sequence += 1
            upcoming = empty_checkpoints(clock.now_nanos_unsafe())
            converter = Converter(delta, str(start_nanos), committed, upcoming)
            data: MetricsData = {
                "resourceMetrics": [
                    {
                        "resource": otel_resource,
                        "scopeMetrics": [{"scope": scope, "metrics": converter.metrics(snapshots)}],
                    }
                ]
            }

            def commit() -> None:
                nonlocal committed, committed_sequence
                if current_sequence < committed_sequence:
                    return
                committed = upcoming
                committed_sequence = current_sequence

            return serialization.metrics(data), sync(commit) if delta else succeed(None)

        yield from exporter.make(
            label="OtlpMetrics",
            url=url,
            headers=headers,
            compression=compression,
            max_batch_size="disabled",
            export_empty=True,
            export_interval="10 seconds" if export_interval is None else export_interval,
            body=body,
            shutdown_timeout="3 seconds" if shutdown_timeout is None else shutdown_timeout,
        )

    return build


def layer(
    *,
    url: str,
    resource: ResourceOptions | None = None,
    headers: _headers.Input | None = None,
    compression: Compression = "none",
    export_interval: Duration | None = None,
    shutdown_timeout: Duration | None = None,
    temporality: AggregationTemporality = "cumulative",
) -> Layer[Flusher, Never, HttpClient | OtlpSerialization]:
    """Starts ``make``'s exporter, with the shared ``layer_flusher``."""
    started = make(
        url=url,
        resource=resource,
        headers=headers,
        compression=compression,
        export_interval=export_interval,
        shutdown_timeout=shutdown_timeout,
        temporality=temporality,
    )
    return _layer.effect_discard(started).pipe(_layer.provide_merge(exporter.layer_flusher))


def layer_from_config(
    *,
    resource: ResourceOptions | None = None,
    headers: _headers.Input | None = None,
) -> Layer[Flusher, Never, HttpClient | OtlpSerialization]:
    """``layer`` configured from the OpenTelemetry environment: nothing
    but the flusher unless ``OTEL_METRICS_EXPORTER`` lists ``otlp``, an
    endpoint is set and ``OTEL_SDK_DISABLED`` is not true. Reads the
    compression, ``OTEL_EXPORTER_OTLP_(METRICS_)TIMEOUT`` /
    ``OTEL_METRIC_EXPORT_TIMEOUT`` (shutdown),
    ``OTEL_METRIC_EXPORT_INTERVAL`` and
    ``OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE``. Invalid
    configuration is a defect."""

    @gen
    def build():
        disabled = yield from config.boolean("OTEL_SDK_DISABLED").with_default(False)
        endpoint = yield from env.endpoint("METRICS")
        exporters = yield from env.exporters("METRICS")
        if disabled or endpoint is None or "otlp" not in exporters:
            return exporter.layer_flusher
        compression = yield from env.compression("METRICS")
        base_timeout = yield from env.millis("OTEL_EXPORTER_OTLP_TIMEOUT")
        metrics_timeout = yield from env.millis("OTEL_EXPORTER_OTLP_METRICS_TIMEOUT")
        export_timeout = yield from env.millis("OTEL_METRIC_EXPORT_TIMEOUT")
        export_interval = yield from env.millis("OTEL_METRIC_EXPORT_INTERVAL")
        preference: config.Config[AggregationTemporality] = config.literal(
            "delta", "cumulative", name="OTEL_EXPORTER_OTLP_METRICS_TEMPORALITY_PREFERENCE"
        )
        temporality = yield from preference.with_default("cumulative")
        signal_headers = headers if headers is not None else (yield from env.headers("METRICS"))
        return layer(
            url=str(endpoint),
            resource=resource,
            headers=signal_headers,
            compression=compression,
            export_interval=export_interval,
            shutdown_timeout=env.first_of(metrics_timeout, base_timeout, export_timeout),
            temporality=temporality,
        )

    return _layer.unwrap(build.or_die())
