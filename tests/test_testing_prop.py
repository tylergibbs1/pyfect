"""``testing.prop`` / ``effect_prop`` behaviours beyond @effect/vitest's
titles: what falsifies a property, what each run gets, and the test's
signature."""

import inspect

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect import testing


def test_returning_false_falsifies_and_shrinks() -> None:
    seen: list[int] = []

    @testing.prop(S.Int, runs=50, seed=1)
    def check(n: int) -> bool:
        seen.append(n)
        return n < 10

    with pytest.raises(testing.PropertyFalsifiedError):
        check()
    assert seen[-1] == 10


def test_an_effect_property_is_falsified_by_false_and_by_a_typed_failure() -> None:
    @testing.effect_prop(S.Int, runs=20, seed=1)
    def returns_false(n: int):
        return fx.succeed(n < 0 or n > 5)

    @testing.effect_prop(S.Int, runs=20, seed=1)
    def fails(n: int):
        return fx.fail(ValueError(n)) if n >= 3 else fx.void

    with pytest.raises(testing.PropertyFalsifiedError):
        returns_false()
    with pytest.raises(ValueError) as raised:
        fails()
    assert raised.value.args == (3,)


def test_each_run_gets_its_own_test_clock() -> None:
    times: list[float] = []

    @testing.effect_prop(S.Int, runs=3, seed=1)
    def check(_n: int):
        times.append((yield from fx.Clock()).now_unsafe())
        yield from testing.adjust(1_000)

    check()
    assert times == [0, 0, 0]


def test_the_test_takes_only_its_fixtures() -> None:
    @testing.effect_prop(S.Int, label=S.String)
    def check(services: object, n: int, label: str):
        yield from fx.void

    assert list(inspect.signature(check).parameters) == ["services"]


def test_inputs_must_fit_the_parameters() -> None:
    def one(n: int) -> None: ...

    with pytest.raises(TypeError, match="too few"):
        testing.prop(S.Int, S.Int)(one)
    with pytest.raises(TypeError, match="too few"):
        testing.prop(S.Int, n=S.Int)(one)
    with pytest.raises(TypeError, match="no parameter"):
        testing.prop(m=S.Int)(one)
