"""`fx.all` takes what Effect's `Effect.all` takes: the effects as arguments, one iterable of
them (a list, a tuple, a generator), or one mapping of them (Effect's struct).

An iterable gives a tuple of values in order, as `fx.all(*effects)` does; a mapping gives a
dict under the same keys, as `fx.all_dict(mapping)` does. Types are pinned in
`tests/type_checks.py`.
"""

from __future__ import annotations

import pytest

import pyfect as fx
from pyfect.result import Err, Ok


def test_a_list_gives_a_tuple_in_order():
    assert fx.run_sync(fx.all([fx.succeed(1), fx.succeed(2)])) == (1, 2)


def test_a_tuple_gives_a_tuple_in_order():
    assert fx.run_sync(fx.all((fx.succeed(1), fx.succeed("a")))) == (1, "a")


def test_a_generator_is_read_once_when_called():
    effects = (fx.succeed(n) for n in range(3))
    program = fx.all(effects)
    assert fx.run_sync(program) == (0, 1, 2)
    assert fx.run_sync(program) == (0, 1, 2)


def test_an_empty_list_gives_an_empty_tuple():
    empty: list[fx.Effect[int]] = []
    assert fx.run_sync(fx.all(empty)) == ()


def test_a_dict_gives_a_dict_under_the_same_keys():
    program = fx.all({"a": fx.succeed(1), "b": fx.succeed("x")})
    assert fx.run_sync(program) == {"a": 1, "b": "x"}


def test_the_options_apply_to_a_list():
    failing: fx.Effect[int, str] = fx.fail("no")
    program = fx.all([fx.succeed(1), failing], mode="result", concurrency=2)
    assert fx.run_sync(program) == (Ok(1), Err("no"))
    assert fx.run_sync(fx.all([fx.succeed(1)], discard=True)) is None


def test_the_options_apply_to_a_dict():
    failing: fx.Effect[int, str] = fx.fail("no")
    assert fx.run_sync(fx.all({"a": failing}, mode="result")) == {"a": Err("no")}
    assert fx.run_sync(fx.all({"a": fx.succeed(1)}, discard=True)) is None


def test_a_list_of_non_effects_names_the_bad_index():
    with pytest.raises(TypeError, match=r"^effects\[1\] must be an Effect, got int: 2$"):
        fx.all([fx.succeed(1), 2])  # pyright: ignore[reportArgumentType, reportCallIssue]


def test_a_list_among_other_arguments_says_to_pass_one_or_the_other():
    with pytest.raises(TypeError) as raised:
        fx.all([fx.succeed(1)], fx.succeed(2))  # pyright: ignore[reportArgumentType, reportCallIssue]
    assert str(raised.value).startswith("effects[0] must be an Effect, got list: ")
    assert str(raised.value).endswith(
        "(pass the effects as arguments, fx.all(a, b), or as one list, fx.all([a, b]))"
    )
