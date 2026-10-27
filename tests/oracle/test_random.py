"""Ports of Effect's ``Random.test.ts``. Each test's docstring is the Effect
test title. Effect's ``assert.notDeepEqual`` is ``!=`` and a provided
``Random`` is a ``FixedDraws`` service.

Every title is ported. Effect has no TestRandom; ``random.with_seed`` is its
deterministic generator."""

import math
import sys
from collections.abc import Iterable

import pytest

import pyfect as fx
from pyfect import random, testing
from pyfect.errors import NoSuchElementException

EPSILON = sys.float_info.epsilon
MIN_VALUE = math.ulp(0.0)
MAX_SAFE = 2**53 - 1


class FixedDraws:
    """A ``RandomService`` whose doubles come from ``draws``, then 0."""

    def __init__(self, *draws: float) -> None:
        self._draws = iter(draws)

    def unsafe_next_int(self) -> int:
        return 0

    def unsafe_next_double(self) -> float:
        return next(self._draws, 0.0)


def with_draws[A, E](eff: fx.Effect[A, E], *draws: float) -> fx.Effect[A, E]:
    return eff.pipe(fx.provide_service(random.Random, FixedDraws(*draws)))


def five_nexts() -> fx.Effect[tuple[float, ...]]:
    return fx.all(*[random.next()] * 5)


# --- next ------------------------------------------------------------------------------


@testing.effect
def test_next_generates_a_number_between_0_inclusive_and_1_exclusive():
    """next / generates a number between 0 inclusive and 1 exclusive"""
    value = yield from random.next()
    assert 0 <= value < 1


# --- next_boolean ----------------------------------------------------------------------


@testing.effect
def test_next_boolean_generates_a_boolean():
    """nextBoolean / generates a boolean"""
    value = yield from random.next_boolean()
    assert isinstance(value, bool)


@testing.effect
def test_next_boolean_is_deterministic_with_the_same_seed():
    """nextBoolean / is deterministic with the same seed"""
    program = fx.all(random.next_boolean(), random.next_boolean(), random.next_boolean())
    result1 = yield from program.pipe(random.with_seed("next-boolean-seed"))
    result2 = yield from program.pipe(random.with_seed("next-boolean-seed"))
    assert result1 == result2


@testing.effect
def test_next_boolean_uses_a_strict_greater_than_threshold():
    """nextBoolean / uses a strict greater-than threshold"""
    program = fx.all(random.next_boolean(), random.next_boolean(), random.next_boolean())
    result = yield from with_draws(program, 0.5, 0.500001, 0.1)
    assert result == (False, True, False)


# --- next_int --------------------------------------------------------------------------


@testing.effect
def test_next_int_generates_a_safe_integer():
    """nextInt / generates a safe integer"""
    value = yield from random.next_int()
    assert isinstance(value, int)
    assert -MAX_SAFE <= value <= MAX_SAFE


# --- next_between ----------------------------------------------------------------------


@pytest.mark.parametrize(
    ("low", "high", "draw", "expected"),
    [
        pytest.param(10, 20, 1 - EPSILON, 20 - 2**-48, id="positive"),
        pytest.param(1e16, 1e16 + 2, 0.75, 1e16, id="adjacent"),
        pytest.param(-1e16 - 2, -1e16, 0.75, -1e16 - 2, id="negative"),
        pytest.param(-MIN_VALUE, 0, 0.75, -MIN_VALUE, id="zero"),
    ],
)
@testing.effect
def test_next_between_excludes_a_rounded_upper_bound(
    low: float, high: float, draw: float, expected: float
):
    """nextBetween / excludes a rounded upper bound: %s"""
    value = yield from with_draws(random.next_between(low, high), draw)
    assert low <= value < high
    assert value == expected


@testing.effect
def test_next_between_preserves_degenerate_bounds():
    """nextBetween / preserves degenerate bounds"""
    assert (yield from with_draws(random.next_between(10, 10), 0.75)) == 10


@testing.effect
def test_next_between_documents_current_behavior_for_unsupported_bounds():
    """nextBetween / documents current behavior for unsupported bounds"""
    assert (yield from with_draws(random.next_between(10, math.inf), 0.75)) == math.inf


@testing.effect
def test_next_between_generates_number_in_half_open_range():
    """nextBetween / generates number in half-open range"""
    for _ in range(100):
        value = yield from random.next_between(10, 20)
        assert 10 <= value < 20


@testing.effect
def test_next_between_does_not_round_the_bounds():
    """nextBetween / does not round the bounds"""
    assert (yield from with_draws(random.next_between(10.5, 20.5), 0.75)) == 18


@testing.effect
def test_next_between_handles_negative_ranges():
    """nextBetween / handles negative ranges"""
    value = yield from random.next_between(-10, 10)
    assert -10 <= value < 10


# --- next_int_between ------------------------------------------------------------------


@testing.effect
def test_next_int_between_generates_integer_in_closed_range():
    """nextIntBetween / generates integer in closed range"""
    for _ in range(100):
        value = yield from random.next_int_between(1, 6)
        assert isinstance(value, int)
        assert 1 <= value <= 6


@testing.effect
def test_next_int_between_generates_integer_in_half_open_range():
    """nextIntBetween / generates integer in half-open range"""
    for _ in range(100):
        value = yield from random.next_int_between(1, 6, half_open=True)
        assert isinstance(value, int)
        assert 1 <= value < 6


@testing.effect
def test_next_int_between_excludes_the_upper_bound_in_half_open_ranges():
    """nextIntBetween / excludes the upper bound in half-open ranges"""
    value = yield from with_draws(random.next_int_between(1, 6, half_open=True), 1 - EPSILON)
    assert value == 5


# --- shuffle ---------------------------------------------------------------------------


@testing.effect
def test_shuffle_returns_a_shuffled_copy_of_all_values():
    """shuffle / returns a shuffled copy of all values"""
    values = [1, 2, 3, 4, 5]
    output = yield from random.shuffle(values)
    assert output is not values
    assert values == [1, 2, 3, 4, 5]
    assert sorted(output) == [1, 2, 3, 4, 5]


@testing.effect
def test_shuffle_is_deterministic_with_the_same_seed():
    """shuffle / is deterministic with the same seed"""
    program = random.shuffle([1, 2, 3, 4, 5])
    result1 = yield from program.pipe(random.with_seed("shuffle-seed"))
    result2 = yield from program.pipe(random.with_seed("shuffle-seed"))
    assert result1 == result2


# --- choice ----------------------------------------------------------------------------


@testing.effect
def test_choice_selects_a_random_element_from_an_iterable():
    """choice / selects a random element from an iterable"""
    assert (yield from with_draws(random.choice(["a", "b", "c"]), 0.75)) == "c"


@testing.effect
def test_choice_fails_with_no_such_element_error_for_an_empty_iterable():
    """choice / fails with NoSuchElementError for an empty iterable"""
    empty: list[int] = []
    error = yield from random.choice(empty).flip()
    assert isinstance(error, NoSuchElementException)
    assert str(error) == "Cannot select a random element from an empty array"


@testing.effect
def test_choice_is_deterministic_with_the_same_seed():
    """choice / is deterministic with the same seed"""
    values = (1, 2, 3, 4, 5)
    program = fx.all(random.choice(values), random.choice(values), random.choice(values))
    result1 = yield from program.pipe(random.with_seed("choice-seed"))
    result2 = yield from program.pipe(random.with_seed("choice-seed"))
    assert result1 == result2


# --- with_seed -------------------------------------------------------------------------


@testing.effect
def test_with_seed_restarts_the_sequence_on_each_evaluation_of_a_reused_effect():
    """withSeed / restarts the sequence on each evaluation of a reused effect"""
    seeded = fx.all(random.next(), random.next()).pipe(random.with_seed("my-seed"))
    first = yield from seeded
    second = yield from seeded
    assert first[0] != first[1]
    assert second == first


@fx.gen
def next_and_int():
    v1 = yield from random.next()
    v2 = yield from random.next_int()
    return (v1, v2)


@testing.effect
def test_with_seed_produces_different_sequences_with_different_seeds():
    """withSeed / produces different sequences with different seeds"""
    result1 = yield from next_and_int.pipe(random.with_seed(12345))
    result2 = yield from next_and_int.pipe(random.with_seed(67890))
    assert result1 != result2


def distinct_runs(seeds: Iterable[str]) -> fx.Effect[list[tuple[float, ...]]]:
    return fx.for_each(seeds, lambda seed: five_nexts().pipe(random.with_seed(seed)))


@testing.effect
def test_with_seed_distinguishes_one_character_string_seeds():
    """withSeed / distinguishes one-character string seeds"""
    empty, result1, result2 = yield from distinct_runs(["", "a", "b"])
    assert result1 != empty
    assert result2 != empty
    assert result1 != result2


@testing.effect
def test_with_seed_distinguishes_trailing_partial_utf8_words_in_string_seeds():
    """withSeed / distinguishes trailing partial UTF-8 words in string seeds"""
    for seed1, seed2 in [("1234a", "1234b"), ("1234ab", "1234ac"), ("1234abc", "1234abd")]:
        result1, result2 = yield from distinct_runs([seed1, seed2])
        assert result1 != result2


@testing.effect
def test_with_seed_distinguishes_astral_character_string_seeds():
    """withSeed / distinguishes astral character string seeds"""
    empty, result1, result2, result3 = yield from distinct_runs(["", "😀", "😁", "🐀"])
    assert result1 != empty
    assert result2 != empty
    assert result1 != result2
    assert result1 != result3


@testing.effect
def test_with_seed_works_with_numeric_seeds():
    """withSeed / works with numeric seeds"""
    result1 = yield from next_and_int.pipe(random.with_seed(12345))
    result2 = yield from next_and_int.pipe(random.with_seed(12345))
    assert result1 == result2
