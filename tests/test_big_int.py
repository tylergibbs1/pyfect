"""``pyfect.big_int``: the integer roots of Effect's ``effect/test/BigInt.test.ts``."""

import math

import pytest

from pyfect import big_int


def test_nth_root_returns_integer_n_th_roots_rounded_toward_zero() -> None:
    """nthRoot returns integer n-th roots rounded toward zero"""
    assert big_int.nth_root(26, 3) == 2
    assert big_int.nth_root(27, 3) == 3
    assert big_int.nth_root(28, 3) == 3
    assert big_int.nth_root(-26, 3) == -2
    assert big_int.nth_root(0, 4) == 0
    assert big_int.nth_root(-7, 1) == -7
    assert big_int.nth_root(2**100, 2**40) == 1
    assert big_int.nth_root(2**262144, 8192) == 2**32
    assert big_int.nth_root(-16, 4) is None
    assert big_int.nth_root_unsafe(1024, 10) == 2
    with pytest.raises(ValueError, match="Cannot take an integer root of degree 4 of -16"):
        big_int.nth_root_unsafe(-16, 4)


@pytest.mark.parametrize(
    ("degree", "shown"),
    [
        (0, "0"),
        (-1, "-1"),
        (0.5, "0.5"),
        (math.nan, "NaN"),
        (math.inf, "Infinity"),
        (2**53, "9007199254740992"),
    ],
)
def test_nth_root_and_nth_root_unsafe_require_a_positive_safe_integer_degree(
    degree: float, shown: str
) -> None:
    """nthRoot and nthRootUnsafe require a positive safe integer degree"""
    for root in (big_int.nth_root, big_int.nth_root_unsafe):
        with pytest.raises(
            ValueError, match=f"^Degree must be a positive safe integer, got {shown}$"
        ):
            root(0, degree)  # pyright: ignore[reportArgumentType]


def test_nth_root_is_the_floor_of_the_real_root_on_both_sides_of_every_power() -> None:
    for degree in range(1, 9):
        for base in range(60):
            power = base**degree
            for n in (power - 1, power, power + 1):
                if n >= 0:
                    root = big_int.nth_root(n, degree)
                    assert root is not None
                    assert root**degree <= n < (root + 1) ** degree
