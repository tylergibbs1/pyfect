"""Tracing beyond the ``Tracer.test.ts`` ports: ``fn("name")``, spans and
forks, the tracer logger, sampling, propagation and the span options.
Expected values were printed by Effect under Node."""

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import pyfect as fx
from pyfect import layer, logger, testing
from pyfect.batching import Entry
from pyfect.tracer import (
    DisablePropagation,
    Ended,
    ExternalSpan,
    NativeSpan,
    NoopSpan,
    Span,
    SpanRequest,
    StackTrace,
    Tracer,
)


def _recording() -> tuple[Tracer, list[NativeSpan]]:
    spans: list[NativeSpan] = []

    def make(request: SpanRequest) -> NativeSpan:
        span = NativeSpan(request)
        spans.append(span)
        return span

    return Tracer(make), spans


def _native(span: Span) -> NativeSpan:
    assert isinstance(span, NativeSpan)
    return span


# --- fn("name") -------------------------------------------------------------------


@testing.effect
def test_a_named_fn_runs_each_call_in_a_span_with_its_options():
    @fx.fn("get_user", kind="server", attributes={"route": "/users"})
    def get_user(user_id: str):
        yield from fx.annotate_current_span("user.id", user_id)
        inner = yield from fx.current_span().with_span("query")
        return (yield from fx.current_span()), inner

    span, inner = yield from get_user("u1")
    assert span.name == "get_user"
    assert span.kind == "server"
    assert dict(span.attributes) == {"route": "/users", "user.id": "u1"}
    assert inner.parent is span
    assert isinstance(span.status, Ended)
    assert span.status.exit == fx.Success((span, inner))


@testing.effect
def test_a_named_fn_ends_its_span_with_the_failure():
    @fx.fn("fails")
    def fails():
        yield from fx.fail("boom")

    tracer, spans = _recording()
    exit_ = yield from fails().with_tracer(tracer).exit()
    assert isinstance(exit_, fx.Failure)
    assert exit_.cause.failures == ("boom",)
    frame = exit_.cause.annotations.get_unsafe(StackTrace)
    assert frame.name == "fails"
    assert frame.parent is not None
    assert frame.parent.name == "fails (definition)"
    status = spans[0].status
    assert isinstance(status, Ended)
    assert status.exit == exit_


@testing.effect
def test_a_named_fn_makes_a_new_span_per_call():
    @fx.fn("call")
    def call():
        return (yield from fx.current_span())

    first = yield from call()
    second = yield from call()
    assert first is not second
    assert first.parent is None


@testing.effect
def test_an_unnamed_fn_makes_no_span():
    @fx.fn
    def plain():
        return (yield from fx.current_span().option())

    assert (yield from plain()) is None


# --- spans and fibers ------------------------------------------------------------


@testing.effect
def test_a_forked_fiber_keeps_the_span_and_records_nothing_on_it_after_it_ended():
    def child_body():
        yield from fx.sleep(10)
        yield from fx.log("late")
        yield from fx.annotate_current_span("late", True)
        return (yield from fx.current_span())

    def parent_body():
        yield from fx.log("early")
        child = yield from fx.gen(child_body).fork_daemon()
        return (yield from fx.current_span()), child

    span, child = yield from fx.gen(parent_body).with_span("A")
    yield from testing.adjust(10)
    child_span = yield from child.join()

    assert child_span is span
    assert isinstance(span.status, Ended)
    assert [name for name, _, _ in _native(span).events] == ["early"]
    assert "late" not in span.attributes


@testing.effect
def test_the_tracer_logger_records_annotations_and_renders_non_text_messages_as_json():
    def body():
        yield from fx.log("a", 1)
        yield from fx.log({"x": 1}).annotate_logs("k", "v")
        yield from fx.log_error("bad", fx.cause.fail("oops"))
        return (yield from fx.current_span())

    span = _native((yield from fx.gen(body).with_span("A")))
    events = [(name, list(attributes)) for name, _, attributes in span.events]
    assert events == [
        ('[\n  "a",\n  1\n]', ["effect.fiberId", "effect.logLevel"]),
        ('{\n  "x": 1\n}', ["k", "effect.fiberId", "effect.logLevel"]),
        ("bad", ["effect.fiberId", "effect.logLevel", "effect.cause"]),
    ]
    assert span.events[2][2]["effect.logLevel"] == "ERROR"
    assert "oops" in str(span.events[2][2]["effect.cause"])


def test_the_tracer_logger_is_a_default_logger():
    assert logger.tracer_logger in fx.run_blocking(fx.CurrentLoggers())


# --- sampling and propagation ------------------------------------------------------


@testing.effect
def test_a_child_of_an_unsampled_span_is_unsampled_unless_told_otherwise():
    child = yield from fx.current_span().with_span("c").with_span("p", sampled=False)
    explicit = (
        yield from fx.current_span().with_span("c", sampled=True).with_span("p", sampled=False)
    )
    assert child.sampled is False
    assert explicit.sampled is True


@testing.effect
def test_a_disabled_tracer_makes_noop_spans_that_disable_propagation():
    span = yield from fx.current_span().with_span("x").with_tracer_enabled(False)
    assert isinstance(span, NoopSpan)
    assert span.span_id == span.trace_id == "noop"
    assert span.annotations.get(DisablePropagation) is True
    assert isinstance(span.status, Ended)


@testing.effect
def test_an_external_parent_that_disables_propagation_is_skipped():
    parent = ExternalSpan(
        span_id="e", trace_id="t", annotations=fx.Context.make(DisablePropagation, True)
    )
    span = yield from fx.current_span().with_span("y").with_parent_span(parent)
    assert span.parent is None


@testing.effect
def test_current_span_fails_and_current_parent_span_succeeds_under_an_external_span():
    parent = ExternalSpan(span_id="e", trace_id="t")
    error = yield from fx.current_span().with_parent_span(parent).flip()
    assert isinstance(error, fx.NoSuchElementException)
    assert (yield from fx.current_parent_span().with_parent_span(parent)) is parent
    outside = yield from fx.current_parent_span().flip()
    assert isinstance(outside, fx.NoSuchElementException)


@testing.effect
def test_span_options_attributes_win_over_annotate_spans():
    span = (
        yield from fx.current_span()
        .with_span("z", attributes={"a": 2})
        .annotate_spans({"a": 1, "b": 1})
    )
    assert list(span.attributes.items()) == [("a", 2), ("b", 1)]


@testing.effect
def test_link_spans_links_every_span_with_the_shared_attributes():
    first = yield from fx.make_span("first")
    second = yield from fx.make_span("second")
    span = (
        yield from fx.current_span().with_span("w").link_spans(first, second, attributes={"r": 1})
    )
    assert [(link.span, dict(link.attributes)) for link in span.links] == [
        (first, {"r": 1}),
        (second, {"r": 1}),
    ]


@testing.effect
def test_a_child_span_shares_its_parent_trace_id():
    parent = ExternalSpan(span_id="e", trace_id="trace-1")
    span = yield from fx.current_span().with_span("c").with_parent_span(parent)
    assert span.trace_id == "trace-1"


# --- scoped spans and layers -------------------------------------------------------------


@testing.effect
def test_with_span_scoped_ends_the_span_when_the_scope_closes():
    def body():
        span = yield from fx.current_span().with_span_scoped("scoped")
        assert not isinstance(span.status, Ended)
        return span

    span = yield from fx.scoped(fx.gen(body))
    assert isinstance(span.status, Ended)


@testing.effect
def test_a_layer_span_ends_with_the_failure_its_scope_closes_with():
    exits: list[fx.Exit[object, object]] = []

    def on_end(_span: Span, ex: fx.Exit[object, object]) -> fx.Effect[None]:
        return fx.sync(lambda: exits.append(ex))

    scope = fx.CloseableScope()
    context = yield from layer.span("startup", on_end=on_end).build_with_scope(scope)
    span = context.get(fx.tracer.ParentSpan)
    yield from scope.close(fx.exit.fail("down"))
    assert exits == [fx.exit.fail("down")]
    assert isinstance(span, NativeSpan)
    assert isinstance(span.status, Ended)
    assert span.status.exit == fx.exit.fail("down")


# --- the tracer context hook -------------------------------------------------------


def test_a_raising_context_hook_is_a_defect():
    boom = RuntimeError("hook")

    def context[T](run: Callable[[], T], fiber: fx.Fiber[Any, Any]) -> T:
        raise boom

    exit_ = fx.run_blocking_exit(fx.succeed(1).with_tracer(Tracer(NativeSpan, context)))
    assert exit_ == fx.exit.die(boom)


# --- what ended spans and scoped spans get ------------------------------------------


class _CountingSpan(NativeSpan):
    """A native span that counts every attribute and event it is given,
    ended or not, so a test can see what the runtime calls on an ended span."""

    __slots__ = ("calls",)

    def __init__(self, request: SpanRequest) -> None:
        super().__init__(request)
        self.calls: list[str] = []

    def attribute(self, key: str, value: object, /) -> None:
        self.calls.append(f"attribute {key}")
        super().attribute(key, value)

    def event(self, name: str, start_time: int, attributes: Any = None, /) -> None:
        self.calls.append(f"event {name}")
        super().event(name, start_time, attributes)


@testing.effect
def test_annotate_current_span_and_logs_leave_an_ended_span_alone():
    spans: list[_CountingSpan] = []

    def make(request: SpanRequest) -> _CountingSpan:
        spans.append(_CountingSpan(request))
        return spans[-1]

    def body():
        span = yield from fx.current_span()
        span.end(1, fx.Success(None))
        yield from fx.annotate_current_span("late", True)
        yield from fx.log("late")

    yield from fx.gen(body).with_span("ended").with_tracer(Tracer(make))
    assert spans[0].calls == []


@testing.effect
def test_an_ended_native_span_takes_no_links():
    other = yield from fx.make_span("other")
    span = _native((yield from fx.make_span("span")))
    span.end(1, fx.Success(None))
    span.add_links([fx.tracer.SpanLink(other)])
    assert span.links == []


@testing.effect
def test_inner_annotate_spans_wins_over_outer():
    span = (
        yield from fx.current_span()
        .with_span("s")
        .annotate_spans("k", "inner")
        .annotate_spans({"k": "outer", "o": 1})
    )
    assert dict(span.attributes) == {"k": "inner", "o": 1}


@testing.effect
def test_make_span_scoped_ends_its_span_however_an_interrupt_lands():
    for ops in range(1, 7):
        for prefix in range(3):
            for yields in range(5):
                tracer, spans = _recording()
                child: fx.Effect[object, Any, Any] = fx.scoped(
                    fx.make_span_scoped("scoped").and_then(fx.never)
                )
                for _ in range(prefix):
                    child = fx.void.and_then(child)

                def body(child: fx.Effect[object, Any, Any] = child, yields: int = yields):
                    fiber = yield from child.fork()
                    for _ in range(yields):
                        yield from fx.yield_now()
                    yield from fiber.interrupt()

                yield from (
                    fx.gen(body)
                    .with_tracer(tracer)
                    .pipe(fx.provide_service(fx.MaxOpsBeforeYield, ops))
                )
                label = f"ops {ops}, prefix {prefix}, yields {yields}"
                assert all(isinstance(s.status, Ended) for s in spans), label


# --- RequestResolver.with_span -------------------------------------------------------


@dataclass(frozen=True)
class _GetSpan(fx.Request[Span]):
    id: int


def _span_resolver(**options: Any) -> fx.RequestResolver[_GetSpan]:
    def run_all(entries: Sequence[Entry[_GetSpan]]):
        span = yield from fx.current_span().or_die()
        for entry in entries:
            entry.complete_unsafe(fx.Success(span))

    return fx.RequestResolver(fx.fn(run_all)).with_span("batch", **options)


@testing.effect
def test_a_traced_batch_links_each_caller_span_once():
    resolver = _span_resolver()
    spans = yield from fx.all(
        fx.request(_GetSpan(1), resolver),
        fx.request(_GetSpan(2), resolver),
        fx.request(_GetSpan(3), resolver).with_span("other"),
        concurrency="unbounded",
    ).with_span("caller")
    batch = spans[0]
    assert spans == (batch, batch, batch)
    assert [_native(_named_parent(link.span)).name for link in batch.links] == ["caller", "other"]
    assert dict(batch.attributes) == {"batchSize": 3}


@testing.effect
def test_a_batch_size_attribute_given_in_the_options_wins():
    batch = yield from fx.request(_GetSpan(1), _span_resolver(attributes={"batchSize": 9}))
    assert dict(batch.attributes) == {"batchSize": 9}


def _named_parent(span: fx.tracer.AnySpan) -> Span:
    assert not isinstance(span, ExternalSpan)
    return span
