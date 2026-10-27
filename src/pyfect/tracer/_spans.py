"""Making spans: the effects that start, end and read them.

A span made by ``use_span`` / ``with_span`` ends when the effect it wraps
ends, however it ends: the frame that ends it is pushed in the same step
that makes the span, so an interrupt cannot land between the two.
"""
# pyright: reportPrivateUsage=false

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, Never, Unpack, final, overload

from pyfect._core import Effect, Frame, Step, _FailCause, _Succeed, _WithFiber
from pyfect._fiber import Fiber
from pyfect._tracer_ref import CurrentTracer
from pyfect.cause import Cause
from pyfect.cause import fail as fail_cause
from pyfect.clock import Clock, ClockService
from pyfect.context import Context
from pyfect.errors import NoSuchElementException
from pyfect.exit import Exit, Failure, Success
from pyfect.scope import Scope
from pyfect.tracer._model import AnySpan, Ended, ExternalSpan, Span, SpanOptions, SpanRequest
from pyfect.tracer._native import NoopSpan
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

_VOID: Effect[None] = _Succeed(None)


def _propagating(span: AnySpan | None) -> AnySpan | None:
    """``span``, or the nearest ancestor of it whose annotations do not
    disable propagation."""
    while span is not None and span.annotations.unsafe_get(DisablePropagation):
        span = None if isinstance(span, ExternalSpan) else span.parent
    return span


def make_span_unsafe(fiber: Fiber[Any, Any], name: str, options: SpanOptions) -> Span:
    """A new span, started now, a child of the fiber's current span unless
    ``options`` say otherwise."""
    annotations = options.get("annotations")
    disabled = not fiber.get_ref(TracerEnabled) or (
        annotations is not None and annotations.unsafe_get(DisablePropagation)
    )
    parent = options.get("parent")
    if parent is None and not options.get("root", False):
        parent = _propagating(fiber.get_ref(ParentSpan))
    if annotations is None:
        annotations = Context.empty()
    if disabled:
        return NoopSpan(name, parent, annotations.add(DisablePropagation, True))
    level = options.get("level")
    if level is None:
        level = fiber.get_ref(CurrentTraceLevel)
    sampled = options.get("sampled")
    if sampled is None:
        sampled = (parent is None or parent.sampled) and not (
            fiber.get_ref(MinimumTraceLevel) > level
        )
    timing = fiber.get_ref(TracerTimingEnabled)
    span = fiber.get_ref(CurrentTracer).span(
        SpanRequest(
            name=name,
            parent=parent,
            annotations=annotations,
            links=[*fiber.get_ref(TracerSpanLinks), *options.get("links", ())],
            start_time=fiber.get_ref(Clock).unsafe_now_nanos() if timing else 0,
            kind=options.get("kind", "internal"),
            root=options.get("root", False),
            sampled=sampled,
        )
    )
    for key, value in fiber.get_ref(TracerSpanAnnotations).items():
        span.attribute(key, value)
    for key, value in options.get("attributes", {}).items():
        span.attribute(key, value)
    return span


def make_span(name: str, **options: Unpack[SpanOptions]) -> Effect[Span]:
    """A new span, started now. Nothing ends it: end it yourself, or use
    ``use_span`` / ``make_span_scoped``."""
    return _WithFiber(lambda fiber: _Succeed(make_span_unsafe(fiber, name, options)))


def make_span_scoped(name: str, **options: Unpack[SpanOptions]) -> Effect[Span, Never, Scope]:
    """A new span, ended when the current scope closes, with the scope's
    exit."""

    def body(fiber: Fiber[Any, Any]) -> Effect[Span]:
        span = make_span_unsafe(fiber, name, options)
        end = _SpanEnder(span, fiber.get_ref(Clock), fiber.get_ref(TracerTimingEnabled))

        def finalizer(ex: Exit[Any, Any]) -> Effect[None]:
            end(ex)
            return _VOID

        return fiber._context.unsafe_get(Scope).add_finalizer(finalizer).as_(span)

    return _WithFiber(body).uninterruptible()


def use_span[A, E = Never, R = Never](
    name: str, f: Callable[[Span], Effect[A, E, R]], /, **options: Unpack[SpanOptions]
) -> Effect[A, E, R]:
    """Run ``f(span)`` with a new span, ended when the effect ``f`` returns
    ends (or when ``f`` raises). The span is not made the parent of spans
    inside; ``with_span`` does that."""
    return _UseSpan(name, f, options)


@final
class _SpanEnder:
    """Ends a span with an exit, at the time of the clock the span started
    with, unless it has ended already."""

    __slots__ = ("clock", "span", "timing")

    def __init__(self, span: Span, clock: ClockService, timing: bool) -> None:
        self.span = span
        self.clock = clock
        self.timing = timing

    def __call__(self, ex: Exit[object, object]) -> None:
        if not isinstance(self.span.status, Ended):
            self.span.end(self.clock.unsafe_now_nanos() if self.timing else 0, ex)


@final
class _UseSpan[A, E, R](Effect[A, E, R]):
    __slots__ = ("f", "name", "options")

    def __init__(
        self, name: str, f: Callable[[Span], Effect[A, E, R]], options: SpanOptions
    ) -> None:
        self.name = name
        self.f = f
        self.options = options

    def _step(self, fiber: Fiber[Any, Any]) -> Step:
        span = make_span_unsafe(fiber, self.name, self.options)
        fiber._push(
            _EndSpan(_SpanEnder(span, fiber.get_ref(Clock), fiber.get_ref(TracerTimingEnabled)))
        )
        return self.f(span)


@final
class _EndSpan(Frame):
    __slots__ = ("end",)

    def __init__(self, end: _SpanEnder) -> None:
        self.end = end

    def _on_success(self, value: Any, fiber: Fiber[Any, Any]) -> Step:
        ex = Success(value)
        self.end(ex)
        return ex

    def _on_failure(self, cause: Cause[Any], fiber: Fiber[Any, Any]) -> Step:
        ex = Failure(cause)
        self.end(ex)
        return ex


def local_span(fiber: Fiber[Any, Any]) -> Span | None:
    """The fiber's current span, unless there is none or it is external."""
    span = fiber.get_ref(ParentSpan)
    return None if span is None or isinstance(span, ExternalSpan) else span


def current_span() -> Effect[Span, NoSuchElementException]:
    """The current span; fails when there is none or it is external."""

    def body(fiber: Fiber[Any, Any]) -> Effect[Span, NoSuchElementException]:
        span = local_span(fiber)
        if span is None:
            return _FailCause(fail_cause(NoSuchElementException()))
        return _Succeed(span)

    return _WithFiber(body)


def current_parent_span() -> Effect[AnySpan, NoSuchElementException]:
    """The current span, external or not; fails outside every span."""

    def body(fiber: Fiber[Any, Any]) -> Effect[AnySpan, NoSuchElementException]:
        span = fiber.get_ref(ParentSpan)
        if span is None:
            return _FailCause(fail_cause(NoSuchElementException()))
        return _Succeed(span)

    return _WithFiber(body)


_MISSING: Any = object()


@overload
def annotate_current_span(key: str, value: object, /) -> Effect[None]: ...
@overload
def annotate_current_span(values: Mapping[str, object], /) -> Effect[None]: ...
def annotate_current_span(
    key_or_values: str | Mapping[str, object], value: object = _MISSING, /
) -> Effect[None]:
    """Set attributes on the current span, unless there is none or it has
    ended."""
    added = {key_or_values: value} if isinstance(key_or_values, str) else key_or_values

    def body(fiber: Fiber[Any, Any]) -> Effect[None]:
        span = local_span(fiber)
        if span is not None and not isinstance(span.status, Ended):
            for k, v in added.items():
                span.attribute(k, v)
        return _VOID

    return _WithFiber(body)
