"""Effect's own OTLP exporters (Effect's ``effect/observability``): logs,
metrics and traces posted over OTLP/HTTP as JSON or protobuf, with no
OpenTelemetry SDK.

- ``otlp``: one layer for all three signals (``layer_json``,
  ``layer_protobuf``, ``layer_from_config``)
- ``otlp_tracer``, ``otlp_logger``, ``otlp_metrics``: one signal each
- ``otlp_exporter``: the shared batch exporter and its ``Flusher``
- ``otlp_serialization``: OTLP/JSON and OTLP/protobuf bodies
- ``otlp_resource``: the resource and OTLP attribute values
- ``otlp_proxy``: routes forwarding browser OTLP exports upstream

``pyfect.otel`` (the ``pyfect-dev[otel]`` extra) is the other path, through
the OpenTelemetry SDK, as Effect's ``@effect/opentelemetry``.
"""

__all__: list[str] = []
