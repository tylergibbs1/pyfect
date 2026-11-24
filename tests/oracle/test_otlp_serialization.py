"""Ports of Effect's ``OtlpSerialization.test.ts``.

Each test's docstring is the Effect test title. A JavaScript number input
is a ``float`` and a ``bigint`` an ``int``. ``encodeAnyValue`` is the
internal ``_otlp_protobuf.encode_any_value``.
"""

from __future__ import annotations

import json
import math
import re
from typing import Any, Literal

import pytest

import pyfect as fx
from pyfect import layer
from pyfect.http.body import Bytes, HttpBody
from pyfect.layer import Layer
from pyfect.observability import otlp_serialization
from pyfect.observability._otlp_protobuf import encode_any_value
from pyfect.observability.otlp_resource import unknown_to_attribute_value
from pyfect.observability.otlp_serialization import OtlpSerialization, OtlpSerializationService

BOUNDARIES = [
    (-1.0, "-1", [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x01]),
    (
        float(-(2**63)),
        "-9223372036854775808",
        [0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x01],
    ),
    (
        float(9_223_372_036_854_774_784),
        "9223372036854774784",
        [0x80, 0xF8, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x7F],
    ),
    (
        -9_223_372_036_854_775_808,
        "-9223372036854775808",
        [0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x01],
    ),
    (
        9_223_372_036_854_775_807,
        "9223372036854775807",
        [0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x7F],
    ),
]

_LAYERS: dict[str, Layer[OtlpSerialization]] = {
    "json": otlp_serialization.layer_json,
    "protobuf": otlp_serialization.layer_protobuf,
}


def _with(serialization: Layer[OtlpSerialization]) -> OtlpSerializationService:
    return fx.run_sync(OtlpSerialization().pipe(layer.provide(serialization)))


def _bytes(body: HttpBody) -> Bytes:
    assert isinstance(body, Bytes)
    return body


@pytest.mark.parametrize("format", ["json", "protobuf"])
@pytest.mark.parametrize(("input", "decimal", "varint"), BOUNDARIES)
def test_preserves_int64_boundary(
    format: Literal["json", "protobuf"], input: float, decimal: str, varint: list[int]
) -> None:
    """${format} preserves int64 boundary $decimal ($input)"""
    serialization = _with(_LAYERS[format])
    attribute: Any = {"key": "v", "value": unknown_to_attribute_value(input)}
    body = _bytes(
        serialization.logs(
            {
                "resourceLogs": [
                    {
                        "resource": {"attributes": [attribute], "droppedAttributesCount": 0},
                        "scopeLogs": [],
                    }
                ]
            }
        )
    )
    if format == "json":
        found = re.search(r'"intValue":\s*(?:"(-?\d+)"|(-?\d+))(?=\s*[,}])', body.body.decode())
        assert found is not None
        assert (found[1] or found[2]) == decimal
    else:
        n = len(varint)
        header = [0x0A, n + 10, 0x0A, n + 8, 0x0A, n + 6, 0x0A, 0x01, 0x76, 0x12, n + 1, 0x18]
        assert list(body.body) == [*header, *varint]


def test_encodes_a_negative_protobuf_int64_as_a_ten_byte_varint() -> None:
    """encodes a negative protobuf int64 as a ten-byte varint"""
    encoded = encode_any_value({"intValue": -1})
    assert len(encoded) == 11
    assert list(encoded) == [0x18, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x01]


def test_layer_protobuf_encodes_summary_metrics() -> None:
    """layerProtobuf encodes Summary metrics"""
    serialization = _with(otlp_serialization.layer_protobuf)
    body = _bytes(
        serialization.metrics(
            {
                "resourceMetrics": [
                    {
                        "resource": {"attributes": [], "droppedAttributesCount": 0},
                        "scopeMetrics": [
                            {
                                "scope": {"name": "s"},
                                "metrics": [
                                    {
                                        "name": "s",
                                        "summary": {
                                            "dataPoints": [
                                                {
                                                    "attributes": [],
                                                    "startTimeUnixNano": "1",
                                                    "timeUnixNano": "2",
                                                    "count": 3,
                                                    "sum": 6,
                                                    "quantileValues": [
                                                        {"quantile": 0.5, "value": 2}
                                                    ],
                                                }
                                            ]
                                        },
                                    }
                                ],
                            }
                        ],
                    }
                ]
            }
        )
    )
    expected = [
        [0x0A, 0x4A],  # resource_metrics
        [0x0A, 0x00],  # resource
        [0x12, 0x46],  # scope_metrics
        [0x0A, 0x03, 0x0A, 0x01, 0x73],  # scope { name: "s" }
        [0x12, 0x3F],  # metrics
        [0x0A, 0x01, 0x73],  # name: "s"
        [0x5A, 0x3A],  # summary (field 11)
        [0x0A, 0x38],  # data_points
        [0x11, 0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],  # start_time_unix_nano: 1
        [0x19, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],  # time_unix_nano: 2
        [0x21, 0x03, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00],  # count: 3
        [0x29, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x18, 0x40],  # sum: 6.0
        [0x32, 0x12],  # quantile_values
        [0x09, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xE0, 0x3F],  # quantile: 0.5
        [0x11, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x40],  # value: 2.0
    ]
    assert list(body.body) == [byte for group in expected for byte in group]


def test_layer_json_preserves_json_values_and_writes_non_finite_doubles_as_strings() -> None:
    """layerJson preserves JSON values and writes non-finite doubles as strings for every signal"""
    serialization = _with(otlp_serialization.layer_json)
    values: list[float | None] = [math.nan, math.inf, -math.inf, 1.5, 0, None]
    resource: Any = {
        "attributes": [
            {
                "key": "values",
                "value": {"arrayValue": {"values": [{"doubleValue": v} for v in values]}},
            },
            {"key": "text", "value": {"stringValue": "null"}},
        ],
        "droppedAttributesCount": 0,
    }
    bodies = [
        (
            "resourceMetrics",
            serialization.metrics(
                {"resourceMetrics": [{"resource": resource, "scopeMetrics": []}]}
            ),
        ),
        (
            "resourceSpans",
            serialization.traces({"resourceSpans": [{"resource": resource, "scopeSpans": []}]}),
        ),
        (
            "resourceLogs",
            serialization.logs({"resourceLogs": [{"resource": resource, "scopeLogs": []}]}),
        ),
    ]
    for key, made in bodies:
        body = _bytes(made)
        assert body.content_type == "application/json"
        data = json.loads(body.body)
        written = ["NaN", "Infinity", "-Infinity", 1.5, 0, None]
        assert data[key][0]["resource"]["attributes"] == [
            {
                "key": "values",
                "value": {"arrayValue": {"values": [{"doubleValue": v} for v in written]}},
            },
            {"key": "text", "value": {"stringValue": "null"}},
        ]


def test_layer_protobuf_omits_absent_metric_start_timestamps() -> None:
    """layerProtobuf omits absent metric start timestamps"""
    serialization = _with(otlp_serialization.layer_protobuf)

    def point(**fields: object) -> dict[str, object]:
        return {"attributes": [], "timeUnixNano": "2", **fields}

    metrics: list[dict[str, Any]] = [
        {"name": "g", "gauge": {"dataPoints": [point(asInt=1)]}},
        {
            "name": "h",
            "histogram": {
                "dataPoints": [point(count=1, bucketCounts=[1], explicitBounds=[])],
                "aggregationTemporality": 2,
            },
        },
        {"name": "s", "summary": {"dataPoints": [point(count=1, sum=1, quantileValues=[])]}},
    ]
    body = _bytes(
        serialization.metrics(
            {
                "resourceMetrics": [
                    {
                        "resource": {"attributes": [], "droppedAttributesCount": 0},
                        "scopeMetrics": [{"scope": {"name": "s"}, "metrics": metrics}],
                    }
                ]
            }
        )
    )
    time = [0x19, 0x02, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]  # time_unix_nano: 2
    one = [0x01, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00]
    expected = [
        [0x0A, 0x6E],  # resource_metrics
        [0x0A, 0x00],  # resource
        [0x12, 0x6A],  # scope_metrics
        [0x0A, 0x03, 0x0A, 0x01, 0x73],  # scope { name: "s" }
        [0x12, 0x19, 0x0A, 0x01, 0x67],  # metrics { name: "g" }
        [0x2A, 0x14, 0x0A, 0x12],  # gauge.data_points
        [*time, 0x31, *one],  # as_int: 1
        [0x12, 0x24, 0x0A, 0x01, 0x68],  # metrics { name: "h" }
        [0x4A, 0x1F, 0x0A, 0x1B],  # histogram.data_points
        [*time, 0x21, *one, 0x31, *one],  # count: 1, bucket_counts: [1]
        [0x10, 0x02],  # aggregation_temporality: 2
        [0x12, 0x22, 0x0A, 0x01, 0x73],  # metrics { name: "s" }
        [0x5A, 0x1D, 0x0A, 0x1B],  # summary.data_points
        [*time, 0x21, *one, 0x29, 0x00, 0x00, 0x00, 0x00, 0x00, 0x00, 0xF0, 0x3F],  # sum: 1.0
    ]
    assert list(body.body) == [byte for group in expected for byte in group]


def _buffer(data: bytes) -> Any:
    """A mutable byte buffer, as Effect's test passes a Node ``Buffer``."""
    return bytearray(data)


def test_layer_json_writes_bytes_as_base64() -> None:
    """layerJson writes bytes as base64"""
    serialization = _with(otlp_serialization.layer_json)
    body = _bytes(
        serialization.traces(
            {
                "resourceSpans": [
                    {
                        "resource": {
                            "attributes": [
                                {
                                    "key": "slice",
                                    "value": {"bytesValue": bytes([9, 0, 255, 1])[1:]},
                                },
                                {
                                    "key": "buffer",
                                    "value": {"bytesValue": _buffer(b"\x00\xff\x01")},
                                },
                            ],
                            "droppedAttributesCount": 0,
                        },
                        "scopeSpans": [],
                    }
                ]
            }
        )
    )
    assert json.loads(body.body)["resourceSpans"][0]["resource"]["attributes"] == [
        {"key": "slice", "value": {"bytesValue": "AP8B"}},
        {"key": "buffer", "value": {"bytesValue": "AP8B"}},
    ]


def test_layer_protobuf_encodes_every_span_and_log_record_field() -> None:
    """layerProtobuf encodes every span and log record field"""
    serialization = _with(otlp_serialization.layer_protobuf)
    trace_id = "0102030405060708090a0b0c0d0e0f10"
    span_id = "1112131415161718"
    resource: Any = {"attributes": [], "droppedAttributesCount": 0}
    scope: Any = {"name": "s"}
    span: Any = {
        "traceId": trace_id,
        "spanId": span_id,
        "parentSpanId": "2122232425262728",
        "name": "op",
        "kind": 2,
        "startTimeUnixNano": "1",
        "endTimeUnixNano": "2",
        "attributes": [{"key": "a", "value": {"boolValue": True}}],
        "droppedAttributesCount": 1,
        "events": [
            {
                "timeUnixNano": "3",
                "name": "e",
                "attributes": [{"key": "b", "value": {"doubleValue": 0.5}}],
                "droppedAttributesCount": 2,
            }
        ],
        "droppedEventsCount": 3,
        "links": [
            {
                "traceId": "3132333435363738393a3b3c3d3e3f40",
                "spanId": "4142434445464748",
                "attributes": [
                    {"key": "c", "value": {"arrayValue": {"values": [{"stringValue": "s"}]}}}
                ],
                "droppedAttributesCount": 4,
            }
        ],
        "droppedLinksCount": 5,
        "status": {"code": 2, "message": "bad"},
    }
    traces = serialization.traces(
        {
            "resourceSpans": [
                {"resource": resource, "scopeSpans": [{"scope": scope, "spans": [span]}]}
            ]
        }
    )
    record: Any = {
        "timeUnixNano": "6",
        "observedTimeUnixNano": "7",
        "severityNumber": 9,
        "severityText": "INFO",
        "body": {"kvlistValue": {"values": [{"key": "d", "value": {"bytesValue": bytes([1, 2])}}]}},
        "attributes": [{"key": "e", "value": {"intValue": 5}}],
        "droppedAttributesCount": 6,
        "flags": 1,
        "traceId": trace_id,
        "spanId": span_id,
    }
    logs = serialization.logs(
        {
            "resourceLogs": [
                {"resource": resource, "scopeLogs": [{"scope": scope, "logRecords": [record]}]}
            ]
        }
    )
    assert _bytes(traces).body.hex() == "".join(
        [
            "0ab101",  # resource_spans
            "0a00",  # resource
            "12ac01",  # scope_spans
            "0a030a0173",  # scope { name: "s" }
            "12a401",  # spans
            "0a100102030405060708090a0b0c0d0e0f10",  # trace_id
            "12081112131415161718",  # span_id
            "22082122232425262728",  # parent_span_id
            "2a026f70",  # name: "op"
            "3002",  # kind: 2
            "390100000000000000",  # start_time_unix_nano: 1
            "410200000000000000",  # end_time_unix_nano: 2
            "4a070a016112021001",  # attributes { a: true }
            "5001",  # dropped_attributes_count: 1
            "5a1e",  # events
            "090300000000000000",  # time_unix_nano: 3
            "120165",  # name: "e"
            "1a0e0a0162120921000000000000e03f",  # attributes { b: 0.5 }
            "2002",  # dropped_attributes_count: 2
            "6003",  # dropped_events_count: 3
            "6a2c",  # links
            "0a103132333435363738393a3b3c3d3e3f40",  # trace_id
            "12084142434445464748",  # span_id
            "220c0a016312072a050a030a0173",  # attributes { c: ["s"] }
            "2804",  # dropped_attributes_count: 4
            "7005",  # dropped_links_count: 5
            "7a071203626164",  # status { message: "bad"
            "1802",  #   code: 2 }
        ]
    )
    assert _bytes(logs).body.hex() == "".join(
        [
            "0a60",  # resource_logs
            "0a00",  # resource
            "125c",  # scope_logs
            "0a030a0173",  # scope { name: "s" }
            "1255",  # log_records
            "090600000000000000",  # time_unix_nano: 6
            "1009",  # severity_number: 9
            "1a04494e464f",  # severity_text: "INFO"
            "2a0d320b0a090a016412043a020102",  # body { d: bytes [1, 2] }
            "32070a016512021805",  # attributes { e: 5 }
            "3806",  # dropped_attributes_count: 6
            "4501000000",  # flags: 1
            "4a100102030405060708090a0b0c0d0e0f10",  # trace_id
            "52081112131415161718",  # span_id
            "590700000000000000",  # observed_time_unix_nano: 7
        ]
    )


def test_layer_protobuf_encodes_log_record_ids_given_as_bytes_like_their_hex_strings() -> None:
    """layerProtobuf encodes log record ids given as bytes like their hex strings"""
    serialization = _with(otlp_serialization.layer_protobuf)

    def encode(trace_id: str | bytes, span_id: str | bytes) -> str:
        record: Any = {
            "timeUnixNano": "1",
            "observedTimeUnixNano": "2",
            "attributes": [],
            "droppedAttributesCount": 0,
            "traceId": trace_id,
            "spanId": span_id,
        }
        body = serialization.logs(
            {
                "resourceLogs": [
                    {
                        "resource": {"attributes": [], "droppedAttributesCount": 0},
                        "scopeLogs": [{"scope": {"name": "s"}, "logRecords": [record]}],
                    }
                ]
            }
        )
        return _bytes(body).body.hex()

    assert encode(bytes(range(1, 17)), bytes(range(17, 25))) == encode(
        "0102030405060708090a0b0c0d0e0f10", "1112131415161718"
    )
