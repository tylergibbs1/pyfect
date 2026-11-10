"""One layer setting up OpenTelemetry for a pyfect program (Effect's
``NodeSdk``).

``layer(Configuration(...))`` provides the ``OtelResource`` (from the
environment and the ``resource`` given) and turns on each signal given
something to send it to: tracing with span processors, metrics with metric
readers, logging with log record processors::

    otel_layer = otel.sdk.layer(
        otel.sdk.Configuration(
            resource=otel.sdk.ResourceConfig(service_name="api"),
            span_processor=BatchSpanProcessor(OTLPSpanExporter()),
        )
    )
"""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any, Never, cast, overload

from opentelemetry.sdk import _logs as sdk_logs
from opentelemetry.sdk.metrics.export import MetricReader
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import SpanLimits, SpanProcessor, TracerProvider
from opentelemetry.sdk.trace.id_generator import IdGenerator
from opentelemetry.sdk.trace.sampling import Sampler
from opentelemetry.util.types import AttributeValue

from pyfect import layer as _layer
from pyfect._core import Effect
from pyfect.duration import Input as DurationInput
from pyfect.effect import sync
from pyfect.layer import Layer
from pyfect.otel import logger as otel_logger
from pyfect.otel import metrics as otel_metrics
from pyfect.otel import resource as otel_resource
from pyfect.otel import tracer as otel_tracer
from pyfect.otel._shutdown import DEFAULT_SHUTDOWN_TIMEOUT, flush_and_shut_down
from pyfect.otel.resource import OtelResource
from pyfect.scope import acquire_release

__all__ = [
    "Configuration",
    "ResourceConfig",
    "layer",
    "layer_empty",
    "layer_tracer_provider",
]


@dataclass(frozen=True, slots=True)
class ResourceConfig:
    """The service the telemetry is about (``resource.config_to_attributes``)."""

    service_name: str
    service_version: str | None = None
    attributes: Mapping[str, AttributeValue] | None = None


@dataclass(frozen=True, slots=True)
class Configuration:
    """What ``layer`` sets up. A signal with nothing to send it to (no span
    processors, metric readers or log record processors) stays off.

    - ``sampler``, ``id_generator``, ``span_limits``: for the tracer provider
    - ``metric_temporality``: ``"cumulative"`` (default) or ``"delta"``
    - ``logger_merge_with_existing``: keep the current loggers (default)
    - ``shutdown_timeout``: how long each provider may flush when released
    """

    span_processor: SpanProcessor | Sequence[SpanProcessor] = ()
    sampler: Sampler | None = None
    id_generator: IdGenerator | None = None
    span_limits: SpanLimits | None = None
    metric_reader: MetricReader | Sequence[MetricReader] = ()
    metric_temporality: otel_metrics.TemporalityPreference = "cumulative"
    log_record_processor: sdk_logs.LogRecordProcessor | Sequence[sdk_logs.LogRecordProcessor] = ()
    logger_merge_with_existing: bool = True
    resource: ResourceConfig | None = None
    shutdown_timeout: DurationInput = DEFAULT_SHUTDOWN_TIMEOUT


def _all[T](given: T | Sequence[T], kind: type[T]) -> list[T]:
    """One item or several, as a list."""
    if isinstance(given, kind):
        return [given]
    return list(cast("Sequence[T]", given))


def layer_tracer_provider(
    processors: SpanProcessor | Sequence[SpanProcessor],
    *,
    sampler: Sampler | None = None,
    id_generator: IdGenerator | None = None,
    span_limits: SpanLimits | None = None,
    shutdown_timeout: DurationInput = DEFAULT_SHUTDOWN_TIMEOUT,
) -> Layer[otel_tracer.OtelTracerProvider, Never, OtelResource]:
    """An SDK tracer provider with the ``OtelResource`` and ``processors``,
    flushed (for at most ``shutdown_timeout``) and shut down when the layer
    is released."""
    given = _all(processors, SpanProcessor)

    def make(resource: Resource) -> TracerProvider:
        provider = TracerProvider(
            sampler=sampler,
            resource=resource,
            shutdown_on_exit=False,
            id_generator=id_generator,
            span_limits=span_limits,
        )
        for processor in given:
            provider.add_span_processor(processor)
        return provider

    return _layer.effect(
        otel_tracer.OtelTracerProvider,
        OtelResource().flat_map(
            lambda resource: acquire_release(
                sync(lambda: make(resource)),
                lambda provider, _exit: flush_and_shut_down(provider, shutdown_timeout),
            )
        ),
    )


def _signals(config: Configuration) -> Layer[OtelResource]:
    signals: list[Layer[Never, Never, OtelResource]] = []
    span_processors = _all(config.span_processor, SpanProcessor)
    if span_processors:
        provider = layer_tracer_provider(
            span_processors,
            sampler=config.sampler,
            id_generator=config.id_generator,
            span_limits=config.span_limits,
            shutdown_timeout=config.shutdown_timeout,
        )
        signals.append(otel_tracer.layer.pipe(_layer.provide(provider)))
    readers = _all(config.metric_reader, MetricReader)
    if readers:
        signals.append(
            otel_metrics.layer(
                lambda: readers,
                temporality=config.metric_temporality,
                shutdown_timeout=config.shutdown_timeout,
            )
        )
    log_processors = _all(config.log_record_processor, sdk_logs.LogRecordProcessor)
    if log_processors:
        logger_provider = otel_logger.layer_logger_provider(
            log_processors, shutdown_timeout=config.shutdown_timeout
        )
        signals.append(
            otel_logger.layer(merge_with_existing=config.logger_merge_with_existing).pipe(
                _layer.provide(logger_provider)
            )
        )
    resource = config.resource
    resource_layer = otel_resource.layer_from_env(
        None
        if resource is None
        else otel_resource.config_to_attributes(
            service_name=resource.service_name,
            service_version=resource.service_version,
            attributes=resource.attributes,
        )
    )
    merged: Layer[Never, Never, OtelResource] = _layer.empty
    for signal in signals:
        merged = _layer.merge(merged, signal)
    return merged.pipe(_layer.provide_merge(resource_layer))


@overload
def layer(config: Configuration | Callable[[], Configuration], /) -> Layer[OtelResource]: ...
@overload
def layer[E, R](config: Effect[Configuration, E, R], /) -> Layer[OtelResource, E, R]: ...
def layer(
    config: Configuration | Callable[[], Configuration] | Effect[Configuration, Any, Any], /
) -> Layer[Any, Any, Any]:
    """Set up OpenTelemetry from ``config``: a configuration, a function
    making one, or an effect making one when the layer builds."""
    match config:
        case Configuration():
            made: Effect[Configuration, Any, Any] = sync(lambda: config)
        case Effect():
            made = config
        case _:
            made = sync(config)
    return _layer.unwrap(made.map(_signals))


layer_empty: Layer[OtelResource] = otel_resource.layer_empty
"""Only an empty ``OtelResource``."""
