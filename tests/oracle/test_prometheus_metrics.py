"""Ports of Effect's ``observability/PrometheusMetrics.test.ts``.

Each test's docstring is the Effect test title. ``PrometheusMetrics.format(
{ prefix, metricNameMapper })`` is ``metric.prometheus_format(prefix=...,
metric_name_mapper=...)``. Each test runs with a fresh registry, so no
test sees another's metrics. Effect has no title for ``layerHttp``
(``http.prometheus.layer_http``); the last tests here pin it to its source.
"""

import math
import re

import pyfect as fx
from pyfect import metric, testing
from pyfect.http import prometheus, router


def _format(
    *updates: fx.Effect[None],
    prefix: str | None = None,
    mapper: metric.MetricNameMapper | None = None,
) -> fx.Effect[str]:
    @fx.gen
    def body():
        for update in updates:
            yield from update
        return (yield from metric.prometheus_format(prefix=prefix, metric_name_mapper=mapper))

    return body.pipe(fx.provide_service(metric.MetricRegistry, {}))


def _snake(name: str) -> str:
    return re.sub(r"([a-z])([A-Z])", r"\1_\2", name).lower()


@testing.effect
def test_counter_formats_a_simple_counter():
    """format > Counter > formats a simple counter"""
    counter = metric.counter("test_counter", description="A test counter")
    output = yield from _format(counter.update(42))
    assert "# HELP test_counter A test counter" in output
    assert "# TYPE test_counter counter" in output
    assert "test_counter 42" in output


@testing.effect
def test_counter_formats_a_counter_with_bigint_value():
    """format > Counter > formats a counter with bigint value"""
    counter = metric.counter("bigint_counter", description="A bigint counter", bigint=True)
    output = yield from _format(counter.update(9007199254740993))
    assert "# TYPE bigint_counter counter" in output
    assert "bigint_counter 9007199254740993" in output


@testing.effect
def test_counter_formats_a_counter_with_attributes():
    """format > Counter > formats a counter with attributes"""
    counter = metric.counter(
        "labeled_counter",
        description="Counter with labels",
        attributes={"method": "GET", "endpoint": "/api/users"},
    )
    output = yield from _format(counter.update(10))
    assert "# TYPE labeled_counter counter" in output
    assert 'labeled_counter{method="GET",endpoint="/api/users"} 10' in output


@testing.effect
def test_counter_formats_a_counter_without_description():
    """format > Counter > formats a counter without description"""
    counter = metric.counter("no_desc_counter")
    output = yield from _format(counter.update(5))
    assert "# HELP no_desc_counter" not in output
    assert "# TYPE no_desc_counter counter" in output
    assert "no_desc_counter 5" in output


@testing.effect
def test_gauge_formats_a_simple_gauge():
    """format > Gauge > formats a simple gauge"""
    gauge = metric.gauge("test_gauge", description="A test gauge")
    output = yield from _format(gauge.update(123.45))
    assert "# HELP test_gauge A test gauge" in output
    assert "# TYPE test_gauge gauge" in output
    assert "test_gauge 123.45" in output


@testing.effect
def test_gauge_formats_a_gauge_with_negative_value():
    """format > Gauge > formats a gauge with negative value"""
    gauge = metric.gauge("negative_gauge", description="A gauge with negative value")
    output = yield from _format(gauge.update(-50))
    assert "negative_gauge -50" in output


@testing.effect
def test_gauge_formats_a_gauge_with_bigint_value():
    """format > Gauge > formats a gauge with bigint value"""
    gauge = metric.gauge("bigint_gauge", description="A bigint gauge", bigint=True)
    output = yield from _format(gauge.update(1000000000000))
    assert "bigint_gauge 1000000000000" in output


@testing.effect
def test_histogram_formats_a_histogram_with_buckets():
    """format > Histogram > formats a histogram with buckets"""
    histogram = metric.histogram(
        "test_histogram", description="A test histogram", boundaries=[10, 50, 100, 500]
    )
    output = yield from _format(*(histogram.update(v) for v in [5, 25, 75, 200, 1000]))
    assert "# HELP test_histogram A test histogram" in output
    assert "# TYPE test_histogram histogram" in output
    assert 'test_histogram_bucket{le="10"} 1' in output
    assert 'test_histogram_bucket{le="50"} 2' in output
    assert 'test_histogram_bucket{le="100"} 3' in output
    assert 'test_histogram_bucket{le="500"} 4' in output
    assert 'test_histogram_bucket{le="+Inf"} 5' in output
    assert "test_histogram_sum 1305" in output
    assert "test_histogram_count 5" in output


@testing.effect
def test_histogram_formats_a_histogram_with_attributes():
    """format > Histogram > formats a histogram with attributes"""
    histogram = metric.histogram(
        "labeled_histogram",
        description="Histogram with labels",
        boundaries=[100, 500],
        attributes={"service": "api"},
    )
    output = yield from _format(histogram.update(250))
    assert 'labeled_histogram_bucket{service="api",le="100"} 0' in output
    assert 'labeled_histogram_bucket{service="api",le="500"} 1' in output
    assert 'labeled_histogram_bucket{service="api",le="+Inf"} 1' in output
    assert 'labeled_histogram_sum{service="api"} 250' in output
    assert 'labeled_histogram_count{service="api"} 1' in output


@testing.effect
def test_histogram_writes_a_single_inf_bucket_when_the_boundaries_end_with_infinity():
    """format > Histogram > writes a single +Inf bucket when the boundaries end with Infinity"""
    histogram = metric.histogram(
        "linear_histogram", boundaries=metric.linear_boundaries(start=0, width=100, count=4)
    )
    output = yield from _format(histogram.update(50), histogram.update(500))
    buckets = [line for line in output.split("\n") if line.startswith("linear_histogram_bucket")]
    assert buckets == [
        'linear_histogram_bucket{le="100"} 1',
        'linear_histogram_bucket{le="200"} 1',
        'linear_histogram_bucket{le="+Inf"} 2',
    ]


@testing.effect
def test_summary_formats_a_summary_with_quantiles():
    """format > Summary > formats a summary with quantiles"""
    summary = metric.summary(
        "test_summary",
        description="A test summary",
        max_age="1 minute",
        max_size=100,
        quantiles=[0.5, 0.9, 0.99],
    )
    output = yield from _format(*(summary.update(i) for i in range(1, 101)))
    assert "# HELP test_summary A test summary" in output
    assert "# TYPE test_summary summary" in output
    assert 'test_summary{quantile="0.5"}' in output
    assert 'test_summary{quantile="0.9"}' in output
    assert 'test_summary{quantile="0.99"}' in output
    assert "test_summary_sum 5050" in output
    assert "test_summary_count 100" in output


@testing.effect
def test_frequency_formats_a_frequency_metric():
    """format > Frequency > formats a frequency metric"""
    frequency = metric.frequency("test_frequency", description="A test frequency")
    words = ["success", "success", "failure", "success"]
    output = yield from _format(*(frequency.update(w) for w in words))
    assert "# HELP test_frequency A test frequency" in output
    assert "# TYPE test_frequency counter" in output
    assert 'test_frequency{key="success"} 3' in output
    assert 'test_frequency{key="failure"} 1' in output


@testing.effect
def test_frequency_formats_a_frequency_metric_with_attributes():
    """format > Frequency > formats a frequency metric with attributes"""
    frequency = metric.frequency(
        "labeled_frequency", description="Frequency with labels", attributes={"service": "api"}
    )
    output = yield from _format(frequency.update("200"), frequency.update("404"))
    assert 'labeled_frequency{service="api",key="200"} 1' in output
    assert 'labeled_frequency{service="api",key="404"} 1' in output


@testing.effect
def test_options_applies_prefix_to_metric_names():
    """format > options > applies prefix to metric names"""
    counter = metric.counter("requests_total", description="Total requests")
    output = yield from _format(counter.update(100), prefix="myapp")
    assert "# HELP myapp_requests_total Total requests" in output
    assert "# TYPE myapp_requests_total counter" in output
    assert "myapp_requests_total 100" in output


@testing.effect
def test_options_applies_custom_metric_name_mapper():
    """format > options > applies custom metric name mapper"""
    counter = metric.counter("requestCount", description="Request count")
    output = yield from _format(counter.update(50), mapper=_snake)
    assert "# HELP request_count Request count" in output
    assert "# TYPE request_count counter" in output
    assert "request_count 50" in output


@testing.effect
def test_options_combines_prefix_and_mapper():
    """format > options > combines prefix and mapper"""
    counter = metric.counter("httpRequests", description="HTTP requests")
    output = yield from _format(counter.update(25), prefix="app", mapper=_snake)
    assert "app_http_requests 25" in output


@testing.effect
def test_sanitization_sanitizes_invalid_metric_name_characters():
    """format > sanitization > sanitizes invalid metric name characters"""
    counter = metric.counter("metric-with-dashes.and.dots", description="Metric with special chars")
    output = yield from _format(counter.update(1))
    assert "metric_with_dashes_and_dots 1" in output


@testing.effect
def test_sanitization_handles_metric_names_starting_with_digits():
    """format > sanitization > handles metric names starting with digits"""
    counter = metric.counter("123_metric", description="Metric starting with number")
    output = yield from _format(counter.update(1))
    assert "_123_metric 1" in output


@testing.effect
def test_sanitization_escapes_special_characters_in_label_values():
    """format > sanitization > escapes special characters in label values"""
    counter = metric.counter(
        "escape_test",
        description="Test escaping",
        attributes={"path": '/api/users"quoted"', "message": "line1\nline2"},
    )
    output = yield from _format(counter.update(1))
    assert 'path="/api/users\\"quoted\\""' in output
    assert 'message="line1\\nline2"' in output


@testing.effect
def test_sanitization_escapes_backslashes_in_label_values():
    """format > sanitization > escapes backslashes in label values"""
    counter = metric.counter(
        "backslash_test",
        description="Test backslash escaping",
        attributes={"path": "C:\\Users\\test"},
    )
    output = yield from _format(counter.update(1))
    assert 'path="C:\\\\Users\\\\test"' in output


@testing.effect
def test_sanitization_escapes_special_characters_in_help_text():
    """format > sanitization > escapes special characters in HELP text"""
    counter = metric.counter("help_escape", description="Line 1\nLine 2 with\\backslash")
    output = yield from _format(counter.update(1))
    assert "# HELP help_escape Line 1\\nLine 2 with\\\\backslash" in output


@testing.effect
def test_special_values_formats_nan_values():
    """format > special values > formats NaN values"""
    gauge = metric.gauge("nan_gauge", description="Gauge with NaN")
    output = yield from _format(gauge.update(math.nan))
    assert "nan_gauge NaN" in output


@testing.effect
def test_special_values_formats_infinity_values():
    """format > special values > formats Infinity values"""
    gauge = metric.gauge("inf_gauge", description="Gauge with Infinity")
    output = yield from _format(gauge.update(math.inf))
    assert "inf_gauge +Inf" in output


@testing.effect
def test_special_values_formats_negative_infinity_values():
    """format > special values > formats negative Infinity values"""
    gauge = metric.gauge("neg_inf_gauge", description="Gauge with -Infinity")
    output = yield from _format(gauge.update(-math.inf))
    assert "neg_inf_gauge -Inf" in output


@testing.effect
def test_empty_output_returns_empty_string_when_no_metrics_are_registered():
    """format > empty output > returns empty string when no metrics are registered"""
    output = yield from _format()
    assert output == ""


@testing.effect
def test_output_format_ends_with_a_newline_when_there_are_metrics():
    """format > output format > ends with a newline when there are metrics"""
    counter = metric.counter("newline_test", description="Test newline")
    output = yield from _format(counter.update(1))
    assert output.endswith("\n")


@testing.effect
def test_a_timer_is_written_in_milliseconds_without_its_time_unit():
    """(not an Effect title; trawl T6) A timer records milliseconds and the
    export leaves out ``time_unit``, so the name says nothing of the unit.
    The expected text is Effect 4.0.6's ``PrometheusMetrics.format()`` under
    Node for the same updates."""
    timer = metric.timer("trawl_visit_seconds", description="Page visits", boundaries=[100, 1000])
    output = yield from _format(timer.update("51521 millis"), timer.update("250 millis"))
    assert output == (
        "# HELP trawl_visit_seconds Page visits\n"
        "# TYPE trawl_visit_seconds histogram\n"
        'trawl_visit_seconds_bucket{le="100"} 0\n'
        'trawl_visit_seconds_bucket{le="1000"} 1\n'
        'trawl_visit_seconds_bucket{le="+Inf"} 2\n'
        "trawl_visit_seconds_sum 51771\n"
        "trawl_visit_seconds_count 2\n"
    )


@testing.effect
def test_layer_http_serves_the_registry_at_metrics():
    yield from metric.counter("served", description="Served").update(2)
    client = yield from router.in_memory_client(prometheus.layer_http())
    response = yield from client.get("http://localhost/metrics")
    assert response.status == 200
    assert response.headers.get("content-type") == "text/plain; version=0.0.4; charset=utf-8"
    text = yield from response.text
    assert "# HELP served Served\n" in text
    assert "served 2\n" in text


@testing.effect
def test_layer_http_takes_a_path_and_the_format_options():
    yield from metric.gauge("depth").update(1)
    routes = prometheus.layer_http(
        path="/internal/metrics", prefix="app", metric_name_mapper=str.upper
    )
    client = yield from router.in_memory_client(routes)
    moved = yield from client.get("http://localhost/metrics")
    assert moved.status == 404
    response = yield from client.get("http://localhost/internal/metrics")
    assert "app_DEPTH 1\n" in (yield from response.text)
