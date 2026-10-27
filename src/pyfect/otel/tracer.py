"""pyfect tracing into OpenTelemetry (Effect's ``OtelTracer``).

The tracer this module installs makes each pyfect span an OpenTelemetry
span (``OtelSpan``) and keeps the current span active in OpenTelemetry's
context while a fiber runs, so libraries instrumented with OpenTelemetry
see it as their parent::

    tracing = otel.tracer.layer.pipe(layer.provide(provider_layer))
    program.with_span("request").pipe(fx.provide(tracing))

A pyfect parent wins over the active OpenTelemetry span; with no pyfect
parent, a span started by other OpenTelemetry code is the parent.
``make_external_span`` and ``with_span_context`` continue a remote trace.
Nothing is exported unless the tracer provider has span processors (see
``otel.sdk``).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Final, Never

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import SpanContext

from pyfect import layer as _layer
from pyfect._core import Effect
from pyfect._fiber import Fiber
from pyfect._tracer_ref import CurrentTracer
from pyfect.clock import Clock, ClockService
from pyfect.context import Tag
from pyfect.errors import NoSuchElementException
from pyfect.layer import Layer
from pyfect.otel._attributes import PYFECT_VERSION
from pyfect.otel._span import (
    EFFECT_SPAN_KEY,
    OtelSpan,
    OtelTraceFlags,
    OtelTraceState,
    external_span_of,
    make_external_span,
    populate_context,
    propagated_span,
)
from pyfect.otel._wrapper import EffectSpanView
from pyfect.tracer import ParentSpan, Span, Tracer, current_span

__all__ = [
    "EffectSpanView",
    "OtelSpan",
    "OtelTraceFlags",
    "OtelTraceState",
    "OtelTracer",
    "OtelTracerProvider",
    "current_otel_span",
    "layer",
    "layer_global",
    "layer_global_provider",
    "layer_global_tracer",
    "layer_tracer",
    "layer_without_otel_tracer",
    "make",
    "make_external_span",
    "with_span_context",
]


class OtelTracer(Tag[trace.Tracer]):
    """The OpenTelemetry tracer pyfect spans are started with."""


class OtelTracerProvider(Tag[trace.TracerProvider]):
    """The OpenTelemetry tracer provider ``layer_tracer`` gets a tracer
    from."""


def _context_hook[T](run: Callable[[], T], fiber: Fiber[Any, Any], /) -> T:
    """Runs a fiber step with the fiber's current span active in
    OpenTelemetry's context."""
    span = propagated_span(fiber.get_ref(ParentSpan))
    if span is None:
        return run()
    context = populate_context(otel_context.get_current(), span)
    context = otel_context.set_value(EFFECT_SPAN_KEY, trace.get_current_span(context), context)
    token = otel_context.attach(context)
    try:
        return run()
    finally:
        otel_context.detach(token)


def _tracer(otel_tracer: trace.Tracer) -> Tracer:
    return Tracer(lambda request: OtelSpan(otel_tracer, request), _context_hook)


make: Final[Effect[Tracer, Never, OtelTracer]] = OtelTracer().map(_tracer)
"""A pyfect tracer starting OpenTelemetry spans with the ``OtelTracer``."""

layer_global_provider: Final[Layer[OtelTracerProvider]] = _layer.sync(
    OtelTracerProvider, trace.get_tracer_provider
)
"""The global OpenTelemetry tracer provider."""

layer_tracer: Final[Layer[OtelTracer, Never, OtelTracerProvider]] = _layer.effect(
    OtelTracer, OtelTracerProvider().map(lambda p: p.get_tracer("pyfect", PYFECT_VERSION))
)
"""A tracer from the provider, with ``pyfect`` and its version as the
instrumentation scope."""

layer_global_tracer: Final[Layer[OtelTracer]] = layer_tracer.pipe(
    _layer.provide(layer_global_provider)
)
"""A tracer from the global tracer provider."""

layer_without_otel_tracer: Final[Layer[Never, Never, OtelTracer]] = _layer.effect(
    CurrentTracer, make
)
"""Installs the bridge's tracer, using the ``OtelTracer`` provided."""

layer: Final[Layer[OtelTracer, Never, OtelTracerProvider]] = layer_without_otel_tracer.pipe(
    _layer.provide_merge(layer_tracer)
)
"""Installs the bridge's tracer, with a tracer from the provider."""

layer_global: Final[Layer[OtelTracer]] = layer_without_otel_tracer.pipe(
    _layer.provide_merge(layer_global_tracer)
)
"""Installs the bridge's tracer, with a tracer from the global provider."""


def _otel_span(span: Span, clock: ClockService) -> trace.Span:
    return span.span if isinstance(span, OtelSpan) else EffectSpanView(span, clock)


def current_otel_span() -> Effect[trace.Span, NoSuchElementException]:
    """The current span as an OpenTelemetry span: the bridge's own, or a
    view writing through to a span another tracer made. Fails outside every
    span, or in an external one."""
    return Clock().flat_map(lambda clock: current_span().map(lambda s: _otel_span(s, clock)))


class _WithSpanContext:
    __slots__ = ("_span_context",)

    def __init__(self, span_context: SpanContext) -> None:
        self._span_context = span_context

    def __call__[A, E, R](self, eff: Effect[A, E, R], /) -> Effect[A, E, R]:
        return eff.with_parent_span(external_span_of(self._span_context))


def with_span_context(span_context: SpanContext) -> _WithSpanContext:
    """Run an effect with the OpenTelemetry span context as its parent span
    (use with ``.pipe``), continuing a trace begun outside pyfect."""
    return _WithSpanContext(span_context)
