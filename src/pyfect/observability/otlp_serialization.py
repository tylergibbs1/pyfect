"""Turning OTLP payloads into HTTP request bodies (Effect's
``OtlpSerialization``): OTLP/JSON with ``layer_json``, OTLP/protobuf with
``layer_protobuf`` (pyfect's own encoder, as Effect's; no protobuf
library)."""

from __future__ import annotations

import base64
import math
from collections.abc import Callable, Mapping
from typing import TYPE_CHECKING, Any, Final, Self, cast

from pyfect import _json_text
from pyfect import layer as _layer
from pyfect._service_copy import replaced
from pyfect.context import Tag
from pyfect.http import body as _body
from pyfect.layer import Layer
from pyfect.observability import _otlp_protobuf as proto

if TYPE_CHECKING:
    from pyfect.observability.otlp_logger import LogsData
    from pyfect.observability.otlp_metrics import MetricsData
    from pyfect.observability.otlp_tracer import TraceData

__all__ = ["OtlpSerialization", "OtlpSerializationService", "layer_json", "layer_protobuf"]


class OtlpSerializationService:
    """How each signal's payload becomes a request body:
    ``layer_json`` and ``layer_protobuf`` provide one, and
    ``OtlpSerializationService(traces=..., metrics=..., logs=...)`` makes
    one of functions."""

    __slots__ = ("_logs", "_metrics", "_traces")

    def __replace__(self, **changes: Any) -> Self:
        """A copy with ``changes`` to the constructor's arguments (``copy.replace``)."""
        return replaced(self, changes)

    def __init__(
        self,
        traces: Callable[[TraceData], _body.HttpBody],
        metrics: Callable[[MetricsData], _body.HttpBody],
        logs: Callable[[LogsData], _body.HttpBody],
    ) -> None:
        self._traces = traces
        self._metrics = metrics
        self._logs = logs

    def traces(self, data: TraceData) -> _body.HttpBody:
        """The request body of the trace export ``data`` (an OTLP
        ``ExportTraceServiceRequest``), with its content type."""
        return self._traces(data)

    def metrics(self, data: MetricsData) -> _body.HttpBody:
        """The request body of the metrics export ``data`` (an OTLP
        ``ExportMetricsServiceRequest``), with its content type."""
        return self._metrics(data)

    def logs(self, data: LogsData) -> _body.HttpBody:
        """The request body of the logs export ``data`` (an OTLP
        ``ExportLogsServiceRequest``), with its content type."""
        return self._logs(data)


class OtlpSerialization(Tag[OtlpSerializationService]):
    """The serialization the OTLP exporters post their payloads with."""


def _json_ready(value: object, key: str = "") -> object:
    """``value`` with each non-finite float as the text OTLP/JSON wants
    (``"NaN"``, ``"Infinity"``, ``"-Infinity"``; ``JSON.stringify`` would
    write ``null``), a ``bytesValue``'s bytes as base64 and other bytes as
    ``JSON.stringify`` writes a ``Uint8Array``."""
    match value:
        case float() if not math.isfinite(value):
            return "NaN" if math.isnan(value) else ("Infinity" if value > 0 else "-Infinity")
        case dict():
            items = cast("Mapping[str, object]", value).items()
            return {name: _json_ready(item, name) for name, item in items}
        case list() | tuple():
            return [_json_ready(item) for item in cast("list[object]", value)]
        case bytes() | bytearray() if key == "bytesValue":
            return base64.b64encode(value).decode("ascii")
        case bytes() | bytearray():
            return {str(i): byte for i, byte in enumerate(value)}
        case _:
            return value


def _json_body(data: object) -> _body.HttpBody:
    return _body.text(_json_text.stringify(_json_ready(data)), "application/json")


def _protobuf_body(data: bytes) -> _body.HttpBody:
    return _body.bytes_(data, "application/x-protobuf")


layer_json: Final[Layer[OtlpSerialization]] = _layer.succeed(
    OtlpSerialization,
    OtlpSerializationService(traces=_json_body, metrics=_json_body, logs=_json_body),
)
"""OTLP/JSON bodies (``application/json``). ``NaN`` and the infinities are
written as the strings OTLP/JSON expects, not as ``null``; ``bytesValue``
data is written as a base64 string."""

layer_protobuf: Final[Layer[OtlpSerialization]] = _layer.succeed(
    OtlpSerialization,
    OtlpSerializationService(
        traces=lambda data: _protobuf_body(proto.encode_traces_data(data)),
        metrics=lambda data: _protobuf_body(proto.encode_metrics_data(data)),
        logs=lambda data: _protobuf_body(proto.encode_logs_data(data)),
    ),
)
"""OTLP/protobuf bodies (``application/x-protobuf``)."""
