"""Ports of the ``head``, ``reduce``, ``findFirst`` and ``findFirstFilter``
sections of Effect's ``Effect.test.ts``.

Each test's docstring is the Effect test title. Callbacks get the item only
(PARITY.md); the titles that read Effect's index argument enumerate the
items instead. ``head`` is a method, ``Option`` is ``Some`` / ``None``, and
a filter returns ``Ok`` / ``Err``.
"""

from typing import Never

import pyfect as fx
from pyfect import testing
from pyfect.exit import fail as exit_fail
from pyfect.result import Err, Ok, Result

# --- head -----------------------------------------------------------------------


@testing.effect
def test_head_returns_the_first_element():
    """returns the first element"""
    assert (yield from fx.succeed([1, 2, 3]).head()) == 1


@testing.effect
def test_head_fails_with_no_such_element_error_for_an_empty_iterable():
    """fails with NoSuchElementError for an empty iterable"""
    empty: list[int] = []
    error = yield from fx.succeed(empty).head().flip()
    assert isinstance(error, fx.NoSuchElementException)


@testing.effect
def test_head_preserves_the_source_failure():
    """preserves the source failure"""
    source: fx.Effect[list[int], str] = fx.fail("failure")
    assert (yield from source.head().flip()) == "failure"


# --- reduce ---------------------------------------------------------------------


@testing.effect
def test_reduce_runs_sequentially_from_left_to_right_and_passes_the_index():
    """runs sequentially from left to right and passes the index"""
    visited: list[str] = []

    def step(acc: int, indexed: tuple[int, int]) -> fx.Effect[int]:
        index, value = indexed

        def run() -> int:
            visited.append(f"{index}:{value}")
            return acc + value

        return fx.sync(run)

    result = yield from fx.reduce(enumerate([1, 2, 3, 4, 5]), lambda: 0, step)
    assert result == 15
    assert visited == ["0:1", "1:2", "2:3", "3:4", "4:5"]


@testing.effect
def test_reduce_stops_at_the_first_failure():
    """stops at the first failure"""
    visited: list[int] = []

    def step(acc: int, value: int) -> fx.Effect[int, str]:
        then: fx.Effect[int, str] = fx.fail("fail") if value == 3 else fx.succeed(acc + value)
        return fx.sync(lambda: visited.append(value)).and_then(then)

    ex = yield from fx.reduce([1, 2, 3, 4, 5], lambda: 0, step).exit()
    assert ex == exit_fail("fail")
    assert visited == [1, 2, 3]


@testing.effect
def test_reduce_returns_zero_for_an_empty_iterable():
    """returns zero for an empty iterable"""
    empty: list[int] = []
    assert (yield from fx.reduce(empty, lambda: 42, lambda acc, n: fx.succeed(acc + n))) == 42


@testing.effect
def test_reduce_evaluates_zero_lazily_for_each_run():
    """evaluates zero lazily for each run"""
    evaluations = 0

    def zero() -> list[int]:
        nonlocal evaluations
        evaluations += 1
        return []

    reduced = fx.reduce([1], zero, lambda acc, n: fx.succeed([*acc, n]))
    assert evaluations == 0
    assert (yield from reduced) == [1]
    assert (yield from reduced) == [1]
    assert evaluations == 2


# --- findFirst ------------------------------------------------------------------


@testing.effect
def test_find_first_returns_first_matching_element():
    """returns first matching element"""
    result = yield from fx.find_first([1, 2, 3, 4], lambda n: fx.succeed(n > 2))
    assert result == fx.Some(3)


@testing.effect
def test_find_first_returns_none_when_no_element_matches():
    """returns none when no element matches"""
    assert (yield from fx.find_first([1, 2, 3, 4], lambda n: fx.succeed(n > 10))) is None


@testing.effect
def test_find_first_short_circuits_on_first_match():
    """short-circuits on first match"""
    seen: list[int] = []

    def check(n: int) -> fx.Effect[bool]:
        def run() -> bool:
            seen.append(n)
            return n > 2

        return fx.sync(run)

    assert (yield from fx.find_first([1, 2, 3, 4], check)) == fx.Some(3)
    assert seen == [1, 2, 3]


# --- findFirstFilter ------------------------------------------------------------


@testing.effect
def test_find_first_filter_returns_first_successful_transformed_value():
    """returns first successful transformed value"""

    def even(n: int) -> fx.Effect[Result[str, None]]:
        return fx.succeed(Ok(f"n={n}") if n % 2 == 0 else Err(None))

    assert (yield from fx.find_first_filter([1, 2, 3, 4], even)) == fx.Some("n=2")


@testing.effect
def test_find_first_filter_passes_index_to_filter():
    """passes index to filter"""

    def third(indexed: tuple[int, int]) -> fx.Effect[Result[str, None]]:
        i, n = indexed
        return fx.succeed(Ok(f"{n}:{i}") if i == 2 else Err(None))

    assert (yield from fx.find_first_filter(enumerate([10, 11, 12]), third)) == fx.Some("12:2")


@testing.effect
def test_find_first_filter_returns_none_when_filter_never_succeeds():
    """returns none when filter never succeeds"""

    def never(_: int) -> fx.Effect[Result[Never, None]]:
        return fx.succeed(Err(None))

    assert (yield from fx.find_first_filter([1, 2, 3], never)) is None
