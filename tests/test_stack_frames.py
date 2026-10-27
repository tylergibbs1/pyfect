"""Stack frames recorded on failures: which frame each reason gets, and how
``Cause.pretty`` prints them. Expected values were printed by Effect's
source under Node (``withSpan``, ``withSpanScoped``, ``withParentSpan``,
``Effect.fn``, ``race``, child interruption)."""

import re
from typing import Any

import pyfect as fx
from pyfect import testing
from pyfect.cause import Interrupt, Reason, reason_annotations
from pyfect.tracer import (
    CurrentStackFrame,
    ExternalSpan,
    InterruptorStackTrace,
    StackFrame,
    StackTrace,
)


def _frames(reason: Reason[Any]) -> tuple[list[str], list[str]]:
    """The names of the reason's StackTrace and InterruptorStackTrace chains."""
    annotations = reason_annotations(reason)

    def names(frame: StackFrame | None) -> list[str]:
        out: list[str] = []
        while frame is not None:
            out.append(frame.name)
            frame = frame.parent
        return out

    trace = annotations.get_option(StackTrace)
    interruptor = annotations.get_option(InterruptorStackTrace)
    return (
        names(trace.value if trace else None),
        names(interruptor.value if interruptor else None),
    )


def _cause(ex: fx.Exit[Any, Any]) -> fx.Cause[Any]:
    assert isinstance(ex, fx.Failure)
    return ex.cause


@testing.effect
def test_a_failure_records_the_innermost_span_and_its_parents():
    ex = yield from fx.fail("x").with_span("inner").with_span("outer").exit()
    assert [_frames(r) for r in _cause(ex).reasons] == [(["inner", "outer"], [])]


@testing.effect
def test_a_failure_keeps_its_frame_through_finalizers_and_outer_spans():
    ex = yield from (
        fx.fail("boom")
        .ensuring(fx.void)
        .with_span("a")
        .on_exit(lambda _: fx.void)
        .with_span("b")
        .exit()
    )
    assert [_frames(r) for r in _cause(ex).reasons] == [(["a", "b"], [])]


@testing.effect
def test_a_new_failure_records_the_span_it_is_raised_in():
    ex = yield from (
        fx.fail("boom").with_span("a").catch_all(lambda e: fx.fail(e + "!")).with_span("b").exit()
    )
    cause = _cause(ex)
    assert cause.failures == ("boom!",)
    assert [_frames(r) for r in cause.reasons] == [(["b"], [])]


@testing.effect
def test_a_failing_finalizer_records_its_own_span():
    ex = (
        yield from fx.fail("x")
        .with_span("a")
        .ensuring(fx.die(ValueError("fin")))
        .with_span("b")
        .exit()
    )
    assert [_frames(r) for r in _cause(ex).reasons] == [(["a", "b"], []), (["b"], [])]


@testing.effect
def test_map_error_keeps_the_frame():
    ex = yield from fx.fail("x").with_span("a").map_error(lambda e: e + "m").with_span("b").exit()
    cause = _cause(ex)
    assert cause.failures == ("xm",)
    assert [_frames(r) for r in cause.reasons] == [(["a", "b"], [])]


@testing.effect
def test_defects_and_raised_exceptions_record_the_span():
    def throw() -> None:
        raise ValueError("t")

    died = yield from fx.die(ValueError("d")).with_span("s").exit()
    raised = yield from fx.sync(throw).with_span("s").exit()
    assert [_frames(r) for r in _cause(died).reasons] == [(["s"], [])]
    assert [_frames(r) for r in _cause(raised).reasons] == [(["s"], [])]


@testing.effect
def test_with_span_scoped_records_its_frame():
    ex = yield from fx.scoped(fx.fail("x").with_span_scoped("sc")).exit()
    assert [_frames(r) for r in _cause(ex).reasons] == [(["sc"], [])]


@testing.effect
def test_an_external_parent_span_adds_no_frame():
    parent = ExternalSpan(span_id="1", trace_id="2", sampled=True)
    ex = yield from fx.fail("x").with_parent_span(parent).exit()
    assert [_frames(r) for r in _cause(ex).reasons] == [([], [])]


@testing.effect
def test_a_frame_without_a_location_prints_its_name_alone():
    ex = yield from fx.fail("x").with_span("nostack", capture_stack_trace=False).exit()
    assert _cause(ex).pretty() == "pyfect.cause.UnhandledError: 'x'\n    at nostack"


@testing.effect
def test_a_named_fn_records_its_call_and_definition_frames():
    @fx.fn("named")
    def named():
        return (yield from fx.fail("q"))

    ex = yield from named().exit()
    cause = _cause(ex)
    assert [_frames(r) for r in cause.reasons] == [(["named", "named (definition)"], [])]
    lines = cause.pretty().splitlines()
    assert re.fullmatch(r"    at named \(.*test_stack_frames\.py:\d+\)", lines[1])
    assert re.fullmatch(r"    at named \(definition\) \(.*test_stack_frames\.py:\d+\)", lines[2])


@testing.effect
def test_a_bare_fn_records_no_frame():
    @fx.fn
    def untraced():
        return (yield from CurrentStackFrame())

    assert (yield from untraced()) is None


@testing.effect
def test_an_interrupted_fiber_records_its_frame_and_the_interruptors_once():
    target = yield from (
        fx.never.on_exit(lambda _: fx.void)
        .ensuring(fx.void)
        .with_span("inner")
        .with_span("outer")
        .fork(start_immediately=True)
    )
    yield from target.interrupt().with_span("interruptor")
    ex = yield from target.await_exit()
    cause = _cause(ex)
    # Effect repeats this reason once per handler it unwinds through; pyfect
    # records each interrupting fiber and frame once.
    assert [_frames(r) for r in cause.reasons] == [(["inner", "outer"], ["interruptor"])]
    pretty = cause.pretty()
    assert "    at inner (" in pretty
    assert re.search(r"interrupted by fiber #\d+\n    at interruptor \(.*test_stack_frames", pretty)


@testing.effect
def test_a_race_loser_records_the_racing_fibers_frame():
    exits: list[fx.Exit[Any, Any]] = []
    loser = fx.never.on_exit(lambda ex: fx.sync(lambda: exits.append(ex))).with_span("loser")
    yield from loser.race(fx.succeed(1)).with_span("racer")
    assert [_frames(r) for r in _cause(exits[0]).reasons] == [(["loser", "racer"], ["racer"])]


@testing.effect
def test_children_interrupted_when_their_parent_ends_record_their_own_frame():
    exits: list[fx.Exit[Any, Any]] = []

    @fx.fn
    def parent():
        yield from fx.never.on_exit(lambda ex: fx.sync(lambda: exits.append(ex))).fork(
            start_immediately=True
        )

    fiber = yield from parent().with_span("parent").fork()
    yield from fiber.await_exit()
    reasons = _cause(exits[0]).reasons
    assert [_frames(r) for r in reasons] == [(["parent"], [])]
    assert isinstance(reasons[0], Interrupt)


@testing.effect
def test_with_span_records_the_call_site_lazily():
    calls: list[int] = []

    def location() -> str:
        calls.append(1)
        return "at here (app.py:3)"

    frame = yield from CurrentStackFrame().with_span("lazy", capture_stack_trace=location)
    assert frame is not None
    assert calls == []
    assert frame.stack() == "at here (app.py:3)"

    default = yield from CurrentStackFrame().with_span("site")
    assert default is not None
    assert re.fullmatch(
        r"at test_with_span_records_the_call_site_lazily \(.*test_stack_frames\.py:\d+\)",
        default.stack() or "",
    )


def test_annotations_take_part_in_equality_but_not_the_hash():
    frame = StackFrame("f", lambda: None)
    plain = fx.cause.fail("x")
    annotated = plain.annotate(fx.Context.make(StackTrace, frame))
    assert plain != annotated
    assert hash(plain.reasons[0]) == hash(annotated.reasons[0])
    assert plain + annotated == fx.Cause((*plain.reasons, *annotated.reasons))
    assert (
        annotated.annotate(fx.Context.make(StackTrace, StackFrame("g", lambda: None))) is annotated
    )
    overwritten = annotated.annotate(
        fx.Context.make(StackTrace, StackFrame("g", lambda: None)), overwrite=True
    )
    assert overwritten.annotations.unsafe_get(StackTrace).name == "g"
