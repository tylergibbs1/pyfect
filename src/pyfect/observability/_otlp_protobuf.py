"""OTLP/protobuf encoding of traces, metrics and logs (Effect's
``observability/internal/otlpProtobuf``), field for field and in Effect's
field order, from the OTLP/JSON-shaped payloads.

Writes the messages of ``opentelemetry-proto`` with a
``pyfect.protobuf.writer.ProtobufWriter``. Each ``_write_*`` function writes
the fields of one message, whose definition its docstring gives, and
returns the writer, so nested messages chain:
``_write_status(w.tag(15, LEN).fork(), status).join()``.
"""

from __future__ import annotations

import binascii
from collections.abc import Callable, Mapping, Sequence
from typing import Any

from pyfect._js import trim_start
from pyfect.protobuf.writer import ProtobufWriter, WireType

type Message = Mapping[str, Any]
type _Write = Callable[[ProtobufWriter, Message], ProtobufWriter]

VARINT = WireType.Varint
I64 = WireType.I64
LEN = WireType.Len
I32 = WireType.I32

_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _parse_hex_pair(pair: str) -> int:
    """``parseInt(pair, 16)`` stored in a ``Uint8Array``: the leading hex
    digits after leading space and an optional sign, wrapped to a byte;
    ``NaN`` is 0."""
    pair = trim_start(pair)
    sign = -1 if pair[:1] == "-" else 1
    digits = pair[1:] if pair[:1] in "+-" else pair
    run = ""
    for char in digits:
        if char not in _HEX_DIGITS:
            break
        run += char
    return sign * int(run, 16) % 256 if run else 0


def _hex_bytes(hex_text: str) -> bytes:
    """The bytes of a hex id. An id that is not valid hex is read pair by
    pair with ``parseInt``, and a trailing odd character is ignored."""
    if len(hex_text) % 2 == 0 and all(char in _HEX_DIGITS for char in hex_text):
        return binascii.unhexlify(hex_text)
    return bytes(_parse_hex_pair(hex_text[i : i + 2]) for i in range(0, len(hex_text) - 1, 2))


def _id_bytes(value: str | bytes) -> bytes:
    """A log record id: a hex string or the bytes themselves."""
    return _hex_bytes(value) if isinstance(value, str) else value


def _present(message: Message, key: str) -> bool:
    return message.get(key) is not None


def _each(w: ProtobufWriter, field_number: int, items: Sequence[Message], write: _Write) -> None:
    for item in items:
        write(w.tag(field_number, LEN).fork(), item).join()


# Common types (opentelemetry.proto.common.v1)


def _write_any_value(w: ProtobufWriter, value: Message) -> ProtobufWriter:
    """``message AnyValue { oneof value { string string_value = 1; bool
    bool_value = 2; int64 int_value = 3; double double_value = 4; ArrayValue
    array_value = 5; KeyValueList kvlist_value = 6; bytes bytes_value = 7; } }``"""
    if _present(value, "stringValue"):
        w.tag(1, LEN).string(value["stringValue"])
    elif _present(value, "boolValue"):
        w.tag(2, VARINT).bool(value["boolValue"])
    elif _present(value, "intValue"):
        w.tag(3, VARINT).int64(value["intValue"])
    elif _present(value, "doubleValue"):
        w.tag(4, I64).double(value["doubleValue"])
    elif "arrayValue" in value:
        _each(w.tag(5, LEN).fork(), 1, value["arrayValue"]["values"], _write_any_value)
        w.join()
    elif "kvlistValue" in value:
        _each(w.tag(6, LEN).fork(), 1, value["kvlistValue"]["values"], _write_key_value)
        w.join()
    elif "bytesValue" in value:
        w.tag(7, LEN).bytes(bytes(value["bytesValue"]))
    return w


def encode_any_value(value: Message) -> bytes:
    """An ``AnyValue`` on its own."""
    return _write_any_value(ProtobufWriter(), value).finish()


def _write_key_value(w: ProtobufWriter, kv: Message) -> ProtobufWriter:
    """``message KeyValue { string key = 1; AnyValue value = 2; }``"""
    w.tag(1, LEN).string(kv["key"])
    return _write_any_value(w.tag(2, LEN).fork(), kv["value"]).join()


def _write_instrumentation_scope(w: ProtobufWriter, scope: Message) -> ProtobufWriter:
    """``message InstrumentationScope { string name = 1; string version = 2;
    repeated KeyValue attributes = 3; uint32 dropped_attributes_count = 4; }``"""
    w.tag(1, LEN).string(scope["name"])
    if scope.get("version"):
        w.tag(2, LEN).string(scope["version"])
    attributes = scope.get("attributes")
    if attributes is not None:
        _each(w, 3, attributes, _write_key_value)
    if scope.get("droppedAttributesCount"):
        w.tag(4, VARINT).uint32(scope["droppedAttributesCount"])
    return w


def _count(w: ProtobufWriter, field_number: int, count: int | None) -> None:
    """A ``uint32`` dropped count, written only when positive."""
    if count is not None and count > 0:
        w.tag(field_number, VARINT).uint32(count)


# Resource types (opentelemetry.proto.resource.v1)


def _write_resource(w: ProtobufWriter, resource: Message) -> ProtobufWriter:
    """``message Resource { repeated KeyValue attributes = 1; uint32
    dropped_attributes_count = 2; }``"""
    _each(w, 1, resource["attributes"], _write_key_value)
    _count(w, 2, resource["droppedAttributesCount"])
    return w


# Trace types (opentelemetry.proto.trace.v1)


def _write_status(w: ProtobufWriter, status: Message) -> ProtobufWriter:
    """``message Status { string message = 2; StatusCode code = 3; }``"""
    if status.get("message"):
        w.tag(2, LEN).string(status["message"])
    return w.tag(3, VARINT).int32(status["code"])


def _write_event(w: ProtobufWriter, event: Message) -> ProtobufWriter:
    """``message Event { fixed64 time_unix_nano = 1; string name = 2; repeated
    KeyValue attributes = 3; uint32 dropped_attributes_count = 4; }``"""
    w.tag(1, I64).fixed64(event["timeUnixNano"])
    w.tag(2, LEN).string(event["name"])
    _each(w, 3, event["attributes"], _write_key_value)
    _count(w, 4, event["droppedAttributesCount"])
    return w


def _flags(w: ProtobufWriter, field_number: int, message: Message) -> None:
    if message.get("flags") is not None:
        w.tag(field_number, I32).fixed32(message["flags"])


def _write_link(w: ProtobufWriter, link: Message) -> ProtobufWriter:
    """``message Link { bytes trace_id = 1; bytes span_id = 2; string
    trace_state = 3; repeated KeyValue attributes = 4; uint32
    dropped_attributes_count = 5; fixed32 flags = 6; }``"""
    w.tag(1, LEN).bytes(_hex_bytes(link["traceId"]))
    w.tag(2, LEN).bytes(_hex_bytes(link["spanId"]))
    if link.get("traceState"):
        w.tag(3, LEN).string(link["traceState"])
    _each(w, 4, link["attributes"], _write_key_value)
    _count(w, 5, link["droppedAttributesCount"])
    _flags(w, 6, link)
    return w


def _write_span(w: ProtobufWriter, span: Message) -> ProtobufWriter:
    """``message Span``: ``bytes trace_id = 1; bytes span_id = 2; string
    trace_state = 3; bytes parent_span_id = 4; string name = 5; SpanKind kind
    = 6; fixed64 start_time_unix_nano = 7; fixed64 end_time_unix_nano = 8;
    repeated KeyValue attributes = 9; uint32 dropped_attributes_count = 10;
    repeated Event events = 11; uint32 dropped_events_count = 12; repeated
    Link links = 13; uint32 dropped_links_count = 14; Status status = 15;
    fixed32 flags = 16``."""
    w.tag(1, LEN).bytes(_hex_bytes(span["traceId"]))
    w.tag(2, LEN).bytes(_hex_bytes(span["spanId"]))
    if span.get("traceState"):
        w.tag(3, LEN).string(span["traceState"])
    if span.get("parentSpanId") is not None:
        w.tag(4, LEN).bytes(_hex_bytes(span["parentSpanId"]))
    w.tag(5, LEN).string(span["name"])
    w.tag(6, VARINT).int32(span["kind"])
    w.tag(7, I64).fixed64(span["startTimeUnixNano"])
    w.tag(8, I64).fixed64(span["endTimeUnixNano"])
    _each(w, 9, span["attributes"], _write_key_value)
    _count(w, 10, span["droppedAttributesCount"])
    _each(w, 11, span["events"], _write_event)
    _count(w, 12, span["droppedEventsCount"])
    _each(w, 13, span["links"], _write_link)
    _count(w, 14, span["droppedLinksCount"])
    _write_status(w.tag(15, LEN).fork(), span["status"]).join()
    _flags(w, 16, span)
    return w


def _scoped(items_key: str, write_item: _Write) -> _Write:
    """``message ScopeSpans`` / ``ScopeMetrics`` / ``ScopeLogs``:
    ``InstrumentationScope scope = 1; repeated ... = 2; string schema_url = 3``."""

    def write(w: ProtobufWriter, scoped: Message) -> ProtobufWriter:
        _write_instrumentation_scope(w.tag(1, LEN).fork(), scoped["scope"]).join()
        _each(w, 2, scoped[items_key], write_item)
        if scoped.get("schemaUrl"):
            w.tag(3, LEN).string(scoped["schemaUrl"])
        return w

    return write


def _resourced(scopes_key: str, write_scope: _Write) -> _Write:
    """``message ResourceSpans`` / ``ResourceMetrics`` / ``ResourceLogs``:
    ``Resource resource = 1; repeated ... = 2; string schema_url = 3``."""

    def write(w: ProtobufWriter, resourced: Message) -> ProtobufWriter:
        _write_resource(w.tag(1, LEN).fork(), resourced["resource"]).join()
        _each(w, 2, resourced[scopes_key], write_scope)
        if resourced.get("schemaUrl"):
            w.tag(3, LEN).string(resourced["schemaUrl"])
        return w

    return write


def _encode(items: Sequence[Message], write: _Write) -> bytes:
    w = ProtobufWriter()
    _each(w, 1, items, write)
    return w.finish()


_write_resource_spans = _resourced("scopeSpans", _scoped("spans", _write_span))


def encode_traces_data(data: Message) -> bytes:
    """``message TracesData { repeated ResourceSpans resource_spans = 1; }``,
    the body of a traces export."""
    return _encode(data["resourceSpans"], _write_resource_spans)


# Metric types (opentelemetry.proto.metrics.v1)


def _times(w: ProtobufWriter, point: Message) -> None:
    """A data point's start time (omitted when absent) and time."""
    if point.get("startTimeUnixNano") is not None:
        w.tag(2, I64).fixed64(point["startTimeUnixNano"])
    w.tag(3, I64).fixed64(point["timeUnixNano"])


def _double(w: ProtobufWriter, field_number: int, message: Message, key: str) -> None:
    if message.get(key) is not None:
        w.tag(field_number, I64).double(message[key])


def _varint_flags(w: ProtobufWriter, field_number: int, message: Message) -> None:
    if message.get("flags") is not None:
        w.tag(field_number, VARINT).uint32(message["flags"])


def _write_number_data_point(w: ProtobufWriter, point: Message) -> ProtobufWriter:
    """``message NumberDataPoint { repeated KeyValue attributes = 7; fixed64
    start_time_unix_nano = 2; fixed64 time_unix_nano = 3; oneof value { double
    as_double = 4; sfixed64 as_int = 6; } uint32 flags = 8; }``"""
    _times(w, point)
    _double(w, 4, point, "asDouble")
    if point.get("asInt") is not None:
        w.tag(6, I64).fixed64(point["asInt"])
    _each(w, 7, point["attributes"], _write_key_value)
    _varint_flags(w, 8, point)
    return w


def _write_histogram_data_point(w: ProtobufWriter, point: Message) -> ProtobufWriter:
    """``message HistogramDataPoint { repeated KeyValue attributes = 9; fixed64
    start_time_unix_nano = 2; fixed64 time_unix_nano = 3; fixed64 count = 4;
    optional double sum = 5; repeated fixed64 bucket_counts = 6; repeated
    double explicit_bounds = 7; optional double min = 11; optional double max
    = 12; uint32 flags = 10; }``. Bucket counts and bounds are written
    unpacked, one field per value, as Effect writes them."""
    _times(w, point)
    w.tag(4, I64).fixed64(point["count"])
    _double(w, 5, point, "sum")
    for count in point["bucketCounts"]:
        w.tag(6, I64).fixed64(count)
    for bound in point["explicitBounds"]:
        w.tag(7, I64).double(bound)
    _each(w, 9, point["attributes"], _write_key_value)
    _varint_flags(w, 10, point)
    _double(w, 11, point, "min")
    _double(w, 12, point, "max")
    return w


def _write_value_at_quantile(w: ProtobufWriter, value: Message) -> ProtobufWriter:
    """``message ValueAtQuantile { double quantile = 1; double value = 2; }``"""
    return w.tag(1, I64).double(value["quantile"]).tag(2, I64).double(value["value"])


def _write_summary_data_point(w: ProtobufWriter, point: Message) -> ProtobufWriter:
    """``message SummaryDataPoint { repeated KeyValue attributes = 7; fixed64
    start_time_unix_nano = 2; fixed64 time_unix_nano = 3; fixed64 count = 4;
    double sum = 5; repeated ValueAtQuantile quantile_values = 6; uint32 flags
    = 8; }``"""
    _times(w, point)
    w.tag(4, I64).fixed64(point["count"])
    w.tag(5, I64).double(point["sum"])
    _each(w, 6, point["quantileValues"], _write_value_at_quantile)
    _each(w, 7, point["attributes"], _write_key_value)
    _varint_flags(w, 8, point)
    return w


def _write_gauge(w: ProtobufWriter, gauge: Message) -> ProtobufWriter:
    """``message Gauge { repeated NumberDataPoint data_points = 1; }``"""
    _each(w, 1, gauge["dataPoints"], _write_number_data_point)
    return w


def _write_sum(w: ProtobufWriter, sum: Message) -> ProtobufWriter:
    """``message Sum { repeated NumberDataPoint data_points = 1;
    AggregationTemporality aggregation_temporality = 2; bool is_monotonic = 3; }``"""
    _each(w, 1, sum["dataPoints"], _write_number_data_point)
    w.tag(2, VARINT).int32(sum["aggregationTemporality"])
    return w.tag(3, VARINT).bool(sum["isMonotonic"])


def _write_histogram(w: ProtobufWriter, histogram: Message) -> ProtobufWriter:
    """``message Histogram { repeated HistogramDataPoint data_points = 1;
    AggregationTemporality aggregation_temporality = 2; }``"""
    _each(w, 1, histogram["dataPoints"], _write_histogram_data_point)
    return w.tag(2, VARINT).int32(histogram["aggregationTemporality"])


def _write_summary(w: ProtobufWriter, summary: Message) -> ProtobufWriter:
    """``message Summary { repeated SummaryDataPoint data_points = 1; }``"""
    _each(w, 1, summary["dataPoints"], _write_summary_data_point)
    return w


_METRIC_DATA: tuple[tuple[int, str, _Write], ...] = (
    (5, "gauge", _write_gauge),
    (7, "sum", _write_sum),
    (9, "histogram", _write_histogram),
    (11, "summary", _write_summary),
)


def _write_metric(w: ProtobufWriter, metric: Message) -> ProtobufWriter:
    """``message Metric { string name = 1; string description = 2; string unit
    = 3; oneof data { Gauge gauge = 5; Sum sum = 7; Histogram histogram = 9;
    Summary summary = 11; } }``"""
    w.tag(1, LEN).string(metric["name"])
    if metric.get("description"):
        w.tag(2, LEN).string(metric["description"])
    if metric.get("unit"):
        w.tag(3, LEN).string(metric["unit"])
    for field_number, key, write in _METRIC_DATA:
        if metric.get(key) is not None:
            write(w.tag(field_number, LEN).fork(), metric[key]).join()
    return w


_write_resource_metrics = _resourced("scopeMetrics", _scoped("metrics", _write_metric))


def encode_metrics_data(data: Message) -> bytes:
    """``message MetricsData { repeated ResourceMetrics resource_metrics = 1; }``,
    the body of a metrics export."""
    return _encode(data["resourceMetrics"], _write_resource_metrics)


# Log types (opentelemetry.proto.logs.v1)


def _write_log_record(w: ProtobufWriter, record: Message) -> ProtobufWriter:
    """``message LogRecord { fixed64 time_unix_nano = 1; fixed64
    observed_time_unix_nano = 11; SeverityNumber severity_number = 2; string
    severity_text = 3; AnyValue body = 5; repeated KeyValue attributes = 6;
    uint32 dropped_attributes_count = 7; fixed32 flags = 8; bytes trace_id =
    9; bytes span_id = 10; }``"""
    w.tag(1, I64).fixed64(record["timeUnixNano"])
    if record.get("severityNumber") is not None:
        w.tag(2, VARINT).int32(record["severityNumber"])
    if record.get("severityText"):
        w.tag(3, LEN).string(record["severityText"])
    if record.get("body") is not None:
        _write_any_value(w.tag(5, LEN).fork(), record["body"]).join()
    _each(w, 6, record["attributes"], _write_key_value)
    _count(w, 7, record.get("droppedAttributesCount"))
    _flags(w, 8, record)
    if record.get("traceId"):
        w.tag(9, LEN).bytes(_id_bytes(record["traceId"]))
    if record.get("spanId"):
        w.tag(10, LEN).bytes(_id_bytes(record["spanId"]))
    if record.get("observedTimeUnixNano") is not None:
        w.tag(11, I64).fixed64(record["observedTimeUnixNano"])
    return w


_write_resource_logs = _resourced("scopeLogs", _scoped("logRecords", _write_log_record))


def encode_logs_data(data: Message) -> bytes:
    """``message LogsData { repeated ResourceLogs resource_logs = 1; }``, the
    body of a logs export."""
    return _encode(data["resourceLogs"], _write_resource_logs)
