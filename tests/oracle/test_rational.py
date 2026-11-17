"""Ports of Effect's ``test/Rational.test.ts``.

Each test's docstring is the Effect test title. ``RangeError`` is ``ValueError``
(``ZeroDivisionError`` for a zero denominator and division by zero), ``Option`` results are
``Rational | None``, ``Order`` is ``compare`` and ``Equivalence`` is ``==``; dual functions
are methods. Effect's ``fc`` properties run as Hypothesis properties. ``pow`` takes an
``int``, so Effect's fractional and non-finite exponents are type errors here; the unsafe
integer exponent is ported. ``inspect`` is Node's; ``repr`` is checked instead.
"""

from __future__ import annotations

import math
import sys

import pytest
from hypothesis import given
from hypothesis import strategies as st

from pyfect import big_decimal, rational
from pyfect._equal import equals
from pyfect.rational import Rational

_ = rational.from_string_unsafe
third = _("1/3")
one = rational.from_big_int(1)
zero = rational.from_big_int(0)
MIN_VALUE = 5e-324


def assert_rational(actual: Rational, numerator: int, denominator: int) -> None:
    assert (actual.numerator, actual.denominator) == (numerator, denominator)


def test_make_normalizes_to_a_canonical_form_and_rejects_a_zero_denominator() -> None:
    """make normalizes to a canonical form and rejects a zero denominator"""
    assert_rational(rational.make_unsafe(6, -4), -3, 2)
    assert_rational(rational.make_unsafe(0, -7), 0, 1)
    assert_rational(rational.make_unsafe(-10, -5), 2, 1)
    assert rational.make(2, 6) == third
    assert rational.make(1, 0) is None
    with pytest.raises(ZeroDivisionError, match=r"^Denominator must be non-zero$"):
        rational.make_unsafe(1, 0)

    assert isinstance(third, Rational)
    assert not isinstance(big_decimal.from_big_int(1), Rational)
    assert not isinstance("1/3", Rational)


def test_the_constructor_refuses_a_pair_that_is_not_canonical() -> None:
    """A ``Rational`` is canonical by construction: equality compares the pair."""
    assert Rational(1, 3) == third
    for numerator, denominator in [(2, 6), (1, -3), (1, 0), (0, 2)]:
        with pytest.raises(ValueError, match="lowest terms"):
            Rational(numerator, denominator)


def test_arithmetic_is_exact_so_a_third_times_three_is_exactly_one() -> None:
    """arithmetic is exact, so a third times three is exactly one"""
    assert third.multiply(rational.from_big_int(3)) == one
    assert rational.sum_all([third, third, third]) == one
    assert third.sum(_("1/6")) == _("1/2")
    assert one.subtract(third) == _("2/3")
    assert rational.multiply_all([_("3/2"), _("4/3"), _("-1/2")]) == _("-1/1")
    assert rational.sum_all([]) == zero
    assert rational.multiply_all([]) == one
    assert third.negate() == _("-1/3")
    assert _("-1/3").abs() == third
    assert _("-1/3").sign() == -1
    assert zero.sign() == 0

    assert third.divide(rational.from_big_int(3)) == _("1/9")
    assert _("-2/3").divide_unsafe(_("4/9")) == _("-3/2")
    assert third.divide(zero) is None
    with pytest.raises(ZeroDivisionError, match=r"^Division by zero$"):
        third.divide_unsafe(zero)
    assert third * rational.from_big_int(3) == one
    assert -third + third == zero


def test_arithmetic_preserves_canonical_fractions_with_shared_factors_signs_and_zero() -> None:
    """arithmetic preserves canonical fractions with shared factors, signs and zero"""
    assert_rational(_("1/6").sum(_("1/10")), 4, 15)
    assert_rational(_("1/6").subtract(_("1/10")), 1, 15)
    assert_rational(third.sum(_("-1/3")), 0, 1)
    assert_rational(third.subtract(third), 0, 1)
    assert_rational(_("6/35").multiply(_("14/15")), 4, 25)
    assert_rational(_("6/35").divide_unsafe(_("-15/14")), -4, 25)
    assert_rational(zero.multiply(third), 0, 1)
    assert_rational(zero.divide_unsafe(_("-2/3")), 0, 1)


def test_pow_takes_integer_exponents_inverting_for_negative_ones() -> None:
    """pow takes integer exponents, inverting for negative ones"""
    # Twelve pure fifths overshoot seven octaves by the Pythagorean comma.
    twelve_fifths = _("3/2").pow_unsafe(12)
    assert_rational(twelve_fifths, 531441, 4096)
    seven_octaves = rational.from_big_int(2).pow(7)
    assert seven_octaves is not None
    assert twelve_fifths > seven_octaves

    assert third.pow(-1) == rational.from_big_int(3)
    assert _("-2/3").pow(-3) == _("-27/8")
    assert zero.pow(0) == one
    assert zero.pow(-1) is None
    with pytest.raises(ZeroDivisionError, match=r"^Division by zero$"):
        zero.pow_unsafe(-1)
    with pytest.raises(
        ValueError, match=r"^Exponent must be a safe integer, got 9007199254740992$"
    ):
        third.pow(2**53)


def test_order_equivalence_equal_and_hash_compare_exact_values() -> None:
    """Order, Equivalence, Equal and Hash compare exact values"""
    nearly_third = rational.from_big_decimal(
        big_decimal.from_string_unsafe("0.333333333333333333333333")
    )
    assert third.compare(nearly_third) == 1
    assert nearly_third.compare(third) == -1
    assert _("-1/2").compare(_("-1/3")) == -1
    assert rational.make_unsafe(2, 6).compare(third) == 0
    assert rational.make_unsafe(-2, -6) == third
    assert third != nearly_third

    assert equals(rational.make_unsafe(2, 6), third)
    assert not equals(third, nearly_third)
    assert not equals(third, "1/3")
    assert hash(rational.make_unsafe(2, 6)) == hash(third)

    assert nearly_third < third
    same = _("2/6")
    assert third <= same
    assert not third > same
    assert third >= nearly_third
    assert third.between(minimum=zero, maximum=one)
    assert _("5/2").clamp(minimum=zero, maximum=one) == one
    assert min(third, nearly_third) == nearly_third
    assert max(third, nearly_third) == third
    assert rational.make_unsafe(4, 2).is_integer()
    assert not third.is_integer()
    assert rational.make_unsafe(0, 5).is_zero()
    assert _("-1/3").is_negative()
    assert third.is_positive()


def test_from_big_decimal_is_exact_for_any_scale() -> None:
    """fromBigDecimal is exact for any scale"""
    assert_rational(rational.from_big_decimal(big_decimal.from_string_unsafe("0.1")), 1, 10)
    assert_rational(rational.from_big_decimal(big_decimal.from_string_unsafe("-12.50")), -25, 2)
    assert_rational(rational.from_big_decimal(big_decimal.make(15, -2)), 1500, 1)
    assert_rational(rational.from_big_decimal(big_decimal.make(0, 7)), 0, 1)


def test_from_number_encodes_the_exact_ieee_754_value_and_rejects_non_finite_input() -> None:
    """fromNumber encodes the exact IEEE-754 value and rejects non-finite input"""
    assert rational.from_number(0.5) == _("1/2")
    assert rational.from_number(-0.75) == _("-3/4")
    # 0.1 is not one tenth: the double nearest to it is 3602879701896397 / 2^55.
    assert rational.from_number(0.1) == rational.make_unsafe(3602879701896397, 1 << 55)
    assert rational.from_number(1e21) == rational.from_big_int(10**21)
    assert rational.from_number(MIN_VALUE) == rational.make_unsafe(1, 1 << 1074)
    assert_rational(rational.from_number_unsafe(-0.0), 0, 1)
    for n, text in [(math.nan, "NaN"), (math.inf, "Infinity"), (-math.inf, "-Infinity")]:
        assert rational.from_number(n) is None
        with pytest.raises(ValueError, match=f"^Number must be finite, got {text}$"):
            rational.from_number_unsafe(n)


@given(st.floats(allow_nan=False, allow_infinity=False))
def test_to_number_unsafe_rounds_the_ratio_rather_than_its_parts(n: float) -> None:
    """toNumberUnsafe rounds the ratio rather than its parts"""
    assert third.to_number_unsafe() == 1 / 3
    assert _("-2/3").to_number_unsafe() == -2 / 3
    assert zero.to_number_unsafe() == 0
    # Numerator and denominator are each far beyond the largest float, the ratio is not.
    assert rational.make_unsafe(10**400 + 1, 3 * 10**400).to_number_unsafe() == 1 / 3
    assert rational.from_big_int(10**400).to_number_unsafe() == math.inf
    negative_zero = rational.make_unsafe(-1, 10**400).to_number_unsafe()
    assert negative_zero == 0 and math.copysign(1, negative_zero) == -1
    assert rational.from_number_unsafe(n).to_number_unsafe() == n


def test_to_number_unsafe_rounds_subnormal_results_once_to_nearest_with_ties_to_even() -> None:
    """toNumberUnsafe rounds subnormal results once, to nearest with ties to even"""
    assert sys.float_info.min * sys.float_info.epsilon == MIN_VALUE
    # Just above half of the smallest subnormal rounds up to it rather than to zero.
    assert rational.make_unsafe(1, (1 << 1075) - 1).to_number_unsafe() == MIN_VALUE
    assert rational.make_unsafe(-1, (1 << 1075) - 1).to_number_unsafe() == -MIN_VALUE
    # Exactly half of it is a tie, and zero is the even neighbour.
    assert rational.make_unsafe(1, 1 << 1075).to_number_unsafe() == 0
    # 1.5 units is a tie between one and two units; two is even.
    assert rational.make_unsafe(3, 1 << 1075).to_number_unsafe() == 2 * MIN_VALUE
    # Just below 1.5 units rounds down to one unit.
    assert rational.make_unsafe(3 * (1 << 60) - 1, 1 << 1135).to_number_unsafe() == MIN_VALUE
    assert rational.make_unsafe(1, 1 << 1074).to_number_unsafe() == MIN_VALUE


def test_to_big_decimal_rounds_at_the_supplied_scale() -> None:
    """toBigDecimal rounds at the supplied scale"""
    decimal = big_decimal.from_string_unsafe
    assert third.to_big_decimal(scale=3) == decimal("0.333")
    assert _("2/3").to_big_decimal(scale=3) == decimal("0.667")
    assert _("-1/8").to_big_decimal(scale=2) == decimal("-0.13")
    assert _("-1/8").to_big_decimal(scale=2, mode="half-even") == decimal("-0.12")
    assert _("-1/8").to_big_decimal(scale=2, mode="ceil") == decimal("-0.12")
    assert _("1/4").to_big_decimal(scale=2) == decimal("0.25")
    assert rational.from_big_int(1250).to_big_decimal(scale=-2) == decimal("1300")
    assert third.to_big_decimal(scale=1) == decimal("0.3")
    with pytest.raises(ValueError, match=r"^Scale must be a safe integer, got 9007199254740992$"):
        third.to_big_decimal(scale=2**53)


@given(st.integers(), st.integers().filter(lambda d: d != 0))
def test_format_and_from_string_are_inverses_over_canonical_fraction_strings(
    numerator: int, denominator: int
) -> None:
    """format and fromString are inverses over canonical fraction strings"""
    assert _("6/5").format() == "6/5"
    assert zero.format() == "0/1"
    assert rational.from_big_int(-3).format() == "-3/1"

    assert rational.from_string("-4/-6") == _("2/3")
    assert rational.from_string("3") == rational.from_big_int(3)
    assert rational.from_string("+1/3") == third
    for text in [
        "",
        " 1/2",
        "1/0",
        "1.5",
        "1/",
        "/2",
        "1/2/3",
        "1e3",
        "a/b",
        "1/2\n",
        "\u0661/\u0662",
    ]:
        assert rational.from_string(text) is None
    with pytest.raises(ValueError, match=r"^Invalid rational string: 1/0$"):
        rational.from_string_unsafe("1/0")

    value = rational.make_unsafe(numerator, denominator)
    assert rational.from_string_unsafe(value.format()) == value


def test_to_string_to_json_inspect_and_pipe() -> None:
    """toString, toJSON, inspect and pipe"""
    assert str(third) == "Rational(1/3)"
    assert repr(third) == "Rational(1/3)"
    assert third.to_json() == {"_id": "Rational", "numerator": "1", "denominator": "3"}
    assert third.multiply(rational.from_big_int(3)) == one


def test_from_string_reads_up_to_max_digits_and_prints_any_size() -> None:
    """pyfect: ``from_string`` reads at most ``MAX_DIGITS`` significant digits by default,
    as ``big_decimal.from_string``; past Python's 4300-digit ``int`` limit both ways."""
    long = "7" * 5000
    value = rational.from_string_unsafe(f"-{long}/1")
    assert value.format() == f"-{long}/1"
    assert value.to_json()["numerator"] == f"-{long}"
    assert rational.from_string("0" * 40_000 + "1/2") == rational.make(1, 2)
    assert rational.from_string("1" * (rational.MAX_DIGITS + 1)) is None
    assert rational.from_string("1" * 100, max_digits=99) is None
    assert rational.from_string("1" * 50 + "/" + "1" * 50, max_digits=99) is None
