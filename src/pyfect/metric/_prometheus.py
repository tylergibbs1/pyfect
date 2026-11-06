"""The registry in the Prometheus text exposition format (Effect's
``PrometheusMetrics.format``). ``pyfect.http.prometheus.layer_http`` serves it;
any other HTTP framework can with the content type
``text/plain; version=0.0.4; charset=utf-8``."""

from __future__ import annotations

import math
import re
from collections.abc import Callable, Mapping, Sequence

from pyfect._core import Effect
from pyfect._js import js_number
from pyfect.context import Context
from pyfect.metric._metric import WithContext
from pyfect.metric._snapshot import snapshot_unsafe
from pyfect.metric._state import (
    CounterState,
    FrequencyState,
    GaugeState,
    HistogramState,
    MetricType,
    Snapshot,
)

type MetricNameMapper = Callable[[str], str]

_PROMETHEUS_TYPES: Mapping[MetricType, str] = {
    "Counter": "counter",
    "Gauge": "gauge",
    "Histogram": "histogram",
    "Summary": "summary",
    "Frequency": "counter",
}
_UNEXPORTED_ATTRIBUTES = frozenset(("unit", "time_unit"))


def prometheus_format(
    *, prefix: str | None = None, metric_name_mapper: MetricNameMapper | None = None
) -> Effect[str]:
    """The current registry as Prometheus text. Metric names go through
    ``metric_name_mapper``, are sanitized and get ``prefix_`` in front."""
    return WithContext(
        lambda context: prometheus_format_unsafe(
            context, prefix=prefix, metric_name_mapper=metric_name_mapper
        )
    )


def prometheus_format_unsafe(
    context: Context,
    *,
    prefix: str | None = None,
    metric_name_mapper: MetricNameMapper | None = None,
) -> str:
    """``prometheus_format`` for ``context``'s registry."""
    start = _metric_name(prefix) + "_" if prefix else ""
    families: dict[str, list[Snapshot]] = {}
    for metric in snapshot_unsafe(context):
        mapped = metric.id if metric_name_mapper is None else metric_name_mapper(metric.id)
        families.setdefault(start + _metric_name(mapped), []).append(metric)
    lines: list[str] = []
    for name, metrics in families.items():
        first = metrics[0]
        if first.description:
            lines.append(f"# HELP {name} {_escape_help(first.description)}")
        lines.append(f"# TYPE {name} {_PROMETHEUS_TYPES[first.type]}")
        for metric in metrics:
            lines.extend(_samples(name, metric))
    return "\n".join(lines) + "\n" if lines else ""


def _samples(name: str, metric: Snapshot) -> list[str]:
    attributes = metric.attributes
    labels = _labels(attributes)
    match metric.state:
        case CounterState(count=value) | GaugeState(value=value):
            return [f"{name}{labels} {_value(value)}"]
        case FrequencyState(occurrences=occurrences):
            return [
                f"{name}{_labels(attributes, [('key', key)])} {count}"
                for key, count in occurrences.items()
            ]
        case HistogramState() as state:
            lines = [
                f"{name}_bucket{_labels(attributes, [('le', js_number(b))])} {cumulated}"
                for b, cumulated in state.buckets
                if b != math.inf
            ]
            lines.append(f"{name}_bucket{_labels(attributes, [('le', '+Inf')])} {state.count}")
            return [*lines, *_totals(name, labels, state.sum, state.count)]
        case state:
            lines = [
                f"{name}{_labels(attributes, [('quantile', js_number(q))])} {_value(v)}"
                for q, v in state.quantiles
                if v is not None
            ]
            return [*lines, *_totals(name, labels, state.sum, state.count)]


def _totals(name: str, labels: str, total: float, count: int) -> list[str]:
    return [f"{name}_sum{labels} {_value(total)}", f"{name}_count{labels} {count}"]


def _labels(attributes: Mapping[str, str] | None, extra: Sequence[tuple[str, str]] = ()) -> str:
    pairs = [
        *(
            (key, value)
            for key, value in (attributes or {}).items()
            if key not in _UNEXPORTED_ATTRIBUTES
        ),
        *extra,
    ]
    if not pairs:
        return ""
    return "{" + ",".join(f'{_label_name(k)}="{_escape_label(v)}"' for k, v in pairs) + "}"


def _value(value: float) -> str:
    if isinstance(value, float) and math.isinf(value):
        return "+Inf" if value > 0 else "-Inf"
    return js_number(value)


_NOT_METRIC_CHAR = re.compile(r"[^a-zA-Z0-9_:]")
_NOT_LABEL_CHAR = re.compile(r"[^a-zA-Z0-9_]")
_UNDERSCORES = re.compile(r"_+")


def _metric_name(name: str) -> str:
    sanitized = _NOT_METRIC_CHAR.sub("_", name)
    if re.match(r"[0-9:]", sanitized):
        sanitized = "_" + sanitized
    sanitized = _UNDERSCORES.sub("_", sanitized)
    return sanitized.removesuffix("_")


def _label_name(name: str) -> str:
    sanitized = _NOT_LABEL_CHAR.sub("_", name)
    if re.match(r"[0-9]", sanitized):
        sanitized = "_" + sanitized
    return _UNDERSCORES.sub("_", sanitized)


def _escape_label(value: str) -> str:
    return value.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")


def _escape_help(text: str) -> str:
    return text.replace("\\", "\\\\").replace("\n", "\\n")
