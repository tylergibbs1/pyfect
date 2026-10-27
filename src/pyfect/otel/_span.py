"""``OtelSpan``: a pyfect span backed by an OpenTelemetry span, and the
conversions between pyfect spans and OpenTelemetry span contexts."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Final

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.trace import (
    INVALID_SPAN,
    Link,
    NonRecordingSpan,
    SpanContext,
    Status,
    StatusCode,
    TraceFlags,
    TraceState,
    format_span_id,
    format_trace_id,
)

from pyfect.context import Context, Tag
from pyfect.exit import Exit, Success
from pyfect.otel._attributes import to_attribute_value, to_attributes
from pyfect.tracer import (
    AnySpan,
    DisablePropagation,
    Ended,
    ExternalSpan,
    SpanKind,
    SpanLink,
    SpanRequest,
    SpanStatus,
    Started,
)


class OtelTraceFlags(Tag[TraceFlags]):
    """Trace flags carried in a span's annotations, used instead of its
    ``sampled`` when it becomes an OpenTelemetry parent or link."""


class OtelTraceState(Tag[TraceState]):
    """Trace state carried in a span's annotations, propagated when it
    becomes an OpenTelemetry parent or link."""


class _OtelParentSpanContext(Tag[SpanContext]):
    """On a parent taken from the active OpenTelemetry span: its context,
    kept whole (trace state, locality) for the child."""


EFFECT_SPAN_KEY: Final = otel_context.create_key("pyfect.otel.effect_span")
"""Marks the OpenTelemetry span the bridge made active for a pyfect span,
so a pyfect run entered from inside it does not take it as a parent."""

_KINDS: Final[Mapping[SpanKind, trace.SpanKind]] = {
    "internal": trace.SpanKind.INTERNAL,
    "client": trace.SpanKind.CLIENT,
    "server": trace.SpanKind.SERVER,
    "producer": trace.SpanKind.PRODUCER,
    "consumer": trace.SpanKind.CONSUMER,
}


def is_sampled(flags: int) -> bool:
    return bool(flags & TraceFlags.SAMPLED)


class OtelSpan:
    """A pyfect span recording into ``span``, an OpenTelemetry span started
    with ``tracer``. With no parent given (and not a root), the active
    OpenTelemetry span is the parent, unless the bridge made it active for
    a pyfect span."""

    __slots__ = (
        "_attributes",
        "annotations",
        "kind",
        "links",
        "name",
        "parent",
        "sampled",
        "span",
        "span_id",
        "status",
        "trace_id",
    )

    def __init__(self, tracer: trace.Tracer, request: SpanRequest) -> None:
        self.name: str = request.name
        self.annotations: Context = request.annotations
        self.links: list[SpanLink] = request.links
        self.kind: SpanKind = request.kind
        active = otel_context.get_current()
        from_active = not request.root and request.parent is None
        self.parent: AnySpan | None = (
            _otel_parent(active, request.annotations) if from_active else request.parent
        )
        if self.parent is None:
            parent_context = trace.set_span_in_context(INVALID_SPAN, active)
        elif from_active and not _overrides_trace_context(request.annotations):
            # Keep the active span object: some SDKs record children on it.
            parent_context = active
        else:
            parent_context = populate_context(active, self.parent, request.annotations)
        self.span: trace.Span = tracer.start_span(
            request.name,
            context=parent_context,
            kind=_KINDS[request.kind],
            links=[_link(link) for link in request.links] or None,
            start_time=request.start_time,
        )
        span_context = self.span.get_span_context()
        self.span_id: str = format_span_id(span_context.span_id)
        self.trace_id: str = format_trace_id(span_context.trace_id)
        self.sampled: bool = is_sampled(span_context.trace_flags)
        self.status: SpanStatus = Started(request.start_time)
        self._attributes: dict[str, object] = {}

    def __repr__(self) -> str:
        return f"OtelSpan({self.name!r})"

    @property
    def attributes(self) -> Mapping[str, object]:
        return self._attributes

    def attribute(self, key: str, value: object, /) -> None:
        if isinstance(self.status, Started):
            self.span.set_attribute(key, to_attribute_value(value))
            self._attributes[key] = value

    def add_links(self, links: Sequence[SpanLink], /) -> None:
        if isinstance(self.status, Started):
            self.links.extend(links)
            for link in links:
                self.span.add_link(make_span_context(link.span), to_attributes(link.attributes))

    def event(
        self, name: str, start_time: int, attributes: Mapping[str, object] | None = None, /
    ) -> None:
        if isinstance(self.status, Started):
            self.span.add_event(
                name, None if attributes is None else to_attributes(attributes), start_time
            )

    def end(self, end_time: int, exit: Exit[object, object], /) -> None:
        if isinstance(self.status, Ended):
            return
        self.status = Ended(self.status.start_time, end_time, exit)
        if isinstance(exit, Success):
            self.span.set_status(Status(StatusCode.OK))
        elif exit.cause.has_interrupts_only:
            self.span.set_attribute("effect.fiber.interrupted", True)
        else:
            errors = exit.cause.pretty_errors()
            for error in errors:
                self.span.record_exception(error, timestamp=end_time)
            if errors:
                self.span.set_status(Status(StatusCode.ERROR, str(errors[0])))
            else:
                self.span.set_status(Status(StatusCode.OK))
        self.span.end(end_time)


def _link(link: SpanLink) -> Link:
    return Link(make_span_context(link.span), to_attributes(link.attributes))


def _otel_parent(active: otel_context.Context, annotations: Context) -> ExternalSpan | None:
    span = trace.get_current_span(active)
    if span is otel_context.get_value(EFFECT_SPAN_KEY, active):
        return None
    parent = span.get_span_context()
    if not parent.is_valid:
        return None
    return ExternalSpan(
        span_id=format_span_id(parent.span_id),
        trace_id=format_trace_id(parent.trace_id),
        sampled=is_sampled(parent.trace_flags),
        annotations=annotations.add(_OtelParentSpanContext, parent),
    )


def _overrides_trace_context(annotations: Context) -> bool:
    return annotations.lookup(OtelTraceFlags)[0] or annotations.lookup(OtelTraceState)[0]


def _annotation[S](tag: type[Tag[S]], *contexts: Context) -> S | None:
    """The first of ``contexts`` holding ``tag``'s service, if any."""
    for context in contexts:
        found, value = context.lookup(tag)
        if found:
            return value
    return None


def hex_id(text: str) -> int:
    """A pyfect span id as an OpenTelemetry id; a non-hex id (a no-op
    span's ``"noop"``) is the invalid id 0."""
    try:
        return int(text, 16)
    except ValueError:
        return 0


def make_external_span(
    *,
    trace_id: str,
    span_id: str,
    trace_flags: int | None = None,
    trace_state: str | TraceState | None = None,
) -> ExternalSpan:
    """A span from another tracing system, to continue its trace with
    ``eff.with_parent_span``. Its trace flags and state are kept in its
    annotations; without flags it is sampled. A trace state given as text
    is parsed as a ``tracestate`` header."""
    annotations = Context.empty()
    if trace_flags is not None:
        annotations = annotations.add(OtelTraceFlags, TraceFlags(trace_flags))
    if isinstance(trace_state, str):
        annotations = annotations.add(OtelTraceState, TraceState.from_header([trace_state]))
    elif trace_state is not None:
        annotations = annotations.add(OtelTraceState, trace_state)
    return ExternalSpan(
        span_id=span_id,
        trace_id=trace_id,
        sampled=True if trace_flags is None else is_sampled(trace_flags),
        annotations=annotations,
    )


def external_span_of(span_context: SpanContext) -> ExternalSpan:
    """``make_external_span`` from an OpenTelemetry span context."""
    return make_external_span(
        trace_id=format_trace_id(span_context.trace_id),
        span_id=format_span_id(span_context.span_id),
        trace_flags=span_context.trace_flags,
        trace_state=span_context.trace_state,
    )


def make_span_context(span: AnySpan, annotations: Context | None = None) -> SpanContext:
    """``span`` as an OpenTelemetry span context. Given ``annotations``,
    trace flags and state come from them, then from the span's annotations;
    flags default to the span's ``sampled``."""
    contexts = () if annotations is None else (annotations, span.annotations)
    found, otel_parent = span.annotations.lookup(_OtelParentSpanContext)
    if found:
        parent: SpanContext = otel_parent
        if annotations is None:
            return parent
        flags = _annotation(OtelTraceFlags, *contexts)
        state = _annotation(OtelTraceState, *contexts)
        return SpanContext(
            parent.trace_id,
            parent.span_id,
            parent.is_remote,
            parent.trace_flags if flags is None else flags,
            parent.trace_state if state is None else state,
        )
    flags = _annotation(OtelTraceFlags, *contexts)
    if flags is None:
        flags = TraceFlags(TraceFlags.SAMPLED if span.sampled else TraceFlags.DEFAULT)
    return SpanContext(
        hex_id(span.trace_id),
        hex_id(span.span_id),
        isinstance(span, ExternalSpan),
        flags,
        _annotation(OtelTraceState, *contexts),
    )


def populate_context(
    context: otel_context.Context, span: AnySpan, annotations: Context | None = None
) -> otel_context.Context:
    """``context`` with ``span`` as its current OpenTelemetry span."""
    if isinstance(span, OtelSpan):
        return trace.set_span_in_context(span.span, context)
    return trace.set_span_in_context(
        NonRecordingSpan(make_span_context(span, annotations)), context
    )


def propagated_span(span: AnySpan | None) -> AnySpan | None:
    """``span``, or its nearest ancestor, that does not disable
    propagation."""
    while span is not None and span.annotations.unsafe_get(DisablePropagation):
        span = None if isinstance(span, ExternalSpan) else span.parent
    return span
