"""OpenTelemetry for pyfect (Effect's ``@effect/opentelemetry``): spans,
logs and metrics sent through the OpenTelemetry SDK. Needs the ``otel``
extra (``pip install 'pyfect[otel]'``); ``pyfect`` itself never imports
it.

- ``otel.sdk.layer(Configuration(...))``: everything in one layer
- ``otel.tracer``: pyfect spans as OpenTelemetry spans
- ``otel.logger``: pyfect logs as OpenTelemetry log records
- ``otel.metrics``: the metric registry for OpenTelemetry metric readers
- ``otel.resource``: the resource describing the service
"""

try:
    import opentelemetry.sdk  # noqa: F401  # pyright: ignore[reportUnusedImport]
except ImportError as error:  # pragma: no cover - depends on the environment
    raise ImportError(
        "pyfect.otel needs the OpenTelemetry SDK: pip install 'pyfect[otel]'"
    ) from error

from pyfect.otel import logger, metrics, resource, sdk, tracer

__all__ = ["logger", "metrics", "resource", "sdk", "tracer"]
