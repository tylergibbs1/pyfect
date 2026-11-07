"""Ports of Effect's ``OtlpTracer.test.ts`` and the OTLP titles of
``Tracer.test.ts``.

Each test's docstring is the Effect test title. The instrumentation scope
is ``{"name": "pyfect", "version": <pyfect's version>}`` where Effect's is
``effect`` and Effect's version. ``span.end(start + 1n, exit)`` is
``span.end(start + 1, exit)`` in whole nanoseconds.
"""

from __future__ import annotations

import re
from typing import Any

import pyfect as fx
from pyfect import cause, exit, layer
from pyfect._version import VERSION
from pyfect.http import body as http_body
from pyfect.layer import Layer
from pyfect.observability import otlp_exporter, otlp_serialization, otlp_tracer
from pyfect.observability.otlp_serialization import OtlpSerialization, OtlpSerializationService
from pyfect.observability.otlp_tracer import OtlpSpan, TraceData
from pyfect.tracer import ExternalSpan, NativeSpan, Span, SpanLink, Started

from ._otlp import Collector, client_layer, collector


def _capture() -> tuple[Collector, Layer[otlp_exporter.Flusher]]:
    seen, http = collector()
    tracing = (
        otlp_tracer.layer(
            url="http://localhost:4318/v1/traces",
            resource={"service_name": "test", "service_version": "service-version"},
            export_interval="1 hour",
        )
        .pipe(layer.provide(otlp_serialization.layer_json))
        .pipe(layer.provide(client_layer(http)))
    )
    return seen, tracing


def _scope_spans(seen: Collector) -> list[dict[str, Any]]:
    return [body["resourceSpans"][0]["scopeSpans"][0] for body in seen.json()]


def _flush() -> fx.Effect[None, Any, Any]:
    return otlp_exporter.Flusher().flat_map(lambda flusher: flusher.flush)


def test_uses_effect_as_the_instrumentation_scope_not_the_service_name() -> None:
    """uses effect as the instrumentation scope, not the service name"""
    seen, tracing = _capture()

    @fx.gen
    def program():
        yield from fx.void.with_span("test")
        yield from _flush()

    fx.run_sync(program.pipe(layer.provide(tracing)))
    assert _scope_spans(seen)[0]["scope"] == {"name": "pyfect", "version": VERSION}


def test_pads_64_bit_trace_ids_in_spans_and_links() -> None:
    """pads 64-bit trace ids in spans and links"""
    seen, tracing = _capture()
    parent = ExternalSpan(trace_id="463ac35c9f6413ad", span_id="0020000000000001")

    @fx.gen
    def program():
        yield from fx.void.with_span("test", parent=parent, links=[SpanLink(parent, {})])
        yield from _flush()

    fx.run_sync(program.pipe(layer.provide(tracing)))
    span = _scope_spans(seen)[0]["spans"][0]
    assert span["traceId"] == "0000000000000000463ac35c9f6413ad"
    assert span["links"][0]["traceId"] == "0000000000000000463ac35c9f6413ad"


def _otlp_tracer_layer(serialization: Layer[OtlpSerialization]) -> Layer[otlp_exporter.Flusher]:
    _, http = collector()
    return (
        otlp_tracer.layer(
            url="http://localhost:4318/v1/traces", resource={"service_name": "test-service"}
        )
        .pipe(layer.provide(serialization))
        .pipe(layer.provide(client_layer(http)))
    )


def test_generates_otlp_span_identifiers() -> None:
    """generates OTLP span identifiers"""

    @fx.gen
    def program():
        root = yield from fx.current_span().with_span("root")
        child = yield from fx.current_span().with_span("child", parent=root)
        return root, child

    root, child = fx.run_sync(
        program.pipe(layer.provide(_otlp_tracer_layer(otlp_serialization.layer_json))).or_die()
    )
    assert not isinstance(root, NativeSpan)
    assert not isinstance(child, NativeSpan)
    assert re.fullmatch(r"[0-9a-f]{32}", root.trace_id)
    assert re.fullmatch(r"[0-9a-f]{16}", root.span_id)
    assert child.trace_id == root.trace_id
    assert re.fullmatch(r"[0-9a-f]{16}", child.span_id)


def test_should_preserve_nested_span_context_with_otlp_tracer() -> None:
    """should preserve nested span context with OtlpTracer"""
    inner = fx.succeed(42).with_span("child-span", attributes={"test": "child"})
    program = inner.with_span("parent-span", attributes={"test": "parent"})
    result = fx.run_sync(
        program.pipe(layer.provide(_otlp_tracer_layer(otlp_serialization.layer_json)))
    )
    assert result == 42


def _export_span(ended: fx.Exit[Any, Any], after_end: Any = None) -> OtlpSpan:
    exported: list[TraceData] = []

    def traces(data: TraceData) -> http_body.HttpBody:
        exported.append(data)
        return http_body.EMPTY

    serialization = layer.succeed(
        OtlpSerialization,
        OtlpSerializationService(
            traces=traces, metrics=lambda _: http_body.EMPTY, logs=lambda _: http_body.EMPTY
        ),
    )

    @fx.gen
    def program():
        span: Span = yield from fx.make_span("test")
        assert isinstance(span.status, Started)
        span.end(span.status.start_time + 1, ended)
        if after_end is not None:
            after_end(span)

    fx.run_sync(program.pipe(layer.provide(_otlp_tracer_layer(serialization))))
    spans = [
        span
        for data in exported
        for resource in data["resourceSpans"]
        for scope in resource["scopeSpans"]
        for span in scope["spans"]
    ]
    assert len(spans) == 1
    return spans[0]


def test_marks_an_empty_cause_ok_without_a_description() -> None:
    """OtlpTracer span status marks an empty cause Ok without a description"""
    span = _export_span(exit.fail_cause(cause.empty))
    assert span["status"] == {"code": 1}
    assert span["events"] == []
    assert span["attributes"] == []


def test_leaves_interruption_unset_with_effect_fiber_interrupted() -> None:
    """OtlpTracer span status leaves interruption Unset with effect.fiber.interrupted"""
    span = _export_span(exit.interrupt())
    assert span["status"] == {"code": 0}
    assert span["events"] == []
    assert span["attributes"] == [{"key": "effect.fiber.interrupted", "value": {"boolValue": True}}]


def test_exports_a_span_once_when_end_is_called_again() -> None:
    """OtlpTracer span status exports a span once when end is called again"""

    def end_again(span: Span) -> None:
        status = span.status
        assert not isinstance(status, Started)
        span.end(status.start_time + 2, exit.fail("late"))

    span = _export_span(exit.void, end_again)
    assert span["status"] == {"code": 1}
