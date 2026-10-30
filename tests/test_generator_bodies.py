"""``@fx.fn`` (Effect's ``fnUntraced``) and ``@fx.gen`` take generator
functions: a ``def`` with no ``yield`` (an effect called without
``yield from``) is rejected where it is decorated, not when the effect runs.

``@fx.fn("name")`` is Effect's ``Effect.fn("name")``, whose body may also
return an effect (``isEffect(iter) ? iter : fromIteratorUnsafe(iter)``), so
it is checked when it runs. Printed by Effect 4.0.7 under Node:
``Effect.fn("traced")((n) => Effect.map(Effect.currentSpan, (s) => [n, s.name]))(1)``
gives ``[1, "traced"]``, and ``Effect.fn("bad")(() => 1)()`` dies with a
``TypeError``."""

from collections.abc import Callable, Generator
from typing import Any

import pytest

import pyfect as fx


def _no_yield() -> int:
    fx.log_info("hello")  # forgotten yield from
    return 1


@pytest.mark.parametrize(
    "decorate",
    [fx.fn, fx.gen],
    ids=["fn", "gen"],
)
def test_a_function_without_yield_is_rejected_when_decorated(
    decorate: Callable[[Any], object],
):
    with pytest.raises(TypeError, match=r"_no_yield is not a generator function.*yield from"):
        decorate(_no_yield)


def test_a_body_that_returns_no_generator_dies_with_a_type_error_when_run():
    not_a_generator: Callable[[], Any] = lambda: 1  # noqa: E731
    exit = fx.run_sync_exit(fx.gen(not_a_generator))
    assert isinstance(exit, fx.Failure)
    defect = exit.cause.squash()
    assert isinstance(defect, TypeError)
    assert "generator" in str(defect)


def _plus_one(n: int) -> Generator[fx.Effect[int], int, int]:
    value = yield from fx.succeed(n)
    return value + 1


def test_a_lambda_returning_a_generator_still_works():
    assert fx.run_sync(fx.gen(lambda: _plus_one(1))) == 2


def test_a_traced_fn_body_may_return_an_effect_that_runs_in_its_span():
    @fx.fn("traced")
    def traced(n: int) -> fx.Effect[tuple[int, str], fx.NoSuchElementException]:
        return fx.current_span().map(lambda span: (n, span.name))

    assert fx.run_sync(traced(1).or_die()) == (1, "traced")


def test_a_traced_fn_body_runs_only_when_its_effect_runs():
    calls: list[int] = []

    @fx.fn("traced")
    def traced() -> fx.Effect[int]:
        calls.append(1)
        return fx.succeed(len(calls))

    effect = traced()
    assert calls == []
    assert fx.run_sync(effect.zip(effect)) == (1, 2)


def test_a_traced_fn_body_that_returns_neither_dies_with_a_type_error():
    @fx.fn("bad")
    def bad() -> fx.Effect[int]:
        return 1  # pyright: ignore[reportReturnType]

    exit = fx.run_sync_exit(bad())
    assert isinstance(exit, fx.Failure)
    defect = exit.cause.squash()
    assert isinstance(defect, TypeError)
    assert "bad" in str(defect)
    assert "yield from" in str(defect)
