"""Exporting logs over OTLP/HTTP (Effect's ``OtlpLogger``): a logger whose
entries become OTLP log records with their level, message, annotations,
cause, fiber id, log spans and the current trace and span ids."""

from __future__ import annotations

from typing import Any, Final, Never, NotRequired, TypedDict

from pyfect import config
from pyfect import layer as _layer
from pyfect.clock import Clock, ClockService
from pyfect.duration import Duration
from pyfect.effect import Effect, gen, succeed
from pyfect.http import headers as _headers
from pyfect.http.client import HttpClient
from pyfect.layer import Layer
from pyfect.logger import CurrentLogAnnotations, CurrentLogSpans, Logger, LogLevel, Options
from pyfect.logger import layer as logger_layer
from pyfect.observability import _otlp_env as env
from pyfect.observability import otlp_exporter as exporter
from pyfect.observability._pretty import pretty_errors
from pyfect.observability.otlp_exporter import Compression, Flusher
from pyfect.observability.otlp_resource import (
    AnyValue,
    KeyValue,
    Resource,
    ResourceOptions,
    entries_to_attributes,
    from_options,
    instrumentation_scope,
    unknown_to_attribute_value,
)
from pyfect.observability.otlp_serialization import OtlpSerialization
from pyfect.scope import Scope
from pyfect.tracer import ParentSpan

__all__ = [
    "LogRecord",
    "LogsData",
    "ResourceLogs",
    "ScopeLogs",
    "layer",
    "layer_from_config",
    "log_level_to_severity_number",
    "make",
]


class LogRecord(TypedDict):
    severityNumber: int
    severityText: str
    timeUnixNano: str
    observedTimeUnixNano: str
    attributes: list[KeyValue]
    body: AnyValue
    droppedAttributesCount: int
    traceId: NotRequired[str]
    spanId: NotRequired[str]


class _InstrumentationScope(TypedDict):
    name: str
    version: NotRequired[str]


class ScopeLogs(TypedDict):
    scope: _InstrumentationScope
    logRecords: list[LogRecord]
    schemaUrl: NotRequired[str]


class ResourceLogs(TypedDict):
    resource: Resource
    scopeLogs: list[ScopeLogs]
    schemaUrl: NotRequired[str]


class LogsData(TypedDict):
    """The body of a logs export."""

    resourceLogs: list[ResourceLogs]


_SEVERITIES: Final = {
    LogLevel.TRACE: 1,
    LogLevel.DEBUG: 5,
    LogLevel.INFO: 9,
    LogLevel.WARN: 13,
    LogLevel.ERROR: 17,
    LogLevel.FATAL: 21,
}

_NANOS_PER_MILLI: Final = 1_000_000


def log_level_to_severity_number(level: LogLevel) -> int:
    """The OTLP severity number of a level; ``ALL`` and ``NONE`` are 0
    (unspecified)."""
    return _SEVERITIES.get(level, 0)


def _log_record(options: Options, exclude_log_spans: bool, clock: ClockService) -> LogRecord:
    fiber = options.fiber
    observed = str(clock.now_nanos_unsafe())
    event_millis = options.millis
    attributes: dict[str, object] = dict(fiber.get_ref(CurrentLogAnnotations))
    attributes["effect.fiberId"] = fiber.id
    if not exclude_log_spans:
        # Spans are innermost first, so the outermost wins a repeated label.
        for label, start in fiber.get_ref(CurrentLogSpans):
            attributes[f"effect.log_span.{label}"] = event_millis - start
    errors = pretty_errors(options.cause)
    if errors:
        attributes["exception.type"] = errors[0].name
        attributes["exception.message"] = errors[0].message
        attributes["exception.stacktrace"] = "\n".join(error.stack for error in errors)
    message = options.message
    record: LogRecord = {
        "severityNumber": log_level_to_severity_number(options.log_level),
        "severityText": str(options.log_level),
        "timeUnixNano": str(event_millis * _NANOS_PER_MILLI),
        "observedTimeUnixNano": observed,
        "attributes": entries_to_attributes(attributes.items()),
        "body": unknown_to_attribute_value(message[0] if len(message) == 1 else list(message)),
        "droppedAttributesCount": 0,
    }
    span = fiber.get_ref(ParentSpan)
    if span is not None:
        record["traceId"] = span.trace_id.rjust(32, "0")
        record["spanId"] = span.span_id
    return record


def make(
    *,
    url: str,
    resource: ResourceOptions | None = None,
    headers: _headers.Input | None = None,
    compression: Compression = "none",
    export_interval: Duration | None = None,
    max_batch_size: int | None = None,
    shutdown_timeout: Duration | None = None,
    exclude_log_spans: bool = False,
) -> Effect[Logger[None], Never, Flusher | OtlpSerialization | HttpClient | Scope]:
    """A logger exporting each entry to ``url`` as an OTLP log record, in
    batches of ``max_batch_size`` (1000) every ``export_interval`` (1
    second), flushed for at most ``shutdown_timeout`` (3 seconds) when the
    scope closes. ``exclude_log_spans`` leaves out the
    ``effect.log_span.<label>`` attributes."""

    @gen
    def build():
        serialization = yield from OtlpSerialization()
        otel_resource = yield from from_options(resource)
        scope = instrumentation_scope()

        def body(records: list[Any]) -> tuple[Any, Effect[None]]:
            data: LogsData = {
                "resourceLogs": [
                    {
                        "resource": otel_resource,
                        "scopeLogs": [{"scope": scope, "logRecords": records}],
                    }
                ]
            }
            return serialization.logs(data), succeed(None)

        made = yield from exporter.make(
            label="OtlpLogger",
            url=url,
            headers=headers,
            compression=compression,
            max_batch_size=1000 if max_batch_size is None else max_batch_size,
            export_interval="1 second" if export_interval is None else export_interval,
            body=body,
            shutdown_timeout="3 seconds" if shutdown_timeout is None else shutdown_timeout,
        )
        clock = yield from Clock()
        return Logger(lambda options: made.push(_log_record(options, exclude_log_spans, clock)))

    return build


def layer(
    *,
    url: str,
    resource: ResourceOptions | None = None,
    headers: _headers.Input | None = None,
    compression: Compression = "none",
    export_interval: Duration | None = None,
    max_batch_size: int | None = None,
    shutdown_timeout: Duration | None = None,
    exclude_log_spans: bool = False,
    merge_with_existing: bool = True,
) -> Layer[Flusher, Never, HttpClient | OtlpSerialization]:
    """Installs ``make``'s logger next to the current loggers (instead of
    them with ``merge_with_existing=False``), with the shared
    ``layer_flusher``."""
    logger = make(
        url=url,
        resource=resource,
        headers=headers,
        compression=compression,
        export_interval=export_interval,
        max_batch_size=max_batch_size,
        shutdown_timeout=shutdown_timeout,
        exclude_log_spans=exclude_log_spans,
    )
    return logger_layer([logger], merge_with_existing=merge_with_existing).pipe(
        _layer.provide_merge(exporter.layer_flusher)
    )


def layer_from_config(
    *,
    resource: ResourceOptions | None = None,
    headers: _headers.Input | None = None,
    exclude_log_spans: bool = False,
    merge_with_existing: bool = True,
) -> Layer[Flusher, Never, HttpClient | OtlpSerialization]:
    """``layer`` configured from the OpenTelemetry environment: nothing
    but the flusher unless ``OTEL_LOGS_EXPORTER`` lists ``otlp``, an
    endpoint is set and ``OTEL_SDK_DISABLED`` is not true. Reads the
    compression, ``OTEL_EXPORTER_OTLP_(LOGS_)TIMEOUT`` /
    ``OTEL_BLRP_EXPORT_TIMEOUT`` (shutdown), ``OTEL_BLRP_SCHEDULE_DELAY``
    and ``OTEL_BLRP_MAX_EXPORT_BATCH_SIZE``. Invalid configuration is a
    defect."""

    @gen
    def build():
        disabled = yield from config.boolean("OTEL_SDK_DISABLED").with_default(False)
        endpoint = yield from env.endpoint("LOGS")
        exporters = yield from env.exporters("LOGS")
        if disabled or endpoint is None or "otlp" not in exporters:
            return exporter.layer_flusher
        compression = yield from env.compression("LOGS")
        base_timeout = yield from env.millis("OTEL_EXPORTER_OTLP_TIMEOUT")
        logs_timeout = yield from env.millis("OTEL_EXPORTER_OTLP_LOGS_TIMEOUT")
        export_timeout = yield from env.millis("OTEL_BLRP_EXPORT_TIMEOUT")
        schedule_delay = yield from env.millis("OTEL_BLRP_SCHEDULE_DELAY")
        max_batch_size = yield from config.integer("OTEL_BLRP_MAX_EXPORT_BATCH_SIZE").with_default(
            None
        )
        signal_headers = headers if headers is not None else (yield from env.headers("LOGS"))
        return layer(
            url=str(endpoint),
            resource=resource,
            headers=signal_headers,
            compression=compression,
            export_interval=schedule_delay,
            max_batch_size=max_batch_size,
            shutdown_timeout=env.first_of(logs_timeout, base_timeout, export_timeout),
            exclude_log_spans=exclude_log_spans,
            merge_with_existing=merge_with_existing,
        )

    return _layer.unwrap(build.or_die())
