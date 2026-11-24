"""``Rational.nth_root`` undoes ``pow`` exactly, on numbers far past a float's range, and
finds no root for a number between two consecutive powers."""

from hypothesis import given
from hypothesis import strategies as st

from pyfect import rational

_NUMERATORS = st.integers(-(10**40), 10**40)
_DENOMINATORS = st.integers(1, 10**40)
_DEGREES = st.integers(1, 60)


@given(_NUMERATORS, _DENOMINATORS, _DEGREES)
def test_the_root_of_a_power_is_the_base(numerator: int, denominator: int, degree: int) -> None:
    base = rational.make_unsafe(numerator, denominator)
    root = base.pow_unsafe(degree).nth_root(degree)
    assert root == (base if degree % 2 or not base.is_negative() else base.abs())


@given(st.integers(2, 10**40), st.integers(2, 60))
def test_one_past_a_power_has_no_root(base: int, degree: int) -> None:
    assert rational.from_big_int(base**degree + 1).nth_root(degree) is None
    assert rational.from_big_int(base**degree - 1).nth_root(degree) is None
