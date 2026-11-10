"""One OTLP/HTTP layer for logs, metrics and traces (Effect's ``Otlp``),
posting to ``/v1/logs``, ``/v1/metrics`` and ``/v1/traces`` below one base
URL with one shared configuration::

    from pyfect.observability import otlp

    TelemetryLive = otlp.layer_json(
        base_url="http://localhost:4318", resource={"service_name": "api"}
    )
"""

from __future__ import annotations

from typing import Never

from pyfect import layer as _layer
from pyfect.duration import Input as DurationInput
from pyfect.http import headers as _headers
from pyfect.http import request as _request
from pyfect.http.client import HttpClient
from pyfect.layer import Layer
from pyfect.observability import otlp_logger, otlp_metrics, otlp_serialization, otlp_tracer
from pyfect.observability.otlp_exporter import Compression, Flusher
from pyfect.observability.otlp_metrics import AggregationTemporality
from pyfect.observability.otlp_resource import ResourceOptions
from pyfect.observability.otlp_serialization import OtlpSerialization
from pyfect.observability.otlp_tracer import SpanContextHook

__all__ = ["layer", "layer_from_config", "layer_json", "layer_protobuf"]


def layer(
    *,
    base_url: str,
    resource: ResourceOptions | None = None,
    headers: _headers.Input | None = None,
    compression: Compression = "none",
    max_batch_size: int | None = None,
    tracer_context: SpanContextHook | None = None,
    logger_export_interval: DurationInput | None = None,
    logger_exclude_log_spans: bool = False,
    logger_merge_with_existing: bool = True,
    metrics_export_interval: DurationInput | None = None,
    metrics_temporality: AggregationTemporality = "cumulative",
    tracer_export_interval: DurationInput | None = None,
    shutdown_timeout: DurationInput | None = None,
) -> Layer[Flusher, Never, HttpClient | OtlpSerialization]:
    """The OTLP logger, metrics exporter and tracer, posting below
    ``base_url``; they share one ``Flusher``."""
    base = _request.get(base_url)

    def url(path: str) -> str:
        return base.append_url(path).url

    return _layer.merge(
        otlp_logger.layer(
            url=url("/v1/logs"),
            resource=resource,
            headers=headers,
            compression=compression,
            export_interval=logger_export_interval,
            max_batch_size=max_batch_size,
            shutdown_timeout=shutdown_timeout,
            exclude_log_spans=logger_exclude_log_spans,
            merge_with_existing=logger_merge_with_existing,
        ),
        otlp_metrics.layer(
            url=url("/v1/metrics"),
            resource=resource,
            headers=headers,
            compression=compression,
            export_interval=metrics_export_interval,
            shutdown_timeout=shutdown_timeout,
            temporality=metrics_temporality,
        ),
        otlp_tracer.layer(
            url=url("/v1/traces"),
            resource=resource,
            headers=headers,
            compression=compression,
            export_interval=tracer_export_interval,
            max_batch_size=max_batch_size,
            context=tracer_context,
            shutdown_timeout=shutdown_timeout,
        ),
    )


def layer_from_config(
    *,
    resource: ResourceOptions | None = None,
    headers: _headers.Input | None = None,
    tracer_context: SpanContextHook | None = None,
    logger_exclude_log_spans: bool = False,
    logger_merge_with_existing: bool = True,
) -> Layer[Flusher, Never, HttpClient | OtlpSerialization]:
    """Each signal's ``layer_from_config``, merged."""
    return _layer.merge(
        otlp_logger.layer_from_config(
            resource=resource,
            headers=headers,
            exclude_log_spans=logger_exclude_log_spans,
            merge_with_existing=logger_merge_with_existing,
        ),
        otlp_metrics.layer_from_config(resource=resource, headers=headers),
        otlp_tracer.layer_from_config(resource=resource, headers=headers, context=tracer_context),
    )


def layer_json(
    *,
    base_url: str,
    resource: ResourceOptions | None = None,
    headers: _headers.Input | None = None,
    compression: Compression = "none",
    max_batch_size: int | None = None,
    tracer_context: SpanContextHook | None = None,
    logger_export_interval: DurationInput | None = None,
    logger_exclude_log_spans: bool = False,
    logger_merge_with_existing: bool = True,
    metrics_export_interval: DurationInput | None = None,
    metrics_temporality: AggregationTemporality = "cumulative",
    tracer_export_interval: DurationInput | None = None,
    shutdown_timeout: DurationInput | None = None,
) -> Layer[Flusher, Never, HttpClient]:
    """``layer`` with OTLP/JSON bodies."""
    return layer(
        base_url=base_url,
        resource=resource,
        headers=headers,
        compression=compression,
        max_batch_size=max_batch_size,
        tracer_context=tracer_context,
        logger_export_interval=logger_export_interval,
        logger_exclude_log_spans=logger_exclude_log_spans,
        logger_merge_with_existing=logger_merge_with_existing,
        metrics_export_interval=metrics_export_interval,
        metrics_temporality=metrics_temporality,
        tracer_export_interval=tracer_export_interval,
        shutdown_timeout=shutdown_timeout,
    ).pipe(_layer.provide(otlp_serialization.layer_json))


def layer_protobuf(
    *,
    base_url: str,
    resource: ResourceOptions | None = None,
    headers: _headers.Input | None = None,
    compression: Compression = "none",
    max_batch_size: int | None = None,
    tracer_context: SpanContextHook | None = None,
    logger_export_interval: DurationInput | None = None,
    logger_exclude_log_spans: bool = False,
    logger_merge_with_existing: bool = True,
    metrics_export_interval: DurationInput | None = None,
    metrics_temporality: AggregationTemporality = "cumulative",
    tracer_export_interval: DurationInput | None = None,
    shutdown_timeout: DurationInput | None = None,
) -> Layer[Flusher, Never, HttpClient]:
    """``layer`` with OTLP/protobuf bodies."""
    return layer(
        base_url=base_url,
        resource=resource,
        headers=headers,
        compression=compression,
        max_batch_size=max_batch_size,
        tracer_context=tracer_context,
        logger_export_interval=logger_export_interval,
        logger_exclude_log_spans=logger_exclude_log_spans,
        logger_merge_with_existing=logger_merge_with_existing,
        metrics_export_interval=metrics_export_interval,
        metrics_temporality=metrics_temporality,
        tracer_export_interval=tracer_export_interval,
        shutdown_timeout=shutdown_timeout,
    ).pipe(_layer.provide(otlp_serialization.layer_protobuf))
