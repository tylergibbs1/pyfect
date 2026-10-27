"""``Effect`` methods for tracing: spans around an effect, and what the
spans made inside it carry."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Mapping
from typing import TYPE_CHECKING, Unpack, overload

from pyfect._effect_base import A_co, E_co, EffectBase, R_co, as_effect

if TYPE_CHECKING:
    from pyfect._core import Effect
    from pyfect._stack_frame import CaptureStackTrace
    from pyfect.scope import Scope
    from pyfect.tracer import AnySpan, TracedSpanOptions, Tracer


class TracingMethods(EffectBase[A_co, E_co, R_co]):
    __slots__ = ()

    def with_span(
        self, name: str, **options: Unpack[TracedSpanOptions]
    ) -> Effect[A_co, E_co, R_co]:
        """Run inside a new span, the parent of the spans made inside. It
        ends with this effect's exit. Failures inside record the span's
        stack frame: this call site unless ``capture_stack_trace`` says
        otherwise."""
        from pyfect._stack_frame import stack_of
        from pyfect.tracer._spans import in_span_frame, span_using

        eff = as_effect(self)
        stack = stack_of(options.get("capture_stack_trace", True), 1)
        return span_using(name, lambda span: in_span_frame(eff, span, stack), options)

    def with_span_scoped(
        self, name: str, **options: Unpack[TracedSpanOptions]
    ) -> Effect[A_co, E_co, R_co | Scope]:
        """Run inside a new span that ends when the current scope closes."""
        from pyfect._stack_frame import stack_of
        from pyfect.tracer._spans import in_span_frame, span_scoped

        eff = as_effect(self)
        stack = stack_of(options.get("capture_stack_trace", True), 1)
        return span_scoped(name, options).flat_map(lambda span: in_span_frame(eff, span, stack))

    def with_parent_span(
        self, span: AnySpan, *, capture_stack_trace: CaptureStackTrace = True
    ) -> Effect[A_co, E_co, R_co]:
        """Run with ``span`` as the parent of the spans made inside, and,
        unless it is external, inside its stack frame."""
        from pyfect._stack_frame import stack_of
        from pyfect.tracer._spans import in_span_frame

        return in_span_frame(as_effect(self), span, stack_of(capture_stack_trace, 1))

    @overload
    def annotate_spans(self, key: str, value: object, /) -> Effect[A_co, E_co, R_co]: ...
    @overload
    def annotate_spans(self, values: Mapping[str, object], /) -> Effect[A_co, E_co, R_co]: ...
    def annotate_spans(
        self, key_or_values: str | Mapping[str, object], value: object = None, /
    ) -> Effect[A_co, E_co, R_co]:
        """Run with these attributes set on every span made inside."""
        from pyfect.tracer._refs import TracerSpanAnnotations

        added = {key_or_values: value} if isinstance(key_or_values, str) else dict(key_or_values)
        return as_effect(self).update_service(
            TracerSpanAnnotations, lambda annotations: {**annotations, **added}
        )

    def link_spans(
        self, *spans: AnySpan, attributes: Mapping[str, object] | None = None
    ) -> Effect[A_co, E_co, R_co]:
        """Run with links to ``spans`` added to every span made inside."""
        from pyfect.tracer._model import SpanLink
        from pyfect.tracer._refs import TracerSpanLinks

        shared: Mapping[str, object] = {} if attributes is None else attributes
        links = tuple(SpanLink(span, shared) for span in spans)
        return as_effect(self).update_service(TracerSpanLinks, lambda current: (*current, *links))

    def with_tracer(self, tracer: Tracer) -> Effect[A_co, E_co, R_co]:
        """Run with spans made by ``tracer``."""
        from pyfect._tracer_ref import CurrentTracer

        return as_effect(self).update_service(CurrentTracer, lambda _: tracer)

    def with_tracer_enabled(self, enabled: bool) -> Effect[A_co, E_co, R_co]:
        """Run with tracing on or off: off, every span is a no-op span."""
        from pyfect.tracer._refs import TracerEnabled

        return as_effect(self).update_service(TracerEnabled, lambda _: enabled)

    def with_tracer_timing(self, enabled: bool) -> Effect[A_co, E_co, R_co]:
        """Run with span timing on or off: off, spans start and end at 0."""
        from pyfect.tracer._refs import TracerTimingEnabled

        return as_effect(self).update_service(TracerTimingEnabled, lambda _: enabled)
