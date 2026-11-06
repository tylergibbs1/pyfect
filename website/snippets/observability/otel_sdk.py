from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter

import pyfect as fx
from pyfect import otel

# In production: BatchSpanProcessor(OTLPSpanExporter()) from opentelemetry-exporter-otlp.
exporter = InMemorySpanExporter()

telemetry = otel.sdk.layer(
    otel.sdk.Configuration(
        resource=otel.sdk.ResourceConfig(service_name="atlas", service_version="1.0.0"),
        span_processor=SimpleSpanProcessor(exporter),
    )
)


@fx.fn("lookup")
def lookup(code: str):
    yield from fx.annotate_current_span("country.code", code)
    return code.lower()


assert fx.run_blocking(lookup("PT").with_span("GET /ask").pipe(fx.provide(telemetry))) == "pt"

spans = {span.name: span for span in exporter.get_finished_spans()}
assert sorted(spans) == ["GET /ask", "lookup"]
lookup_span, request_span = spans["lookup"], spans["GET /ask"]
assert lookup_span.attributes == {"country.code": "PT"}
assert lookup_span.parent is not None and request_span.context is not None
assert lookup_span.parent.span_id == request_span.context.span_id
assert lookup_span.resource.attributes["service.name"] == "atlas"
