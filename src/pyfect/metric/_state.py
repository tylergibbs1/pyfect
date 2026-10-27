"""What a metric holds: one state class per kind, and the snapshot of a
series."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from typing import Generic, Literal, TypeVar

N_co = TypeVar("N_co", bound=float, covariant=True)

type MetricType = Literal["Counter", "Frequency", "Gauge", "Histogram", "Summary"]


@dataclass(frozen=True, slots=True)
class CounterState(Generic[N_co]):
    """The running total. ``incremental`` counters ignore negative updates."""

    count: N_co
    incremental: bool


@dataclass(frozen=True, slots=True)
class GaugeState(Generic[N_co]):
    value: N_co


@dataclass(frozen=True, slots=True)
class FrequencyState:
    """How many times each word was seen, in first-seen order."""

    occurrences: Mapping[str, int]


@dataclass(frozen=True, slots=True)
class HistogramState:
    """``buckets`` pairs each boundary with how many values were at most
    that boundary (cumulative). ``min`` and ``max`` start at the largest
    finite float and its negation."""

    buckets: tuple[tuple[float, int], ...]
    count: int
    min: float
    max: float
    sum: float


@dataclass(frozen=True, slots=True)
class SummaryState:
    """Each quantile with its value over the observations within
    ``max_age``, or ``None`` when there are none."""

    quantiles: tuple[tuple[float, float | None], ...]
    count: int
    min: float
    max: float
    sum: float


type MetricState = (
    CounterState[float] | GaugeState[float] | FrequencyState | HistogramState | SummaryState
)


@dataclass(frozen=True, slots=True)
class Snapshot:
    """One series of the registry: the metric's identity, the attributes
    of the series (``None`` for a metric with none) and its state."""

    id: str
    type: MetricType
    description: str | None
    attributes: Mapping[str, str] | None
    state: MetricState
