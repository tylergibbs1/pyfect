"""Ports of Effect's ``Tracer.test.ts``.

Each test's docstring is the Effect test title. ``Effect.withSpan(eff,
name, options)`` is ``eff.with_span(name, **options)``, ``Effect.currentSpan``
is ``fx.current_span()``, ``Tracer.make({ span })`` is
``tracer.Tracer(span)`` and ``new Tracer.NativeSpan(options)`` is
``NativeSpan(request)``. ``span.parent`` is the span or ``None`` (Effect: an
``Option``). Times are whole nanoseconds; durations are seconds or
``timedelta``. ``Tracer.DisablePropagation.context(true)`` is
``Context.make(DisablePropagation, True)``.

Adapted, with the reason:

- "should capture only the span frame for a string failure": a typed error
  that is not an exception has no traceback, so ``Cause.pretty()`` shows its
  ``Error: ...`` line and the span frame alone (Effect checks
  ``prettyErrors(cause)[0].stack``).

- "should capture the stack trace": a Python exception gets its traceback
  where it is raised, so the defect is raised and caught first; the check
  is that the span keeps the traceback in ``Cause.pretty()``.

The OTLP titles ("generates OTLP span identifiers", "should preserve nested
span context with OtlpTracer" and the "OtlpTracer span status" titles) are
ported in ``tests/oracle/test_otlp_tracer.py``.
"""

import re
from collections.abc import Callable, Sequence
from datetime import timedelta
from typing import Any

import pyfect as fx
from pyfect import layer, testing
from pyfect.tracer import (
    AnySpan,
    DisablePropagation,
    Ended,
    ExternalSpan,
    MinimumTraceLevel,
    NativeSpan,
    Span,
    SpanLink,
    SpanRequest,
    Tracer,
)


def _parent(span: Span) -> AnySpan:
    assert span.parent is not None, "Expected parent span"
    return span.parent


def _named(span: AnySpan) -> Span:
    assert not isinstance(span, ExternalSpan)
    return span


def _recording() -> tuple[Tracer, list[NativeSpan]]:
    """A tracer making native spans, and the spans it made."""
    spans: list[NativeSpan] = []

    def make(request: SpanRequest) -> NativeSpan:
        span = NativeSpan(request)
        spans.append(span)
        return span

    return Tracer(make), spans


def _hex(text: str, digits: int) -> bool:
    return len(text) == digits and all(c in "0123456789abcdef" for c in text)


@testing.effect
def test_generates_native_span_identifiers():
    """generates native span identifiers"""
    root = yield from fx.current_span().with_span("root")
    child = yield from fx.current_span().with_span("child", parent=root)
    assert _hex(root.trace_id, 32)
    assert _hex(root.span_id, 16)
    assert child.trace_id == root.trace_id
    assert _hex(child.span_id, 16)


@testing.effect
def test_should_capture_only_the_span_frame_for_a_string_failure():
    """should capture only the span frame for a string failure"""
    cause = yield from fx.fail("boom").with_span("test").sandbox().flip()

    assert len(cause.pretty_errors()) == 1
    assert re.fullmatch(
        r"Error: boom\n    at test \(.*test_tracer\.py:\d+\)",
        cause.pretty(),
    ), cause.pretty()


@testing.effect
def test_should_capture_the_stack_trace():
    """should capture the stack trace"""
    try:
        raise RuntimeError("boom")
    except RuntimeError as raised:
        error = raised
    cause = yield from (
        fx.die(error)
        .with_span("C", annotations=fx.Context.make(DisablePropagation, True))
        .sandbox()
        .flip()
    )
    assert "test_should_capture_the_stack_trace" in cause.pretty()
    assert 'raise RuntimeError("boom")' in cause.pretty()


@testing.effect
def test_should_set_the_parent_span():
    """should set the parent span"""
    span = yield from fx.current_span().with_span("A").with_span("B")
    assert span.name == "A"
    assert _named(_parent(span)).name == "B"


@testing.effect
def test_should_override_the_parent_span_when_root_is_set_to_true():
    """should override the parent span when root is set to true"""
    span = yield from fx.current_span().with_span("A", root=True).with_span("B")
    assert span.name == "A"
    assert span.parent is None


@testing.effect
def test_should_set_an_external_parent_span():
    """should set an external parent span"""
    span = yield from fx.current_span().with_span(
        "A", parent=ExternalSpan(span_id="000", trace_id="111", sampled=True)
    )
    assert span.name == "A"
    assert _parent(span).span_id == "000"


@testing.effect
def test_should_still_apply_minimum_trace_level_with_sampled_parent_spans():
    """should still apply minimum trace level with sampled parent spans"""
    span = yield from (
        fx.current_span()
        .with_span(
            "A",
            parent=ExternalSpan(span_id="000", trace_id="111", sampled=True),
            level=fx.LogLevel.INFO,
        )
        .pipe(fx.provide_service(MinimumTraceLevel, fx.LogLevel.ERROR))
    )
    assert span.sampled is False


@testing.effect
def test_should_not_set_the_parent_span_when_none_exists():
    """should not set the parent span when none exists"""
    span = yield from fx.current_span().with_span("A")
    assert span.name == "A"
    assert span.parent is None
    assert "code.stacktrace" not in span.attributes


@testing.effect
def test_should_set_the_correct_start_and_end_time():
    """should set the correct start and end time"""
    span_fiber = yield from fx.current_span().delay(1).with_span("A").fork()
    yield from testing.adjust(2)
    span = yield from span_fiber.join()
    assert span.name == "A"
    assert span.status.start_time == 0
    assert isinstance(span.status, Ended)
    assert span.status.end_time == 1_000_000_000


@testing.effect
def test_should_capture_logs_as_span_events():
    """should capture logs as span events"""
    yield from testing.adjust(timedelta(microseconds=10))
    span, fiber_id = yield from (
        fx.log("event").and_then(fx.all(fx.current_span(), fx.fiber_id())).with_span("A")
    )
    assert span.name == "A"
    assert span.parent is None
    assert isinstance(span, NativeSpan)
    assert span.events == [
        ("event", 10_000, {"effect.fiberId": fiber_id, "effect.logLevel": "INFO"})
    ]


@testing.effect
def test_should_attach_attributes_and_kind_to_the_current_span():
    """should attach attributes and kind to the current span"""
    result = yield from fx.succeed(42).with_span(
        "test-span", attributes={"code.filepath": "test.ts", "code.lineno": 1}
    )
    assert result == 42


@testing.effect
def test_ignores_mutations_after_end():
    """ignores mutations after end"""
    span = yield from fx.make_span("A")
    assert isinstance(span, NativeSpan)
    span.end(1, fx.Success(None))
    ended = span.status

    span.attribute("late", True)
    span.event("late", 2)
    span.end(3, fx.exit.fail("late"))

    assert span.status is ended
    assert "late" not in span.attributes
    assert span.events == []


@testing.effect
def test_should_allow_adding_span_attributes_as_key_value_pairs():
    """should allow adding span attributes as key/value pairs"""
    span = yield from fx.current_span().with_span("A").annotate_spans("key", "value")
    assert span.name == "A"
    assert span.parent is None
    assert span.attributes.get("key") == "value"


@testing.effect
def test_should_allow_adding_span_attributes_as_a_record():
    """should allow adding span attributes as a record"""
    span = (
        yield from fx.current_span()
        .with_span("A")
        .annotate_spans({"key": "value", "key2": "value2"})
    )
    assert span.attributes.get("key") == "value"
    assert span.attributes.get("key2") == "value2"


@testing.effect
def test_ends_the_span_when_the_callback_throws():
    """ends the span when the callback throws"""
    defect = RuntimeError("boom")
    tracer, spans = _recording()

    def evaluate(_span: Span) -> fx.Effect[None]:
        raise defect

    exit_ = yield from fx.use_span("A", evaluate).with_tracer(tracer).exit()

    assert exit_ == fx.exit.die(defect)
    assert len(spans) == 1
    status = spans[0].status
    assert isinstance(status, Ended)
    assert status.exit == fx.exit.die(defect)


def _interrupt_at_every_step(
    make: Callable[[], fx.Effect[object]],
    check: Callable[[Sequence[NativeSpan], str], None],
):
    """Interrupt a child running ``make()`` at every point it can be
    interrupted, sweeping the step budget, the steps before it and the
    yields before the interrupt."""
    started = 0
    for ops in range(3, 7):
        for prefix in range(4):
            for yields in range(6):
                tracer, spans = _recording()
                eff = make()
                for _ in range(prefix):
                    eff = fx.void.and_then(eff)

                def body(eff: fx.Effect[object] = eff, yields: int = yields):
                    fiber = yield from eff.fork()
                    for _ in range(yields):
                        yield from fx.yield_now()
                    yield from fiber.interrupt()

                yield from (
                    fx.gen(body)
                    .with_tracer(tracer)
                    .pipe(fx.provide_service(fx.MaxOpsBeforeYield, ops))
                )
                started += len(spans)
                check(spans, f"ops {ops}, prefix {prefix}, yields {yields}")
    assert started > 0, "the child never started a span"


@testing.effect
def test_ends_interrupted_spans_and_restores_the_parent_for_outer_finalizers():
    """ends interrupted spans and restores the parent for outer finalizers"""
    seen: list[str | None] = [None]
    checked = 0

    def record(span: AnySpan) -> fx.Effect[None]:
        def write() -> None:
            seen[0] = span.span_id if isinstance(span, ExternalSpan) else span.name

        return fx.sync(write)

    def make() -> fx.Effect[object]:
        seen[0] = None
        finalizer = fx.current_parent_span().or_die().flat_map(record)
        return fx.never.with_span("inner").ensuring(finalizer).with_span("outer")

    def check(spans: Sequence[NativeSpan], label: str) -> None:
        nonlocal checked
        for span in spans:
            assert isinstance(span.status, Ended), f"{span.name}: {label}"
        if seen[0] is not None:
            checked += 1
            assert seen[0] == "outer", label

    yield from _interrupt_at_every_step(make, check)
    assert checked > 0, "the outer finalizer never ran"


@testing.effect
def test_should_control_span_lifetimes_with_a_scope():
    """should control span lifetimes with a scope"""
    span = yield from fx.scoped(fx.make_span_scoped("A"))
    assert isinstance(span.status, Ended)
    assert "code.stacktrace" not in span.attributes


@testing.effect
def test_should_allow_adding_attributes_to_the_current_span():
    """should allow adding attributes to the current span"""

    def body():
        yield from fx.annotate_current_span("key", "value")
        span = yield from fx.current_span()
        assert span.attributes.get("key") == "value"

    yield from fx.gen(body).with_span("A")


def test_runs_continuations_after_the_region_under_the_restored_span():
    """runs continuations after the region under the restored span"""
    active: list[str | None] = [None]

    def context[T](run: Callable[[], T], fiber: fx.Fiber[Any, Any]) -> T:
        previous = active[0]
        span = fiber.get_ref(fx.tracer.ParentSpan)
        active[0] = None if span is None else span.span_id
        try:
            return run()
        finally:
            active[0] = previous

    tracer = Tracer(NativeSpan, context)
    seen: list[str | None] = []

    def record(_: object) -> None:
        seen.append(active[0])

    fx.run_blocking(
        fx.sync(lambda: None)
        .map(record)
        .with_parent_span(ExternalSpan(span_id="child", trace_id="trace"))
        .map(record)
        .with_parent_span(ExternalSpan(span_id="parent", trace_id="trace"))
        .with_tracer(tracer)
    )
    assert seen == ["child", "parent"]


@testing.effect
def test_should_allow_setting_the_parent_span_for_the_current_span():
    """should allow setting the parent span for the current span"""

    def body():
        span = yield from fx.current_span()
        assert _parent(span).span_id == "456"

    yield from (
        fx.gen(body)
        .with_span("A")
        .with_parent_span(ExternalSpan(trace_id="123", span_id="456", sampled=True))
    )


@testing.effect
def test_should_allow_enabling_disabling_the_tracer():
    """should allow enabling/disabling the tracer"""
    span = yield from fx.current_span().with_span("A").with_tracer_enabled(False)
    span_b = yield from fx.current_span().with_span("B").with_tracer_enabled(True)
    assert span.name == "A"
    assert span.span_id == "noop"
    assert span_b.name == "B"


@testing.effect
def test_should_include_timing_information_in_spans_when_true():
    """should include timing information in spans when true"""
    yield from testing.adjust(0.001)
    span = yield from fx.current_span().with_span("A").with_tracer_timing(True)
    assert span.status.start_time == 1_000_000


@testing.effect
def test_should_not_include_timing_information_in_spans_when_false():
    """should not include timing information in spans when false"""
    yield from testing.adjust(0.001)
    span = yield from fx.current_span().with_span("A").with_tracer_timing(False)
    assert span.status.start_time == 0


@testing.effect
def test_should_set_start_and_end_times_to_zero_when_timing_is_disabled():
    """should set start and end times to zero when timing is disabled"""

    def body():
        yield from testing.adjust(0.001)
        use_span = yield from fx.use_span("useSpan", fx.succeed)
        with_span = yield from fx.current_span().with_span("withSpan")
        times: list[tuple[int, int]] = []
        for status in (use_span.status, with_span.status):
            assert isinstance(status, Ended)
            times.append((status.start_time, status.end_time))
        assert times == [(0, 0), (0, 0)], "disabled span timing"

    yield from fx.gen(body).with_tracer_timing(False)


@testing.effect
def test_should_link_two_spans_together():
    """should link two spans together"""
    child_a = yield from fx.make_span("childA")
    child_b = yield from fx.make_span("childB")
    current = (
        yield from fx.current_span().with_span("A", links=[SpanLink(child_b)]).link_spans(child_a)
    )
    assert [link.span for link in current.links] == [child_a, child_b]


@testing.effect
def test_should_set_the_parent_trace_span_for_the_layer_constructor():
    """should set the parent trace span for the layer constructor"""

    def body():
        span = yield from fx.make_span("child")
        parent = _named(_parent(span))
        assert parent.name == "parent"
        assert "code.stacktrace" not in span.attributes
        assert "code.stacktrace" not in parent.attributes

    yield from fx.gen(body).pipe(
        fx.provide(layer.unwrap(fx.make_span_scoped("parent").map(layer.parent_span)))
    )


@testing.effect
def test_should_create_a_new_parent_trace_span_for_the_layer_constructor():
    """should create a new parent trace span for the layer constructor"""

    def body():
        span = yield from fx.make_span("child")
        parent = _named(_parent(span))
        assert parent.name == "parent"
        assert "code.stacktrace" not in parent.attributes

    yield from fx.gen(body).pipe(fx.provide(layer.span("parent")))


@testing.effect
def test_should_call_on_end_when_the_span_is_ending():
    """should call onEnd when the span is ending"""
    on_end_called = False

    def on_end(span: Span, _exit: object) -> fx.Effect[None]:
        def mark() -> None:
            nonlocal on_end_called
            assert span.name == "span"
            on_end_called = True

        return fx.sync(mark)

    span = yield from fx.current_span().pipe(fx.provide(layer.span("span", on_end=on_end)))
    assert span.name == "span"
    assert on_end_called


@testing.effect
def test_sets_the_trace_span_for_the_layer_constructor():
    """sets the trace span for the layer constructor"""
    on_end_called = False

    def construct():
        span = yield from fx.current_span()
        assert span.name == "span"
        assert "code.stacktrace" not in span.attributes

    def on_end(span: Span, _exit: object) -> fx.Effect[None]:
        def mark() -> None:
            nonlocal on_end_called
            assert span.name == "span"
            on_end_called = True

        return fx.sync(mark)

    built = layer.effect_discard(fx.gen(construct)).with_span("span", on_end=on_end)
    span = yield from fx.current_span().pipe(fx.provide(built)).option()
    assert span is None
    assert on_end_called


@testing.effect
def test_should_allow_disabling_span_propagation_via_noop_spans():
    """should allow disabling span propagation via noop spans"""
    span = yield from fx.current_span().with_span(
        "A", annotations=fx.Context.make(DisablePropagation, True)
    )
    span_b = yield from fx.current_span().with_span("B")
    assert span.name == "A"
    assert span.span_id == "noop"
    assert span_b.name == "B"


@testing.effect
def test_should_prevent_a_span_from_being_used_as_a_parent_span():
    """should prevent a span from being used as a parent span"""
    span = yield from (
        fx.current_span()
        .with_span("child")
        .with_span("disabled", annotations=fx.Context.make(DisablePropagation, True))
        .with_span("parent")
    )
    assert span.name == "child"
    assert _named(_parent(span)).name == "parent"
