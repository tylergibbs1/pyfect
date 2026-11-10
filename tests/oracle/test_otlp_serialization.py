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
