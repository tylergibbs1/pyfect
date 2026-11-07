"""Registry snapshots as OTLP metrics in their JSON shape, cumulative or
as deltas against the last committed snapshot (the conversion inside
Effect's ``OtlpMetrics``)."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, Final

from pyfect.metric._state import (
    CounterState,
    FrequencyState,
    GaugeState,
    HistogramState,
    MetricState,
    Snapshot,
    SummaryState,
)
from pyfect.observability.otlp_resource import KeyValue, entries_to_attributes

type Point = dict[str, Any]
type Metric = dict[str, Any]

_DELTA: Final = 1
_CUMULATIVE: Final = 2
_MAX_SAFE_INTEGER: Final = 2**53 - 1
_UCUM_UNITS: Final = {
    "nanoseconds": "ns",
    "microseconds": "us",
    "milliseconds": "ms",
    "seconds": "s",
    "bytes": "By",
}


def _unit(attributes: Mapping[str, str] | None) -> str:
    if attributes is None:
        return "1"
    unit = attributes.get("unit", attributes.get("time_unit"))
    return "1" if unit is None else _UCUM_UNITS.get(unit, unit)


def _int64(value: int) -> int | str:
    """OTLP/JSON's int64: decimal text past JavaScript's safe integers."""
    return value if -_MAX_SAFE_INTEGER <= value <= _MAX_SAFE_INTEGER else str(value)


def _series_key(id: str, attributes: Mapping[str, str] | None) -> str:
    return id if not attributes else f"{id}:{sorted(attributes.items())!r}"


def _number(bigint: bool, value: float) -> Point:
    return {"asInt": _int64(int(value))} if bigint else {"asDouble": value}


@dataclass(frozen=True, slots=True)
class _HistogramCheckpoint:
    count: int
    sum: float
    bucket_counts: list[int]


@dataclass(frozen=True, slots=True)
class Checkpoints:
    """What a delta export subtracts: the series of one snapshot."""

    time_nanos: int
    counters: dict[str, float]
    histograms: dict[str, _HistogramCheckpoint]
    frequencies: dict[str, dict[str, int]]


def empty_checkpoints(time_nanos: int) -> Checkpoints:
    return Checkpoints(time_nanos, {}, {}, {})


def _histogram_buckets(state: HistogramState) -> tuple[list[float], list[int]]:
    boundaries: list[float] = []
    counts: list[int] = []
    previous = 0
    for boundary, value in state.buckets:
        if boundary == float("inf"):
            break
        boundaries.append(boundary)
        counts.append(value - previous)
        previous = value
    # The overflow bucket from the total, whether or not Infinity is a boundary.
    counts.append(state.count - previous)
    return boundaries, counts


@dataclass(frozen=True, slots=True)
class _Series:
    """One snapshot entry with what every point of it shares."""

    snapshot: Snapshot
    key: str
    attributes: list[KeyValue]
    interval_start: str
    start_time: str
    now: str

    def point(self, start: str, value: Point) -> Point:
        return {
            "attributes": self.attributes,
            "startTimeUnixNano": start,
            "timeUnixNano": self.now,
            **value,
        }


@dataclass(frozen=True, slots=True)
class Converter:
    """Converts one snapshot, reading ``previous`` (for deltas) and
    filling ``upcoming``. Only series in the snapshot carry their delta
    state forward, so a removed series neither leaks state nor reports a
    negative delta when it comes back."""

    delta: bool
    start_time: str
    previous: Checkpoints
    upcoming: Checkpoints

    def metrics(self, snapshots: list[Snapshot]) -> list[Metric]:
        metrics: list[Metric] = []
        by_name: dict[str, Metric] = {}
        interval_start = str(self.previous.time_nanos) if self.delta else self.start_time
        now = str(self.upcoming.time_nanos)
        for snapshot in snapshots:
            raw = snapshot.attributes
            attributes = [] if raw is None else entries_to_attributes(raw.items())
            series = _Series(
                snapshot,
                _series_key(snapshot.id, raw),
                attributes,
                interval_start,
                self.start_time,
                now,
            )
            kind, body, points = self._convert(series, snapshot.state)
            existing = by_name.get(snapshot.id)
            if existing is not None:
                existing[kind]["dataPoints"].extend(points)
                continue
            metric: Metric = {"name": snapshot.id}
            if snapshot.description is not None:
                metric["description"] = snapshot.description
            metric["unit"] = _unit(raw)
            metric[kind] = {**body, "dataPoints": points}
            metrics.append(metric)
            by_name[snapshot.id] = metric
        return metrics

    def _temporality(self) -> int:
        return _DELTA if self.delta else _CUMULATIVE

    def _convert(self, series: _Series, state: MetricState) -> tuple[str, Point, list[Point]]:
        match state:
            case CounterState():
                body = {
                    "aggregationTemporality": self._temporality(),
                    "isMonotonic": state.incremental,
                }
                return (
                    "sum",
                    body,
                    [series.point(series.interval_start, self._counter(series, state))],
                )
            case GaugeState():
                value = _number(series.snapshot.bigint, state.value)
                return "gauge", {}, [series.point(series.start_time, value)]
            case HistogramState():
                body = {"aggregationTemporality": self._temporality()}
                return (
                    "histogram",
                    body,
                    [series.point(series.interval_start, self._histogram(series, state))],
                )
            case FrequencyState():
                body = {"aggregationTemporality": self._temporality(), "isMonotonic": True}
                return "sum", body, self._frequency(series, state)
            case SummaryState():
                # Count and sum are lifetime totals, so a summary is always
                # cumulative.
                value: Point = {
                    "count": state.count,
                    "sum": state.sum,
                    "quantileValues": [
                        {"quantile": q, "value": v} for q, v in state.quantiles if v is not None
                    ],
                }
                return "summary", {}, [series.point(series.start_time, value)]

    def _counter(self, series: _Series, state: CounterState[float]) -> Point:
        bigint = series.snapshot.bigint
        current = state.count
        report: float = current
        if self.delta:
            before = self.previous.counters.get(series.key)
            if before is not None:
                report = int(current) - int(before) if bigint else float(current) - float(before)
                if state.incremental and report < 0:
                    report = current
            self.upcoming.counters[series.key] = current
        return _number(bigint, report)

    def _histogram(self, series: _Series, state: HistogramState) -> Point:
        boundaries, counts = _histogram_buckets(state)
        count, total, bucket_counts = state.count, state.sum, counts
        before = self.previous.histograms.get(series.key) if self.delta else None
        if before is not None:
            count = state.count - before.count
            total = state.sum - before.sum
            known = before.bucket_counts
            bucket_counts = [
                max(0, c - (known[i] if i < len(known) else 0)) for i, c in enumerate(counts)
            ]
        if self.delta:
            self.upcoming.histograms[series.key] = _HistogramCheckpoint(
                state.count, state.sum, counts
            )
        point: Point = {"count": count}
        if before is None:
            # Cumulative extrema cannot describe a later delta interval.
            point["min"] = state.min
            point["max"] = state.max
        point["sum"] = total
        point["bucketCounts"] = bucket_counts
        point["explicitBounds"] = boundaries
        return point

    def _frequency(self, series: _Series, state: FrequencyState) -> list[Point]:
        seen = self.previous.frequencies.get(series.key) if self.delta else None
        current = dict(state.occurrences)
        if self.delta:
            self.upcoming.frequencies[series.key] = current
        return [
            {
                "attributes": [*series.attributes, {"key": "key", "value": {"stringValue": word}}],
                "startTimeUnixNano": series.interval_start,
                "timeUnixNano": series.now,
                "asInt": value if seen is None else max(0, value - seen.get(word, 0)),
            }
            for word, value in current.items()
        ]
