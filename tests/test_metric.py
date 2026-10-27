"""Metrics beyond the Effect test ports: summaries over time, runtime
metrics, the ``track*`` mappers, argument checks, and text output pinned
against Effect under Node."""

import math
from datetime import timedelta
from typing import Any

import pytest

import pyfect as fx
from pyfect import metric, testing
from pyfect._js import js_number


def _fresh[A, E](eff: fx.Effect[A, E]) -> fx.Effect[A, E]:
    return eff.pipe(fx.provide_service(metric.MetricRegistry, {}))


@testing.effect
def test_a_summary_keeps_observations_up_to_max_age_inclusive():
    summary = metric.summary("ages", max_age=60, max_size=10, quantiles=[0, 1])
    yield from summary.update(1)
    yield from testing.adjust(30)
    yield from summary.update(2)
    yield from testing.adjust(30)
    assert (yield from summary.value()).quantiles == ((0, 1), (1, 2))
    yield from testing.adjust(0.001)
    assert (yield from summary.value()).quantiles == ((0, 2), (1, 2))
    yield from testing.adjust(60)
    state = yield from summary.value()
    assert state.quantiles == ((0, None), (1, None))
    assert (state.count, state.min, state.max, state.sum) == (2, 1, 2, 3)


@testing.effect
def test_summary_with_timestamp_drops_future_and_expired_observations():
    summary = metric.summary_with_timestamp("stamped", max_age=10, max_size=10, quantiles=[0.5])
    yield from testing.set_time(100)
    yield from summary.update((1, 85))  # 15s old
    yield from summary.update((2, 101))  # in the future
    yield from summary.update((3, 90.0))  # exactly max_age old
    state = yield from summary.value()
    assert state.quantiles == ((0.5, 3),)
    assert state.count == 3


@testing.effect
def test_summary_with_timestamp_ages_non_finite_timestamps_as_effect_does():
    # Effect under Node: NaN and +Infinity timestamps are never in range; a
    # -Infinity one is only within an infinite max_age. All are counted.
    summary = metric.summary_with_timestamp("odd", max_age=60, max_size=10, quantiles=[0, 1])
    yield from testing.set_time(100)
    yield from summary.update((1, math.nan))
    yield from summary.update((2, math.inf))
    yield from summary.update((3, -math.inf))
    yield from summary.update((4, 100))
    state = yield from summary.value()
    assert state.quantiles == ((0, 4), (1, 4))
    assert (state.count, state.min, state.max, state.sum) == (4, 1, 4, 10)
    forever = metric.summary_with_timestamp("forever", max_age=math.inf, max_size=10, quantiles=[0])
    yield from forever.update((3, -math.inf))
    assert (yield from forever.value()).quantiles == ((0, 3),)


@testing.effect
def test_a_summary_quantile_on_an_exact_rank_takes_the_lower_sample():
    # Effect under Node: [[0.25,1],[0.3,2],[0.5,2],[0.75,3]].
    summary = metric.summary("ranks", max_age=60, max_size=10, quantiles=[0.75, 0.5, 0.25, 0.3])
    yield from fx.for_each([4, 1, 3, 2], summary.update)
    state = yield from summary.value()
    assert state.quantiles == ((0.25, 1), (0.3, 2), (0.5, 2), (0.75, 3))


@testing.effect
def test_a_summary_keeps_only_the_last_max_size_observations():
    summary = metric.summary("ring", max_age=60, max_size=3, quantiles=[0.9, 0.5, 0])
    yield from fx.for_each([5, 1, 4, 2], summary.update)
    assert (yield from summary.value()) == metric.SummaryState(
        quantiles=((0, 1), (0.5, 2), (0.9, 4)), count=4, min=1, max=5, sum=12
    )


@testing.effect
def test_a_summary_of_size_zero_counts_but_keeps_no_samples():
    summary = metric.summary("none", max_age=60, max_size=0, quantiles=[0.5])
    yield from summary.update(7)
    assert (yield from summary.value()) == metric.SummaryState(
        quantiles=((0.5, None),), count=1, min=7, max=7, sum=7
    )


def test_summary_arguments_are_checked_when_it_is_made():
    with pytest.raises(ValueError, match=r"Quantile must be between 0 and 1, found: 1\.5"):
        metric.summary("bad", max_age=1, max_size=1, quantiles=[0.5, 1.5])
    with pytest.raises(ValueError, match="max_size"):
        metric.summary("bad", max_age=1, max_size=-1, quantiles=[])


@testing.effect
def test_a_histogram_counts_nan_past_every_boundary():
    histogram = metric.histogram("h", boundaries=[5, 1, 2.5])
    yield from fx.for_each([0.5, 1, 3, 10, math.nan, -1], histogram.update)
    state = yield from histogram.value()
    assert state.buckets == ((1, 3), (2.5, 3), (5, 4))
    assert (state.count, state.min, state.max) == (6, -1, 10)
    assert math.isnan(state.sum)


@testing.effect
def test_a_timer_records_milliseconds_with_a_time_unit_attribute():
    timer = metric.timer("t", attributes={"route": "/"}, boundaries=[1, 10])
    yield from timer.update(timedelta(milliseconds=5))
    yield from timer.update(0.0005)
    state = yield from timer.value()
    assert state.buckets == ((1, 1), (10, 2))
    assert state.sum == 5.5
    assert timer.attributes == {"route": "/", "time_unit": "milliseconds"}
    text = yield from metric.prometheus_format()
    assert 't_bucket{route="/",le="10"} 2' in text


@testing.effect
def test_the_default_timer_boundaries_double_from_half_a_millisecond():
    timer = metric.timer("t")
    buckets = (yield from timer.value()).buckets
    assert len(buckets) == 35
    assert buckets[0][0] == 0.5
    assert buckets[33][0] == 2**32
    assert buckets[34][0] == math.inf


@testing.effect
def test_a_frequency_state_does_not_change_after_it_is_read():
    frequency = metric.frequency("f", preregistered_words=["z"])
    yield from frequency.update("a")
    before = yield from frequency.value()
    yield from frequency.update("a")
    assert before.occurrences == {"z": 0, "a": 1}
    assert (yield from frequency.value()).occurrences == {"z": 0, "a": 2}


@testing.effect
def test_modify_adds_to_a_gauge_and_updates_a_counter():
    gauge = metric.gauge("g")
    counter = metric.counter("c")
    yield from gauge.update(5)
    yield from gauge.modify(-2)
    yield from counter.modify(3)
    assert (yield from gauge.value()).value == 3
    assert (yield from counter.value()).count == 3


@testing.effect
def test_track_maps_exits_errors_and_defects():
    exits = metric.frequency("exits")
    errors = metric.frequency("errors")
    defects = metric.frequency("defects")
    yield from fx.succeed(1).track(exits, lambda ex: type(ex).__name__)
    yield from fx.fail("boom").track(exits, lambda ex: type(ex).__name__).exit()
    yield from fx.fail("boom").track_errors(errors, lambda e: e.upper()).exit()
    yield from fx.die(KeyError("k")).track_defects(defects, lambda d: type(d).__name__).exit()
    assert (yield from exits.value()).occurrences == {"Success": 1, "Failure": 1}
    assert (yield from errors.value()).occurrences == {"BOOM": 1}
    assert (yield from defects.value()).occurrences == {"KeyError": 1}


@testing.effect
def test_track_duration_records_a_failing_effect_too():
    timer = metric.timer("failing")
    fiber = yield from fx.sleep(2).flat_map(lambda _: fx.fail("x")).track_duration(timer).fork()
    yield from testing.adjust(2)
    yield from fiber.await_exit()
    assert (yield from timer.value()).sum == 2000


@testing.effect
def test_track_duration_records_milliseconds_as_effect_divides_nanoseconds():
    # Effect: Duration.toMillis(5_000_001n nanos) is 5000001 / 1e6 = 5.000001;
    # going through float seconds would give 5.000000999999999.
    timer = metric.timer("exact")
    fiber = yield from fx.sleep(0.005000001).track_duration(timer).fork()
    yield from testing.adjust(0.005000001)
    yield from fiber.join()
    assert (yield from timer.value()).sum == 5.000001


@testing.effect
def test_runtime_metrics_count_the_fibers_started_inside():
    @fx.gen
    def body():
        ok = yield from fx.void.fork()
        bad = yield from fx.fail("x").fork()
        yield from ok.await_exit()
        yield from bad.await_exit()
        return {s.id: s.state for s in (yield from metric.snapshot)}

    states = yield from _fresh(metric.enable_runtime_metrics(body))
    assert states == {
        "child_fibers_started": metric.CounterState(2, True),
        "child_fibers_active": metric.GaugeState(0),
        "child_fiber_successes": metric.CounterState(1, True),
        "child_fiber_failures": metric.CounterState(1, True),
    }


@testing.effect
def test_runtime_metrics_can_be_turned_off_inside():
    @fx.gen
    def body():
        fiber = yield from fx.void.fork()
        yield from fiber.await_exit()
        return (yield from metric.snapshot)

    snapshots = yield from _fresh(
        metric.enable_runtime_metrics(metric.disable_runtime_metrics(body))
    )
    assert snapshots == []


@testing.effect
def test_runtime_metrics_layers_provide_the_reference():
    service = yield from metric.FiberRuntimeMetrics().pipe(
        fx.provide(metric.enable_runtime_metrics_layer)
    )
    assert service is metric.fiber_runtime_metrics
    off = yield from metric.FiberRuntimeMetrics().pipe(
        fx.provide(metric.disable_runtime_metrics_layer)
    )
    assert off is None


@testing.effect
def test_remove_through_with_attributes_removes_only_that_series():
    @fx.gen
    def body():
        counter = metric.counter("c")
        tagged = counter.with_attributes({"k": "v"})
        yield from counter.update(1)
        yield from tagged.update(2)
        yield from tagged.remove()
        return [(s.attributes, s.state) for s in (yield from metric.snapshot)]

    assert (yield from _fresh(body)) == [(None, metric.CounterState(1, False))]


@testing.effect
def test_dump_of_an_empty_registry_is_empty():
    assert (yield from _fresh(metric.dump)) == ""


# Printed by Effect's ``Metric.dump`` and ``PrometheusMetrics.format`` under Node.
_NODE_DUMP = """\
name=f    description=              type=Frequency  attributes=[]                               state=[occurrences: (z -> 0), (a -> 2), (b -> 1)]
name=g-g  description=              type=Gauge      attributes=[]                               state=[value: [1e+21]]
name=h    description=              type=Histogram  attributes=[]                               state=[buckets: [(1 -> 3), (2.5 -> 3), (5 -> 4)], count: [6], min: [-1], max: [10], sum: [NaN]]
name=req  description=Requests
all  type=Counter    attributes=[1x: q"\\, route: /u]             state=[count: [3.1]]
name=req  description=Requests
all  type=Counter    attributes=[1x: q"\\, route: /u, tenant: a]  state=[count: [2]]
name=s2   description=              type=Summary    attributes=[]                               state=[quantiles: [(0.5 -> 0)], count: [0], min: [1.7976931348623157e+308], max: [-1.7976931348623157e+308], sum: [0]]"""  # noqa: E501

_NODE_PROMETHEUS = """\
# HELP app_req Requests\\nall
# TYPE app_req counter
app_req{route="/u",_1x="q\\"\\\\"} 3.1
app_req{route="/u",_1x="q\\"\\\\",tenant="a"} 2
# TYPE app_g_g gauge
app_g_g 1e+21
# TYPE app_h histogram
app_h_bucket{le="1"} 3
app_h_bucket{le="2.5"} 3
app_h_bucket{le="5"} 4
app_h_bucket{le="+Inf"} 6
app_h_sum NaN
app_h_count 6
# TYPE app_s2 summary
app_s2_sum 0
app_s2_count 0
# TYPE app_f counter
app_f{key="z"} 0
app_f{key="a"} 2
app_f{key="b"} 1
"""


@testing.effect
def test_dump_and_prometheus_text_match_effect():
    @fx.gen
    def body():
        counter = metric.counter(
            "req", description="Requests\nall", attributes={"route": "/u", "1x": 'q"\\'}
        )
        yield from counter.update(3)
        yield from counter.update(0.1)
        yield from counter.with_attributes({"tenant": "a"}).update(2)
        yield from metric.gauge("g-g").update(1e21)
        histogram = metric.histogram("h", boundaries=[5, 1, 2.5])
        yield from fx.for_each([0.5, 1, 3, 10, math.nan, -1], histogram.update)
        yield from metric.summary("s2", max_age=60, max_size=3, quantiles=[0.5]).value()
        frequency = metric.frequency("f", preregistered_words=["z"])
        yield from fx.for_each(["a", "a", "b"], frequency.update)
        dumped = yield from metric.dump
        text = yield from metric.prometheus_format(
            prefix="app-", metric_name_mapper=lambda n: n + "__"
        )
        return dumped, text

    dumped, text = yield from _fresh(body)
    assert dumped == _NODE_DUMP
    assert text == _NODE_PROMETHEUS


@pytest.mark.parametrize(
    ("value", "text"),
    [
        (0.1 + 0.2, "0.30000000000000004"),
        (123456789012345680000.0, "123456789012345680000"),
        (1e-7, "1e-7"),
        (1.234e-5, "0.00001234"),
        (5e-324, "5e-324"),
        (-0.000001, "-0.000001"),
        (100.0, "100"),
        (-0.0, "0"),
        (1e21, "1e+21"),
        (float(2**70), "1.1805916207174113e+21"),
        (0.1 * 3e22, "3e+21"),
        (math.inf, "Infinity"),
        (math.nan, "NaN"),
        (2**70, "1180591620717411303424"),
    ],
)
def test_numbers_print_as_in_javascript(value: float, text: str):
    assert js_number(value) == text


def test_boundaries_match_effect():
    assert metric.exponential_boundaries(start=1.1, factor=1.7, count=5) == (
        1.1,
        1.87,
        3.179,
        5.4043,
        math.inf,
    )
    assert metric.linear_boundaries(start=0.1, width=0.2, count=4) == (
        0.1,
        0.30000000000000004,
        0.5,
        math.inf,
    )
    assert metric.linear_boundaries(start=3, width=1, count=0) == (3, math.inf)
    assert metric.boundaries_from_iterable([2, 0, -1, 2, 1]) == (2, 1, math.inf)


def test_exponential_boundaries_overflow_to_infinity_as_in_javascript():
    # Effect under Node: 311 boundaries ending 1e+308, Infinity, Infinity.
    boundaries = metric.exponential_boundaries(start=1, factor=10, count=400)
    assert len(boundaries) == 311
    assert boundaries[-3:] == (1e308, math.inf, math.inf)


def test_a_registration_is_removed_only_while_it_is_current():
    context = fx.Context.make(metric.MetricRegistry, {})
    gauge = metric.gauge("g").with_attributes({"k": "v"})
    first = metric.unsafe_register(gauge, context, lambda _: metric.GaugeState(1))
    second = metric.unsafe_register(gauge, context, lambda _: metric.GaugeState(2))
    first.remove()
    assert gauge.unsafe_value(context) == metric.GaugeState(2)
    second.remove()
    second.remove()
    assert metric.unsafe_snapshot(context) == []


def test_a_metric_is_its_own_description():
    counter: metric.Metric[Any, Any] = metric.counter("c", description="d", attributes=[("a", "b")])
    assert (counter.id, counter.type, counter.description) == ("c", "Counter", "d")
    assert counter.attributes == {"a": "b"}
    assert counter.with_constant_input(1).type == "Counter"
    assert counter.pipe(lambda m: m.id) == "c"
