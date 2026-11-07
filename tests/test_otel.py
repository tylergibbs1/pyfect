"""The OpenTelemetry bridge beyond Effect's own tests: what pyfect does
differently (attribute values, summaries, layers) and that the core never
imports OpenTelemetry."""

import ast
from pathlib import Path

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry import trace
from opentelemetry.sdk.metrics.export import (
    InMemoryMetricReader,
    Metric,
    MetricsData,
    NumberDataPoint,
    Sum,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import StatusCode, TraceFlags

import pyfect as fx
from pyfect import config_provider, metric, otel, testing
from pyfect.context import Context
from pyfect.otel._attributes import to_attribute_value
from pyfect.otel.metrics import MetricProducer
from pyfect.otel.tracer import OtelSpan, OtelTraceFlags, OtelTraceState
from pyfect.tracer import DisablePropagation, Ended, NativeSpan, SpanLink

_SOURCE = Path(__file__).parent.parent / "src" / "pyfect"


def _imported_modules(path: Path) -> set[str]:
    modules: set[str] = set()
    for node in ast.walk(ast.parse(path.read_text())):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module is not None:
            modules.add(node.module)
    return modules


def test_only_pyfect_otel_imports_opentelemetry():
    offenders = [
        str(path.relative_to(_SOURCE))
        for path in _SOURCE.rglob("*.py")
        if "otel" not in path.relative_to(_SOURCE).parts
        and any(m.split(".")[0] == "opentelemetry" for m in _imported_modules(path))
    ]
    assert offenders == []


def _resource_from(provider: config_provider.ConfigProvider) -> Resource:
    return testing.run_test(
        otel.resource.OtelResource()
        .pipe(fx.provide(otel.resource.layer_from_env({"extra": "x"})))
        .pipe(fx.provide(config_provider.layer(provider)))
    )


def test_resource_from_env_reads_the_current_config_provider():
    # Effect's layerFromEnv reads both variables through Config.
    provider = config_provider.from_unknown(
        {"OTEL_SERVICE_NAME": "svc", "OTEL_RESOURCE_ATTRIBUTES": "a=1"}
    )
    attributes = _resource_from(provider).attributes
    assert (attributes["service.name"], attributes["a"], attributes["extra"]) == ("svc", "1", "x")


def test_resource_from_env_treats_an_empty_service_name_as_absent():
    # Checked under Node: fromEnv reads "" as absent, so Config.option gives None.
    provider = config_provider.from_env({"OTEL_SERVICE_NAME": "", "OTEL_RESOURCE_ATTRIBUTES": ""})
    assert "service.name" not in _resource_from(provider).attributes


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("text", "text"),
        (3, 3),
        (2.5, 2.5),
        (True, True),
        (2**63, str(2**63)),
        (-(2**63), -(2**63)),
        (("a", "b"), ["a", "b"]),
        ([1, 2.5], [1, 2.5]),
        ([2**63], "[\n  9223372036854775808\n]"),
        ([1, -(2**63) - 1], "[\n  1,\n  -9223372036854775809\n]"),
        ([True, 1], "[\n  true,\n  1\n]"),
        ([], []),
        ({"a": 1}, '{\n  "a": 1\n}'),
        (None, "null"),
    ],
)
def test_attribute_values(value: object, expected: object):
    assert to_attribute_value(value) == expected


def _metrics(data: MetricsData | None) -> dict[str, Metric]:
    assert data is not None
    return {m.name: m for m in data.resource_metrics[0].scope_metrics[0].metrics}


def _points(found: Metric) -> list[NumberDataPoint]:
    assert isinstance(found.data, Sum)
    return list(found.data.data_points)


@testing.effect
def test_summary_is_a_quantiles_sum_with_count_and_sum():
    reader = InMemoryMetricReader()
    summary = metric.summary(
        "latency", max_age="1 minute", max_size=10, quantiles=[0.5], description="d"
    ).with_attributes({"unit": "ms"})

    @fx.gen
    def program():
        for value in (1, 2, 3):
            yield from summary.update(value)
        found = _metrics(reader.get_metrics_data())
        assert set(found) == {"latency_quantiles", "latency_count", "latency_sum"}
        quantiles = _points(found["latency_quantiles"])
        assert [(p.attributes or {}).get("quantile") for p in quantiles] == ["min", "0.5", "max"]
        assert [p.value for p in quantiles] == [1, 2, 3]
        assert found["latency_quantiles"].unit == "ms"
        assert (found["latency_count"].unit, _points(found["latency_count"])[0].value) == ("1", 3)
        assert _points(found["latency_sum"])[0].value == 6

    metrics_layer = otel.metrics.layer(lambda: reader).pipe(fx.provide(otel.resource.layer_empty))
    yield from program.pipe(fx.provide(metrics_layer)).pipe(
        fx.provide_service(metric.MetricRegistry, {})
    )


@testing.effect
def test_frequency_points_carry_the_word_as_key():
    reader = InMemoryMetricReader()
    words = metric.frequency("words")

    @fx.gen
    def program():
        yield from words.update("a")
        yield from words.update("b")
        yield from words.update("a")
        found = _metrics(reader.get_metrics_data())["words"]
        assert isinstance(found.data, Sum) and found.data.is_monotonic
        assert [((p.attributes or {})["key"], p.value) for p in _points(found)] == [
            ("a", 2),
            ("b", 1),
        ]

    config = otel.sdk.Configuration(metric_reader=reader)
    yield from program.pipe(fx.provide(otel.sdk.layer(config))).pipe(
        fx.provide_service(metric.MetricRegistry, {})
    )


class _RecordingReader(InMemoryMetricReader):
    def __init__(self) -> None:
        super().__init__()
        self.shutdowns: list[float] = []

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: object) -> None:
        self.shutdowns.append(timeout_millis)


@testing.effect
def test_a_released_metrics_layer_shuts_its_readers_down():
    reader = _RecordingReader()
    metrics_layer = otel.metrics.layer(lambda: reader, shutdown_timeout="1500 millis").pipe(
        fx.provide(otel.resource.layer_empty)
    )
    yield from fx.void.pipe(fx.provide(metrics_layer))
    assert reader.shutdowns == [1500]


@testing.effect
def test_external_span_keeps_flags_and_trace_state():
    span = otel.tracer.make_external_span(
        trace_id="1" * 32, span_id="2" * 16, trace_flags=0, trace_state="vendor=value"
    )
    assert not span.sampled
    assert span.annotations.get_unsafe(OtelTraceFlags) == TraceFlags(0)
    assert span.annotations.get_unsafe(OtelTraceState).to_header() == "vendor=value"
    yield from fx.void


@testing.effect
def test_logs_inside_a_span_are_its_events_and_links_are_exported():
    exporter = InMemorySpanExporter()
    tracing = otel.sdk.layer(otel.sdk.Configuration(span_processor=SimpleSpanProcessor(exporter)))
    linked = otel.tracer.make_external_span(trace_id="1" * 32, span_id="2" * 16)

    @fx.gen
    def program():
        yield from fx.log_info("hello").with_span("work", links=[SpanLink(linked, {"a": 1})])
        (span,) = exporter.get_finished_spans()
        assert [event.name for event in span.events] == ["hello"]
        (link,) = span.links
        assert (link.context.trace_id, link.context.span_id) == (
            int("1" * 32, 16),
            int("2" * 16, 16),
        )
        assert dict(link.attributes or {}) == {"a": 1}
        assert span.status.status_code is StatusCode.OK

    yield from program.pipe(fx.provide(tracing))


@testing.effect
def test_an_error_status_through_the_view_ends_the_span_with_its_message():
    @fx.gen
    def program():
        span = yield from fx.current_span()
        view = yield from otel.tracer.current_otel_span()
        view.set_status(StatusCode.ERROR, "broken")
        view.end()
        status = span.status
        assert isinstance(status, Ended)
        assert fx.exit.is_failure(status.exit)
        assert "broken" in status.exit.cause.pretty()

    yield from program.with_span("native")


@testing.effect
def test_a_propagation_disabled_span_leaves_its_parent_active():
    exporter = InMemorySpanExporter()
    tracing = otel.sdk.layer(otel.sdk.Configuration(span_processor=SimpleSpanProcessor(exporter)))

    @fx.gen
    def program():
        outer = yield from fx.current_span()
        active = yield from fx.sync(trace.get_current_span).with_span(
            "disabled", annotations=Context.make(DisablePropagation, True)
        )
        assert isinstance(outer, OtelSpan)
        assert active is outer.span

    yield from program.with_span("outer").pipe(fx.provide(tracing))


@testing.effect
def test_the_view_writes_attributes_events_links_and_exceptions_to_the_span():
    """Effect's ``makeOtelSpan``: OpenTelemetry API calls on the current span
    write through to the pyfect span, at the clock's time by default."""
    linked = otel.tracer.make_external_span(trace_id="1" * 32, span_id="2" * 16)

    @fx.gen
    def program():
        span = yield from fx.current_span()
        view = yield from otel.tracer.current_otel_span()
        assert isinstance(span, NativeSpan)
        context = view.get_span_context()
        assert (context.trace_id, context.span_id) == (
            int(span.trace_id, 16),
            int(span.span_id, 16),
        )
        assert view.is_recording()
        view.update_name("ignored")
        view.set_attribute("a", 1)
        view.set_attributes({"b": "two", "c": True})
        view.add_event("now", {"k": 1})
        view.add_event("then", None, 7)
        view.add_link(trace.SpanContext(int("1" * 32, 16), int("2" * 16, 16), False), {"r": 1})
        view.record_exception(ValueError("bad"), timestamp=9)
        view.end(11)
        assert span.name == "native"
        assert dict(span.attributes) == {"a": 1, "b": "two", "c": True}
        events = [(name, time, dict(attributes)) for name, time, attributes in span.events]
        assert events[:2] == [("now", 0, {"k": 1}), ("then", 7, {})]
        name, time, attributes = events[2]
        assert (name, time) == ("bad", 9)
        assert attributes["exception.type"] == "ValueError"
        assert attributes["exception.message"] == "bad"
        assert "ValueError: bad" in str(attributes["exception.stacktrace"])
        (link,) = span.links
        assert (link.span.trace_id, link.span.span_id) == (linked.trace_id, linked.span_id)
        assert dict(link.attributes) == {"r": 1}
        status = span.status
        assert isinstance(status, Ended)
        assert (status.end_time, status.exit) == (11, fx.Success(None))

    yield from program.with_span("native")


@testing.effect
def test_links_added_to_a_started_otel_span_are_exported():
    exporter = InMemorySpanExporter()
    tracing = otel.sdk.layer(otel.sdk.Configuration(span_processor=SimpleSpanProcessor(exporter)))
    linked = otel.tracer.make_external_span(trace_id="1" * 32, span_id="2" * 16)

    @fx.gen
    def program():
        span = yield from fx.current_span()
        assert isinstance(span, OtelSpan)
        span.add_links([SpanLink(linked, {"a": 1})])
        assert [link.span for link in span.links] == [linked]

    yield from program.with_span("work").pipe(fx.provide(tracing))
    (exported,) = exporter.get_finished_spans()
    (link,) = exported.links
    assert (link.context.trace_id, link.context.span_id) == (int("1" * 32, 16), int("2" * 16, 16))
    assert dict(link.attributes or {}) == {"a": 1}


@testing.effect
def test_a_view_status_set_back_to_ok_ends_the_span_successfully():
    @fx.gen
    def program():
        span = yield from fx.current_span()
        view = yield from otel.tracer.current_otel_span()
        view.set_status(StatusCode.ERROR, "broken")
        view.set_status(StatusCode.OK)
        view.end()
        assert isinstance(span.status, Ended)
        assert fx.exit.is_success(span.status.exit)

    yield from program.with_span("native")


def _delta_values(data: MetricsData, name: str) -> list[tuple[dict[str, object], object]]:
    return [(dict(p.attributes or {}), p.value) for p in _points(_metrics(data)[name])]


@testing.effect
def test_a_non_incremental_counter_reports_negative_deltas():
    """Effect's ``Metric.test.ts`` "Counter > exports negative updates as
    deltas", through the OpenTelemetry producer instead of Effect's OTLP
    exporter."""

    @fx.gen
    def program():
        services = yield from fx.context()
        producer = MetricProducer(Resource({}), services, "delta")
        counter = metric.counter("counter_delta")
        values: list[object] = []
        for update in (5, -2, 4):
            yield from counter.update(update)
            values.extend(value for _, value in _delta_values(producer.collect(), "counter_delta"))
        assert values == [5, -2, 4]

    yield from program.pipe(fx.provide_service(metric.MetricRegistry, {}))


@testing.effect
def test_delta_frequencies_and_summaries_report_changes_since_the_last_collection():
    @fx.gen
    def program():
        services = yield from fx.context()
        producer = MetricProducer(Resource({}), services, "delta")
        words = metric.frequency("words")
        summary = metric.summary("latency", max_age="1 minute", max_size=10, quantiles=[0.5])
        yield from words.update("a")
        yield from words.update("a")
        yield from summary.update(1)
        yield from summary.update(2)
        producer.collect()
        yield from words.update("a")
        yield from words.update("b")
        yield from summary.update(4)
        data = producer.collect()
        assert _delta_values(data, "words") == [({"key": "a"}, 1), ({"key": "b"}, 1)]
        assert _delta_values(data, "latency_count") == [({}, 1)]
        assert _delta_values(data, "latency_sum") == [({}, 4)]

    yield from program.pipe(fx.provide_service(metric.MetricRegistry, {}))
