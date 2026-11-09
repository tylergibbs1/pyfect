"""Ports of Effect's ``OtlpMetrics.test.ts`` and ``Metric.test.ts``'s
"Counter > exports negative updates as deltas".

Each test's docstring is the Effect test title. ``Metric.update(m, v)`` is
``m.update(v)``; each test gets a fresh ``MetricRegistry``. A
``bigint`` counter or gauge is one made with ``bigint=True``.
"""

from __future__ import annotations

from typing import Any

import pytest

import pyfect as fx
from pyfect import layer, metric, testing
from pyfect.http import client, response
from pyfect.http.client import HttpClientError
from pyfect.http.request import HttpClientRequest
from pyfect.http.response import HttpClientResponse
from pyfect.layer import Layer
from pyfect.observability import otlp_exporter, otlp_metrics, otlp_serialization
from pyfect.observability.otlp_metrics import AggregationTemporality

from ._otlp import Collector, client_layer, collector


def _layer(
    http: Any, temporality: AggregationTemporality, export_interval: str = "10 seconds"
) -> Layer[otlp_exporter.Flusher]:
    return (
        otlp_metrics.layer(
            url="http://localhost:4318/v1/metrics",
            resource={"service_name": "test-service"},
            temporality=temporality,
            export_interval=export_interval,
        )
        .pipe(layer.provide_merge(client_layer(http)))
        .pipe(layer.provide(otlp_serialization.layer_json))
    )


def _run(
    program: fx.Effect[Any, Any, Any], temporality: AggregationTemporality
) -> fx.Effect[Collector, Any, Any]:
    """``program`` with an exporter every 10 seconds and a fresh registry;
    what it exported by its end (as Effect reads it, before the exporter's
    shutdown export)."""
    seen, http = collector()
    exported = program.and_then(fx.sync(lambda: Collector(list(seen.requests))))
    return exported.pipe(layer.provide(_layer(http, temporality))).pipe(
        fx.provide_service(metric.MetricRegistry, {})
    )


def _trigger_export() -> fx.Effect[None]:
    return testing.adjust("10 seconds")


def _find_metric(body: Any, name: str) -> Any:
    for resource_metrics in body["resourceMetrics"]:
        for scope_metrics in resource_metrics["scopeMetrics"]:
            for found in scope_metrics["metrics"]:
                if found["name"] == name:
                    return found
    return None


def _frequency_value(body: Any, name: str, key: str) -> Any:
    for point in _find_metric(body, name)["sum"]["dataPoints"]:
        if {"key": "key", "value": {"stringValue": key}} in point["attributes"]:
            return point["asInt"]
    return None


@testing.effect
def test_retains_delta_checkpoints_after_a_failed_export():
    """retains delta checkpoints after a failed export"""
    seen = Collector()

    def answer(request: HttpClientRequest) -> HttpClientResponse:
        seen.requests.append(request)
        return response.make(request, status=400 if len(seen.requests) == 1 else 200)

    _, http = collector(answer)

    @fx.gen
    def program():
        yield from metric.counter("repro_counter").update(5)
        histogram = metric.histogram("repro_histogram", boundaries=[10, 50, 100])
        yield from histogram.update(25)
        yield from histogram.update(75)
        frequency = metric.frequency("repro_frequency")
        yield from frequency.update("a")
        yield from frequency.update("a")
        yield from frequency.update("b")
        flusher = yield from otlp_exporter.Flusher()
        yield from flusher.flush
        yield from testing.adjust("1 minute")
        yield from flusher.flush

    yield from program.pipe(layer.provide(_layer(http, "delta", "1 hour"))).pipe(
        fx.provide_service(metric.MetricRegistry, {})
    )
    first, second = seen.json()[:2]
    counter = "repro_counter"
    assert _find_metric(first, counter)["sum"]["dataPoints"][0]["asDouble"] == 5
    assert _find_metric(second, counter)["sum"]["dataPoints"][0]["asDouble"] == 5
    for body in (first, second):
        point = _find_metric(body, "repro_histogram")["histogram"]["dataPoints"][0]
        assert (point["count"], point["sum"]) == (2, 100)
        assert _frequency_value(body, "repro_frequency", "a") == 2
        assert _frequency_value(body, "repro_frequency", "b") == 1
    assert (
        _find_metric(second, counter)["sum"]["dataPoints"][0]["startTimeUnixNano"]
        == _find_metric(first, counter)["sum"]["dataPoints"][0]["startTimeUnixNano"]
    )


@testing.effect
def test_does_not_regress_delta_checkpoints_when_exports_complete_out_of_order():
    """does not regress delta checkpoints when exports complete out of order"""
    started = yield from fx.for_each(range(2), lambda _: fx.Deferred[None].make())
    releases = yield from fx.for_each(range(2), lambda _: fx.Deferred[None].make())
    seen = Collector()

    def post(
        requests: fx.Effect[HttpClientRequest, Any, Any],
    ) -> fx.Effect[HttpClientResponse, HttpClientError]:
        @fx.gen
        def send():
            request = yield from requests
            index = len(seen.requests)
            seen.requests.append(request)
            if index < 2:
                yield from started[index].succeed(None)
                yield from releases[index].wait()
            return response.make(request)

        return send

    http = client.make_with(post, fx.succeed)

    @fx.gen
    def program():
        counter = metric.counter("concurrent_delta")
        flusher = yield from otlp_exporter.Flusher()
        yield from counter.update(1)
        first = yield from flusher.flush.fork()
        yield from started[0].wait()

        yield from testing.adjust("1 second")
        yield from counter.update(1)
        second = yield from flusher.flush.fork()
        yield from started[1].wait()

        yield from releases[1].succeed(None)
        yield from second.join()
        yield from releases[0].succeed(None)
        yield from first.join()

        yield from testing.adjust("1 second")
        yield from flusher.flush

    yield from fx.scoped(
        program.pipe(layer.provide(_layer(http, "delta", "1 hour"))).pipe(
            fx.provide_service(metric.MetricRegistry, {})
        )
    )
    third = seen.json()[2]
    assert _find_metric(third, "concurrent_delta")["sum"]["dataPoints"][0]["asDouble"] == 0


@testing.effect
def test_reports_counter_totals_across_export_intervals():
    """cumulative temporality reports counter totals across export intervals"""

    @fx.gen
    def program():
        counter = metric.counter("cumulative_counter_test", description="Test counter")
        yield from counter.update(5)
        yield from _trigger_export()
        yield from counter.update(3)
        yield from _trigger_export()

    seen = yield from _run(program, "cumulative")
    first, second = seen.json()[:2]
    assert _find_metric(first, "cumulative_counter_test")["sum"]["dataPoints"][0]["asDouble"] == 5
    assert _find_metric(second, "cumulative_counter_test")["sum"]["dataPoints"][0]["asDouble"] == 8


@testing.effect
def test_reports_histogram_count_and_sum_across_export_intervals():
    """cumulative temporality reports histogram count and sum across export intervals"""

    @fx.gen
    def program():
        histogram = metric.histogram(
            "cumulative_histogram_test", description="Test histogram", boundaries=[10, 50, 100]
        )
        yield from histogram.update(25)
        yield from histogram.update(75)
        yield from _trigger_export()
        yield from histogram.update(30)
        yield from _trigger_export()

    seen = yield from _run(program, "cumulative")
    first, second = (
        _find_metric(body, "cumulative_histogram_test")["histogram"]["dataPoints"][0]
        for body in seen.json()[:2]
    )
    assert (first["count"], first["sum"], first["min"], first["max"]) == (2, 100, 25, 75)
    assert (second["count"], second["sum"], second["min"], second["max"]) == (3, 130, 25, 75)


@testing.effect
def test_reports_histogram_buckets_above_the_last_boundary():
    """cumulative temporality reports histogram buckets above the last boundary"""

    @fx.gen
    def program():
        custom = metric.histogram("custom_boundaries_histogram", boundaries=[10, 50, 100])
        linear = metric.histogram(
            "linear_boundaries_histogram",
            boundaries=metric.linear_boundaries(start=0, width=50, count=3),
        )
        for value in (25, 75, 500):
            yield from custom.update(value)
            yield from linear.update(value)
        yield from _trigger_export()

    seen = yield from _run(program, "cumulative")
    body = seen.json()[0]
    custom = _find_metric(body, "custom_boundaries_histogram")["histogram"]["dataPoints"][0]
    assert custom["explicitBounds"] == [10, 50, 100]
    assert custom["bucketCounts"] == [0, 1, 1, 1]
    linear = _find_metric(body, "linear_boundaries_histogram")["histogram"]["dataPoints"][0]
    assert linear["explicitBounds"] == [50]
    assert linear["bucketCounts"] == [1, 2]


def _frequency_program(name: str) -> fx.Effect[None]:
    @fx.gen
    def program():
        frequency = metric.frequency(name, description="Test frequency")
        for word in ("a", "a", "b"):
            yield from frequency.update(word)
        yield from _trigger_export()
        for word in ("a", "b", "b"):
            yield from frequency.update(word)
        yield from _trigger_export()

    return program


@testing.effect
def test_reports_frequency_counts_across_export_intervals():
    """cumulative temporality reports frequency counts across export intervals"""
    name = "cumulative_frequency_test"
    seen = yield from _run(_frequency_program(name), "cumulative")
    first, second = seen.json()[:2]
    assert (_frequency_value(first, name, "a"), _frequency_value(first, name, "b")) == (2, 1)
    assert (_frequency_value(second, name, "a"), _frequency_value(second, name, "b")) == (3, 3)


@testing.effect
def test_reports_counter_deltas_across_export_intervals():
    """delta temporality reports counter deltas across export intervals"""

    @fx.gen
    def program():
        counter = metric.counter("delta_counter_test", description="Test counter")
        yield from counter.update(5)
        yield from _trigger_export()
        yield from counter.update(3)
        yield from _trigger_export()

    seen = yield from _run(program, "delta")
    first, second = seen.json()[:2]
    assert _find_metric(first, "delta_counter_test")["sum"]["dataPoints"][0]["asDouble"] == 5
    assert _find_metric(second, "delta_counter_test")["sum"]["dataPoints"][0]["asDouble"] == 3


@testing.effect
def test_reports_a_removed_and_recreated_series_from_zero():
    """delta temporality reports a removed and recreated series from zero"""

    @fx.gen
    def program():
        counter = metric.counter("delta_removed_counter_test")
        histogram = metric.histogram("delta_removed_histogram_test", boundaries=[10])
        yield from counter.update(5)
        yield from histogram.update(5)
        yield from _trigger_export()
        yield from counter.remove()
        yield from histogram.remove()
        yield from _trigger_export()
        yield from counter.update(7)
        yield from histogram.update(7)
        yield from _trigger_export()

    seen = yield from _run(program, "delta")
    last = seen.json()[-1]
    counter = _find_metric(last, "delta_removed_counter_test")["sum"]["dataPoints"][0]
    assert counter["asDouble"] == 7
    point = _find_metric(last, "delta_removed_histogram_test")["histogram"]["dataPoints"][0]
    assert [point["count"], point["sum"]] == [1, 7]


@testing.effect
def test_reports_histogram_count_and_sum_deltas_across_export_intervals():
    """delta temporality reports histogram count and sum deltas across export intervals"""

    @fx.gen
    def program():
        histogram = metric.histogram(
            "delta_histogram_test", description="Test histogram", boundaries=[10, 50, 100]
        )
        yield from histogram.update(25)
        yield from histogram.update(75)
        yield from _trigger_export()
        yield from histogram.update(30)
        yield from _trigger_export()

    seen = yield from _run(program, "delta")
    first, second = (
        _find_metric(body, "delta_histogram_test")["histogram"]["dataPoints"][0]
        for body in seen.json()[:2]
    )
    assert (first["count"], first["sum"], first["min"], first["max"]) == (2, 100, 25, 75)
    assert (second["count"], second["sum"]) == (1, 30)
    assert "min" not in second
    assert "max" not in second


@testing.effect
def test_reports_frequency_count_deltas_across_export_intervals():
    """delta temporality reports frequency count deltas across export intervals"""
    name = "delta_frequency_test"
    seen = yield from _run(_frequency_program(name), "delta")
    first, second = seen.json()[:2]
    assert (_frequency_value(first, name, "a"), _frequency_value(first, name, "b")) == (2, 1)
    assert (_frequency_value(second, name, "a"), _frequency_value(second, name, "b")) == (1, 2)


@testing.effect
def test_exports_a_cumulative_summary_with_window_quantiles():
    """Summary exports a cumulative Summary with window quantiles"""

    @fx.gen
    def program():
        summary = metric.summary(
            "summary_test", max_age="15 seconds", max_size=100, quantiles=[0.5]
        )
        for value in (10, 20, 30):
            yield from summary.update(value)
        yield from _trigger_export()
        yield from summary.update(40)
        yield from _trigger_export()
        # Every observation is now older than max_age.
        yield from _trigger_export()

    seen = yield from _run(program, "delta")
    bodies = seen.json()
    names = [
        found["name"]
        for resource in bodies[0]["resourceMetrics"]
        for scope in resource["scopeMetrics"]
        for found in scope["metrics"]
    ]
    assert names == ["summary_test"]
    points = [_find_metric(body, "summary_test")["summary"]["dataPoints"][0] for body in bodies]
    assert [
        {"count": p["count"], "sum": p["sum"], "quantileValues": p["quantileValues"]}
        for p in points
    ] == [
        {"count": 3, "sum": 60, "quantileValues": [{"quantile": 0.5, "value": 20}]},
        {"count": 4, "sum": 100, "quantileValues": [{"quantile": 0.5, "value": 40}]},
        {"count": 4, "sum": 100, "quantileValues": []},
    ]
    assert points[2]["startTimeUnixNano"] == points[0]["startTimeUnixNano"]


@testing.effect
def test_maps_unit_attributes_to_ucum():
    """maps unit attributes to UCUM"""

    @fx.gen
    def program():
        yield from metric.timer("unit_timer_test", boundaries=[10, 100]).update("5 millis")
        yield from metric.gauge("unit_custom_test", attributes={"unit": "{request}"}).update(1)
        yield from _trigger_export()

    seen = yield from _run(program, "cumulative")
    body = seen.json()[0]
    assert _find_metric(body, "unit_timer_test")["unit"] == "ms"
    assert _find_metric(body, "unit_custom_test")["unit"] == "{request}"


@testing.effect
def test_keeps_bigint_precision_beyond_2_53():
    """keeps bigint precision beyond 2^53"""

    @fx.gen
    def program():
        counter = metric.counter("bigint_counter_test", bigint=True)
        yield from counter.update(9007199254740993)
        yield from metric.gauge("bigint_gauge_test", bigint=True).update(-9007199254740993)
        yield from _trigger_export()
        yield from counter.update(9007199254740993)
        yield from _trigger_export()

    seen = yield from _run(program, "delta")
    first, second = seen.json()[:2]
    counter = "bigint_counter_test"
    assert _find_metric(first, counter)["sum"]["dataPoints"][0]["asInt"] == "9007199254740993"
    assert _find_metric(second, counter)["sum"]["dataPoints"][0]["asInt"] == "9007199254740993"
    gauge = _find_metric(first, "bigint_gauge_test")["gauge"]["dataPoints"][0]
    assert gauge["asInt"] == "-9007199254740993"


@pytest.mark.parametrize("temporality", ["cumulative", "delta"])
@testing.effect
def test_temporality_reports_current_value(temporality: AggregationTemporality):
    """Gauge (no temporality) %s temporality reports current value"""

    @fx.gen
    def program():
        gauge = metric.gauge("delta_gauge_test", description="Test gauge")
        yield from gauge.update(100)
        yield from _trigger_export()
        yield from gauge.update(50)
        yield from _trigger_export()

    seen = yield from _run(program, temporality)
    first, second = seen.json()[:2]
    assert _find_metric(first, "delta_gauge_test")["gauge"]["dataPoints"][0]["asDouble"] == 100
    assert _find_metric(second, "delta_gauge_test")["gauge"]["dataPoints"][0]["asDouble"] == 50


@testing.effect
def test_exports_negative_updates_as_deltas():
    """Counter exports negative updates as deltas"""
    seen, http = collector()

    @fx.gen
    def program():
        counter = metric.counter("counter_delta")
        flusher = yield from otlp_exporter.Flusher()
        for update in (5, -2, 4):
            yield from counter.update(update)
            yield from flusher.flush
        return Collector(list(seen.requests))

    exported = yield from program.pipe(layer.provide(_layer(http, "delta", "1 hour"))).pipe(
        fx.provide_service(metric.MetricRegistry, {})
    )
    values = [
        next(
            m
            for m in body["resourceMetrics"][0]["scopeMetrics"][0]["metrics"]
            if m["name"] == "counter_delta"
        )["sum"]["dataPoints"][0]["asDouble"]
        for body in exported.json()
    ]
    assert values == [5, -2, 4]
