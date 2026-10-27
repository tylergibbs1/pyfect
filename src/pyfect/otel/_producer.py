"""``MetricProducer``: the pyfect metric registry as OpenTelemetry metric
data (Effect's ``MetricProducerImpl``)."""

from __future__ import annotations

import math
import time
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Final, Literal, cast

from opentelemetry.sdk.metrics.export import (
    AggregationTemporality,
    DataT,
    Gauge,
    Histogram,
    HistogramDataPoint,
    Metric,
    MetricsData,
    NumberDataPoint,
    ResourceMetrics,
    ScopeMetrics,
    Sum,
)
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.util.instrumentation import InstrumentationScope

from pyfect._js import js_number
from pyfect.context import Context
from pyfect.metric import (
    CounterState,
    FrequencyState,
    GaugeState,
    HistogramState,
    Snapshot,
    SummaryState,
    unsafe_snapshot,
)

type TemporalityPreference = Literal["cumulative", "delta"]
"""``"cumulative"``: totals since the producer started (the default).
``"delta"``: changes since the producer's last collection."""

_SCOPE: Final = InstrumentationScope("pyfect.otel.metrics")

_NO_EXTREMUM: Final = cast(float, None)
"""A delta histogram leaves out ``min`` and ``max``, which cannot be
derived from cumulative ones. The SDK types them as floats; OTLP encodes
``None`` as an unset optional field."""

type _Kind = Literal["sum", "monotonic_sum", "gauge", "histogram"]


@dataclass(slots=True)
class _Series:
    """The data points of one metric name, gathered over its series; the
    first series seen names its description and unit."""

    kind: _Kind
    description: str
    unit: str
    points: list[NumberDataPoint | HistogramDataPoint] = field(
        default_factory=list[NumberDataPoint | HistogramDataPoint]
    )

    def data(self, temporality: AggregationTemporality) -> DataT:
        match self.kind:
            case "gauge":
                return Gauge(cast(list[NumberDataPoint], self.points))
            case "histogram":
                return Histogram(cast(list[HistogramDataPoint], self.points), temporality)
            case "sum" | "monotonic_sum":
                numbers = cast(list[NumberDataPoint], self.points)
                return Sum(numbers, temporality, self.kind == "monotonic_sum")


@dataclass(frozen=True, slots=True)
class _HistogramTotals:
    count: int
    sum: float
    bucket_counts: list[int]


@dataclass(slots=True)
class _Totals:
    """What each series held at the last delta collection, by series key."""

    counters: dict[str, float] = field(default_factory=dict[str, float])
    histograms: dict[str, _HistogramTotals] = field(default_factory=dict[str, _HistogramTotals])
    frequencies: dict[str, Mapping[str, int]] = field(default_factory=dict[str, Mapping[str, int]])
    summaries: dict[str, tuple[int, float]] = field(default_factory=dict[str, tuple[int, float]])


class MetricProducer:
    """Collects the registry of ``context`` (captured when the producer was
    made) as ``MetricsData`` with ``resource``. A delta producer remembers
    the values of the series it last collected, so give each reader its
    own ``fork()``."""

    def __init__(
        self,
        resource: Resource,
        context: Context,
        temporality: TemporalityPreference = "cumulative",
    ) -> None:
        self.resource = resource
        self.context = context
        self.temporality: TemporalityPreference = temporality
        self._start_times: dict[str, int] = {}
        self._start_time = time.time_ns()
        self._previous_export_time = self._start_time
        self._totals = _Totals()

    def fork(self) -> MetricProducer:
        """A fresh producer of the same registry, resource and temporality."""
        return MetricProducer(self.resource, self.context, self.temporality)

    def collect(self) -> MetricsData:
        """Every series of the registry now."""
        delta = self.temporality == "delta"
        run = _Collection(
            now=time.time_ns(),
            delta=delta,
            start_time=self._start_time,
            interval_start=self._previous_export_time if delta else self._start_time,
            start_times=self._start_times,
            previous=self._totals,
        )
        for snapshot in unsafe_snapshot(self.context):
            run.add(snapshot)
        # Only series in this snapshot carry their delta state forward, so a
        # removed series does not report a negative delta when recreated.
        self._totals = run.totals
        if delta:
            self._previous_export_time = run.now
        return MetricsData(
            [ResourceMetrics(self.resource, [ScopeMetrics(_SCOPE, run.metrics(), "")], "")]
        )


class _Collection:
    """One ``collect``: gathers the data points of each metric name."""

    def __init__(
        self,
        *,
        now: int,
        delta: bool,
        start_time: int,
        interval_start: int,
        start_times: dict[str, int],
        previous: _Totals,
    ) -> None:
        self.now = now
        self.delta = delta
        self.start_time = start_time
        self.interval_start = interval_start
        self.start_times = start_times
        self.previous = previous
        self.totals = _Totals()
        self.series: dict[str, _Series] = {}

    def metrics(self) -> list[Metric]:
        temporality = (
            AggregationTemporality.DELTA if self.delta else AggregationTemporality.CUMULATIVE
        )
        return [
            Metric(name, series.description, series.unit, series.data(temporality))
            for name, series in self.series.items()
        ]

    def series_for(
        self,
        snapshot: Snapshot,
        kind: _Kind,
        attributes: Mapping[str, str],
        *,
        name: str | None = None,
        unit: str | None = None,
    ) -> _Series:
        """The series of ``name`` (the snapshot's id unless given), made
        from this snapshot if it is the first of its name. The unit is the
        ``unit`` or ``time_unit`` attribute unless given, else ``"1"``."""
        name = snapshot.id if name is None else name
        if name not in self.series:
            if unit is None:
                unit = attributes.get("unit", attributes.get("time_unit", "1"))
            self.series[name] = _Series(kind, snapshot.description or "", unit)
        return self.series[name]

    def started(self, name: str) -> int:
        """A data point's start: the interval's for delta, else when the
        metric was first collected."""
        if self.delta:
            return self.interval_start
        return self.start_times.setdefault(name, self.interval_start)

    def add(self, snapshot: Snapshot) -> None:
        attributes = dict(snapshot.attributes or {})
        key = _series_key(snapshot)
        match snapshot.state:
            case CounterState() as state:
                self.counter(snapshot, state, key, attributes)
            case GaugeState() as state:
                start = self.start_times.setdefault(snapshot.id, self.start_time)
                self.series_for(snapshot, "gauge", attributes).points.append(
                    NumberDataPoint(attributes, start, self.now, state.value)
                )
            case HistogramState() as state:
                self.histogram(snapshot, state, key, attributes)
            case FrequencyState() as state:
                self.frequency(snapshot, state, key, attributes)
            case SummaryState() as state:
                self.summary(snapshot, state, key, attributes)

    def counter(
        self, snapshot: Snapshot, state: CounterState[float], key: str, attributes: dict[str, str]
    ) -> None:
        value = state.count
        if self.delta:
            before = self.previous.counters.get(key)
            if before is not None:
                value = state.count - before
                if state.incremental and value < 0:
                    value = state.count
            self.totals.counters[key] = state.count
        kind: _Kind = "monotonic_sum" if state.incremental else "sum"
        self.series_for(snapshot, kind, attributes).points.append(
            NumberDataPoint(attributes, self.started(snapshot.id), self.now, value)
        )

    def histogram(
        self, snapshot: Snapshot, state: HistogramState, key: str, attributes: dict[str, str]
    ) -> None:
        boundaries, counts = _buckets(state)
        count, total, reported = state.count, state.sum, counts
        low, high = state.min, state.max
        if self.delta:
            before = self.previous.histograms.get(key)
            if before is not None:
                count -= before.count
                total -= before.sum
                earlier = [*before.bucket_counts, *[0] * len(counts)]
                reported = [max(0, c - earlier[i]) for i, c in enumerate(counts)]
                low = high = _NO_EXTREMUM
            self.totals.histograms[key] = _HistogramTotals(state.count, state.sum, counts)
        self.series_for(snapshot, "histogram", attributes).points.append(
            HistogramDataPoint(
                attributes,
                self.started(snapshot.id),
                self.now,
                count,
                total,
                reported,
                boundaries,
                low,
                high,
            )
        )

    def frequency(
        self, snapshot: Snapshot, state: FrequencyState, key: str, attributes: dict[str, str]
    ) -> None:
        before = self.previous.frequencies.get(key) if self.delta else None
        series = self.series_for(snapshot, "monotonic_sum", attributes)
        for word, seen in state.occurrences.items():
            reported = seen if before is None else max(0, seen - before.get(word, 0))
            series.points.append(
                NumberDataPoint(
                    {**attributes, "key": word}, self.started(snapshot.id), self.now, reported
                )
            )
        if self.delta:
            self.totals.frequencies[key] = dict(state.occurrences)

    def summary(
        self, snapshot: Snapshot, state: SummaryState, key: str, attributes: dict[str, str]
    ) -> None:
        count, total = state.count, state.sum
        if self.delta:
            before = self.previous.summaries.get(key)
            if before is not None:
                count -= before[0]
                total -= before[1]
            self.totals.summaries[key] = (state.count, state.sum)
        start, now = self.interval_start, self.now
        labelled = [
            ("min", state.min),
            *((js_number(q), 0 if v is None else v) for q, v in state.quantiles),
            ("max", state.max),
        ]
        self.series_for(snapshot, "sum", attributes, name=f"{snapshot.id}_quantiles").points.extend(
            NumberDataPoint({**attributes, "quantile": label}, start, now, value)
            for label, value in labelled
        )
        for suffix, value in (("count", count), ("sum", total)):
            self.series_for(
                snapshot, "monotonic_sum", attributes, name=f"{snapshot.id}_{suffix}", unit="1"
            ).points.append(NumberDataPoint(attributes, start, now, value))


def _series_key(snapshot: Snapshot) -> str:
    """The metric id and its sorted attributes: one series."""
    if not snapshot.attributes:
        return snapshot.id
    return f"{snapshot.id}:{sorted(snapshot.attributes.items())!r}"


def _buckets(state: HistogramState) -> tuple[list[float], list[int]]:
    """The finite boundaries and the count in each bucket (not cumulative),
    the last bucket holding everything above the last boundary."""
    boundaries: list[float] = []
    counts: list[int] = []
    below = 0
    for boundary, cumulative in state.buckets:
        if boundary == math.inf:
            break
        boundaries.append(boundary)
        counts.append(cumulative - below)
        below = cumulative
    counts.append(state.count - below)
    return boundaries, counts
