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
- "should reuse the definition frame across calls" and the ``tracing``
  titles ("terminal root failure captures stack frame", "caught sandboxed
  failure captures stack frame", "failure without a current frame has no
  stack annotation and reuses the original exit"): pyfect records no stack
  frames and causes carry no annotations.
"""

import gc
import inspect
import weakref

import pyfect as fx
from pyfect import testing


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
