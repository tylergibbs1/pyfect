"""Pipeables after an ``fn`` body (Effect's ``Effect.fn(body, ...pipeables)``
and ``Effect.fnUntraced``), with results printed by Effect 4.0.6 under
Node: each pipeable gets the previous result, and the call's arguments when
it takes them; a named function's span and frames cover what the pipeables
add; a result that is not an effect comes back as it is."""

import pytest

import pyfect as fx
from pyfect import testing
from pyfect.tracer import CurrentStackFrame


def _identity(n: int):
    yield from fx.void
    return n


@testing.effect
def test_pipeables_run_in_order_each_on_the_previous_result():
    f = fx.fn_untraced(
        _identity,
        lambda eff: eff.map(lambda x: x + 1),
        lambda eff, n: eff.map(lambda x: (x, n)),
    )
    assert (yield from f(1)) == (2, 1)


@testing.effect
def test_a_named_functions_frames_cover_what_the_pipeables_add():
    def frame_names(eff: fx.Effect[int]) -> fx.Effect[tuple[int, str | None, str | None]]:
        def read(n: int):
            frame = yield from CurrentStackFrame()
            assert frame is not None and frame.parent is not None
            return n, frame.name, frame.parent.name

        return eff.flat_map(fx.fn_untraced(read))

    f = fx.fn("named")(_identity, frame_names)
    assert (yield from f(1)) == (1, "named", "named (definition)")


@testing.effect
def test_a_named_functions_span_covers_what_the_pipeables_add():
    def body():
        yield from fx.void
        return 1

    f = fx.fn("spanned")(body, lambda eff: eff.flat_map(lambda _: fx.current_span()))
    span = yield from f()
    assert span.name == "spanned"


def test_a_result_that_is_not_an_effect_comes_back_as_it_is():
    named = fx.fn("named")(_identity, lambda _eff, n: n * 10)
    untraced = fx.fn_untraced(_identity, lambda _eff, n: n * 10)
    assert named(4) == 40
    assert untraced(4) == 40


@testing.effect
def test_a_pipeable_with_a_default_gets_only_the_effect():
    def scaled(eff: fx.Effect[int], factor: int = 3) -> fx.Effect[int]:
        return eff.map(lambda x: x * factor)

    f = fx.fn(_identity, scaled)
    assert (yield from f(2)) == 6


@testing.effect
def test_a_pipeable_gets_keyword_arguments():
    def body(*, key: str):
        yield from fx.void
        return len(key)

    def labelled(eff: fx.Effect[int], *, key: str) -> fx.Effect[str]:
        return eff.map(lambda n: f"{key}={n}")

    f = fx.fn_untraced(body, labelled)
    assert (yield from f(key="abc")) == "abc=3"


@testing.effect
def test_a_curried_combinator_is_a_pipeable():
    class Boom(fx.TaggedError): ...

    def body(fail: bool):
        if fail:
            yield from fx.fail(Boom())
        return "ok"

    f = fx.fn("caught")(body, fx.catch_tag(Boom, lambda _: fx.succeed("caught")))
    assert (yield from f(True)) == "caught"
    assert (yield from f(False)) == "ok"


def test_span_options_need_a_name():
    # Effect takes span options only after a name (``Effect.fn(name, options)``);
    # given with a body they would be dropped silently.
    with pytest.raises(TypeError, match="span options"):
        fx.fn(_identity, kind="server")  # pyright: ignore[reportArgumentType]
