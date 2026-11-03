"""Ports of ``@effect/vitest``'s property tests (``index.test.ts`` "property
testing" and "property failures", the two ``it.effect.prop`` titles of its
layer block, and ``arbitrary-configuration.test.ts``) to ``testing.prop`` /
``effect_prop`` / ``live_prop``.

``it.prop(name, [A, B], ([a, b]) => ...)`` is ``@testing.prop(A, B)`` on
``def test(a, b)``; the keyed form ``{ a: A }`` is ``prop(a=A)``. An
``Arbitrary`` is a Hypothesis strategy, ``Arbitrary.schema(s)`` is
``S.to_strategy(s)``, ``{ arbitrary: { runs, seed } }`` is ``runs=`` /
``seed=``, and ``Arbitrary.configureGlobal`` is a Hypothesis settings
profile. A ``fails: true`` test is run inside a test that expects it to
fail.

Adapted, with the reason:

- "shrinks synchronous defects" / "shrinks Effect defects": Effect's
  expected values ``[8, 1]`` are fast-check's draws for its seed; here the
  last value tried is the shrunk minimum, ``1``.
- The ``arbitrary-configuration`` titles draw ``S.Int`` where Effect draws
  ``Schema.Boolean``: Hypothesis stops once it has tried every value, which
  for a boolean is two runs, while fast-check repeats values.
"""

import math
from collections.abc import Iterator

import hypothesis
import pytest
from hypothesis import strategies as st

import pyfect as fx
from pyfect import layer, testing
from pyfect import schema as S
from pyfect.testing import Services

real_number = S.Finite
text_arbitrary = S.to_strategy(S.Literals(["a", "b"]))


@testing.prop(S.String, S.Int)
def test_schema_with_array(text: object, count: object) -> bool:
    """schema with array"""
    return isinstance(text, str) and isinstance(count, int)


@testing.prop(text=S.String, count=S.Int)
def test_schema_with_object(text: object, count: object) -> bool:
    """schema with object"""
    return isinstance(text, str) and isinstance(count, int)


def test_schema_and_arbitrary_with_array() -> None:
    """Schema and Arbitrary with array"""
    runs: list[tuple[int, str]] = []

    @testing.prop(S.Int, text_arbitrary, runs=5, seed=1)
    def check(count: int, text: str) -> None:
        runs.append((count, text))
        assert isinstance(count, int)
        assert text in ("a", "b")

    check()
    assert len(runs) == 5


def test_schema_and_arbitrary_with_object() -> None:
    """Schema and Arbitrary with object"""
    runs: list[tuple[int, str]] = []

    @testing.effect_prop(count=S.Int, text=text_arbitrary, runs=5, seed=2)
    def check(count: int, text: str):
        def record() -> None:
            runs.append((count, text))
            assert isinstance(count, int)
            assert text in ("a", "b")

        return fx.sync(record)

    check()
    assert len(runs) == 5


@testing.prop(real_number, S.Int)
def test_symmetry(a: float, b: int) -> bool:
    """symmetry"""
    return a + b == b + a


@testing.prop(a=real_number, b=S.Int)
def test_symmetry_with_object(a: float, b: int) -> bool:
    """symmetry with object"""
    return a + b == b + a


@testing.live_prop(value=S.Int)
def test_live_schema_with_object(value: object):
    """schema with object (``it.live.prop``)"""
    return fx.sync(lambda: isinstance(value, int))


def test_schema_with_arbitrary_options() -> None:
    """schema with Arbitrary options"""
    runs: list[tuple[str, int]] = []

    @testing.effect_prop(S.String, S.Int, runs=5, seed=3)
    def check(text: str, count: int):
        def record() -> None:
            runs.append((text, count))
            assert isinstance(text, str)
            assert isinstance(count, int)

        return fx.sync(record)

    check()
    assert len(runs) == 5


@testing.effect_prop(real_number, S.Int)
def test_effect_symmetry(a: float, b: int):
    """symmetry (``it.effect.prop``)"""
    yield from fx.void
    assert a + b == b + a


@testing.effect_prop(a=real_number, b=S.Int)
def test_effect_symmetry_with_object(a: float, b: int):
    """symmetry with object (``it.effect.prop``)"""
    yield from fx.void
    assert a + b == b + a


@testing.effect_prop(a=S.String, b=S.String, c=S.String)
def test_should_detect_the_substring(a: str, b: str, c: str):
    """should detect the substring"""
    yield from fx.Scope()
    assert b in a + b + c


# --- property failures ---------------------------------------------------------------

Input = S.Int.check(S.is_between(minimum=1, maximum=1_000))


def test_rejects_effect_returns_from_synchronous_properties() -> None:
    """rejects Effect returns from synchronous properties"""

    @testing.prop(S.Int)  # pyright: ignore[reportArgumentType]
    def check(_n: int):
        return fx.fail("must not silently pass")

    with pytest.raises(TypeError, match=r"use testing\.effect_prop"):
        check()


def test_shrinks_synchronous_defects() -> None:
    """shrinks synchronous defects"""
    values: list[int] = []

    @testing.prop(Input, runs=1, seed=4)
    def check(value: int) -> None:
        values.append(value)
        raise RuntimeError("property defect")

    with pytest.raises(RuntimeError, match="property defect"):
        check()
    assert values[-1] == 1


def test_shrinks_effect_defects() -> None:
    """shrinks Effect defects"""
    values: list[int] = []

    @testing.effect_prop(Input, runs=1, seed=4)
    def check(value: int):
        def record() -> None:
            values.append(value)
            assert value == 0

        return fx.sync(record)

    with pytest.raises(AssertionError):
        check()
    assert values[-1] == 1


def test_preserves_interruption() -> None:
    """preserves interruption"""
    runs: list[int] = []

    @testing.effect_prop(Input, runs=1, seed=4)
    def check(value: int):
        runs.append(value)
        return fx.interrupt()

    with pytest.raises(fx.Interrupted):
        check()
    assert len(runs) == 1


def test_interrupts_property_checking_on_timeout() -> None:
    """interrupts property checking on timeout"""
    events: list[str] = []

    @testing.effect_prop(S.Literal("value"), runs=1, timeout=0.01)
    def check(_value: str):
        return fx.acquire_use_release(
            fx.sync(lambda: events.append("started")),
            lambda _: fx.never,
            lambda _a, _e: fx.sync(lambda: events.append("released")),
        )

    with pytest.raises(testing.TestTimeoutError):
        check()
    assert events == ["started", "released"]


# --- in a layer ----------------------------------------------------------------------


class Foo(fx.Tag[str]): ...


foo = testing.layer_fixture(layer.succeed(Foo, "foo"))


@testing.effect_prop(real_number, runs=200)
def test_layer_adds_context(foo: Services[Foo], num: float):
    """adds context (``it.effect.prop`` in ``layer(Foo.layer)``)"""
    assert (yield from Foo()) == "foo"
    return not math.isnan(num)


@testing.effect_prop(S.Int, runs=5, seed=5)
def test_layer_adds_context_with_a_schema_property(foo: Services[Foo], value: int):
    """adds context with a Schema property"""
    assert (yield from Foo()) == "foo"
    assert isinstance(value, int)


# --- arbitrary-configuration.test.ts ---------------------------------------------------


@pytest.fixture
def seven_runs() -> Iterator[None]:
    hypothesis.settings.register_profile("pyfect-seven-runs", max_examples=7)
    previous = hypothesis.settings.get_current_profile_name()
    hypothesis.settings.load_profile("pyfect-seven-runs")
    yield
    hypothesis.settings.load_profile(previous)


def test_uses_global_defaults_in_plain_properties(seven_runs: None) -> None:
    """uses global defaults in plain properties"""
    runs: list[int] = []

    @testing.prop(S.Int)
    def check(n: int) -> None:
        runs.append(n)

    check()
    assert len(runs) == 7


def test_uses_global_defaults_in_effect_properties(seven_runs: None) -> None:
    """uses global defaults in Effect properties"""
    runs: list[int] = []

    @testing.effect_prop(S.Int)
    def check(n: int):
        return fx.sync(lambda: runs.append(n))

    check()
    assert len(runs) == 7


def test_lets_a_property_override_the_run_count(seven_runs: None) -> None:
    """lets a property override the run count"""
    runs: list[int] = []

    @testing.prop(S.Int, runs=2)
    def check(n: int) -> None:
        runs.append(n)

    check()
    assert len(runs) == 2


@pytest.fixture
def seven_run_counter(seven_runs: None) -> Iterator[list[int]]:
    runs: list[int] = []
    yield runs
    assert len(runs) == 7


@testing.effect_prop(st.integers())
def test_uses_global_defaults_inside_a_layer(
    foo: Services[Foo], seven_run_counter: list[int], n: int
):
    """uses global defaults inside a layer"""
    assert (yield from Foo()) == "foo"
    seven_run_counter.append(n)
