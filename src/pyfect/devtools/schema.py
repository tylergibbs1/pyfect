"""The messages between an app and the Effect DevTools (Effect's
``devtools/DevToolsSchema``).

The app sends ``Request``\\s (``Ping``, ``Span`` snapshots, ``SpanEvent``\\s,
``MetricsSnapshot``\\s); the DevTools answer ``Response``\\s (``Pong``,
``MetricsRequest``). Both are newline-delimited JSON of ``REQUEST_CODEC``
and ``RESPONSE_CODEC``. Optional fields (Effect's ``UndefinedOr``) are
``None``.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any, Literal, TypedDict

from pyfect import schema as S
from pyfect.exit import Exit
from pyfect.option import Option

__all__ = [
    "REQUEST_CODEC",
    "RESPONSE_CODEC",
    "Counter",
    "CounterState",
    "ExternalSpan",
    "Frequency",
    "FrequencyState",
    "Gauge",
    "GaugeState",
    "Histogram",
    "HistogramState",
    "Metric",
    "MetricLabel",
    "MetricsRequest",
    "MetricsSnapshot",
    "ParentSpan",
    "Ping",
    "Pong",
    "Request",
    "Response",
    "Span",
    "SpanEvent",
    "SpanStatus",
    "SpanStatusEnded",
    "SpanStatusStarted",
    "Summary",
    "SummaryState",
    "counter",
    "external_span",
    "frequency",
    "gauge",
    "histogram",
    "metric",
    "metrics_request",
    "metrics_snapshot",
    "parent_span",
    "ping",
    "pong",
    "request",
    "response",
    "span",
    "span_event",
    "span_status",
    "span_status_ended",
    "span_status_started",
    "summary",
]


class SpanStatusStarted(TypedDict):
    _tag: Literal["Started"]
    startTime: int


class SpanStatusEnded(TypedDict):
    _tag: Literal["Ended"]
    startTime: int
    endTime: int
    exit: Exit[None, object]


type SpanStatus = SpanStatusStarted | SpanStatusEnded

_DEFECT = S.Defect(include_stack=True)

span_status_started = S.TaggedStruct(SpanStatusStarted, startTime=S.BigInt)
span_status_ended = S.TaggedStruct(
    SpanStatusEnded,
    startTime=S.BigInt,
    endTime=S.BigInt,
    exit=S.Exit(S.Null, _DEFECT, _DEFECT),
)
span_status = S.Union(span_status_started, span_status_ended)


class ExternalSpan(TypedDict):
    _tag: Literal["ExternalSpan"]
    spanId: str
    traceId: str
    sampled: bool


class Span(TypedDict):
    _tag: Literal["Span"]
    spanId: str
    traceId: str
    name: str
    sampled: bool
    attributes: Mapping[str, object]
    status: SpanStatus
    parent: Option[ParentSpan]


type ParentSpan = Span | ExternalSpan

external_span = S.TaggedStruct(ExternalSpan)


def _parent_span() -> S.Codec[Any, Any, Any, Any]:
    return parent_span


span: S.Codec[Span, Any, Any, Any] = S.TaggedStruct(
    Span,
    attributes=S.Map(S.String, S.Any),
    status=span_status,
    parent=S.Option(S.suspend(_parent_span)),
)
parent_span: S.Codec[ParentSpan, Any, Any, Any] = S.Union(span, external_span)


class SpanEvent(TypedDict):
    _tag: Literal["SpanEvent"]
    traceId: str
    spanId: str
    name: str
    startTime: int
    attributes: Mapping[str, object] | None


span_event = S.TaggedStruct(
    SpanEvent, startTime=S.BigInt, attributes=S.NullOr(S.Record(S.String, S.Any))
)


class Ping(TypedDict):
    _tag: Literal["Ping"]


class Pong(TypedDict):
    _tag: Literal["Pong"]


class MetricsRequest(TypedDict):
    _tag: Literal["MetricsRequest"]


ping = S.TaggedStruct(Ping)
pong = S.TaggedStruct(Pong)
metrics_request = S.TaggedStruct(MetricsRequest)


class MetricLabel(TypedDict):
    key: str
    value: str


class CounterState(TypedDict):
    count: float
    incremental: bool


class FrequencyState(TypedDict):
    occurrences: Mapping[str, int]


class GaugeState(TypedDict):
    value: float


class HistogramState(TypedDict):
    buckets: tuple[tuple[float, int], ...]
    count: int
    min: float
    max: float
    sum: float


class SummaryState(TypedDict):
    quantiles: tuple[tuple[float, float | None], ...]
    count: int
    min: float
    max: float
    sum: float


class Counter(TypedDict):
    id: str
    type: Literal["Counter"]
    description: str | None
    attributes: Mapping[str, str] | None
    state: CounterState


class Frequency(TypedDict):
    id: str
    type: Literal["Frequency"]
    description: str | None
    attributes: Mapping[str, str] | None
    state: FrequencyState


class Gauge(TypedDict):
    id: str
    type: Literal["Gauge"]
    description: str | None
    attributes: Mapping[str, str] | None
    state: GaugeState


class Histogram(TypedDict):
    id: str
    type: Literal["Histogram"]
    description: str | None
    attributes: Mapping[str, str] | None
    state: HistogramState


class Summary(TypedDict):
    id: str
    type: Literal["Summary"]
    description: str | None
    attributes: Mapping[str, str] | None
    state: SummaryState


type Metric = Counter | Frequency | Gauge | Histogram | Summary

_NUMBER = S.Union(S.Number, S.BigInt)
_ATTRIBUTES = S.NullOr(S.Record(S.String, S.String))
_DESCRIPTION = S.NullOr(S.String)
_QUANTILE = S.Finite.check(S.is_between(minimum=0, maximum=1))


def _metric(
    typed_dict: type[Any], kind: S.Codec[Any, Any, Any, Any], state: S.Codec[Any, Any, Any, Any]
) -> Any:
    return S.Struct(
        typed_dict,
        type=kind,
        description=_DESCRIPTION,
        attributes=_ATTRIBUTES,
        state=state,
    )


counter = _metric(Counter, S.Literal("Counter"), S.Struct(CounterState, count=_NUMBER))
frequency = _metric(
    Frequency,
    S.Literal("Frequency"),
    S.Struct(FrequencyState, occurrences=S.Map(S.String, S.Natural)),
)
gauge = _metric(Gauge, S.Literal("Gauge"), S.Struct(GaugeState, value=_NUMBER))
histogram = _metric(
    Histogram,
    S.Literal("Histogram"),
    S.Struct(
        HistogramState,
        buckets=S.Array(S.Tuple(S.Number, S.Natural)),
        count=S.Natural,
    ),
)
summary = _metric(
    Summary,
    S.Literal("Summary"),
    S.Struct(
        SummaryState,
        quantiles=S.Array(S.Tuple(_QUANTILE, S.NullOr(S.Number))),
        count=S.Natural,
    ),
)
metric: S.Codec[Metric, Any, Any, Any] = S.Union(counter, frequency, gauge, histogram, summary)


class MetricsSnapshot(TypedDict):
    _tag: Literal["MetricsSnapshot"]
    metrics: tuple[Metric, ...]


metrics_snapshot = S.TaggedStruct(MetricsSnapshot, metrics=S.Array(metric))

type Request = Ping | Span | SpanEvent | MetricsSnapshot
type Response = Pong | MetricsRequest

request: S.Codec[Request, Any, Any, Any] = S.Union(ping, span, span_event, metrics_snapshot)
response: S.Codec[Response, Any, Any, Any] = S.Union(pong, metrics_request)

REQUEST_CODEC = S.to_codec_json(request)
"""``Request`` as JSON values (Effect's ``toCodecJson(Request)``)."""
RESPONSE_CODEC = S.to_codec_json(response)
"""``Response`` as JSON values."""
