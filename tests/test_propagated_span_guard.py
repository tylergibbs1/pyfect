"""Exporters read the current span only through ``propagated_parent_span``.

Effect #10609: with tracing disabled a log inside ``with_span`` sees a ``NoopSpan``, and
``OtlpLogger`` exported its invalid ids. A span made with tracing off, or one annotated with
``DisablePropagation``, must never lend its ids to a log record or an exported context, so the
OTLP and OpenTelemetry integrations may not read ``ParentSpan`` directly.
"""

import re

import _source

_EXPORTERS = ("observability", "otel")
_RAW_READ = re.compile(r"\.get_(?:ref|unsafe)\(ParentSpan\)|\bParentSpan\(\)")

_ALLOWED = {
    # The user's SpanContextHook gets the span the fiber step runs in, to make it current in
    # its own context library; no id is exported here.
    "observability/otlp_tracer.py": 1,
}


def test_exporters_read_the_parent_span_only_through_propagated_parent_span() -> None:
    found: dict[str, int] = {}
    for package in _EXPORTERS:
        for path in _source.files(_source.SRC / package):
            count = len(_RAW_READ.findall(_source.text(path)))
            if count:
                found[path.relative_to(_source.SRC).as_posix()] = count
    assert found == _ALLOWED, (
        "read the current span with pyfect.tracer._spans.propagated_parent_span(fiber)"
    )
