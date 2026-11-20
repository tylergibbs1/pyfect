"""An `fx.run_*` call (or any combinator taking an effect) given something close to an effect
says what to write instead.

`fx.sync(f)` was the only hint, and it led the wrong way for an `@fx.fn` function that was not
called and for a generator function that was not decorated (`fx.sync(greet)` succeeds with an
unrun effect). pyright rejects all of these first; this is the runtime message.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Generator
from typing import Any

import pytest

import pyfect as fx
from pyfect import stream


@fx.fn
def greet(name: str):
    yield from fx.void
    return f"hi {name}"


@fx.fn
def ping():
    yield from fx.void
    return "pong"


@fx.fn_untraced
def greet_untraced(name: str):
    yield from fx.void
    return f"hi {name}"


def plain_gen() -> Generator[fx.Effect[None], object, int]:
    yield from fx.void
    return 1


def _sync(value: Any) -> object:
    return fx.run_sync(value)


def _blocking(value: Any) -> object:
    return fx.run_blocking(value)


def _blocking_exit(value: Any) -> object:
    return fx.run_blocking_exit(value)


def _async(value: Any) -> object:
    return asyncio.run(fx.run_async(value))


RUNS: list[Callable[[Any], object]] = [_sync, _blocking, _blocking_exit, _async]


def _message(run: Callable[[Any], object], value: object) -> str:
    with pytest.raises(TypeError) as raised:
        run(value)
    return str(raised.value)


@pytest.mark.parametrize("run", RUNS)
def test_an_uncalled_fn_function_says_to_call_it(run: Callable[[Any], object]):
    message = _message(run, greet)
    assert message.startswith("eff must be an Effect, got function: ")
    assert message.endswith("(greet is an @fx.fn function: call it to get its effect, greet(...))")


def test_an_uncalled_fn_function_without_parameters_shows_the_empty_call():
    assert _message(_sync, ping).endswith(
        "(ping is an @fx.fn function: call it to get its effect, ping())"
    )


def test_an_uncalled_fn_untraced_function_says_to_call_it():
    assert _message(_sync, greet_untraced).endswith(
        "(greet_untraced is an @fx.fn function: call it to get its effect, greet_untraced(...))"
    )


@pytest.mark.parametrize("run", RUNS)
def test_a_plain_generator_function_says_to_decorate_it(run: Callable[[Any], object]):
    message = _message(run, plain_gen)
    assert message.startswith("eff must be an Effect, got function: ")
    assert message.endswith(
        "(plain_gen is a generator function: decorate it with @fx.gen, "
        "or with @fx.fn when it takes arguments)"
    )


@pytest.mark.parametrize("run", RUNS)
def test_a_generator_object_says_to_decorate_its_function(run: Callable[[Any], object]):
    generator = plain_gen()
    message = _message(run, generator)
    assert message.startswith("eff must be an Effect, got generator: ")
    assert message.endswith(
        "(plain_gen() made a generator, not an effect: decorate plain_gen with @fx.gen, "
        "or with @fx.fn when it takes arguments)"
    )
    generator.close()


@pytest.mark.parametrize("run", RUNS)
def test_a_stream_points_to_run_collect(run: Callable[[Any], object]):
    message = _message(run, stream.make(1, 2))
    assert message.startswith("eff must be an Effect, got Stream: ")
    assert message.endswith(
        "(a Stream is not an Effect: stream.run_collect() is an effect giving its items)"
    )


def test_a_plain_function_keeps_the_sync_hint():
    assert _message(_sync, print).endswith("(to run a function, pass fx.sync(f) or fx.suspend(f))")


def test_the_hints_apply_to_every_effect_parameter():
    with pytest.raises(TypeError, match=r"^that must be an Effect.*call it to get its effect"):
        fx.void.zip(greet)  # pyright: ignore[reportArgumentType]
