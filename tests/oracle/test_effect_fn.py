"""Ports of the ``Effect.fn`` and ``tracing`` sections of Effect's
``Effect.test.ts``.

Each test's docstring is the Effect test title. ``Effect.fn("name")(body)``
is ``@fx.fn("name")``; ``Effect.fn(body)`` is ``@fx.fn``.

Adapted, with the reason:

- "should proxy body length": Python functions have no ``length``; the
  decorated functions keep the body's signature (``inspect.signature``).

Omitted, with the reason:

- "should support pipeable arguments", "should support self with pipeable
  arguments": ``fn`` takes no pipeables; apply combinators to the effect
  the body returns or to the call's result. A decorated method binds
  ``self`` as any method does.
- ``StackCapture.test.ts`` (six titles on ``Error.stackTraceLimit``): a
  JavaScript stack costs an ``Error``; pyfect reads the caller's code
  object and line, which allocates no exception and has no limit to honour.

The ``tracing`` titles use ``run_sync_exit`` for ``runForkWith(...)`` plus
``pollUnsafe``; an ``Exit`` is not an effect in pyfect, so "reuses the
original exit" checks that the failure keeps the cause it was given.
"""

import gc
import inspect
import weakref

import pyfect as fx
from pyfect import testing
from pyfect.cause import die
from pyfect.tracer import CurrentStackFrame, StackFrame, StackTrace


class _Input:
    pass


@testing.effect
def test_does_not_retain_arguments_in_the_stack_frame_of_forked_fibers():
    """does not retain arguments in the stack frame of forked fibers"""

    @fx.fn("start")
    def start(_input: _Input):
        yield from fx.never.fork()

    reference: list[weakref.ref[_Input]] = []

    def make_input() -> _Input:
        made = _Input()
        reference.append(weakref.ref(made))
        return made

    yield from start(make_input())
    gc.collect()
    assert reference[0]() is None


def test_should_proxy_body_length():
    """should proxy body length"""

    @fx.fn
    def traced(a: str, b: int):
        yield from fx.void
        return len(a) + b

    @fx.fn("named")
    def named(a: str, b: int, c: bool):
        yield from fx.void
        return len(a) + b if c else b

    assert len(inspect.signature(traced).parameters) == 2
    assert len(inspect.signature(named).parameters) == 3


@testing.effect
def test_should_reuse_the_definition_frame_across_calls():
    """should reuse the definition frame across calls"""

    @fx.fn("traced")
    def traced():
        return (yield from CurrentStackFrame())

    first = yield from traced()
    second = yield from traced()
    assert first is not None and second is not None
    assert first.parent is not None and second.parent is not None
    assert first.parent.name == "traced (definition)"
    assert "test_effect_fn.py" in (first.parent.stack() or "")
    assert first.parent.stack() == second.parent.stack()
    assert first.stack() != second.stack()


def test_terminal_root_failure_captures_stack_frame():
    """terminal root failure captures stack frame"""
    frame = StackFrame("root frame", lambda: None, None)
    ex = fx.run_sync_exit(fx.fail("boom"), context=fx.Context.make(CurrentStackFrame, frame))
    assert isinstance(ex, fx.Failure)
    assert ex.cause.annotations.get_option(StackTrace) == fx.Some(frame)


@testing.effect
def test_caught_sandboxed_failure_captures_stack_frame():
    """caught sandboxed failure captures stack frame"""
    cause = yield from fx.fail_cause(die(Exception("boom"))).with_span("test span").sandbox().flip()
    assert cause.annotations.unsafe_get(StackTrace).name == "test span"


def test_failure_without_a_current_frame_has_no_stack_annotation_and_reuses_the_original_exit():
    """failure without a current frame has no stack annotation and reuses the original exit"""
    failure = fx.cause.fail("boom")
    ex = fx.run_sync_exit(fx.fail_cause(failure))
    assert isinstance(ex, fx.Failure)
    assert ex.cause is failure
    assert ex.cause.annotations.get_option(StackTrace) is None
