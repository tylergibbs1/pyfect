"""The metric kinds: counter, gauge, frequency, histogram, summary and
timer, each a series with its own state."""

from __future__ import annotations

import math
import sys
from collections.abc import Iterable, Sequence
from typing import Any, Literal, overload

from pyfect.clock import Clock
from pyfect.context import Context
from pyfect.duration import Duration, nanos_or_infinite, to_millis, to_nanos, to_seconds
from pyfect.metric._boundaries import exponential_boundaries
from pyfect.metric._metric import Metric, Series, map_input_with_context
from pyfect.metric._refs import Attributes, Hooks, merge
from pyfect.metric._state import (
    CounterState,
    FrequencyState,
    GaugeState,
    HistogramState,
    SummaryState,
)

type Counter[N: float] = Metric[N, CounterState[N]]
type Gauge[N: float] = Metric[N, GaugeState[N]]
type Frequency = Metric[str, FrequencyState]
type Histogram[In] = Metric[In, HistogramState]
type Summary[In] = Metric[In, SummaryState]

# Effect's ``Number.MAX_VALUE``: where an empty histogram's or summary's
# ``min`` starts (``max`` starts at its negation).
_MAX_VALUE = sys.float_info.max


class _Counter(Series[Any, Any]):
    __slots__ = ("_incremental",)

    def __init__(
        self,
        id: str,
        description: str | None,
        attributes: Attributes | None,
        incremental: bool,
    ) -> None:
        super().__init__("Counter", id, description, attributes)
        self._incremental = incremental

    def _create_hooks(self) -> Hooks:
        incremental = self._incremental
        count: float = 0

        def get(_: Context) -> CounterState[float]:
            return CounterState(count, incremental)

        def update(value: float, _: Context) -> None:
            nonlocal count
            if not incremental or value >= 0:
                count += value

        return Hooks(get, update, update)


class _Gauge(Series[Any, Any]):
    __slots__ = ()

    def _create_hooks(self) -> Hooks:
        current: float = 0

        def get(_: Context) -> GaugeState[float]:
            return GaugeState(current)

        def update(value: float, _: Context) -> None:
            nonlocal current
            current = value

        def modify(value: float, _: Context) -> None:
            nonlocal current
            current += value

        return Hooks(get, update, modify)


class _Frequency(Series[Any, Any]):
    __slots__ = ("_preregistered",)

    def __init__(
        self,
        id: str,
        description: str | None,
        attributes: Attributes | None,
        preregistered: tuple[str, ...],
    ) -> None:
        super().__init__("Frequency", id, description, attributes)
        self._preregistered = preregistered

    def _create_hooks(self) -> Hooks:
        occurrences = dict.fromkeys(self._preregistered, 0)

        def get(_: Context) -> FrequencyState:
            return FrequencyState(dict(occurrences))

        def update(word: str, _: Context) -> None:
            occurrences[word] = occurrences.get(word, 0) + 1

        return Hooks(get, update, update)


class _Histogram(Series[Any, Any]):
    __slots__ = ("_boundaries",)

    def __init__(
        self,
        id: str,
        description: str | None,
        attributes: Attributes | None,
        boundaries: tuple[float, ...],
    ) -> None:
        super().__init__("Histogram", id, description, attributes)
        self._boundaries = boundaries

    def _create_hooks(self) -> Hooks:
        bounds = self._boundaries
        size = len(bounds)
        values = [0] * (size + 1)
        count = 0
        total: float = 0
        low = _MAX_VALUE
        high = -_MAX_VALUE

        def update(value: float, _: Context) -> None:
            nonlocal count, total, low, high
            values[_bucket(bounds, value)] += 1
            count += 1
            total += value
            low = min(low, value)
            high = max(high, value)

        def get(_: Context) -> HistogramState:
            buckets: list[tuple[float, int]] = []
            cumulated = 0
            for boundary, seen in zip(bounds, values, strict=False):
                cumulated += seen
                buckets.append((boundary, cumulated))
            return HistogramState(tuple(buckets), count, low, high, total)

        return Hooks(get, update, update)


def _bucket(bounds: tuple[float, ...], value: float) -> int:
    """The first boundary ``value`` is at most, as Effect's binary search
    finds it (NaN goes past every boundary)."""
    low, high = 0, len(bounds)
    while low != high:
        mid = low + (high - low) // 2
        if value <= bounds[mid]:
            high = mid
        else:
            low = mid
        if high == low + 1:
            if value <= bounds[low]:
                high = low
            else:
                low = high
    return low


class _Summary(Series[Any, Any]):
    """Observations are ``(value, wall-clock nanoseconds)``; a timestamp
    from ``summary_with_timestamp`` can also be NaN or infinite."""

    __slots__ = ("_max_age_ns", "_max_size", "_quantiles")

    def __init__(
        self,
        id: str,
        description: str | None,
        attributes: Attributes | None,
        *,
        max_age: Duration,
        max_size: int,
        quantiles: tuple[float, ...],
    ) -> None:
        super().__init__("Summary", id, description, attributes)
        age = max(to_seconds(max_age), 0.0)
        self._max_age_ns: float = nanos_or_infinite(age)
        self._max_size = max_size
        self._quantiles = tuple(sorted(quantiles))

    def _create_hooks(self) -> Hooks:
        max_age_ns, max_size, quantiles = self._max_age_ns, self._max_size, self._quantiles
        observations: list[tuple[float, float] | None] = [None] * max_size
        head = 0
        count = 0
        total: float = 0
        low = _MAX_VALUE
        high = -_MAX_VALUE

        def update(observation: tuple[float, float], _: Context) -> None:
            nonlocal head, count, total, low, high
            value, timestamp = observation
            if max_size > 0:
                observations[head % max_size] = (timestamp, value)
                head += 1
            count += 1
            total += value
            low = min(low, value)
            high = max(high, value)

        def get(context: Context) -> SummaryState:
            now = context.get_unsafe(Clock).now_nanos_unsafe()
            samples = sorted(
                observed[1]
                for observed in observations
                if observed is not None and 0 <= now - observed[0] <= max_age_ns
            )
            return SummaryState(
                tuple((q, _quantile(samples, q)) for q in quantiles), count, low, high, total
            )

        return Hooks(get, update, update)


def _quantile(samples: list[float], q: float) -> float | None:
    """The largest sample with at most ``q * n`` samples at or below it."""
    if not samples:
        return None
    if q <= 0:
        return samples[0]
    if q >= 1:
        return samples[-1]
    return samples[math.ceil(q * len(samples)) - 1]


@overload
def counter(
    name: str,
    *,
    description: str | None = None,
    attributes: Attributes | None = None,
    bigint: Literal[False] = False,
    incremental: bool = False,
) -> Counter[float]: ...
@overload
def counter(
    name: str,
    *,
    description: str | None = None,
    attributes: Attributes | None = None,
    bigint: Literal[True],
    incremental: bool = False,
) -> Counter[int]: ...
def counter(
    name: str,
    *,
    description: str | None = None,
    attributes: Attributes | None = None,
    bigint: bool = False,
    incremental: bool = False,
) -> Counter[Any]:
    """A running total: ``update`` adds. An ``incremental`` counter ignores
    negative updates. ``bigint=True`` types it as ``int`` (Effect's
    ``bigint``); either way a counter of ints stays exact."""
    del bigint  # only the type differs: Python ints never lose precision
    return _Counter(name, description, attributes, incremental)


@overload
def gauge(
    name: str,
    *,
    description: str | None = None,
    attributes: Attributes | None = None,
    bigint: Literal[False] = False,
) -> Gauge[float]: ...
@overload
def gauge(
    name: str,
    *,
    description: str | None = None,
    attributes: Attributes | None = None,
    bigint: Literal[True],
) -> Gauge[int]: ...
def gauge(
    name: str,
    *,
    description: str | None = None,
    attributes: Attributes | None = None,
    bigint: bool = False,
) -> Gauge[Any]:
    """The latest value: ``update`` sets it, ``modify`` adds to it."""
    del bigint
    return _Gauge("Gauge", name, description, attributes)


def frequency(
    name: str,
    *,
    description: str | None = None,
    attributes: Attributes | None = None,
    preregistered_words: Iterable[str] = (),
) -> Frequency:
    """How often each word is seen. ``preregistered_words`` start at 0."""
    return _Frequency(name, description, attributes, tuple(preregistered_words))


def histogram(
    name: str,
    *,
    boundaries: Iterable[float],
    description: str | None = None,
    attributes: Attributes | None = None,
) -> Histogram[float]:
    """Values counted into buckets. The state reports one cumulative
    bucket per boundary (sorted); values past the last are only in
    ``count`` (end the boundaries with ``math.inf`` to see them, as the
    ``*_boundaries`` helpers do)."""
    return _Histogram(name, description, attributes, tuple(sorted(map(float, boundaries))))


def summary_with_timestamp(
    name: str,
    *,
    max_age: Duration,
    max_size: int,
    quantiles: Sequence[float],
    description: str | None = None,
    attributes: Attributes | None = None,
) -> Summary[tuple[float, float]]:
    """``summary`` updated with ``(value, timestamp)``, the timestamp in
    wall-clock seconds since the epoch."""
    inner = _summary(
        name,
        max_age=max_age,
        max_size=max_size,
        quantiles=quantiles,
        description=description,
        attributes=attributes,
    )
    return map_input_with_context(inner, lambda observation, _: _stamped(*observation))


def _stamped(value: float, timestamp: float) -> tuple[float, float]:
    """A timestamp in whole nanoseconds; NaN and the infinities stay as they
    are, so they age as in Effect (never in range, or always too old)."""
    return value, to_nanos(timestamp) if math.isfinite(timestamp) else timestamp


def summary(
    name: str,
    *,
    max_age: Duration,
    max_size: int,
    quantiles: Sequence[float],
    description: str | None = None,
    attributes: Attributes | None = None,
) -> Summary[float]:
    """Quantiles over the last ``max_size`` values seen within ``max_age``
    (by the ``Clock``'s wall time), with the count, min, max and sum of
    every value. Each quantile is between 0 and 1."""
    inner = _summary(
        name,
        max_age=max_age,
        max_size=max_size,
        quantiles=quantiles,
        description=description,
        attributes=attributes,
    )
    return map_input_with_context(
        inner, lambda value, context: (value, context.get_unsafe(Clock).now_nanos_unsafe())
    )


def _summary(
    name: str,
    *,
    max_age: Duration,
    max_size: int,
    quantiles: Sequence[float],
    description: str | None,
    attributes: Attributes | None,
) -> _Summary:
    for quantile in quantiles:
        if quantile < 0 or quantile > 1:
            raise ValueError(f"Quantile must be between 0 and 1, found: {quantile}")
    if max_size < 0:
        raise ValueError(f"max_size must be at least 0, got {max_size}")
    return _Summary(
        name,
        description,
        attributes,
        max_age=max_age,
        max_size=max_size,
        quantiles=tuple(quantiles),
    )


def timer(
    name: str,
    *,
    description: str | None = None,
    attributes: Attributes | None = None,
    boundaries: Iterable[float] | None = None,
) -> Histogram[Duration]:
    """A histogram of durations in milliseconds, with the attribute
    ``time_unit="milliseconds"``. The default boundaries double from 0.5ms,
    34 of them, then ``math.inf``.

    ``prometheus_format`` leaves ``time_unit`` out (as Effect does), so end
    the name in ``_milliseconds``: ``request_milliseconds``, not
    ``request_seconds``."""
    bounds = (
        exponential_boundaries(start=0.5, factor=2, count=35) if boundaries is None else boundaries
    )
    with_unit = merge(attributes, {"time_unit": "milliseconds"})
    return histogram(
        name, boundaries=bounds, description=description, attributes=with_unit
    ).map_input(to_millis)
