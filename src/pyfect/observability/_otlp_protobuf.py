"""OTLP/protobuf encoding of traces, metrics and logs (Effect's
``observability/internal/otlpProtobuf``), field for field and in Effect's
field order, from the OTLP/JSON-shaped payloads.

The message definitions are those of ``opentelemetry-proto``; each
encoder's docstring names its message.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from pyfect.observability._protobuf import (
    bool_field,
    bytes_field_from_hex,
    double_field,
    fixed32_field,
    fixed64_field,
    length_delimited_field,
    message_field,
    optional_string_field,
    repeated_field,
    string_field,
    varint_field,
)

type Message = Mapping[str, Any]


def _present(message: Message, key: str) -> bool:
    return message.get(key) is not None


def encode_any_value(value: Message) -> bytes:  # noqa: PLR0911
    """``AnyValue``: the first field set, in the order string, bool, int,
    double, array, key/value list, bytes; nothing when none is."""
    if _present(value, "stringValue"):
        return string_field(1, value["stringValue"])
    if _present(value, "boolValue"):
        return bool_field(2, value["boolValue"])
    if _present(value, "intValue"):
        return varint_field(3, int(value["intValue"]))
    if _present(value, "doubleValue"):
        return double_field(4, value["doubleValue"])
    if "arrayValue" in value:
        return message_field(5, encode_array_value(value["arrayValue"]))
    if "kvlistValue" in value:
        return message_field(6, encode_key_value_list(value["kvlistValue"]))
    if "bytesValue" in value:
        return length_delimited_field(7, bytes(value["bytesValue"]))
    return b""


def encode_array_value(value: Message) -> bytes:
    """``ArrayValue``."""
    return repeated_field(1, value["values"], encode_any_value)


def encode_key_value_list(value: Message) -> bytes:
    """``KeyValueList``."""
    return repeated_field(1, value["values"], encode_key_value)


def encode_key_value(kv: Message) -> bytes:
    """``KeyValue``."""
    return string_field(1, kv["key"]) + message_field(2, encode_any_value(kv["value"]))


def _attributes(field_number: int, attributes: Sequence[Message]) -> bytes:
    return repeated_field(field_number, attributes, encode_key_value)


def _count(field_number: int, count: int | None) -> bytes:
    """A ``uint32`` dropped count, written only when positive."""
    return varint_field(field_number, count) if count is not None and count > 0 else b""


def encode_instrumentation_scope(scope: Message) -> bytes:
    """``InstrumentationScope``."""
    attributes = scope.get("attributes")
    dropped = scope.get("droppedAttributesCount")
    return (
        string_field(1, scope["name"])
        + optional_string_field(2, scope.get("version"))
        + (_attributes(3, attributes) if attributes is not None else b"")
        + (varint_field(4, dropped) if dropped else b"")
    )


def encode_resource(resource: Message) -> bytes:
    """``Resource``."""
    return _attributes(1, resource["attributes"]) + _count(2, resource["droppedAttributesCount"])


def encode_status(status: Message) -> bytes:
    """``Status``."""
    return optional_string_field(2, status.get("message")) + varint_field(3, status["code"])


def encode_event(event: Message) -> bytes:
    """``Span.Event``."""
    return (
        fixed64_field(1, int(event["timeUnixNano"]))
        + string_field(2, event["name"])
        + _attributes(3, event["attributes"])
        + _count(4, event["droppedAttributesCount"])
    )


def _flags(field_number: int, message: Message) -> bytes:
    flags = message.get("flags")
    return fixed32_field(field_number, flags) if flags is not None else b""


def encode_link(link: Message) -> bytes:
    """``Span.Link``."""
    return (
        bytes_field_from_hex(1, link["traceId"])
        + bytes_field_from_hex(2, link["spanId"])
        + optional_string_field(3, link.get("traceState"))
        + _attributes(4, link["attributes"])
        + _count(5, link["droppedAttributesCount"])
        + _flags(6, link)
    )


def encode_span(span: Message) -> bytes:
    """``Span``."""
    parent = span.get("parentSpanId")
    return (
        bytes_field_from_hex(1, span["traceId"])
        + bytes_field_from_hex(2, span["spanId"])
        + optional_string_field(3, span.get("traceState"))
        + (bytes_field_from_hex(4, parent) if parent is not None else b"")
        + string_field(5, span["name"])
        + varint_field(6, span["kind"])
        + fixed64_field(7, int(span["startTimeUnixNano"]))
        + fixed64_field(8, int(span["endTimeUnixNano"]))
        + _attributes(9, span["attributes"])
        + _count(10, span["droppedAttributesCount"])
        + repeated_field(11, span["events"], encode_event)
        + _count(12, span["droppedEventsCount"])
        + repeated_field(13, span["links"], encode_link)
        + _count(14, span["droppedLinksCount"])
        + message_field(15, encode_status(span["status"]))
        + _flags(16, span)
    )


def _scoped(scoped: Message, items_key: str, encode_item: Any) -> bytes:
    """``ScopeSpans`` / ``ScopeMetrics`` / ``ScopeLogs``."""
    return (
        message_field(1, encode_instrumentation_scope(scoped["scope"]))
        + repeated_field(2, scoped[items_key], encode_item)
        + optional_string_field(3, scoped.get("schemaUrl"))
    )


def _resourced(resourced: Message, scopes_key: str, encode_scope: Any) -> bytes:
    """``ResourceSpans`` / ``ResourceMetrics`` / ``ResourceLogs``."""
    return (
        message_field(1, encode_resource(resourced["resource"]))
        + repeated_field(2, resourced[scopes_key], encode_scope)
        + optional_string_field(3, resourced.get("schemaUrl"))
    )


def encode_scope_spans(scope_spans: Message) -> bytes:
    return _scoped(scope_spans, "spans", encode_span)


def encode_resource_spans(resource_spans: Message) -> bytes:
    return _resourced(resource_spans, "scopeSpans", encode_scope_spans)


def encode_traces_data(data: Message) -> bytes:
    """``TracesData``, the body of a traces export."""
    return repeated_field(1, data["resourceSpans"], encode_resource_spans)


def _times(point: Message) -> bytes:
    """A data point's start time (omitted when absent) and time."""
    start = point.get("startTimeUnixNano")
    return (b"" if start is None else fixed64_field(2, int(start))) + fixed64_field(
        3, int(point["timeUnixNano"])
    )


def _varint_flags(field_number: int, message: Message) -> bytes:
    flags = message.get("flags")
    return varint_field(field_number, flags) if flags is not None else b""


def _optional_double(field_number: int, message: Message, key: str) -> bytes:
    return double_field(field_number, message[key]) if message.get(key) is not None else b""


def encode_number_data_point(point: Message) -> bytes:
    """``NumberDataPoint``."""
    as_int = point.get("asInt")
    return (
        _times(point)
        + _optional_double(4, point, "asDouble")
        + (fixed64_field(6, int(as_int)) if as_int is not None else b"")
        + _attributes(7, point["attributes"])
        + _varint_flags(8, point)
    )


def encode_histogram_data_point(point: Message) -> bytes:
    """``HistogramDataPoint``; bucket counts and bounds unpacked, as
    Effect writes them."""
    return (
        _times(point)
        + fixed64_field(4, int(point["count"]))
        + _optional_double(5, point, "sum")
        + b"".join(fixed64_field(6, int(count)) for count in point["bucketCounts"])
        + b"".join(double_field(7, bound) for bound in point["explicitBounds"])
        + _attributes(9, point["attributes"])
        + _varint_flags(10, point)
        + _optional_double(11, point, "min")
        + _optional_double(12, point, "max")
    )


def _value_at_quantile(value: Message) -> bytes:
    return double_field(1, value["quantile"]) + double_field(2, value["value"])


def encode_summary_data_point(point: Message) -> bytes:
    """``SummaryDataPoint``."""
    return (
        _times(point)
        + fixed64_field(4, int(point["count"]))
        + double_field(5, point["sum"])
        + repeated_field(6, point["quantileValues"], _value_at_quantile)
        + _attributes(7, point["attributes"])
        + _varint_flags(8, point)
    )


def encode_gauge(gauge: Message) -> bytes:
    return repeated_field(1, gauge["dataPoints"], encode_number_data_point)


def encode_sum(sum: Message) -> bytes:
    return (
        repeated_field(1, sum["dataPoints"], encode_number_data_point)
        + varint_field(2, sum["aggregationTemporality"])
        + bool_field(3, sum["isMonotonic"])
    )


def encode_histogram(histogram: Message) -> bytes:
    return repeated_field(1, histogram["dataPoints"], encode_histogram_data_point) + varint_field(
        2, histogram["aggregationTemporality"]
    )


def encode_summary(summary: Message) -> bytes:
    return repeated_field(1, summary["dataPoints"], encode_summary_data_point)


def encode_metric(metric: Message) -> bytes:
    """``Metric``: one of gauge, sum, histogram or summary."""
    data = b""
    for field_number, key, encode in (
        (5, "gauge", encode_gauge),
        (7, "sum", encode_sum),
        (9, "histogram", encode_histogram),
        (11, "summary", encode_summary),
    ):
        if key in metric:
            data += message_field(field_number, encode(metric[key]))
    return (
        string_field(1, metric["name"])
        + optional_string_field(2, metric.get("description"))
        + optional_string_field(3, metric.get("unit"))
        + data
    )


def encode_scope_metrics(scope_metrics: Message) -> bytes:
    return _scoped(scope_metrics, "metrics", encode_metric)


def encode_resource_metrics(resource_metrics: Message) -> bytes:
    return _resourced(resource_metrics, "scopeMetrics", encode_scope_metrics)


def encode_metrics_data(data: Message) -> bytes:
    """``MetricsData``, the body of a metrics export."""
    return repeated_field(1, data["resourceMetrics"], encode_resource_metrics)


def encode_log_record(record: Message) -> bytes:
    """``LogRecord``."""
    severity = record.get("severityNumber")
    body = record.get("body")
    trace_id = record.get("traceId")
    span_id = record.get("spanId")
    observed = record.get("observedTimeUnixNano")
    return (
        fixed64_field(1, int(record["timeUnixNano"]))
        + (varint_field(2, severity) if severity is not None else b"")
        + optional_string_field(3, record.get("severityText"))
        + (message_field(5, encode_any_value(body)) if body is not None else b"")
        + _attributes(6, record["attributes"])
        + _count(7, record.get("droppedAttributesCount"))
        + _flags(8, record)
        + (bytes_field_from_hex(9, trace_id) if trace_id else b"")
        + (bytes_field_from_hex(10, span_id) if span_id else b"")
        + (fixed64_field(11, int(observed)) if observed is not None else b"")
    )


def encode_scope_logs(scope_logs: Message) -> bytes:
    return _scoped(scope_logs, "logRecords", encode_log_record)


def encode_resource_logs(resource_logs: Message) -> bytes:
    return _resourced(resource_logs, "scopeLogs", encode_scope_logs)


def encode_logs_data(data: Message) -> bytes:
    """``LogsData``, the body of a logs export."""
    return repeated_field(1, data["resourceLogs"], encode_resource_logs)
