"""Metrics (Effect's ``Metric``): counters, gauges, frequencies,
histograms, summaries and timers, kept in a registry and read as
snapshots or Prometheus text.

    requests = metric.counter("http_requests", attributes={"route": "/users"})
    latency = metric.timer("http_latency")

    handler = get_users().track_duration(latency).track(requests.with_constant_input(1))
    text = yield from metric.prometheus_format()

A metric is a description: updating it finds its series in the current
``MetricRegistry`` (one process-wide registry by default), with the
``CurrentMetricAttributes`` in scope merged into its own. Effects track
metrics with ``eff.track``, ``track_successes``, ``track_errors``,
``track_defects`` and ``track_duration``.
"""

from pyfect._metric_ref import FiberRuntimeMetrics, FiberRuntimeMetricsService
from pyfect.metric._boundaries import (
    boundaries_from_iterable,
    exponential_boundaries,
    linear_boundaries,
)
from pyfect.metric._kinds import (
    Counter,
    Frequency,
    Gauge,
    Histogram,
    Summary,
    counter,
    frequency,
    gauge,
    histogram,
    summary,
    summary_with_timestamp,
    timer,
)
from pyfect.metric._metric import Metric, Registration, unsafe_register
from pyfect.metric._prometheus import (
    MetricNameMapper,
    prometheus_format,
    unsafe_prometheus_format,
)
from pyfect.metric._refs import (
    Attributes,
    CurrentMetricAttributes,
    Hooks,
    Metadata,
    MetricKey,
    MetricRegistry,
    Registry,
)
from pyfect.metric._runtime import (
    disable_runtime_metrics,
    disable_runtime_metrics_layer,
    enable_runtime_metrics,
    enable_runtime_metrics_layer,
    fiber_runtime_metrics,
)
from pyfect.metric._snapshot import dump, snapshot, unsafe_snapshot
from pyfect.metric._state import (
    CounterState,
    FrequencyState,
    GaugeState,
    HistogramState,
    MetricState,
    MetricType,
    Snapshot,
    SummaryState,
)

__all__ = [
    "Attributes",
    "Counter",
    "CounterState",
    "CurrentMetricAttributes",
    "FiberRuntimeMetrics",
    "FiberRuntimeMetricsService",
    "Frequency",
    "FrequencyState",
    "Gauge",
    "GaugeState",
    "Histogram",
    "HistogramState",
    "Hooks",
    "Metadata",
    "Metric",
    "MetricKey",
    "MetricNameMapper",
    "MetricRegistry",
    "MetricState",
    "MetricType",
    "Registration",
    "Registry",
    "Snapshot",
    "Summary",
    "SummaryState",
    "boundaries_from_iterable",
    "counter",
    "disable_runtime_metrics",
    "disable_runtime_metrics_layer",
    "dump",
    "enable_runtime_metrics",
    "enable_runtime_metrics_layer",
    "exponential_boundaries",
    "fiber_runtime_metrics",
    "frequency",
    "gauge",
    "histogram",
    "linear_boundaries",
    "prometheus_format",
    "snapshot",
    "summary",
    "summary_with_timestamp",
    "timer",
    "unsafe_prometheus_format",
    "unsafe_register",
    "unsafe_snapshot",
]
