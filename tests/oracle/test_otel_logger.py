"""Ports of ``@effect/opentelemetry``'s ``OtelLogger.test.ts``.

Each test's docstring is the Effect test title. ``NodeSdk.layer`` is
``otel.sdk.layer(Configuration(...))``; a record's ``spanContext`` is the
``trace_id`` / ``span_id`` / ``trace_flags`` of Python's ``LogRecord``,
which keeps no trace state or locality. Severity texts are pyfect's level
names (``"INFO"``).

Adapted, with the reason:

- "keeps event time separate from observed time and uses wall-clock span
  time": a pyfect log's date comes from the clock's nanoseconds (Effect's
  from its milliseconds), so the port checks the record's time is that
  instant to the microsecond, and the observed time and the span's start
  are the wall clock, not the monotonic one.
- "correlates a log with an external parent span": Python's ``LogRecord``
  has no trace state or ``is_remote``; the ids and flags are checked.
- "uses ambient context only when there is no Effect parent span": the
  ambient context is attached with ``context.attach``.
"""

from collections.abc import Sequence
from datetime import timedelta
from typing import Any

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry._logs import SeverityNumber
from opentelemetry.sdk._logs import LogRecordProcessor, ReadableLogRecord, ReadWriteLogRecord
from opentelemetry.sdk._logs.export import InMemoryLogRecordExporter, SimpleLogRecordProcessor
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    TraceFlags,
    TraceState,
    format_span_id,
    format_trace_id,
)

import pyfect as fx
from pyfect import config_provider, layer, otel, testing
from pyfect.cause import Cause, Fail
from pyfect.clock import Clock
from pyfect.context import Context
from pyfect.duration import Duration
from pyfect.layer import Layer
from pyfect.logger import LogLevel, MinimumLogLevel
from pyfect.otel._attributes import PYFECT_VERSION
from pyfect.otel.resource import OtelResource
from pyfect.otel.tracer import OtelTraceFlags, OtelTraceState
from pyfect.tracer import ExternalSpan


def _sdk(
    logs: InMemoryLogRecordExporter, spans: InMemorySpanExporter | None = None
) -> Layer[OtelResource]:
    return otel.sdk.layer(
        otel.sdk.Configuration(
            resource=otel.sdk.ResourceConfig(
                service_name="test", service_version="service-version"
            ),
            log_record_processor=[SimpleLogRecordProcessor(logs)],
            span_processor=() if spans is None else [SimpleSpanProcessor(spans)],
        )
    )


def _records(exporter: InMemoryLogRecordExporter) -> Sequence[ReadableLogRecord]:
    return exporter.get_finished_logs()


def _attributes(record: ReadableLogRecord) -> dict[str, Any]:
    return dict(record.log_record.attributes or {})


@testing.effect
def test_adds_sdk_resource_defaults_when_the_resource_comes_only_from_the_environment():
    """adds SDK resource defaults when the resource comes only from the environment"""
    exporter = InMemoryLogRecordExporter()
    config = otel.sdk.Configuration(log_record_processor=[SimpleLogRecordProcessor(exporter)])

    @fx.gen
    def program():
        yield from fx.log("test")
        record = _records(exporter)[0]
        scope = record.instrumentation_scope
        assert scope is not None
        assert (scope.name, scope.version) == ("pyfect", PYFECT_VERSION)
        assert dict(record.resource.attributes) == {
            "service.name": "env-service",
            "telemetry.sdk.name": "pyfect",
            "telemetry.sdk.language": "python",
            "telemetry.sdk.version": PYFECT_VERSION,
        }

    provider = config_provider.from_env({"OTEL_SERVICE_NAME": "env-service"})
    yield from program.pipe(fx.provide(otel.sdk.layer(lambda: config))).pipe(
        fx.provide_service(config_provider.CurrentConfigProvider, provider)
    )


@testing.effect
def test_namespaces_generated_attributes_and_lets_them_override_annotations():
    """namespaces generated attributes and lets them override annotations"""
    exporter = InMemoryLogRecordExporter()
    error = TypeError("cause message")
    error.__cause__ = ValueError("nested failure")

    @fx.gen
    def logged():
        yield from testing.adjust(timedelta(milliseconds=5))
        yield from fx.log_error("boom", Cause((Fail(error),)))

    @fx.gen
    def program():
        fiber = yield from fx.current_fiber()
        yield from logged.with_log_span("op").annotate_logs(
            {
                "effect.fiberId": -1,
                "effect.log_span.op": -1,
                "exception.type": "annotated type",
                "exception.message": "annotated message",
                "exception.stacktrace": "annotated stack",
            }
        )
        attributes = _attributes(_records(exporter)[0])
        assert attributes["effect.fiberId"] == fiber.id
        assert attributes["effect.log_span.op"] == 5
        assert attributes["exception.type"] == "TypeError"
        assert attributes["exception.message"] == "cause message"
        assert "nested failure" in attributes["exception.stacktrace"]

    yield from program.pipe(fx.provide(_sdk(exporter)))


class _FailingFlush(LogRecordProcessor):
    def __init__(self) -> None:
        self.shutdowns = 0

    def on_emit(self, log_record: ReadWriteLogRecord) -> None:
        pass

    def force_flush(self, timeout_millis: int = 30000) -> bool:
        raise RuntimeError("flush failed")

    def shutdown(self) -> None:
        self.shutdowns += 1


@testing.effect
def test_shuts_down_the_logger_provider_after_force_flush_rejects():
    """shuts down the logger provider after forceFlush rejects"""
    processor = _FailingFlush()
    provider = otel.logger.layer_logger_provider(processor).pipe(
        layer.provide(otel.resource.layer_empty)
    )
    yield from fx.scoped(provider.build()).exit()
    assert processor.shutdowns == 1


@testing.effect
def test_emits_log_records():
    """emits log records"""
    exporter = InMemoryLogRecordExporter()

    @fx.gen
    def program():
        yield from fx.log("test").repeat(times=9)
        assert len(_records(exporter)) == 10
        record = _records(exporter)[0]
        assert not record.log_record.trace_id
        assert not record.log_record.span_id
        assert "traceId" not in _attributes(record)
        assert "spanId" not in _attributes(record)

    yield from program.pipe(fx.provide(_sdk(exporter)))


@testing.effect
def test_maps_effect_log_level_to_otel_severity_number_spec_values():
    """maps Effect LogLevel to OTel SeverityNumber spec values"""
    exporter = InMemoryLogRecordExporter()

    @fx.gen
    def program():
        yield from fx.log_trace("trace")
        yield from fx.log_debug("debug")
        yield from fx.log_info("info")
        yield from fx.log_warning("warn")
        yield from fx.log_error("error")
        yield from fx.log_fatal("fatal")
        by_text = {
            r.log_record.severity_text: r.log_record.severity_number for r in _records(exporter)
        }
        assert by_text == {
            "Trace": SeverityNumber.TRACE,
            "Debug": SeverityNumber.DEBUG,
            "Info": SeverityNumber.INFO,
            "Warn": SeverityNumber.WARN,
            "Error": SeverityNumber.ERROR,
            "Fatal": SeverityNumber.FATAL,
        }

    yield from program.pipe(fx.provide(_sdk(exporter))).pipe(
        fx.provide_service(MinimumLogLevel, LogLevel.TRACE)
    )


_WALL_NANOS = 1_735_689_600_123_456_789
_MONOTONIC_NANOS = 123_456_789


class _SkewedClock:
    def current_time_millis_unsafe(self) -> float:
        return _WALL_NANOS / 1e6

    def monotonic_unsafe(self) -> float:
        return _MONOTONIC_NANOS / 1e9

    def now_nanos_unsafe(self) -> int:
        return _WALL_NANOS

    def monotonic_nanos_unsafe(self) -> int:
        return _MONOTONIC_NANOS

    def sleep(self, seconds: Duration) -> fx.Effect[None]:
        return fx.void


@testing.effect
def test_keeps_event_time_separate_from_observed_time_and_uses_wall_clock_span_time():
    """keeps event time separate from observed time and uses wall-clock span time"""
    logs = InMemoryLogRecordExporter()
    spans = InMemorySpanExporter()

    @fx.gen
    def program():
        yield from fx.log("test").with_span("parent")
        records = _records(logs)
        finished = spans.get_finished_spans()
        assert (len(records), len(finished)) == (1, 1)
        record, span = records[0].log_record, finished[0]
        assert record.timestamp == _WALL_NANOS // 1000 * 1000
        assert record.observed_timestamp == _WALL_NANOS
        assert record.observed_timestamp == span.start_time
        span_context = span.get_span_context()
        assert span_context is not None
        attributes = dict(record.attributes or {})
        assert attributes["spanId"] == format_span_id(span_context.span_id)
        assert attributes["traceId"] == format_trace_id(span_context.trace_id)

    yield from program.pipe(fx.provide(_sdk(logs, spans))).pipe(
        fx.provide_service(Clock, _SkewedClock())
    )


@testing.effect
def test_does_not_let_annotations_overwrite_active_span_correlation():
    """does not let annotations overwrite active span correlation"""
    logs = InMemoryLogRecordExporter()
    spans = InMemorySpanExporter()

    @fx.gen
    def program():
        yield from (
            fx.log("test")
            .annotate_logs({"traceId": "spoof-trace", "spanId": "spoof-span"})
            .with_span("parent")
        )
        record = _records(logs)[0].log_record
        span_context = spans.get_finished_spans()[0].get_span_context()
        assert span_context is not None
        attributes = dict(record.attributes or {})
        assert attributes["traceId"] == format_trace_id(span_context.trace_id)
        assert attributes["spanId"] == format_span_id(span_context.span_id)
        assert (record.trace_id, record.span_id, record.trace_flags) == (
            span_context.trace_id,
            span_context.span_id,
            span_context.trace_flags,
        )

    yield from program.pipe(fx.provide(_sdk(logs, spans)))


@testing.effect
def test_correlates_a_log_with_an_external_parent_span():
    """correlates a log with an external parent span"""
    exporter = InMemoryLogRecordExporter()
    trace_id, span_id = "ab" * 16, "cd" * 8
    annotations = Context.make(OtelTraceFlags, TraceFlags(0x02)).add(
        OtelTraceState, TraceState([("vendor", "value")])
    )
    parent = ExternalSpan(
        span_id=span_id, trace_id=trace_id, sampled=False, annotations=annotations
    )

    @fx.gen
    def program():
        yield from fx.log("test").with_parent_span(parent)
        record = _records(exporter)[0].log_record
        assert record.trace_id is not None and record.span_id is not None
        assert format_trace_id(record.trace_id) == trace_id
        assert format_span_id(record.span_id) == span_id
        assert record.trace_flags == 0x02

    yield from program.pipe(fx.provide(_sdk(exporter)))


def test_uses_ambient_context_only_when_there_is_no_effect_parent_span():
    """uses ambient context only when there is no Effect parent span"""
    exporter = InMemoryLogRecordExporter()
    ambient = SpanContext(
        int("ab" * 16, 16), int("cd" * 8, 16), False, TraceFlags(TraceFlags.SAMPLED)
    )
    effect_span = ExternalSpan(span_id="12" * 8, trace_id="ef" * 16)

    @fx.gen
    def program():
        yield from fx.log("ambient")
        yield from fx.log("effect").with_parent_span(effect_span)
        records = [r.log_record for r in _records(exporter)]
        assert len(records) == 2
        assert (records[0].trace_id, records[0].span_id) == (ambient.trace_id, ambient.span_id)
        assert "traceId" not in dict(records[0].attributes or {})
        assert "spanId" not in dict(records[0].attributes or {})
        assert records[1].trace_id is not None and records[1].span_id is not None
        assert format_trace_id(records[1].trace_id) == effect_span.trace_id
        assert format_span_id(records[1].span_id) == effect_span.span_id

    token = otel_context.attach(trace.set_span_in_context(NonRecordingSpan(ambient)))
    try:
        fx.run_blocking(program.pipe(fx.provide(_sdk(exporter))))
    finally:
        otel_context.detach(token)


@testing.effect
def test_with_span_not_provided():
    """withSpan (not provided)"""
    exporter = InMemoryLogRecordExporter()
    config = otel.sdk.Configuration(resource=otel.sdk.ResourceConfig(service_name="test"))

    @fx.gen
    def program():
        yield from fx.log("test")
        assert len(_records(exporter)) == 0

    yield from program.pipe(fx.provide(otel.sdk.layer(config)))
