"""pyfect logs as OpenTelemetry log records (Effect's ``OtelLogger``).

``layer()`` installs a logger emitting every log through the
``OtelLoggerProvider``; ``layer_logger_provider(processors)`` makes an SDK
logger provider, flushed and shut down when the layer is released. A log
inside a span carries the span's context, so backends correlate the two.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

import traceback
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Final, Never

from opentelemetry import context as otel_context
from opentelemetry._logs import LogRecord, SeverityNumber
from opentelemetry.sdk import _logs as sdk_logs
from opentelemetry.sdk.resources import Resource
from opentelemetry.util.types import AnyValue

from pyfect import layer as _layer
from pyfect.clock import Clock, ClockService
from pyfect.context import Tag
from pyfect.duration import Duration
from pyfect.effect import gen, sync
from pyfect.layer import Layer
from pyfect.logger import CurrentLogAnnotations, CurrentLogSpans, Logger, LogLevel, Options
from pyfect.logger import layer as logger_layer
from pyfect.otel._attributes import PYFECT_VERSION, to_attribute_value
from pyfect.otel._shutdown import DEFAULT_SHUTDOWN_TIMEOUT, flush_and_shut_down
from pyfect.otel._span import populate_context
from pyfect.otel.resource import OtelResource
from pyfect.scope import acquire_release
from pyfect.tracer import ParentSpan

__all__ = [
    "OtelLoggerProvider",
    "layer",
    "layer_logger_provider",
    "log_level_to_severity_number",
    "make",
]


class OtelLoggerProvider(Tag[sdk_logs.LoggerProvider]):
    """The OpenTelemetry logger provider pyfect logs are emitted through."""


_SEVERITIES: Final = {
    LogLevel.TRACE: SeverityNumber.TRACE,
    LogLevel.DEBUG: SeverityNumber.DEBUG,
    LogLevel.INFO: SeverityNumber.INFO,
    LogLevel.WARN: SeverityNumber.WARN,
    LogLevel.ERROR: SeverityNumber.ERROR,
    LogLevel.FATAL: SeverityNumber.FATAL,
}


def log_level_to_severity_number(level: LogLevel) -> SeverityNumber:
    """The OpenTelemetry severity of a level (1 to 24); ``ALL`` and ``NONE``
    are ``UNSPECIFIED``."""
    return _SEVERITIES.get(level, SeverityNumber.UNSPECIFIED)


_EPOCH: Final = datetime(1970, 1, 1, tzinfo=UTC)
_MICROSECOND: Final = timedelta(microseconds=1)


def _record(options: Options, observed: int) -> LogRecord:
    fiber = options.fiber
    attributes: dict[str, AnyValue] = {
        key: to_attribute_value(value)
        for key, value in fiber.get_ref(CurrentLogAnnotations).items()
    }
    attributes["effect.fiberId"] = fiber.id
    span = fiber.get_ref(ParentSpan)
    context = otel_context.get_current()
    if span is not None:
        context = populate_context(context, span, span.annotations)
        attributes["spanId"] = span.span_id
        attributes["traceId"] = span.trace_id
    now = options.millis
    # Spans are innermost first, so the outermost wins a repeated label.
    for label, start in fiber.get_ref(CurrentLogSpans):
        attributes[f"effect.log_span.{label}"] = now - start
    errors = options.cause.pretty_errors()
    if errors:
        attributes["exception.type"] = type(errors[0]).__name__
        attributes["exception.message"] = str(errors[0])
        attributes["exception.stacktrace"] = "\n".join(
            "".join(traceback.format_exception(error)) for error in errors
        )
    message = [to_attribute_value(item) for item in options.message]
    return LogRecord(
        timestamp=(options.date - _EPOCH) // _MICROSECOND * 1000,
        observed_timestamp=observed,
        context=context,
        severity_text=options.log_level.name,
        severity_number=log_level_to_severity_number(options.log_level),
        body=message[0] if len(message) == 1 else message,
        attributes=attributes,
    )


def _logger(provider: sdk_logs.LoggerProvider, clock: ClockService) -> Logger[None]:
    otel_logger = provider.get_logger("pyfect", PYFECT_VERSION)
    return Logger(lambda options: otel_logger.emit(_record(options, clock.unsafe_now_nanos())))


@gen
def make():
    """A logger emitting each log as a record through the
    ``OtelLoggerProvider``: the log annotations, ``effect.fiberId``, the
    span ids, each log span's elapsed milliseconds
    (``effect.log_span.<label>``) and the cause's first error
    (``exception.*``) as attributes."""
    provider = yield from OtelLoggerProvider()
    clock = yield from Clock()
    return _logger(provider, clock)


def layer(*, merge_with_existing: bool = True) -> Layer[Never, Never, OtelLoggerProvider]:
    """Installs ``make``'s logger, next to the current loggers (or instead
    of them, with ``merge_with_existing=False``)."""
    return logger_layer([make], merge_with_existing=merge_with_existing)


def layer_logger_provider(
    processors: sdk_logs.LogRecordProcessor | Sequence[sdk_logs.LogRecordProcessor],
    *,
    shutdown_timeout: Duration = DEFAULT_SHUTDOWN_TIMEOUT,
) -> Layer[OtelLoggerProvider, Never, OtelResource]:
    """An SDK logger provider with the ``OtelResource`` and ``processors``,
    flushed (for at most ``shutdown_timeout``) and shut down when the layer
    is released."""
    given = [processors] if isinstance(processors, sdk_logs.LogRecordProcessor) else processors

    def acquire(resource: Resource) -> sdk_logs.LoggerProvider:
        provider = sdk_logs.LoggerProvider(resource=resource, shutdown_on_exit=False)
        for processor in given:
            provider.add_log_record_processor(processor)
        return provider

    return _layer.effect(
        OtelLoggerProvider,
        OtelResource().flat_map(
            lambda resource: acquire_release(
                sync(lambda: acquire(resource)),
                lambda provider, _exit: flush_and_shut_down(provider, shutdown_timeout),
            )
        ),
    )
