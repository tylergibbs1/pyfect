"""Ports of Effect's ``Metric.test.ts``.

Each test's docstring is the Effect test title. ``Metric.update(m, x)`` is
``m.update(x)``, ``Metric.value(m)`` is ``m.value()``, ``Metric.snapshot``
is ``metric.snapshot``; ``Effect.trackSuccesses(eff, m)`` is
``eff.track_successes(m)`` and the other ``track*`` likewise.
``Effect.provideService(Metric.MetricRegistry, new Map())`` is
``fx.provide_service(metric.MetricRegistry, {})``. A ``bigint`` metric
holds Python ``int``. ``Effect.die(1)`` dies with an exception. States are
dataclasses; buckets and quantiles are tuples.

Adapted, with the reason:

- "registerUnsafe reads on snapshot and removes only its own
  registration", "registerUnsafe ignores update and modify through an
  input-changing transform": ``register_unsafe`` takes only the ``get``
  hook (Effect ignores the ``update`` and ``modify`` it is given), so the
  second checks that updates through the transform leave the registered
  value alone.

Omitted, with the reason:

- "uses collection interval starts for delta $name points" (three cases):
  ported with the OpenTelemetry bridge, in ``tests/oracle/test_otel_metrics.py``.
- "Counter > exports negative updates as deltas": ported with the OTLP
  exporter, in ``tests/oracle/test_otlp_metrics.py``.
"""

import itertools
import json
import math
import sys
from collections.abc import Callable, Sequence
from typing import Any

import pytest

import pyfect as fx
from pyfect import metric, testing

_attributes = {"x": "a", "y": "b"}
_ids = itertools.count(1)


def _next_id() -> str:
    return f"metric-{next(_ids)}"


def _fresh_registry[A, E](eff: fx.Effect[A, E]) -> fx.Effect[A, E]:
    return eff.pipe(fx.provide_service(metric.MetricRegistry, {}))


def _series_of(snapshots: Sequence[metric.Snapshot]) -> list[tuple[Any, Any]]:
    rows: list[tuple[Any, Any]] = [
        (
            None if s.attributes is None else dict(s.attributes),
            s.state.count if isinstance(s.state, metric.CounterState) else None,
        )
        for s in snapshots
    ]
    return sorted(rows, key=lambda row: json.dumps(row[0]))


_series = metric.snapshot.map(_series_of)


def _make_buckets(
    boundaries: Sequence[float], values: Sequence[float]
) -> tuple[tuple[float, int], ...]:
    results: list[tuple[float, int]] = []
    count = 0
    index = 0
    for bucket in boundaries:
        while index < len(values) and values[index] <= bucket:
            count += 1
            index += 1
        results.append((bucket, count))
    return tuple(results)


def _in(registry: metric.Registry):
    return fx.provide_service(metric.MetricRegistry, registry)


def _with_attributes(attributes: dict[str, str]):
    return fx.provide_service(metric.CurrentMetricAttributes, attributes)


@testing.effect
def test_keeps_shared_metrics_scoped_to_the_active_registry():
    """keeps shared metrics scoped to the active registry"""
    counter = metric.counter(_next_id())
    registry_a: metric.Registry = {}
    registry_b: metric.Registry = {}

    yield from counter.update(1).pipe(_in(registry_a))
    yield from counter.update(10).pipe(_in(registry_b))
    yield from counter.update(2).pipe(_in(registry_a))

    value_a = yield from counter.value().pipe(_in(registry_a))
    value_b = yield from counter.value().pipe(_in(registry_b))
    assert value_a == metric.CounterState(3, False)
    assert value_b == metric.CounterState(10, False)


@testing.effect
def test_keeps_attributed_metrics_scoped_to_the_active_registry():
    """keeps attributed metrics scoped to the active registry"""
    counter = metric.counter(_next_id()).with_attributes(_attributes)
    registry_a: metric.Registry = {}
    registry_b: metric.Registry = {}

    yield from counter.update(1).pipe(_in(registry_a))
    yield from counter.update(10).pipe(_in(registry_b))

    assert (yield from counter.value().pipe(_in(registry_a))).count == 1
    assert (yield from counter.value().pipe(_in(registry_b))).count == 10


@testing.effect
def test_registers_an_unattributed_metric_again_after_the_registry_is_cleared():
    """registers an unattributed metric again after the registry is cleared"""
    registry: metric.Registry = {}

    @fx.gen
    def body():
        counter = metric.counter(_next_id())
        yield from counter.update(1)
        registry.clear()
        yield from counter.update(10)
        snapshots = yield from metric.snapshot
        assert [s.state for s in snapshots] == [metric.CounterState(10, False)]
        assert (yield from counter.value()).count == 10

    yield from body.pipe(_in(registry))


@testing.effect
def test_shares_one_series_between_no_attributes_and_empty_attributes():
    """shares one series between no attributes and empty attributes"""

    @fx.gen
    def body():
        id = _next_id()
        first = metric.counter(id)
        second = metric.counter(id, attributes={})
        third = metric.counter(id, attributes=[])
        yield from first.update(1)
        yield from second.update(10)
        yield from third.update(100)
        assert len((yield from metric.snapshot)) == 1
        assert (yield from first.value()).count == 111

    yield from _fresh_registry(body)


@testing.effect
def test_keeps_distinct_attribute_sets_in_separate_series():
    """keeps distinct attribute sets in separate series"""
    id = _next_id()
    first = metric.counter(id, attributes={"a": "b,c=d"})
    second = metric.counter(id, attributes={"a": "b", "c": "d"})
    yield from first.update(1)
    yield from second.update(10)
    assert (yield from first.value()).count == 1
    assert (yield from second.value()).count == 10


@testing.effect
def test_keeps_an_id_containing_a_colon_apart_from_an_id_with_a_description():
    """keeps an id containing a colon apart from an id with a description"""

    @fx.gen
    def body():
        id = _next_id()
        first = metric.counter(f"{id}:requests")
        second = metric.counter(id, description="requests")
        yield from first.update(1)
        yield from second.update(10)
        assert (yield from first.value()).count == 1
        assert (yield from second.value()).count == 10
        assert len((yield from metric.snapshot)) == 2

    yield from _fresh_registry(body)


@testing.effect
def test_keeps_a_description_apart_from_attributes():
    """keeps a description apart from attributes"""

    @fx.gen
    def body():
        id = _next_id()
        first = metric.counter(id, description='[["route","/users"]]')
        second = metric.counter(id, attributes={"route": "/users"})
        yield from first.update(1)
        yield from second.update(10)
        assert (yield from first.value()).count == 1
        assert (yield from second.value()).count == 10
        assert len((yield from metric.snapshot)) == 2

    yield from _fresh_registry(body)


@testing.effect
def test_keeps_equal_attribute_names_with_different_values_in_separate_series():
    """keeps equal attribute names with different values in separate series"""
    id = _next_id()
    first = metric.counter(id, attributes={"route": "/users", "method": "GET"})
    second = metric.counter(id, attributes={"route": "/users", "method": "POST"})
    yield from first.update(1)
    yield from second.update(10)
    assert (yield from first.value()).count == 1


@testing.effect
def test_shares_a_series_for_equal_attributes_in_different_record_orders():
    """shares a series for equal attributes in different record orders"""
    id = _next_id()
    first = metric.counter(id, attributes={"route": "/users", "method": "GET"})
    second = metric.counter(id, attributes={"method": "GET", "route": "/users"})
    yield from first.update(1)
    yield from second.update(10)
    assert (yield from first.value()).count == 11


@testing.effect
def test_follows_contextual_attributes_that_change_between_updates_of_a_plain_metric():
    """follows contextual attributes that change between updates of a plain metric"""

    @fx.gen
    def body():
        counter = metric.counter(_next_id())
        tenant_a = {"tenant": "a"}
        yield from counter.update(1).pipe(_with_attributes(tenant_a))
        yield from counter.update(10).pipe(_with_attributes({"tenant": "b"}))
        yield from counter.update(100).pipe(_with_attributes(tenant_a))
        yield from counter.update(1000)
        assert (yield from _series) == [(None, 1000), ({"tenant": "a"}, 101), ({"tenant": "b"}, 10)]

    yield from _fresh_registry(body)


@testing.effect
def test_shares_a_series_after_merging_metric_and_contextual_attributes():
    """shares a series after merging metric and contextual attributes"""
    id = _next_id()
    first = metric.counter(id, attributes={"route": "/users"})
    second = metric.counter(id, attributes={"method": "GET"})
    first_context = {"method": "GET"}
    yield from first.update(1).pipe(_with_attributes(first_context))
    yield from second.update(10).pipe(_with_attributes({"route": "/users"}))
    assert (yield from first.value().pipe(_with_attributes(first_context))).count == 11


@testing.effect
def test_preserves_attribute_order_in_snapshots():
    """preserves attribute order in snapshots"""

    @fx.gen
    def body():
        counter = metric.counter(_next_id(), attributes={"route": "/users", "method": "GET"})
        yield from counter.update(1)
        snapshot = yield from metric.snapshot
        assert list(snapshot[0].attributes or {}) == ["route", "method"]

    yield from _fresh_registry(body)


@testing.effect
def test_remove_deletes_only_the_series_for_the_current_attributes():
    """remove deletes only the series for the current attributes"""

    @fx.gen
    def body():
        counter = metric.counter(_next_id())
        tenant_a = _with_attributes({"tenant": "a"})
        yield from counter.update(1).pipe(tenant_a)
        yield from counter.update(10)
        yield from counter.remove().pipe(tenant_a)
        assert (yield from _series) == [(None, 10)]
        yield from counter.update(100).pipe(tenant_a)
        assert (yield from _series) == [(None, 10), ({"tenant": "a"}, 100)]

    yield from _fresh_registry(body)


def test_register_unsafe_reads_on_snapshot_and_removes_only_its_own_registration():
    """registerUnsafe reads on snapshot and removes only its own registration"""
    context = fx.Context.make(metric.MetricRegistry, {})
    gauge = metric.gauge(_next_id(), bigint=True)
    size = 1

    def values() -> list[metric.MetricState]:
        return [s.state for s in metric.snapshot_unsafe(context)]

    first = metric.register_unsafe(gauge, context, lambda _: metric.GaugeState(size))
    assert values() == [metric.GaugeState(1)]
    size = 2
    assert values() == [metric.GaugeState(2)]

    second = metric.register_unsafe(gauge, context, lambda _: metric.GaugeState(3))
    first.remove()
    assert values() == [metric.GaugeState(3)]
    second.remove()
    assert values() == []


def test_register_unsafe_ignores_update_and_modify_through_an_input_changing_transform():
    """registerUnsafe ignores update and modify through an input-changing transform"""
    context = fx.Context.make(metric.MetricRegistry, {})
    lengths = metric.gauge(_next_id()).map_input(len)

    metric.register_unsafe(lengths, context, lambda _: metric.GaugeState(1))
    lengths.update_unsafe("hello", context)
    lengths.modify_unsafe("hi", context)

    assert lengths.value_unsafe(context) == metric.GaugeState(1)


@testing.effect
def test_with_attributes_follows_the_contextual_attributes_when_they_change_between_updates():
    """withAttributes > follows the contextual attributes when they change between updates"""

    @fx.gen
    def body():
        counter = metric.counter(_next_id()).with_attributes({"route": "/users"})
        yield from counter.update(1)
        yield from counter.update(10).pipe(_with_attributes({"tenant": "a"}))
        yield from counter.update(100).pipe(_with_attributes({"tenant": "b"}))
        yield from counter.update(1000)
        assert (yield from _series) == [
            ({"route": "/users"}, 1001),
            ({"tenant": "a", "route": "/users"}, 10),
            ({"tenant": "b", "route": "/users"}, 100),
        ]

    yield from _fresh_registry(body)


@testing.effect
def test_with_attributes_applies_inner_attributes_over_outer_contextual_and_metric_attributes():
    """withAttributes > applies inner attributes over outer, contextual and metric attributes"""

    @fx.gen
    def body():
        counter = (
            metric.counter(_next_id(), attributes={"a": "own", "b": "own", "c": "own", "d": "own"})
            .with_attributes({"a": "inner"})
            .with_attributes({"a": "outer", "b": "outer"})
        )
        yield from counter.update(1).pipe(
            _with_attributes({"a": "context", "b": "context", "c": "context"})
        )
        yield from counter.update(10)
        assert (yield from _series) == [
            ({"a": "inner", "b": "outer", "c": "context", "d": "own"}, 1),
            ({"a": "inner", "b": "outer", "c": "own", "d": "own"}, 10),
        ]

    yield from _fresh_registry(body)


@testing.effect
def test_with_attributes_registers_the_series_again_after_the_registry_is_cleared():
    """withAttributes > registers the series again after the registry is cleared"""
    registry: metric.Registry = {}

    @fx.gen
    def body():
        counter = metric.counter(_next_id()).with_attributes({"route": "/users"})
        yield from counter.update(1)
        registry.clear()
        yield from counter.update(10)
        assert (yield from _series) == [({"route": "/users"}, 10)]

    yield from body.pipe(_in(registry))


@testing.effect
def test_with_attributes_uses_the_unattributed_series_for_empty_attributes():
    """withAttributes > uses the unattributed series for empty attributes"""

    @fx.gen
    def body():
        counter = metric.counter(_next_id())
        yield from counter.with_attributes({}).update(10)
        yield from counter.with_attributes([]).update(100)
        yield from counter.update(1)
        assert (yield from _series) == [(None, 111)]

    yield from _fresh_registry(body)


@testing.effect
def test_with_attributes_modifies_and_reads_the_attributed_series():
    """withAttributes > modifies and reads the attributed series"""

    @fx.gen
    def body():
        gauge = metric.gauge(_next_id())
        tagged = gauge.with_attributes([("route", "/users")])
        yield from tagged.update(5)
        yield from tagged.modify(2)
        yield from gauge.update(1)
        assert (yield from tagged.value()).value == 7
        assert (yield from gauge.value()).value == 1

    yield from _fresh_registry(body)


@testing.effect
def test_should_be_referentially_transparent():
    """should be referentially transparent"""
    id = _next_id()
    counter1 = metric.counter(id).with_attributes(_attributes).with_constant_input(1)
    counter2 = metric.counter(id).with_attributes(_attributes).with_constant_input(1)
    counter3 = metric.counter(id).with_attributes({"z": "c"}).with_constant_input(1)
    yield from fx.void.track(counter1)
    yield from fx.void.track(counter2)
    yield from fx.void.track(counter3)
    assert (yield from counter1.value()) == metric.CounterState(2, False)
    assert (yield from counter2.value()) == metric.CounterState(2, False)
    assert (yield from counter3.value()) == metric.CounterState(1, False)


@testing.effect
def test_should_dump_the_current_state_of_all_metrics():
    """should dump the current state of all metrics"""

    @fx.gen
    def body():
        counter1 = metric.counter("counter").with_attributes(_attributes).with_constant_input(1)
        counter2 = metric.counter("counter").with_attributes(_attributes).with_constant_input(1)
        counter3 = metric.counter("counter").with_attributes({"z": "c"}).with_constant_input(1)
        yield from fx.void.track(counter1)
        yield from fx.void.track(counter2)
        yield from fx.void.track(counter3)
        result = yield from metric.dump
        assert result.split("\n") == [
            "name=counter  description=  type=Counter  attributes=[x: a, y: b]  state=[count: [2]]",
            "name=counter  description=  type=Counter  attributes=[z: c]        state=[count: [1]]",
        ]

    yield from _fresh_registry(body)


@testing.effect
def test_should_record_fiber_runtime_metrics_once_for_yielded_fibers():
    """should record fiber runtime metrics once for yielded fibers"""
    starts = 0
    ends = 0

    class Service:
        def record_fiber_start(self, context: fx.Context) -> None:
            nonlocal starts
            starts += 1

        def record_fiber_end(self, context: fx.Context, exit: fx.Exit[Any, Any]) -> None:
            nonlocal ends
            ends += 1

    @fx.gen
    def body():
        @fx.gen
        def child():
            yield from fx.yield_now()
            yield from fx.yield_now()

        fiber = yield from child.fork()
        yield from fiber.join()
        assert starts == 1
        assert ends == 1

    yield from body.pipe(fx.provide_service(metric.FiberRuntimeMetrics, Service()))


@testing.effect
def test_counter_custom_increment_with_value():
    """Counter > custom increment with value"""
    counter = metric.counter(_next_id()).with_attributes(_attributes)
    yield from fx.succeed(1).track_successes(counter)
    yield from fx.succeed(2).track_successes(counter)
    assert (yield from counter.value()) == metric.CounterState(3, False)


@testing.effect
def test_counter_custom_increment_with_constant():
    """Counter > custom increment with constant"""
    counter = metric.counter(_next_id()).with_attributes(_attributes).with_constant_input(1)
    yield from fx.succeed(1).track_successes(counter)
    yield from fx.succeed(2).track_successes(counter)
    assert (yield from counter.value()) == metric.CounterState(2, False)


@testing.effect
def test_counter_custom_decrement_with_value():
    """Counter > custom decrement with value"""
    counter = metric.counter(_next_id()).with_attributes(_attributes)
    yield from fx.succeed(-1).track_successes(counter)
    yield from fx.succeed(-2).track_successes(counter)
    assert (yield from counter.value()) == metric.CounterState(-3, False)


@testing.effect
def test_counter_custom_decrement_with_constant():
    """Counter > custom decrement with constant"""
    counter = metric.counter(_next_id()).with_attributes(_attributes).with_constant_input(-1)
    yield from fx.succeed(-1).track_successes(counter)
    yield from fx.succeed(-2).track_successes(counter)
    assert (yield from counter.value()) == metric.CounterState(-2, False)


@testing.effect
def test_counter_custom_increment_with_bigint_value():
    """Counter > custom increment with bigint value"""
    counter = metric.counter(_next_id(), bigint=True).with_attributes(_attributes)
    yield from fx.succeed(1).track_successes(counter)
    yield from fx.succeed(2).track_successes(counter)
    assert (yield from counter.value()) == metric.CounterState(3, False)


@testing.effect
def test_counter_custom_increment_with_bigint_constant():
    """Counter > custom increment with bigint constant"""
    counter = (
        metric.counter(_next_id(), bigint=True).with_attributes(_attributes).with_constant_input(1)
    )
    yield from fx.succeed(1).track_successes(counter)
    yield from fx.succeed(2).track_successes(counter)
    assert (yield from counter.value()) == metric.CounterState(2, False)


@testing.effect
def test_counter_custom_decrement_with_bigint_value():
    """Counter > custom decrement with bigint value"""
    counter = metric.counter(_next_id(), bigint=True).with_attributes(_attributes)
    yield from fx.succeed(-1).track_successes(counter)
    yield from fx.succeed(-2).track_successes(counter)
    assert (yield from counter.value()) == metric.CounterState(-3, False)


@testing.effect
def test_counter_custom_decrement_with_bigint_constant():
    """Counter > custom decrement with bigint constant"""
    counter = (
        metric.counter(_next_id(), bigint=True).with_attributes(_attributes).with_constant_input(-1)
    )
    yield from fx.succeed(-1).track_successes(counter)
    yield from fx.succeed(-2).track_successes(counter)
    assert (yield from counter.value()) == metric.CounterState(-2, False)


@testing.effect
def test_counter_fails_to_decrement_incremental_counter():
    """Counter > fails to decrement incremental counter"""
    counter = (
        metric.counter(_next_id(), incremental=True)
        .with_attributes(_attributes)
        .with_constant_input(-1)
    )
    yield from fx.succeed(-1).track_successes(counter)
    yield from fx.succeed(-2).track_successes(counter)
    assert (yield from counter.value()) == metric.CounterState(0, True)


@testing.effect
def test_counter_fails_to_decrement_incremental_bigint_counter():
    """Counter > fails to decrement incremental bigint counter"""
    counter = (
        metric.counter(_next_id(), bigint=True, incremental=True)
        .with_attributes(_attributes)
        .with_constant_input(-1)
    )
    yield from fx.succeed(-1).track_successes(counter)
    yield from fx.succeed(-2).track_successes(counter)
    assert (yield from counter.value()) == metric.CounterState(0, True)


@testing.effect
def test_gauge_custom_set_with_value():
    """Gauge > custom set with value"""
    gauge = metric.gauge(_next_id()).with_attributes(_attributes)
    yield from fx.succeed(1).track_successes(gauge)
    yield from fx.succeed(2).track_successes(gauge)
    assert (yield from gauge.value()) == metric.GaugeState(2)


@testing.effect
def test_gauge_custom_set_with_constant():
    """Gauge > custom set with constant"""
    gauge = metric.gauge(_next_id()).with_attributes(_attributes).with_constant_input(1)
    yield from fx.succeed(1).track_successes(gauge)
    yield from fx.succeed(2).track_successes(gauge)
    assert (yield from gauge.value()) == metric.GaugeState(1)


@testing.effect
def test_gauge_custom_set_with_negative_value():
    """Gauge > custom set with negative value"""
    gauge = metric.gauge(_next_id()).with_attributes(_attributes)
    yield from fx.succeed(-1).track_successes(gauge)
    yield from fx.succeed(-2).track_successes(gauge)
    assert (yield from gauge.value()) == metric.GaugeState(-2)


@testing.effect
def test_gauge_custom_set_with_negative_constant():
    """Gauge > custom set with negative constant"""
    gauge = metric.gauge(_next_id()).with_attributes(_attributes).with_constant_input(-1)
    yield from fx.succeed(-1).track_successes(gauge)
    yield from fx.succeed(-2).track_successes(gauge)
    assert (yield from gauge.value()) == metric.GaugeState(-1)


@testing.effect
def test_gauge_custom_set_with_bigint_value():
    """Gauge > custom set with bigint value"""
    gauge = metric.gauge(_next_id(), bigint=True).with_attributes(_attributes)
    yield from fx.succeed(1).track_successes(gauge)
    yield from fx.succeed(2).track_successes(gauge)
    assert (yield from gauge.value()) == metric.GaugeState(2)


@testing.effect
def test_gauge_custom_set_with_bigint_constant():
    """Gauge > custom set with bigint constant"""
    gauge = (
        metric.gauge(_next_id(), bigint=True).with_attributes(_attributes).with_constant_input(1)
    )
    yield from fx.succeed(1).track_successes(gauge)
    yield from fx.succeed(2).track_successes(gauge)
    assert (yield from gauge.value()) == metric.GaugeState(1)


@testing.effect
def test_gauge_custom_set_with_negative_bigint_value():
    """Gauge > custom set with negative bigint value"""
    gauge = metric.gauge(_next_id(), bigint=True).with_attributes(_attributes)
    yield from fx.succeed(-1).track_successes(gauge)
    yield from fx.succeed(-2).track_successes(gauge)
    assert (yield from gauge.value()) == metric.GaugeState(-2)


@testing.effect
def test_gauge_custom_set_with_negative_bigint_constant():
    """Gauge > custom set with negative bigint constant"""
    gauge = (
        metric.gauge(_next_id(), bigint=True).with_attributes(_attributes).with_constant_input(-1)
    )
    yield from fx.succeed(-1).track_successes(gauge)
    yield from fx.succeed(-2).track_successes(gauge)
    assert (yield from gauge.value()) == metric.GaugeState(-1)


@testing.effect
def test_frequency_custom_occurence_with_value():
    """Frequency > custom occurence with value"""
    frequency = metric.frequency(_next_id()).with_attributes(_attributes)
    yield from fx.succeed("foo").track_successes(frequency)
    yield from fx.succeed("bar").track_successes(frequency)
    assert (yield from frequency.value()) == metric.FrequencyState({"foo": 1, "bar": 1})


@testing.effect
def test_frequency_custom_set_with_constant():
    """Frequency > custom set with constant"""
    frequency = (
        metric.frequency(_next_id()).with_attributes(_attributes).with_constant_input("constant")
    )
    yield from fx.succeed("foo").track_successes(frequency)
    yield from fx.succeed("bar").track_successes(frequency)
    assert (yield from frequency.value()) == metric.FrequencyState({"constant": 2})


@testing.effect
def test_uses_finite_extrema_for_empty_histogram_and_summary_states():
    """uses finite extrema for empty histogram and summary states"""
    histogram = metric.histogram(_next_id(), boundaries=[])
    summary = metric.summary(_next_id(), max_age="1 minute", max_size=10, quantiles=[])
    histogram_state = yield from histogram.value()
    summary_state = yield from summary.value()
    largest = sys.float_info.max
    assert (histogram_state.min, histogram_state.max) == (largest, -largest)
    assert (summary_state.min, summary_state.max) == (largest, -largest)


def test_creates_evenly_spaced_linear_boundaries():
    """creates evenly spaced linear boundaries"""
    assert metric.linear_boundaries(start=10, width=20, count=5) == (10, 30, 50, 70, math.inf)


@testing.effect
def test_histogram_reports_the_maximum_for_negative_only_observations():
    """Histogram > reports the maximum for negative-only observations"""
    histogram = metric.histogram(_next_id(), boundaries=[-10, -5, 0])
    yield from histogram.update(-10)
    yield from histogram.update(-5)
    result = yield from histogram.value()
    assert result.min == -10
    assert result.max == -5


@testing.effect
def test_histogram_custom_observe_with_value():
    """Histogram > custom observe with value"""
    boundaries = metric.linear_boundaries(start=0, width=1, count=10)
    histogram = metric.histogram(_next_id(), boundaries=boundaries).with_attributes(_attributes)
    yield from fx.succeed(1).track_successes(histogram)
    yield from fx.succeed(3).track_successes(histogram)
    assert (yield from histogram.value()) == metric.HistogramState(
        buckets=_make_buckets(boundaries, [1, 3]), count=2, sum=4, min=1, max=3
    )


@testing.effect
def test_histogram_custom_observe_with_constant():
    """Histogram > custom observe with constant"""
    boundaries = metric.linear_boundaries(start=0, width=1, count=10)
    histogram = (
        metric.histogram(_next_id(), boundaries=boundaries)
        .with_attributes(_attributes)
        .with_constant_input(1)
    )
    yield from fx.succeed(1).track_successes(histogram)
    yield from fx.succeed(3).track_successes(histogram)
    assert (yield from histogram.value()) == metric.HistogramState(
        buckets=_make_buckets(boundaries, [1, 1]), count=2, sum=2, min=1, max=1
    )


@testing.effect
def test_histogram_preserves_precision_of_boundary_values():
    """Histogram > preserves precision of boundary values"""
    boundaries = [0.005, 0.01, 0.025, 0.05, 0.075, 0.1]
    histogram = metric.histogram("precision_test", boundaries=boundaries)
    result = yield from histogram.value()
    for index, (boundary, _) in enumerate(result.buckets):
        if index < len(boundaries):
            assert boundary == boundaries[index]


@testing.effect
def test_summary_reports_the_maximum_for_negative_only_observations():
    """Summary > reports the maximum for negative-only observations"""
    summary = metric.summary(_next_id(), max_age="1 minute", max_size=10, quantiles=[0.5])
    yield from summary.update(-10)
    yield from summary.update(-5)
    result = yield from summary.value()
    assert result.min == -10
    assert result.max == -5


@testing.effect
def test_summary_custom_observe_with_value():
    """Summary > custom observe with value"""
    summary = metric.summary(
        _next_id(), max_age="1 minute", max_size=10, quantiles=[0, 0.1, 0.9]
    ).with_attributes(_attributes)
    yield from fx.succeed(1).track_successes(summary)
    yield from fx.succeed(3).track_successes(summary)
    assert (yield from summary.value()) == metric.SummaryState(
        quantiles=((0, 1), (0.1, 1), (0.9, 3)), count=2, sum=4, min=1, max=3
    )


@testing.effect
def test_summary_custom_observe_with_constant():
    """Summary > custom observe with constant"""
    summary = (
        metric.summary(_next_id(), max_age="1 minute", max_size=10, quantiles=[0, 0.1, 0.9])
        .with_attributes(_attributes)
        .with_constant_input(1)
    )
    yield from fx.succeed(1).track_successes(summary)
    yield from fx.succeed(3).track_successes(summary)
    assert (yield from summary.value()) == metric.SummaryState(
        quantiles=((0, 1), (0.1, 1), (0.9, 1)), count=2, sum=2, min=1, max=1
    )


@testing.effect
def test_summary_should_return_the_correct_quantile_when_the_first_chunk_overshoots():
    """Summary > should return the correct quantile when the first chunk overshoots"""
    samples = [10, 10, 10, 10, 10, 10, 20, 30, 40, 50]
    summary = metric.summary(_next_id(), max_age="1 minute", max_size=15, quantiles=[0.5])
    yield from fx.for_each(samples, summary.update)
    assert (yield from summary.value()) == metric.SummaryState(
        quantiles=((0.5, 10),), count=10, min=10, max=50, sum=200
    )


_TRACKERS: list[
    tuple[str, Callable[[fx.Effect[int, int], Any], fx.Effect[int, int]], list[int]]
] = [
    ("track", lambda eff, counter: eff.track(counter), [1, 2, 3]),
    ("track_errors", lambda eff, counter: eff.track_errors(counter), [0, 1, 1]),
    ("track_defects", lambda eff, counter: eff.track_defects(counter), [0, 0, 1]),
]


@pytest.mark.parametrize(("name", "track", "expected"), _TRACKERS, ids=[t[0] for t in _TRACKERS])
def test_track_updates_after_success_failure_and_defect(
    name: str,
    track: Callable[[fx.Effect[int, int], Any], fx.Effect[int, int]],
    expected: list[float],
) -> None:
    """${name} updates after success, failure and defect: ${expected}"""
    defect = RuntimeError(1)

    @fx.gen
    def program():
        counter = metric.counter(_next_id()).with_constant_input(1)
        exits: list[fx.Exit[int, int]] = []
        counts: list[float] = []
        effects: list[fx.Effect[int, int]] = [fx.succeed(1), fx.fail(1), fx.die(defect)]
        for effect in effects:
            exits.append((yield from track(effect, counter).exit()))
            counts.append((yield from counter.value()).count)
        return exits, counts

    exits, counts = testing.run_test(program)
    assert exits == [fx.exit.succeed(1), fx.exit.fail(1), fx.exit.die(defect)]
    assert counts == expected


@testing.effect
def test_track_duration_tracks_execution_duration():
    """trackDuration > tracks execution duration"""
    timer = metric.timer(_next_id())
    fiber = yield from fx.sleep("1 hour").track_duration(timer).fork()
    yield from testing.adjust("1 hour")
    yield from fiber.join()
    result = yield from timer.value()
    assert result.count == 1
    assert result.min == 3_600_000
    assert result.max == 3_600_000
    assert result.sum == 3_600_000


@testing.effect
def test_track_duration_uses_monotonic_time_when_wall_time_moves_backward():
    """trackDuration > uses monotonic time when wall time moves backward"""
    timer = metric.timer(_next_id())
    yield from testing.set_time(1_000)

    @fx.gen
    def moves():
        yield from testing.adjust("100 millis")
        yield from testing.set_time(0)

    yield from moves.track_duration(timer)
    result = yield from timer.value()
    assert result.count == 1
    assert result.min == 100
    assert result.max == 100
    assert result.sum == 100


@testing.effect
def test_track_duration_with_tracks_execution_duration():
    """trackDurationWith > tracks execution duration"""
    gauge = metric.gauge(_next_id())
    fiber = yield from fx.sleep("1 hour").track_duration(gauge, lambda d: d.to_minutes()).fork()
    yield from testing.adjust("1 hour")
    yield from fiber.join()
    assert (yield from gauge.value()) == metric.GaugeState(60)
