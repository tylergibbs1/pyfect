"""Tracing (Effect's ``Tracer``): spans, the tracer that makes them, and the
references that steer them.

``eff.with_span("name")`` runs ``eff`` inside a new span, the parent of
the spans made inside it; ``@fx.fn("name")`` does the same for every call
of a generator function::

    @fx.fn("get_user")
    def get_user(user_id: str):
        yield from fx.annotate_current_span("user.id", user_id)
        ...

    program.pipe(fx.provide(layer.span("startup")))

The native tracer keeps spans in memory (``NativeSpan``) and exports
nothing; install another with ``eff.with_tracer(tracer)`` or a layer
providing ``CurrentTracer``. Logs inside a span are recorded as its events
(``logger.tracer_logger``).
"""

from pyfect._tracer_ref import CurrentTracer
from pyfect.tracer._model import (
    AnySpan,
    ContextHook,
    Ended,
    ExternalSpan,
    Span,
    SpanKind,
    SpanLink,
    SpanOptions,
    SpanRequest,
    SpanStatus,
    Started,
    Tracer,
)
from pyfect.tracer._native import NativeSpan, NoopSpan, SpanEvent, native_tracer
from pyfect.tracer._refs import (
    CurrentTraceLevel,
    DisablePropagation,
    MinimumTraceLevel,
    ParentSpan,
    TracerEnabled,
    TracerSpanAnnotations,
    TracerSpanLinks,
    TracerTimingEnabled,
)
from pyfect.tracer._spans import (
    annotate_current_span,
    current_parent_span,
    current_span,
    make_span,
    make_span_scoped,
    use_span,
)

__all__ = [
    "AnySpan",
    "ContextHook",
    "CurrentTraceLevel",
    "CurrentTracer",
    "DisablePropagation",
    "Ended",
    "ExternalSpan",
    "MinimumTraceLevel",
    "NativeSpan",
    "NoopSpan",
    "ParentSpan",
    "Span",
    "SpanEvent",
    "SpanKind",
    "SpanLink",
    "SpanOptions",
    "SpanRequest",
    "SpanStatus",
    "Started",
    "Tracer",
    "TracerEnabled",
    "TracerSpanAnnotations",
    "TracerSpanLinks",
    "TracerTimingEnabled",
    "annotate_current_span",
    "current_parent_span",
    "current_span",
    "make_span",
    "make_span_scoped",
    "native_tracer",
    "use_span",
]
