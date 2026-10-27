"""Layers and spans: a layer providing a parent span, and spans around a
layer's construction (Effect's ``Layer.span`` / ``parentSpan`` /
``withSpan`` / ``withParentSpan``)."""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Never, Unpack

from pyfect._core import Effect, _Succeed
from pyfect._layer_core import Layer, feed
from pyfect._stack_frame import CurrentStackFrame, push
from pyfect.context import Context
from pyfect.exit import Exit
from pyfect.scope import Scope, add_finalizer
from pyfect.tracer import AnySpan, ExternalSpan, ParentSpan, Span, SpanOptions
from pyfect.tracer._spans import span_scoped

type OnEnd = Callable[[Span, Exit[Any, Any]], Effect[object]]
"""Runs when a layer's span ends (when the layer's scope closes)."""


def parent_span(span: AnySpan) -> Layer[ParentSpan]:
    """Provide ``span`` as the parent of the spans made with it."""
    built: Effect[Context] = _Succeed(Context.make(ParentSpan, span))
    return Layer(lambda _memo, _scope: built)


def _scoped_span(
    name: str, on_end: OnEnd | None, options: SpanOptions
) -> Effect[Span, Never, Scope]:
    made = span_scoped(name, options)
    if on_end is None:
        return made
    return made.tap(lambda span: add_finalizer(lambda ex: on_end(span, ex)))


def span(
    name: str, *, on_end: OnEnd | None = None, **options: Unpack[SpanOptions]
) -> Layer[ParentSpan]:
    """Provide a new span as the parent of the spans made with it. The span
    ends, and ``on_end`` runs, when the layer's scope closes."""
    from pyfect.layer import effect

    return effect(ParentSpan, _scoped_span(name, on_end, options))


def with_parent_span[O, E, R](
    layer: Layer[O, E, R], span: AnySpan, stack: Callable[[], str | None]
) -> Layer[O, E, R]:
    """``layer`` built with ``span`` as the parent span and, unless it is
    external, inside a stack frame named after it at ``stack``."""
    if not isinstance(span, ExternalSpan):
        layer = layer.update_service(CurrentStackFrame, push(span.name, stack))
    return feed(parent_span(span), layer, keep_dep=False)


def with_span[O, E, R](
    layer: Layer[O, E, R],
    name: str,
    on_end: OnEnd | None,
    options: SpanOptions,
    stack: Callable[[], str | None],
) -> Layer[O, E, R]:
    from pyfect.layer import unwrap

    return unwrap(
        _scoped_span(name, on_end, options).map(lambda s: with_parent_span(layer, s, stack))
    )
