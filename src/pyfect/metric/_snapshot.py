"""Reading the registry: every series' state, as data or as text."""

from __future__ import annotations

from collections.abc import Iterable, Mapping

from pyfect._core import Effect
from pyfect._js import js_number
from pyfect.context import Context
from pyfect.metric._metric import WithContext
from pyfect.metric._refs import MetricRegistry
from pyfect.metric._state import (
    CounterState,
    FrequencyState,
    GaugeState,
    HistogramState,
    MetricState,
    Snapshot,
)


def unsafe_snapshot(context: Context) -> list[Snapshot]:
    """Every series in ``context``'s registry, in registration order."""
    return [
        Snapshot(m.id, m.type, m.description, m.attributes, m.hooks.get(context))
        for m in list(context.unsafe_get(MetricRegistry).values())
    ]


snapshot: Effect[list[Snapshot]] = WithContext(unsafe_snapshot)
"""Every series in the current registry, in registration order."""


def _dump(context: Context) -> str:
    metrics = unsafe_snapshot(context)
    if not metrics:
        return ""
    name_width = max(len(m.id) for m in metrics) + 2
    description_width = max(len(m.description or "") for m in metrics) + 2
    type_width = max(len(m.type) for m in metrics) + 2
    attributes_width = (
        max(len(_attributes(m.attributes)) if m.attributes is not None else 0 for m in metrics) + 2
    )
    groups: dict[str, list[Snapshot]] = {}
    for m in metrics:
        groups.setdefault(m.id, []).append(m)
    return "\n".join(
        f"name={m.id.ljust(name_width)}"
        f"description={(m.description or '').ljust(description_width)}"
        f"type={m.type.ljust(type_width)}"
        f"{_attributes(m.attributes or {}).ljust(attributes_width)}"
        f"state={_state(m.state)}"
        for _, group in sorted(groups.items(), key=lambda item: item[0])
        for m in group
    )


dump: Effect[str] = WithContext(_dump)
"""The current registry as text, one line per series, grouped by id."""


def _attributes(attributes: Mapping[str, str]) -> str:
    pairs = ", ".join(f"{k}: {v}" for k, v in sorted(attributes.items(), key=lambda kv: kv[0]))
    return f"attributes=[{pairs}]"


def _state(state: MetricState) -> str:
    match state:
        case CounterState():
            return f"[count: [{js_number(state.count)}]]"
        case FrequencyState():
            return f"[occurrences: {_pairs(state.occurrences.items())}]"
        case GaugeState():
            return f"[value: [{js_number(state.value)}]]"
        case HistogramState():
            buckets = _pairs(state.buckets)
            rest = _totals(state.count, state.min, state.max, state.sum)
            return f"[buckets: [{buckets}], {rest}]"
        case _:
            quantiles = _pairs((q, 0 if v is None else v) for q, v in state.quantiles)
            rest = _totals(state.count, state.min, state.max, state.sum)
            return f"[quantiles: [{quantiles}], {rest}]"


def _totals(count: int, low: float, high: float, total: float) -> str:
    return (
        f"count: [{count}], min: [{js_number(low)}], max: [{js_number(high)}], "
        f"sum: [{js_number(total)}]"
    )


def _pairs(pairs: Iterable[tuple[float | str, float]]) -> str:
    return ", ".join(f"({_text(k)} -> {js_number(v)})" for k, v in pairs)


def _text(key: float | str) -> str:
    return key if isinstance(key, str) else js_number(key)
