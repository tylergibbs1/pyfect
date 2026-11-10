"""Ports of Effect's ``test/BigDecimal.test.ts``.

Each test's docstring is the Effect test title. ``RangeError`` is
``ValueError`` (``ZeroDivisionError`` for division by zero), ``Option`` results
are ``BigDecimal | None``, ``Order`` is ``compare`` and ``Equivalence`` is
``==``; dual functions are methods.

Omitted: ``toJSON()`` and ``inspect`` (no JSON or Node inspection protocol;
``repr`` is covered by ``toString()``). Effect skips its property-based
suite for speed; it is ported here with ``testing.prop`` at Hypothesis's
default number of runs.
"""

from __future__ import annotations

from decimal import Decimal

import pytest
from hypothesis import strategies as st

from pyfect import big_decimal, testing
from pyfect._equal import equals
from pyfect.big_decimal import BigDecimal, RoundingMode

MAX_SAFE = 2**53 - 1
MIN_SAFE = -MAX_SAFE
_ = big_decimal.from_string_unsafe
make = big_decimal.make


def assert_divide(x: str, y: str, z: str) -> None:
    assert _(x).divide(_(y)) == _(z)
    assert _(x).divide_unsafe(_(y)) == _(z)


def test_make() -> None:
    """make"""
    assert make(1, MAX_SAFE).scale == MAX_SAFE
    assert make(1, MIN_SAFE).scale == MIN_SAFE
    for scale, text in [
        (0.5, "0.5"),
        (float("nan"), "NaN"),
        (float("inf"), "Infinity"),
        (float("-inf"), "-Infinity"),
        (1.7976931348623157e308, "1.7976931348623157e+308"),
        (MIN_SAFE - 1, "-9007199254740992"),
    ]:
        with pytest.raises(ValueError) as raised:
            make(1, scale)  # pyright: ignore[reportArgumentType]
        assert str(raised.value) == f"Scale must be a safe integer, got {text}"


def test_make_normalized_unsafe_validates_the_value_and_scale() -> None:
    """makeNormalizedUnsafe validates the value and scale"""
    for value in (120, -120):
        with pytest.raises(ValueError, match=r"^Value must be normalized$"):
            big_decimal.make_normalized_unsafe(value, 0)
    with pytest.raises(ValueError, match=r"^Scale must be a safe integer, got 0.5$"):
        big_decimal.make_normalized_unsafe(1, 0.5)  # pyright: ignore[reportArgumentType]


def test_is_big_decimal() -> None:
    """isBigDecimal"""
    for text in ["0", "987", "123.0", "0.123", "123.456"]:
        assert isinstance(_(text), BigDecimal)
    assert not isinstance("1", BigDecimal)
    assert not isinstance(True, BigDecimal)


def test_sign() -> None:
    """sign"""
    assert [_(t).sign() for t in ["-5", "0", "5", "-123.456", "456.789"]] == [-1, 0, 1, -1, 1]


def test_equals() -> None:
    """equals"""
    assert _("1") == _("1")
    assert _("0.00012300") == _("0.000123")
    assert _("5") == _("5.0")
    assert _("123.0000") == _("123.00")
    assert _("1") != _("2")
    assert _("1") != _("1.1")
    assert _("1") != _("0.1")


def test_sum() -> None:
    """sum"""
    for a, b, c in [
        ("2", "0", "2"),
        ("0", "2", "2"),
        ("0", "0", "0"),
        ("2", "1", "3"),
        ("3.00000", "50", "53"),
        ("1.23", "0.0045678", "1.2345678"),
        ("123.456", "-123.456", "0"),
    ]:
        assert _(a).sum(_(b)) == _(c)
    assert _("1.5") + _("2") == _("3.5")


def test_sum_all() -> None:
    """sumAll"""
    assert big_decimal.sum_all([]) == _("0")
    assert big_decimal.sum_all([_("2"), _("3"), _("4")]) == _("9")
    assert big_decimal.sum_all([_("1.5"), _("-1.5")]) == _("0")


def test_multiply() -> None:
    """multiply"""
    for b, c in [("2", "6"), ("0", "0"), ("-1", "-3"), ("0.5", "1.5"), ("-2.5", "-7.5")]:
        assert _("3").multiply(_(b)) == _(c)
    assert _("3") * _("0.5") == _("1.5")


def test_multiply_all() -> None:
    """multiplyAll"""
    assert big_decimal.multiply_all([]) == _("1")
    assert big_decimal.multiply_all([_("2"), _("3"), _("4")]) == _("24")
    assert big_decimal.multiply_all([_("2"), _("0"), _("4")]) == _("0")


def test_subtract() -> None:
    """subtract"""
    for a, b, c in [
        ("0", "1", "-1"),
        ("2.1", "1", "1.1"),
        ("3", "1", "2"),
        ("3", "0", "3"),
        ("3", "-1", "4"),
        ("3", "0.5", "2.5"),
        ("3", "-2.5", "5.5"),
    ]:
        assert _(a).subtract(_(b)) == _(c)
    assert _("3") - _("0.5") == _("2.5")


def test_round_terminal() -> None:
    """roundTerminal"""
    for n, expected in [(0, 0), (4, 0), (5, 1), (9, 1), (49, 0), (59, 1), (99, 1)]:
        assert big_decimal.round_terminal(n) == expected
        assert big_decimal.round_terminal(-n) == expected


def test_divide() -> None:
    """divide"""
    for x, y, z in [
        ("0", "1", "0"),
        ("0", "10", "0"),
        ("2", "1", "2"),
        ("20", "1", "20"),
        ("10", "10", "1"),
        ("100", "10.0", "10"),
        ("20.0", "200", "0.1"),
        ("4", "2", "2.0"),
        ("15", "3", "5.0"),
        ("1", "2", "0.5"),
        ("1", "0.02", "50"),
        ("1", "0.2", "5"),
        ("1.0", "0.02", "50"),
        ("1", "0.020", "50"),
        ("5.0", "4.00", "1.25"),
        ("5.0", "4.000", "1.25"),
        ("5", "4.000", "1.25"),
        ("5", "4", "1.25"),
        ("100", "5", "20"),
        ("-50", "5", "-10"),
        ("200", "-5", "-40.0"),
        ("1", "3", "0." + "3" * 100),
        ("-2", "-3", "0." + "6" * 99 + "7"),
        (
            "-12.34",
            "1.233",
            "-10.00811030008110300081103000811030008110300081103000811030008110300081103000811030008110300081103001",
        ),
        (
            "125348",
            "352.2283",
            "355.8714617763535752237966114591019517738921035021887792661748076460636467881768727839301952739175132",
        ),
    ]:
        assert_divide(x, y, z)
    assert _("5").divide(_("0")) is None
    with pytest.raises(ZeroDivisionError, match=r"^Division by zero$"):
        _("5").divide_unsafe(_("0"))
    assert _("1") / _("2") == _("0.5")


def test_equivalence() -> None:
    """Equivalence"""
    assert _("1") == _("1")
    assert _("0.00012300") == _("0.000123")
    assert _("5") == _("5.00")
    assert _("1") != _("2")
    assert _("1") != _("1.1")


def test_order() -> None:
    """Order"""
    for a, b, expected in [
        ("1", "2", -1),
        ("2", "1", 1),
        ("2", "2", 0),
        ("1", "1.1", -1),
        ("1.1", "1", 1),
        ("0.00012300", "0.000123", 0),
        ("5", "5.000", 0),
        ("5", "0.500", 1),
        ("5", "50.00", -1),
    ]:
        assert _(a).compare(_(b)) == expected
    assert sorted([_("5"), _("0.5"), _("50")]) == [_("0.5"), _("5"), _("50")]


def test_order_and_equivalence_support_extreme_scale_differences() -> None:
    """Order and Equivalence support extreme scale differences"""
    positive, negative = make(1, 0), make(-1, 0)
    positive_tiny, negative_tiny = make(1, MAX_SAFE), make(-1, MAX_SAFE)
    zero_tiny = make(0, MAX_SAFE)
    assert positive.compare(positive_tiny) == 1
    assert positive_tiny.compare(positive) == -1
    assert negative.compare(negative_tiny) == -1
    assert negative_tiny.compare(negative) == 1
    assert make(0, 0).compare(zero_tiny) == 0
    assert positive != positive_tiny
    assert make(0, 0) == zero_tiny

    equal = make(10**101, 101)
    assert make(1, 0).compare(equal) == 0
    assert make(1, 0) == equal

    below, above = make(9, -MAX_SAFE), make(10**102, -(MAX_SAFE - 101))
    assert below.compare(above) == -1
    assert above.compare(below) == 1
    assert below != above

    power = 10**102
    for sign in (-1, 1):
        exact, after = make(sign, -1), make(sign * (power + 1), 101)
        assert exact.compare(after) == (-1 if sign == 1 else 1)
        assert after.compare(exact) == (1 if sign == 1 else -1)
        assert exact != after


def test_order_and_equivalence_agree_with_exact_bounded_scale_alignment() -> None:
    """Order and Equivalence agree with exact bounded scale alignment"""
    values = [-12345, -100, -1, 0, 1, 100, 12345]
    scales = [-102, -101, -100, -8, -1, 0, 1, 8, 100, 101, 102]
    decimals = [make(value, scale) for value in values for scale in scales]
    for a in decimals:
        for b in decimals:
            scale = max(a.scale, b.scale)
            x, y = a.rescale(scale).value, b.rescale(scale).value
            expected = -1 if x < y else 1 if x > y else 0
            assert a.compare(b) == expected
            assert (a == b) == (expected == 0)


def test_is_less_than() -> None:
    """isLessThan"""
    assert _("2") < _("3")
    assert not _("3") < _("3")
    assert not _("4") < _("3")


def test_is_less_than_or_equal_to() -> None:
    """isLessThanOrEqualTo"""
    assert _("2") <= _("3")
    assert _("3") <= _("3")
    assert not _("4") <= _("3")


def test_is_greater_than() -> None:
    """isGreaterThan"""
    assert not _("2") > _("3")
    assert not _("3") > _("3")
    assert _("4") > _("3")


def test_is_greater_than_or_equal_to() -> None:
    """isGreaterThanOrEqualTo"""
    assert not _("2") >= _("3")
    assert _("3") >= _("3")
    assert _("4") >= _("3")


def test_between() -> None:
    """between"""
    assert _("3").between(minimum=_("0"), maximum=_("5"))
    assert not _("-1").between(minimum=_("0"), maximum=_("5"))
    assert not _("6").between(minimum=_("0"), maximum=_("5"))
    assert not _("0.0123").between(minimum=_("0.02"), maximum=_("5"))
    assert _("0.05").between(minimum=_("0.02"), maximum=_("5"))


def test_clamp() -> None:
    """clamp"""
    for x, expected in [("3", "3"), ("-1", "0"), ("6", "5")]:
        assert _(x).clamp(minimum=_("0"), maximum=_("5")) == _(expected)
    assert _("0.0123").clamp(minimum=_("0.02"), maximum=_("5")) == _("0.02")


def test_min() -> None:
    """min"""
    for a, b, expected in [
        ("2", "3", "2"),
        ("5", "0.1", "0.1"),
        ("0.005", "3", "0.005"),
        ("123.456", "1.2", "1.2"),
    ]:
        assert min(_(a), _(b)) == _(expected)


def test_max() -> None:
    """max"""
    for a, b, expected in [
        ("2", "3", "3"),
        ("5", "0.1", "5"),
        ("0.005", "3", "3"),
        ("123.456", "1.2", "123.456"),
    ]:
        assert max(_(a), _(b)) == _(expected)


def test_abs() -> None:
    """abs"""
    for a, expected in [("2", "2"), ("-3", "3"), ("0.000456", "0.000456"), ("-0.123", "0.123")]:
        assert _(a).abs() == _(expected)
        assert abs(_(a)) == _(expected)


def test_negate() -> None:
    """negate"""
    for a, expected in [("2", "-2"), ("-3", "3"), ("0.000456", "-0.000456"), ("-0.123", "0.123")]:
        assert _(a).negate() == _(expected)
        assert -_(a) == _(expected)


def test_remainder() -> None:
    """remainder"""
    assert _("5").remainder(_("2")) == _("1")
    assert _("4").remainder(_("2")) == _("0")
    assert _("123.456").remainder(_("0.2")) == _("0.056")
    assert _("-5").remainder(_("2")) == _("-1")
    assert _("5").remainder(_("0")) is None


def test_unsafe_remainder() -> None:
    """unsafeRemainder"""
    assert _("5").remainder_unsafe(_("2")) == _("1")
    assert _("4").remainder_unsafe(_("2")) == _("0")
    assert _("123.456") % _("0.2") == _("0.056")
    with pytest.raises(ZeroDivisionError, match=r"^Division by zero$"):
        _("5").remainder_unsafe(_("0"))


def _same(a: BigDecimal, b: BigDecimal) -> bool:
    return (a.value, a.scale) == (b.value, b.scale)


def test_normalize() -> None:
    """normalize"""
    for text, value, scale in [
        ("0", 0, 0),
        ("0.123000", 123, 3),
        ("123.000", 123, 0),
        ("-0.000123000", -123, 6),
        ("-123.000", -123, 0),
        ("12300000", 123, -5),
    ]:
        assert _same(_(text).normalize(), big_decimal.make_normalized_unsafe(value, scale))


def test_normalize_caches_results_without_changing_the_original_value_or_scale() -> None:
    """normalize caches results without changing the original value or scale"""
    for value, scale, expected_value, expected_scale in [
        (0, MAX_SAFE, 0, 0),
        (0, MIN_SAFE, 0, 0),
        (123, 2, 123, 2),
        (-123000, 2, -123, -1),
        (10**4097, 4097, 1, 0),
        (100, MIN_SAFE + 2, 1, MIN_SAFE),
    ]:
        decimal = make(value, scale)
        normalized = decimal.normalize()
        assert (normalized.value, normalized.scale) == (expected_value, expected_scale)
        assert decimal.normalize() is normalized
        assert normalized.normalize() is normalized
        assert (decimal.value, decimal.scale) == (value, scale)


def test_normalize_rejects_an_unsafe_resulting_scale() -> None:
    """normalize rejects an unsafe resulting scale"""
    decimal = make(10, MIN_SAFE)
    for _attempt in range(2):
        with pytest.raises(
            ValueError, match=r"^Scale must be a safe integer, got -9007199254740992$"
        ):
            decimal.normalize()


def test_from_string() -> None:
    """fromString"""
    for text, value, scale in [
        ("2", 2, 0),
        ("-2", -2, 0),
        ("0.123", 123, 3),
        ("200", 200, 0),
        ("20000000", 20000000, 0),
        ("-20000000", -20000000, 0),
        ("2.00", 200, 2),
        ("0.0000200", 200, 7),
        ("", 0, 0),
        ("1e5", 1, -5),
        ("1E15", 1, -15),
        ("1e+5", 1, -5),
        ("1E+15", 1, -15),
        ("-1.5E3", -15, -2),
        ("-1.5e3", -15, -2),
        ("-.5e3", -5, -2),
        ("-5e3", -5, -3),
        ("-5e-3", -5, 3),
        ("15e-3", 15, 3),
        ("0.00002e5", 2, 0),
        ("0.00002e-5", 2, 10),
    ]:
        assert big_decimal.from_string(text) == make(value, scale), text
    assert big_decimal.from_string("0.0000e2e1") is None
    assert big_decimal.from_string("0.1.2") is None
    assert big_decimal.from_string(".-1") is None
    assert big_decimal.from_string(".+1") is None
    with pytest.raises(ValueError, match=r"^Invalid numerical string: abc$"):
        _("abc")


def test_from_string_rejects_scales_beyond_10_000() -> None:
    """fromString rejects scales beyond 10_000"""
    assert big_decimal.from_string("1e10000") == make(1, -10_000)
    assert big_decimal.from_string("1e-10000") == make(1, 10_000)
    for text in [
        "1e10001",
        "1e-10001",
        "0.1e-10000",
        f"1.{'0' * 10_001}",
        "10e10000",
        "1e300000000",
    ]:
        assert big_decimal.from_string(text) is None, text[:20]


def test_arithmetic_rejects_scale_alignment_beyond_20_000() -> None:
    """arithmetic rejects scale alignment beyond 20_000"""
    large = make(1, -20_001)
    small = make(1, 20_001)
    for thunk in [
        lambda: large.sum(_("1")),
        lambda: _("1").subtract(large),
        lambda: large.remainder(_("1")),
        lambda: large.rescale(0),
        small.truncate,
        small.round,
    ]:
        with pytest.raises(ValueError, match=r"^Scale alignment must not exceed 20000 digits"):
            thunk()
    assert _("1e10000").sum(_("1e-10000")) == _(f"1{'0' * 10_000}.{'0' * 9_999}1")
    assert make(1, 20_000).truncate() == _("0")
    huge = make(1, -300_000_000)
    assert equals(huge.sum(_("0")), huge)
    assert equals(huge.rescale(huge.scale), huge)
    assert equals(huge.truncate(), huge)
    assert equals(huge.floor(), huge)
    assert equals(huge.ceil(), huge)
    assert equals(huge.round(), huge)
    assert _("1e10000").round(mode="half-even") == _("1e10000")


def test_format() -> None:
    """format"""
    for text, expected in [
        ("0", "0"),
        ("2", "2"),
        ("-2", "-2"),
        ("0.123", "0.123"),
        ("200", "200"),
        ("20000000", "20000000"),
        ("-20000000", "-20000000"),
        ("2.00", "2"),
        ("0.200", "0.2"),
        ("0.123000", "0.123"),
        ("-456.123", "-456.123"),
    ]:
        assert _(text).format() == expected
    assert make(10, -1).format() == "100"
    assert make(1, -25).format() == "1e+25"
    assert make(12345, -25).format() == "1.2345e+29"
    assert make(12345, 25).format() == "1.2345e-21"
    assert make(-12345, 20).format() == "-1.2345e-16"
    assert str(_("2.50")) == "2.5"


def test_format_preserves_the_boundary_between_plain_and_scientific_notation() -> None:
    """format preserves the boundary between plain and scientific notation"""
    assert make(1, 15).format() == "0.000000000000001"
    assert make(-1, 16).format() == "-1e-16"
    assert make(-1, -15).format() == "-1000000000000000"
    assert make(1, -16).format() == "1e+16"


def test_to_exponential() -> None:
    """toExponential"""
    assert make(0, 42).to_exponential() == "0e+0"
    assert _("-1").to_exponential() == "-1e+0"
    assert _("123.4500").to_exponential() == "1.2345e+2"
    assert _("-0.0012345").to_exponential() == "-1.2345e-3"


def test_to_string() -> None:
    """toString()"""
    assert repr(_("2")) == "BigDecimal(2)"


def test_equal_symbol() -> None:
    """Equal.symbol"""
    assert equals(_("2"), _("2"))
    assert equals(_("2"), _("2.00"))
    assert not equals(_("2"), _("2.01"))
    assert not equals(_("2"), 2)


def test_hash_symbol_preserves_hashes_across_equivalent_representations() -> None:
    """Hash.symbol preserves hashes across equivalent representations"""
    for value, scale, normalized_value, normalized_scale in [
        (0, 42, 0, 0),
        (12345, 0, 12345, 0),
        (12345000, 7, 12345, 4),
        (-12345000, 7, -12345, 4),
    ]:
        assert hash(make(value, scale)) == hash(make(normalized_value, normalized_scale))
    assert len({_("2"), _("2.00"), _("2.0")}) == 1


def test_pipe() -> None:
    """pipe()"""
    assert _("2").multiply(_("3")) == _("6")


def test_scale() -> None:
    """scale"""
    assert _same(_("3.0005").rescale(3), _("3.000"))
    assert _same(_("-3.0005").rescale(3), _("-3.000"))


def test_from_big_int() -> None:
    """fromBigInt"""
    assert _same(big_decimal.from_big_int(1), make(1, 0))


def test_from_number() -> None:
    """fromNumber"""
    assert big_decimal.from_number(123) == make(123, 0)
    assert big_decimal.from_number(123.456) == make(123456, 3)
    assert big_decimal.from_number(0.1) == make(1, 1)
    assert big_decimal.from_number(1e-7) == make(1, 7)
    assert big_decimal.from_number(float("inf")) is None
    assert big_decimal.from_number(float("nan")) is None
    with pytest.raises(ValueError, match=r"^Number must be finite, got NaN$"):
        big_decimal.from_number_unsafe(float("nan"))


def test_to_number_unsafe() -> None:
    """toNumberUnsafe"""
    assert _("123.456").to_number_unsafe() == 123.456


def test_is_integer() -> None:
    """isInteger"""
    assert _("0").is_integer()
    assert _("1").is_integer()
    assert _("1.0").is_integer()
    assert not _("1.1").is_integer()


def test_is_zero() -> None:
    """isZero"""
    assert _("0").is_zero()
    assert not _("1").is_zero()


def test_is_negative() -> None:
    """isNegative"""
    assert _("-1").is_negative()
    assert not _("0").is_negative()
    assert not _("1").is_negative()


def test_is_positive() -> None:
    """isPositive"""
    assert not _("-1").is_positive()
    assert not _("0").is_positive()
    assert _("1").is_positive()


def test_digit_at() -> None:
    """digitAt"""
    assert [_("12.34").digit_at(s) for s in range(-2, 4)] == [0, 1, 2, 3, 4, 0]


def _rounds(mode: RoundingMode, cases: list[tuple[str, int, str]]) -> None:
    for text, scale, expected in cases:
        assert _(text).round(scale=scale, mode=mode) == _(expected), (mode, text, scale)


def test_round_ceil() -> None:
    """round: ceil"""
    assert _("145").ceil(-1) == _("150")
    assert _("-14.5").ceil() == _("-14")
    _rounds(
        "ceil",
        [
            ("321.123", -3, "1000"),
            ("145", -1, "150"),
            ("-2.0", 0, "-2"),
            ("-1.9", 0, "-1"),
            ("0.12345678987654321", 13, "0.1234567898766"),
            ("-0.12345678987654321", 13, "-0.1234567898765"),
        ],
    )


def test_round_floor() -> None:
    """round: floor"""
    assert _("145").floor(-1) == _("140")
    assert _("-14.5").floor() == _("-15")
    _rounds(
        "floor",
        [
            ("321.123", -3, "0"),
            ("145", -1, "140"),
            ("-2.1", 0, "-3"),
            ("-1.9", 0, "-2"),
            ("0.12345678987654321", 13, "0.1234567898765"),
            ("-0.12345678987654321", 13, "-0.1234567898766"),
        ],
    )


def test_round_to_zero_truncate() -> None:
    """round: to-zero (truncate)"""
    assert _("145").truncate(-1) == _("140")
    assert _("-14.5").truncate() == _("-14")
    _rounds(
        "to-zero",
        [
            ("321.123", -3, "0"),
            ("145", -1, "140"),
            ("-2.1", 0, "-2"),
            ("-1.9", 0, "-1"),
            ("0.12345678987654321", 13, "0.1234567898765"),
            ("-0.12345678987654321", 13, "-0.1234567898765"),
        ],
    )


def test_round_from_zero() -> None:
    """round: from-zero"""
    _rounds(
        "from-zero",
        [
            ("321.123", -3, "1000"),
            ("145", -1, "150"),
            ("-2.1", 0, "-3"),
            ("-1.9", 0, "-2"),
            ("0.12345678987654321", 13, "0.1234567898766"),
            ("-0.12345678987654321", 13, "-0.1234567898766"),
        ],
    )


def test_round_half_ceil() -> None:
    """round: half-ceil"""
    _rounds(
        "half-ceil",
        [
            ("321.123", -3, "0"),
            ("145", -1, "150"),
            ("-2.5", 0, "-2"),
            ("1.95", 1, "2"),
            ("-1.95", 1, "-1.9"),
            ("0.1234567898765", 12, "0.123456789877"),
            ("-0.1234567898765", 12, "-0.123456789876"),
        ],
    )


def test_round_half_floor() -> None:
    """round: half-floor"""
    _rounds(
        "half-floor",
        [
            ("321.123", -3, "0"),
            ("145", -1, "140"),
            ("-2.4", 0, "-2"),
            ("-2.5", 0, "-3"),
            ("1.95", 1, "1.9"),
            ("-1.95", 1, "-2"),
            ("0.1234567898765", 12, "0.123456789876"),
            ("-0.1234567898765", 12, "-0.123456789877"),
        ],
    )


def test_round_half_to_zero() -> None:
    """round: half-to-zero"""
    _rounds(
        "half-to-zero",
        [
            ("321.123", -3, "0"),
            ("145", -1, "140"),
            ("-2.4", 0, "-2"),
            ("-2.5", 0, "-2"),
            ("1.95", 1, "1.9"),
            ("-1.95", 1, "-1.9"),
            ("0.1234567898765", 12, "0.123456789876"),
            ("-0.1234567898765", 12, "-0.123456789876"),
        ],
    )


def test_round_half_from_zero() -> None:
    """round: half-from-zero"""
    _rounds(
        "half-from-zero",
        [
            ("321.123", -3, "0"),
            ("145", -1, "150"),
            ("-2.4", 0, "-2"),
            ("-2.5", 0, "-3"),
            ("1.95", 1, "2"),
            ("-1.95", 1, "-2"),
            ("0.1234567898765", 12, "0.123456789877"),
            ("-0.1234567898765", 12, "-0.123456789877"),
        ],
    )
    assert _("2.5").round() == _("3")


_HALF_EVEN = [
    ("321.123", -3, "0"),
    ("145", -1, "140"),
    ("-2.4", 0, "-2"),
    ("-2.5", 0, "-2"),
    ("1.95", 1, "2"),
    ("-1.95", 1, "-2"),
    ("0.1234567898765", 12, "0.123456789876"),
    ("-0.1234567898765", 12, "-0.123456789876"),
]


def test_round_half_even() -> None:
    """round: half-even"""
    _rounds("half-even", _HALF_EVEN)


def test_round_half_odd() -> None:
    """round: half-odd"""
    # Effect's test repeats the half-even cases; half-odd itself is checked below.
    _rounds("half-even", _HALF_EVEN)
    _rounds(
        "half-odd", [("145", -1, "150"), ("-2.5", 0, "-3"), ("1.85", 1, "1.9"), ("2.4", 0, "2")]
    )


# Property based testing (``describe.skip`` in Effect)

_INT32 = st.integers(-(2**31), 2**31 - 1)
_ARB_WITH_ZERO = st.one_of(
    st.just(big_decimal.make_normalized_unsafe(0, 0)),
    st.tuples(st.integers(), _INT32).map(lambda vs: make(*vs)),
    st.tuples(st.integers(), _INT32).map(lambda vs: make(*vs)),
    st.tuples(st.integers(), _INT32).map(lambda vs: make(*vs)),
)


def _js_to_exponential(n: float) -> str:
    """``Number.prototype.toExponential()`` with no digit count: the shortest
    round-trip digits, as ``repr`` gives them."""
    if n == 0:
        return "0e+0"
    sign, digits, exponent = Decimal(repr(n)).normalize().as_tuple()
    assert isinstance(exponent, int)
    text = "".join(map(str, digits))
    mantissa = text[0] + (f".{text[1:]}" if len(text) > 1 else "")
    power = exponent + len(text) - 1
    return f"{'-' if sign else ''}{mantissa}e{'+' if power >= 0 else '-'}{abs(power)}"


# Effect 4.1.2's ``fromString`` refuses a scale past 10,000 either way, which its skipped
# property (scales over all int32) would now find; the round trip is drawn within that bound.
_PARSEABLE = st.one_of(
    st.just(big_decimal.make_normalized_unsafe(0, 0)),
    st.tuples(st.integers(-(10**30), 10**30), st.integers(-9_900, 10_000)).map(
        lambda vs: make(*vs)
    ),
)


@testing.prop(_PARSEABLE)
def test_unsafe_from_string_and_format_should_be_inverses(bd: BigDecimal) -> bool:
    """unsafeFromString and format should be inverses"""
    return big_decimal.from_string_unsafe(bd.format()) == bd


@testing.prop(st.floats(width=32, allow_nan=False, allow_infinity=False))
def test_to_exponential_should_harmonize_with_number_to_exponential(n: float) -> bool:
    """toExponential should harmonize with Number.prototype.toExponential"""
    return _js_to_exponential(n) == big_decimal.from_number_unsafe(n).to_exponential()


def test_js_to_exponential_matches_node() -> None:
    """The reference above gives what Node printed for these numbers."""
    printed = [
        (0.0, "0e+0"),
        (-0.0, "0e+0"),
        (-1.0, "-1e+0"),
        (0.1, "1e-1"),
        (3.4028234663852886e38, "3.4028234663852886e+38"),
        (123456.7, "1.234567e+5"),
        (-0.000123, "-1.23e-4"),
        (1e21, "1e+21"),
        (5e-7, "5e-7"),
        (0.30000001192092896, "3.0000001192092896e-1"),
    ]
    for n, text in printed:
        assert _js_to_exponential(n) == text
