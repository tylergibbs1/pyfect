"""Ports of ``@effect/opentelemetry``'s ``OtelTracer.test.ts``.

Each test's docstring is the Effect test title. ``OtelTracer.layer`` is
``otel.tracer.layer``, ``NodeSdk.layerTracerProvider`` is
``otel.sdk.layer_tracer_provider`` and ``NodeSdk.layer`` is
``otel.sdk.layer(Configuration(...))``. Python's OpenTelemetry context lives
in ``contextvars``, so no context manager has to be installed; ids are
integers there (``format_trace_id`` / ``format_span_id``), and attribute
lists are exported as tuples.

Adapted, with the reason:

- "uses the shared Effect version as the tracer instrumentation scope": the
  scope is ``pyfect`` and pyfect's version.
- "inherits an OpenTelemetry span started inside an Effect span" and "does
  not inherit an ambient Effect span when re-entering from JavaScript":
  re-entering is a nested ``run_blocking`` from inside the outer program.
- "inherits getter-based OpenTelemetry parent ids with trace flags %s": a
  Python ``SpanContext`` is a tuple, with no getter-based variant; the port
  keeps the check that the active parent's ids are inherited and that
  ``OtelTraceFlags`` overrides its flags.
- "preserves identity, trace state and locality on an active OpenTelemetry
  parent": the active context is attached with ``context.attach`` instead of
  a fake ``ContextAPI``.
- "renders nested error causes in the stacktrace": an exception's
  ``__cause__`` is its nested cause; Python's traceback shows it.
- "withSpanContext": the OpenTelemetry span is started with the provided
  tracer (Effect's test uses the unregistered global one, whose spans all
  have the invalid id).

Omitted, with the reason:

- "exports the HTTP server span when disposed right after the response":
  the HTTP router is not ported.
"""

from collections.abc import Generator
from typing import Any

import pytest

pytest.importorskip("opentelemetry.sdk")

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.sdk.trace import ReadableSpan
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from opentelemetry.trace import (
    NonRecordingSpan,
    SpanContext,
    Status,
    StatusCode,
    TraceFlags,
    TraceState,
    format_span_id,
    format_trace_id,
)

import pyfect as fx
from pyfect import exit, layer, otel, testing
from pyfect.cause import Cause, Fail
from pyfect.context import Context
from pyfect.layer import Layer
from pyfect.otel._attributes import PYFECT_VERSION
from pyfect.otel.tracer import OtelSpan, OtelTraceFlags, OtelTracer
from pyfect.tracer import DisablePropagation, Ended, ExternalSpan, Span, SpanRequest


def _tracing() -> Layer[OtelTracer]:
    return otel.tracer.layer.pipe(
        layer.provide(otel.sdk.layer_tracer_provider(SimpleSpanProcessor(InMemorySpanExporter())))
    ).pipe(layer.provide(otel.resource.layer_empty))


def _sdk(exporter: InMemorySpanExporter) -> Layer[otel.resource.OtelResource]:
    return otel.sdk.layer(
        otel.sdk.Configuration(
            resource=otel.sdk.ResourceConfig(service_name="test"),
            span_processor=SimpleSpanProcessor(exporter),
        )
    )


def _otel(span: Span) -> OtelSpan:
    assert isinstance(span, OtelSpan)
    return span


def _finished(exporter: InMemorySpanExporter) -> ReadableSpan:
    spans = exporter.get_finished_spans()
    assert spans, "Missing span data"
    return spans[0]


@testing.effect
def test_uses_the_shared_effect_version_as_the_tracer_instrumentation_scope():
    """uses the shared Effect version as the tracer instrumentation scope"""
    exporter = InMemorySpanExporter()
    config = otel.sdk.Configuration(
        resource=otel.sdk.ResourceConfig(service_name="test", service_version="service-version"),
        span_processor=[SimpleSpanProcessor(exporter)],
    )

    @fx.gen
    def program():
        yield from fx.void.with_span("test")
        scope = _finished(exporter).instrumentation_scope
        assert scope is not None
        assert (scope.name, scope.version) == ("pyfect", PYFECT_VERSION)

    yield from program.pipe(fx.provide(otel.sdk.layer(fx.sync(lambda: config))))


@testing.effect
def test_with_span():
    """withSpan"""
    span = yield from fx.current_span().with_span("ok").pipe(fx.provide(_tracing()))
    assert isinstance(span, OtelSpan)


@testing.effect
def test_with_span_links():
    """withSpan links"""

    @fx.gen
    def program():
        linked = yield from fx.make_span_scoped("B")
        span = yield from fx.current_span().with_span("A").link_spans(linked)
        assert len(_otel(span).links) == 1

    yield from program.pipe(fx.provide(_tracing()))


@testing.effect
def test_nested_with_span_sets_correct_parent_chain():
    """nested withSpan sets correct parent chain"""
    child = yield from (
        fx.current_span().with_span("child").with_span("parent").pipe(fx.provide(_tracing()))
    )
    assert _otel(child).name == "child"
    assert isinstance(child.parent, OtelSpan)
    assert child.parent.name == "parent"


@testing.effect
def test_inherits_an_opentelemetry_span_started_inside_an_effect_span():
    """inherits an OpenTelemetry span started inside an Effect span"""

    @fx.gen
    def program():
        services = yield from fx.context()
        otel_tracer = yield from OtelTracer()

        def inside() -> None:
            with otel_tracer.start_as_current_span("otel-parent") as parent:
                child = fx.run_blocking(
                    fx.current_span().with_span("child").or_die(), context=services
                )
                assert child.trace_id == format_trace_id(parent.get_span_context().trace_id)
                assert child.parent is not None
                assert child.parent.span_id == format_span_id(parent.get_span_context().span_id)

        yield from fx.sync(inside).with_span("outer")

    yield from program.pipe(fx.provide(_tracing()))


@testing.effect
def test_does_not_inherit_an_ambient_effect_span_when_re_entering():
    """does not inherit an ambient Effect span when re-entering from JavaScript"""

    @fx.gen
    def program():
        services = yield from fx.context()

        @fx.gen
        def inner():
            outer = yield from fx.current_span()
            child = yield from fx.sync(
                lambda: fx.run_blocking(
                    fx.current_span().with_span("child").or_die(), context=services
                )
            )
            assert child.parent is None
            assert child.trace_id != outer.trace_id

        yield from inner.with_span("outer")

    yield from program.pipe(fx.provide(_tracing()))


@testing.effect
def test_a_propagation_disabled_effect_span_is_not_a_parent():
    """a propagation-disabled Effect span is not a parent"""
    child = yield from (
        fx.current_span()
        .with_span("child")
        .with_span("disabled", annotations=Context.make(DisablePropagation, True))
        .pipe(fx.provide(_tracing()))
    )
    assert child.parent is None


def _active_span_is_set() -> None:
    assert trace.get_current_span().get_span_context().is_valid


@testing.effect
def test_supervisor_sets_context():
    """supervisor sets context"""
    yield from fx.sync(_active_span_is_set).with_span("ok").pipe(fx.provide(_tracing()))


@testing.effect
def test_supervisor_sets_context_generator():
    """supervisor sets context generator"""

    @fx.gen
    def program():
        yield from fx.yield_now()
        _active_span_is_set()

    yield from program.with_span("ok").pipe(fx.provide(_tracing()))


@testing.effect
def test_current_otel_span():
    """currentOtelSpan"""

    @fx.gen
    def program():
        span = yield from fx.current_span()
        otel_span = yield from otel.tracer.current_otel_span()
        assert _otel(span).span is otel_span

    yield from program.with_span("ok").pipe(fx.provide(_tracing()))


@pytest.mark.parametrize("status", [StatusCode.UNSET, StatusCode.OK])
@testing.effect
def test_honors_non_error_wrapper_status(status: StatusCode):
    """honors non-error wrapper status %s"""

    @fx.gen
    def program():
        span = yield from fx.current_span()
        wrapper = yield from otel.tracer.current_otel_span()
        wrapper.set_status(Status(status))
        wrapper.end()
        assert isinstance(span.status, Ended)
        assert exit.is_success(span.status.exit)

    yield from program.with_span("repro")


@testing.effect
def test_honors_an_error_wrapper_status():
    """honors an error wrapper status"""

    @fx.gen
    def program():
        span = yield from fx.current_span()
        wrapper = yield from otel.tracer.current_otel_span()
        wrapper.set_status(Status(StatusCode.ERROR))
        wrapper.end()
        assert isinstance(span.status, Ended)
        assert exit.is_failure(span.status.exit)

    yield from program.with_span("repro")


@testing.effect
def test_preserves_the_sampling_decision_of_generic_external_spans():
    """preserves the sampling decision of generic external spans"""
    parent = ExternalSpan(span_id="2" * 16, trace_id="1" * 32, sampled=False)
    span = yield from (
        fx.current_span().with_span("child").with_parent_span(parent).pipe(fx.provide(_tracing()))
    )
    assert _otel(span).span.get_span_context().trace_flags == TraceFlags.DEFAULT


class _RecordingTracer(trace.Tracer):
    """Records the parent context it is asked to start a span in."""

    def __init__(self) -> None:
        self.context: otel_context.Context | None = None

    def start_span(
        self, name: str, context: otel_context.Context | None = None, *args: Any, **kwargs: Any
    ) -> trace.Span:
        self.context = context
        return NonRecordingSpan(
            SpanContext(int("3" * 32, 16), int("4" * 16, 16), False, TraceFlags(1))
        )

    def start_as_current_span(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError


def test_preserves_identity_trace_state_and_locality_on_an_active_opentelemetry_parent():
    """preserves identity, trace state and locality on an active OpenTelemetry parent"""
    parent = SpanContext(
        int("1" * 32, 16),
        int("2" * 16, 16),
        False,
        TraceFlags(TraceFlags.SAMPLED),
        TraceState([("vendor", "value")]),
    )
    active = trace.set_span_in_context(NonRecordingSpan(parent))
    tracer = _RecordingTracer()
    request = SpanRequest("child", None, Context.empty(), [], 0, "internal", False, True)
    token = otel_context.attach(active)
    try:
        OtelSpan(tracer, request)
    finally:
        otel_context.detach(token)
    assert tracer.context is not None
    assert trace.get_current_span(tracer.context) is trace.get_current_span(active)
    received = trace.get_current_span(tracer.context).get_span_context()
    assert (received.trace_state.to_header(), received.is_remote) == ("vendor=value", False)


@pytest.mark.parametrize("flags", [TraceFlags.SAMPLED, TraceFlags.DEFAULT])
@testing.effect
def test_inherits_opentelemetry_parent_ids_with_trace_flags(flags: int):
    """inherits getter-based OpenTelemetry parent ids with trace flags %s"""
    parent = SpanContext(int("1" * 32, 16), int("2" * 16, 16), False, TraceFlags(1))
    active = trace.set_span_in_context(NonRecordingSpan(parent))
    annotations = (
        Context.make(OtelTraceFlags, TraceFlags(flags))
        if flags == TraceFlags.DEFAULT
        else Context.empty()
    )

    @fx.gen
    def program():
        services = yield from fx.context()

        def run_child() -> Span:
            token = otel_context.attach(active)
            try:
                child = fx.current_span().with_span("child", annotations=annotations)
                return fx.run_blocking(child.or_die(), context=services)
            finally:
                otel_context.detach(token)

        child = yield from fx.sync(run_child)
        assert child.trace_id == "1" * 32
        assert child.parent is not None
        assert child.parent.span_id == "2" * 16
        assert _otel(child).span.get_span_context().trace_flags == flags

    yield from program.pipe(fx.provide(_tracing()))


def _keep_exporter(
    eff: fx.Effect[Any, Any, otel.resource.OtelResource], exporter: InMemorySpanExporter
) -> Generator[fx.Effect[Any, Any, Any], Any, ReadableSpan]:
    """Run ``eff`` in the SDK layer, and read its span while the layer is
    still open."""

    @fx.gen
    def inside():
        yield from eff.exit()
        return _finished(exporter)

    return (yield from inside.pipe(fx.provide(_sdk(exporter))))


@testing.effect
def test_records_every_pretty_error():
    """records every pretty error"""
    exporter = InMemorySpanExporter()
    cause = Cause((Fail(Exception("first")), Fail(Exception("second"))))
    span = yield from _keep_exporter(fx.fail_cause(cause).with_span("error-span"), exporter)
    assert len([event for event in span.events if event.name == "exception"]) == 2
    assert span.status.description == "first"


@testing.effect
def test_renders_nested_error_causes_in_the_stacktrace():
    """renders nested error causes in the stacktrace"""
    exporter = InMemorySpanExporter()
    error = RuntimeError("outer failure")
    error.__cause__ = ValueError("inner cause")
    span = yield from _keep_exporter(fx.die(error).with_span("error-span"), exporter)
    event = next(event for event in span.events if event.name == "exception")
    assert event.attributes is not None
    stacktrace = event.attributes["exception.stacktrace"]
    assert isinstance(stacktrace, str)
    assert "ValueError: inner cause" in stacktrace


@testing.effect
def test_leaves_interruption_unset_with_effect_fiber_interrupted():
    """leaves interruption Unset with effect.fiber.interrupted"""
    exporter = InMemorySpanExporter()

    @fx.gen
    def program():
        span = yield from fx.make_span("test")
        assert not isinstance(span.status, Ended)
        span.end(span.status.start_time + 1, exit.interrupt())
        spans = exporter.get_finished_spans()
        assert len(spans) == 1
        assert spans[0].status.status_code is StatusCode.UNSET
        assert list(spans[0].events) == []
        assert dict(spans[0].attributes or {}) == {"effect.fiber.interrupted": True}

    yield from program.pipe(fx.provide(_sdk(exporter)))


@testing.effect
def test_exports_homogeneous_primitive_arrays_as_array_attributes():
    """exports homogeneous primitive arrays as array attributes"""
    exporter = InMemorySpanExporter()
    attributes = {
        "strings": ["a", "b"],
        "numbers": [1, 2],
        "booleans": [True, False],
        "mixed": [1, "a"],
    }
    span = yield from _keep_exporter(
        fx.void.with_span("array-span", attributes=attributes), exporter
    )
    exported = span.attributes or {}
    assert exported["strings"] == ("a", "b")
    assert exported["numbers"] == (1, 2)
    assert exported["booleans"] == (True, False)
    assert isinstance(exported["mixed"], str)


@testing.effect
def test_with_span_context():
    """withSpanContext"""

    @fx.gen
    def program():
        services = yield from fx.context()
        otel_tracer = yield from OtelTracer()
        effect = fx.current_parent_span().with_span("child").or_die()

        def inside() -> None:
            with otel_tracer.start_as_current_span("otel-span", attributes={"root": "yes"}) as span:
                child = fx.run_blocking(
                    effect.pipe(otel.tracer.with_span_context(span.get_span_context())),
                    context=services,
                )
                assert isinstance(child, OtelSpan)
                parent = child.parent
                assert parent is not None
                assert parent.span_id == format_span_id(span.get_span_context().span_id)
                assert parent.trace_id == format_trace_id(span.get_span_context().trace_id)

        yield from fx.sync(inside)

    yield from program.pipe(fx.provide(_tracing()))


@testing.effect
def test_with_span_not_provided():
    """withSpan (not provided)"""
    span = yield from fx.current_span().with_span("ok")
    assert not isinstance(span, OtelSpan)
