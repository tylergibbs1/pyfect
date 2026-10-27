"""Ports of ``@effect/opentelemetry``'s ``OtelMetrics.test.ts``, and of the
``OtelMetrics`` title of Effect's ``Metric.test.ts``.

Each test's docstring is the Effect test title. ``new
internal.MetricProducerImpl(resource, services, temporality)`` is
``otel.metrics.MetricProducer(resource, context, temporality)`` and
``producer.collect()`` returns the ``MetricsData`` directly. Python's SDK
has no metric descriptor: an instrument's ``type`` is the data's class
(``Gauge``; ``Sum`` with ``is_monotonic`` for counters), and its
``valueType`` is the type of the values (``int`` for a ``bigint`` metric).
A reader is bound to a producer instead of a ``MeterProvider``; one bound
already (here by a ``MeterProvider``) cannot be bound again.

Adapted, with the reason:

- "uses collection interval starts for delta $name points": ``Date.now``
  is the producer's ``time.time_ns``, patched with ``monkeypatch``.
"""

from collections.abc import Callable, Sequence
from typing import Any

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry.sdk.metrics import MeterProvider
from opentelemetry.sdk.metrics.export import (
    Gauge,
    Histogram,
    HistogramDataPoint,
    InMemoryMetricReader,
    Metric,
    MetricReader,
    MetricsData,
    NumberDataPoint,
    Sum,
)
from opentelemetry.sdk.resources import Resource

import pyfect as fx
from pyfect import exit, metric, otel, testing
from pyfect.cause import Die
from pyfect.otel import _producer
from pyfect.otel.metrics import MetricProducer, register_producer


def _isolated[A, E](eff: fx.Effect[A, E, Any]) -> fx.Effect[A, E, Any]:
    return eff.pipe(fx.provide_service(metric.MetricRegistry, {}))


def _find(data: MetricsData | None, name: str) -> Metric:
    assert data is not None
    (resource_metrics,) = data.resource_metrics
    (scope_metrics,) = resource_metrics.scope_metrics
    return next(m for m in scope_metrics.metrics if m.name == name)


def _numbers(found: Metric) -> list[NumberDataPoint]:
    assert isinstance(found.data, Sum | Gauge)
    return list(found.data.data_points)


def _histogram(found: Metric) -> HistogramDataPoint:
    assert isinstance(found.data, Histogram)
    return found.data.data_points[0]


class _ShutdownTrackingReader(MetricReader):
    def __init__(self, reject_shutdown: bool = False) -> None:
        super().__init__()
        self.reject_shutdown = reject_shutdown
        self.shutdowns = 0

    def _receive_metrics(
        self, metrics_data: MetricsData, timeout_millis: float = 10_000, **kwargs: Any
    ) -> None:
        pass

    def shutdown(self, timeout_millis: float = 30_000, **kwargs: Any) -> None:
        self.shutdowns += 1
        if self.reject_shutdown:
            raise RuntimeError("shutdown failed")


@pytest.mark.parametrize("reject_shutdown", [False, True])
@testing.effect
def test_rolls_back_bound_readers_and_preserves_the_binding_defect(reject_shutdown: bool):
    """rolls back bound readers and preserves the binding defect (shutdown rejects: %s)"""
    services = yield from fx.context()
    producer = MetricProducer(Resource({}), services)
    fresh = _ShutdownTrackingReader(reject_shutdown)
    already_bound = _ShutdownTrackingReader()
    MeterProvider(metric_readers=[already_bound])

    result = yield from fx.scoped(
        register_producer(producer, lambda: [fresh, already_bound])
    ).exit()

    assert exit.is_failure(result)
    assert any(isinstance(reason, Die) for reason in result.cause.reasons)
    assert already_bound.shutdowns == 0
    assert fresh.shutdowns == 1
    assert "has been registered already" in result.cause.pretty()


def _resource() -> Resource:
    return Resource({"name": "test", "version": "1.0.0"})


def _collect_two_series(
    make: Callable[[], metric.Metric[Any, Any]], first: object, second: object, third: object
) -> fx.Effect[MetricsData]:
    @fx.gen
    def program():
        services = yield from fx.context()
        producer = MetricProducer(_resource(), services)
        m = make()
        yield from m.with_attributes({"key": "value", "unit": "requests"}).update(first)
        yield from m.with_attributes({"key": "value"}).update(second)
        yield from m.with_attributes({"key": "value"}).update(third)
        data = producer.collect()
        assert dict(data.resource_metrics[0].resource.attributes) == {
            "name": "test",
            "version": "1.0.0",
        }
        assert len(data.resource_metrics[0].scope_metrics) == 1
        return data

    return _isolated(program)


def _check_points(points: Sequence[NumberDataPoint], values: list[object]) -> None:
    assert [dict(p.attributes or {}) for p in points] == [
        {"unit": "requests", "key": "value"},
        {"key": "value"},
    ]
    assert [p.value for p in points] == values
    assert points[0].start_time_unix_nano == points[1].start_time_unix_nano


@testing.effect
def test_gauge():
    """gauge"""
    data = yield from _collect_two_series(lambda: metric.gauge("rps"), 10.0, 10.0, 20.0)
    found = _find(data, "rps")
    assert (found.description, found.unit) == ("", "requests")
    assert isinstance(found.data, Gauge)
    _check_points(_numbers(found), [10.0, 20.0])
    assert all(isinstance(p.value, float) for p in _numbers(found))


@testing.effect
def test_gauge_bigint():
    """gauge bigint"""
    data = yield from _collect_two_series(
        lambda: metric.gauge("rps-bigint", bigint=True), 10, 10, 20
    )
    found = _find(data, "rps-bigint")
    assert (found.description, found.unit) == ("", "requests")
    assert isinstance(found.data, Gauge)
    _check_points(_numbers(found), [10, 20])
    assert all(type(p.value) is int for p in _numbers(found))


def _check_sum(found: Metric, monotonic: bool) -> None:
    assert (found.description, found.unit) == ("Example", "requests")
    assert isinstance(found.data, Sum)
    assert found.data.is_monotonic is monotonic
    assert found.data.aggregation_temporality == 2  # cumulative
    _check_points(_numbers(found), [1, 2])


@testing.effect
def test_counter():
    """counter"""
    data = yield from _collect_two_series(
        lambda: metric.counter("counter", description="Example"), 1.0, 1.0, 1.0
    )
    _check_sum(_find(data, "counter"), monotonic=False)


@testing.effect
def test_counter_inc():
    """counter-inc"""
    data = yield from _collect_two_series(
        lambda: metric.counter("counter-inc", description="Example", incremental=True),
        1.0,
        1.0,
        1.0,
    )
    _check_sum(_find(data, "counter-inc"), monotonic=True)


@testing.effect
def test_counter_bigint():
    """counter-bigint"""
    data = yield from _collect_two_series(
        lambda: metric.counter(
            "counter-bigint", description="Example", incremental=True, bigint=True
        ),
        1,
        1,
        1,
    )
    found = _find(data, "counter-bigint")
    _check_sum(found, monotonic=True)
    assert all(type(p.value) is int for p in _numbers(found))


@testing.effect
def test_reports_the_same_delta_to_every_registered_reader():
    """reports the same delta to every registered reader"""

    @fx.gen
    def program():
        services = yield from fx.context()
        producer = MetricProducer(Resource({}), services, "delta")
        first, second = InMemoryMetricReader(), InMemoryMetricReader()
        yield from register_producer(producer, lambda: [first, second])
        yield from metric.counter("requests", incremental=True).update(1)
        values = [
            _numbers(_find(reader.get_metrics_data(), "requests"))[0].value
            for reader in (first, second)
        ]
        assert values == [1, 1]

    yield from _isolated(program)


@testing.effect
def test_reports_a_removed_and_recreated_series_from_zero_with_delta_temporality():
    """reports a removed and recreated series from zero with delta temporality"""

    @fx.gen
    def program():
        services = yield from fx.context()
        producer = MetricProducer(Resource({}), services, "delta")
        counter = metric.counter("requests")
        histogram = metric.histogram("latency", boundaries=[10])
        yield from counter.update(5)
        yield from histogram.update(5)
        producer.collect()
        yield from counter.remove()
        yield from histogram.remove()
        producer.collect()
        yield from counter.update(7)
        yield from histogram.update(7)
        result = producer.collect()
        assert _numbers(_find(result, "requests"))[0].value == 7
        point = _histogram(_find(result, "latency"))
        assert (point.count, point.sum) == (1, 7)

    yield from _isolated(program)


def _histogram_value(point: HistogramDataPoint) -> dict[str, object]:
    value: dict[str, object] = {
        "boundaries": list(point.explicit_bounds),
        "counts": list(point.bucket_counts),
        "count": point.count,
        "sum": point.sum,
    }
    if point.min is not None:  # pyright: ignore[reportUnnecessaryComparison]
        value["min"] = point.min
        value["max"] = point.max
    return value


@pytest.mark.parametrize("temporality", ["delta", "cumulative"])
@testing.effect
def test_histogram_extrema(temporality: otel.metrics.TemporalityPreference):
    """histogram extrema with %s temporality"""

    @fx.gen
    def program():
        services = yield from fx.context()
        producer = MetricProducer(Resource({}), services, temporality)
        histogram = metric.histogram(
            "latency", boundaries=metric.linear_boundaries(start=0, width=50, count=3)
        )
        yield from histogram.update(1)
        yield from histogram.update(100)
        first = _histogram_value(_histogram(_find(producer.collect(), "latency")))
        assert first == {
            "boundaries": [50],
            "counts": [1, 1],
            "count": 2,
            "sum": 101,
            "min": 1,
            "max": 100,
        }
        yield from histogram.update(50)
        yield from histogram.update(60)
        second = _histogram_value(_histogram(_find(producer.collect(), "latency")))
        assert second == (
            {"boundaries": [50], "counts": [1, 1], "count": 2, "sum": 110}
            if temporality == "delta"
            else {
                "boundaries": [50],
                "counts": [2, 2],
                "count": 4,
                "sum": 211,
                "min": 1,
                "max": 100,
            }
        )

    yield from _isolated(program)


@testing.effect
def test_histogram_buckets_above_the_last_custom_boundary():
    """histogram buckets above the last custom boundary"""

    @fx.gen
    def program():
        services = yield from fx.context()
        producer = MetricProducer(Resource({}), services)
        histogram = metric.histogram("latency", boundaries=[10, 50, 100])
        yield from histogram.update(25)
        yield from histogram.update(75)
        yield from histogram.update(500)
        point = _histogram(_find(producer.collect(), "latency"))
        assert (list(point.explicit_bounds), list(point.bucket_counts)) == (
            [10, 50, 100],
            [0, 1, 1, 1],
        )

    yield from _isolated(program)


_UPDATES: dict[str, Callable[[], fx.Effect[None]]] = {
    "counter": lambda: metric.counter("delta-counter").update(1),
    "histogram": lambda: metric.histogram("delta-histogram", boundaries=[1]).update(1),
    "frequency": lambda: metric.frequency("delta-frequency").update("value"),
}


@pytest.mark.parametrize("name", list(_UPDATES))
@testing.effect
def test_uses_collection_interval_starts_for_delta_points(
    name: str, monkeypatch: pytest.MonkeyPatch
):
    """uses collection interval starts for delta $name points"""
    now = [1_000_000_000]
    monkeypatch.setattr(_producer.time, "time_ns", lambda: now[0])

    @fx.gen
    def program():
        producer = yield from otel.metrics.make_producer("delta").pipe(
            fx.provide(otel.resource.layer_empty)
        )
        update = _UPDATES[name]()
        intervals: list[tuple[int, int]] = []
        for seconds in (2, 3):
            now[0] = seconds * 1_000_000_000
            yield from update
            data = producer.collect()
            point = data.resource_metrics[0].scope_metrics[0].metrics[0].data.data_points[0]
            intervals.append((point.start_time_unix_nano, point.time_unix_nano))
        assert intervals == [(1_000_000_000, 2_000_000_000), (2_000_000_000, 3_000_000_000)]

    yield from _isolated(program)
