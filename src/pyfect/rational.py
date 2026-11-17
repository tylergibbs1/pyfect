"""Exact fractions (Effect's ``Rational``): an ``int`` numerator over a positive ``int``
denominator, always in lowest terms::

    third = rational.make_unsafe(1, 3)
    third * rational.from_big_int(3) == rational.from_big_int(1)  # True
    third.to_big_decimal(scale=3)                                  # BigDecimal(0.333)

A ``Rational`` is canonical by construction: ``make`` reduces, and the class refuses a pair
that is not reduced or has a non-positive denominator, so ``==`` and ``hash`` compare the
pair. ``fractions.Fraction`` is the standard library's equivalent; this type follows
Effect's API, text format and rounding (``to_big_decimal`` takes Effect's rounding modes).
"""

from __future__ import annotations

import math
import re
from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from pyfect import big_decimal
from pyfect._digits import to_int
from pyfect._js import int_text, js_number

_MAX_SAFE = 2**53 - 1
MAX_DIGITS = big_decimal.MAX_DIGITS
"""The most significant digits ``from_string`` (and so ``S.RationalFromString``) reads by
default, as ``big_decimal.from_string``: converting a longer run costs superlinear time."""
_FRACTION = re.compile(r"([+-]?[0-9]+)(?:/([+-]?[0-9]+))?")


@dataclass(frozen=True, slots=True)
class Rational:
    """``numerator / denominator`` in lowest terms with ``denominator > 0``; use ``make`` or
    ``make_unsafe`` to reduce any other pair."""

    numerator: int
    denominator: int

    def __post_init__(self) -> None:
        if self.denominator <= 0 or math.gcd(self.numerator, self.denominator) != 1:
            raise ValueError(
                f"Rational({int_text(self.numerator)}, {int_text(self.denominator)}) is not in "
                "lowest terms with a "
                "positive denominator; use rational.make_unsafe"
            )

    # --- representation ---------------------------------------------------------------

    def format(self) -> str:
        """``"numerator/denominator"``, which ``from_string`` reads back."""
        return f"{int_text(self.numerator)}/{int_text(self.denominator)}"

    def __str__(self) -> str:
        return f"Rational({self.format()})"

    def __repr__(self) -> str:
        return f"Rational({self.format()})"

    def to_json(self) -> dict[str, str]:
        """Effect's ``toJSON``."""
        return {
            "_id": "Rational",
            "numerator": int_text(self.numerator),
            "denominator": int_text(self.denominator),
        }

    def to_number_unsafe(self) -> float:
        """The nearest float, rounding the ratio once (ties to even, subnormals included);
        too large a magnitude is an infinity."""
        try:
            return self.numerator / self.denominator
        except OverflowError:
            return math.inf if self.numerator > 0 else -math.inf

    def to_big_decimal(
        self, *, scale: int, mode: big_decimal.RoundingMode = "half-from-zero"
    ) -> big_decimal.BigDecimal:
        """The value rounded to ``scale`` digits after the point with ``mode``."""
        if type(scale) is not int or not -_MAX_SAFE <= scale <= _MAX_SAFE:
            raise ValueError(f"Scale must be a safe integer, got {js_number(scale)}")
        numerator, denominator = self.numerator, self.denominator
        if scale >= 0:
            numerator *= 10**scale
        else:
            denominator *= 10**-scale
        quotient = abs(numerator) // denominator
        remainder = abs(numerator) - quotient * denominator
        if numerator < 0:
            quotient, remainder = -quotient, -remainder
        adjustment = _rounding_adjustment(quotient, remainder, denominator, mode)
        return big_decimal.make(quotient + adjustment, scale)

    # --- predicates -------------------------------------------------------------------

    def sign(self) -> Literal[-1, 0, 1]:
        return 0 if self.numerator == 0 else -1 if self.numerator < 0 else 1

    def is_zero(self) -> bool:
        return self.numerator == 0

    def is_negative(self) -> bool:
        return self.numerator < 0

    def is_positive(self) -> bool:
        return self.numerator > 0

    def is_integer(self) -> bool:
        return self.denominator == 1

    # --- arithmetic -------------------------------------------------------------------

    def sum(self, that: Rational) -> Rational:
        return _sum_coprime(self.numerator, self.denominator, that.numerator, that.denominator)

    def subtract(self, that: Rational) -> Rational:
        return _sum_coprime(self.numerator, self.denominator, -that.numerator, that.denominator)

    def multiply(self, that: Rational) -> Rational:
        return _multiply_coprime(self.numerator, self.denominator, that.numerator, that.denominator)

    def divide(self, that: Rational) -> Rational | None:
        """``self / that``, or ``None`` when ``that`` is zero."""
        if that.numerator == 0:
            return None
        if that.numerator < 0:
            return _multiply_coprime(
                self.numerator, self.denominator, -that.denominator, -that.numerator
            )
        return _multiply_coprime(self.numerator, self.denominator, that.denominator, that.numerator)

    def divide_unsafe(self, that: Rational) -> Rational:
        """``self / that``; raises ``ZeroDivisionError`` when ``that`` is zero."""
        out = self.divide(that)
        if out is None:
            raise ZeroDivisionError("Division by zero")
        return out

    def pow(self, exponent: int) -> Rational | None:
        """``self ** exponent``, inverting for a negative exponent; ``None`` for zero to a
        negative power. The exponent must be a safe integer."""
        if type(exponent) is not int or not -_MAX_SAFE <= exponent <= _MAX_SAFE:
            raise ValueError(f"Exponent must be a safe integer, got {js_number(exponent)}")
        if exponent >= 0:
            # Powers of coprime integers stay coprime.
            return _canonical(self.numerator**exponent, self.denominator**exponent)
        if self.numerator == 0:
            return None
        numerator = self.numerator**-exponent
        denominator = self.denominator**-exponent
        if numerator < 0:
            return _canonical(-denominator, -numerator)
        return _canonical(denominator, numerator)

    def pow_unsafe(self, exponent: int) -> Rational:
        """``pow``; raises ``ZeroDivisionError`` for zero to a negative power."""
        out = self.pow(exponent)
        if out is None:
            raise ZeroDivisionError("Division by zero")
        return out

    def negate(self) -> Rational:
        return _canonical(-self.numerator, self.denominator)

    def abs(self) -> Rational:
        return self.negate() if self.numerator < 0 else self

    def __add__(self, that: Rational) -> Rational:
        return self.sum(that)

    def __sub__(self, that: Rational) -> Rational:
        return self.subtract(that)

    def __mul__(self, that: Rational) -> Rational:
        return self.multiply(that)

    def __truediv__(self, that: Rational) -> Rational:
        return self.divide_unsafe(that)

    def __pow__(self, exponent: int) -> Rational:
        return self.pow_unsafe(exponent)

    def __neg__(self) -> Rational:
        return self.negate()

    def __abs__(self) -> Rational:
        return self.abs()

    # --- comparison -------------------------------------------------------------------

    def compare(self, that: Rational) -> Literal[-1, 0, 1]:
        """Effect's ``Order``: ``-1``, ``0`` or ``1``."""
        # Denominators are positive, so cross-multiplying keeps the order.
        left = self.numerator * that.denominator
        right = that.numerator * self.denominator
        return -1 if left < right else 1 if left > right else 0

    def between(self, *, minimum: Rational, maximum: Rational) -> bool:
        """``minimum <= self <= maximum``."""
        return minimum <= self <= maximum

    def clamp(self, *, minimum: Rational, maximum: Rational) -> Rational:
        """``self`` held within ``minimum`` and ``maximum``."""
        return min(max(self, minimum), maximum)

    def __lt__(self, other: Rational) -> bool:
        return self.compare(other) < 0

    def __le__(self, other: Rational) -> bool:
        return self.compare(other) <= 0

    def __gt__(self, other: Rational) -> bool:
        return self.compare(other) > 0

    def __ge__(self, other: Rational) -> bool:
        return self.compare(other) >= 0


def _canonical(numerator: int, denominator: int) -> Rational:
    """A pair already coprime with a positive denominator."""
    out = object.__new__(Rational)
    object.__setattr__(out, "numerator", numerator)
    object.__setattr__(out, "denominator", denominator)
    return out


def _reduce(numerator: int, denominator: int) -> Rational:
    if denominator < 0:
        numerator, denominator = -numerator, -denominator
    divisor = math.gcd(numerator, denominator)
    return _canonical(numerator // divisor, denominator // divisor)


def _sum_coprime(n1: int, d1: int, n2: int, d2: int) -> Rational:
    # The sum shares factors only with the denominators' gcd (Knuth, TAOCP vol. 2, 4.5.1).
    g = math.gcd(d1, d2)
    if g == 1:
        return _canonical(n1 * d2 + n2 * d1, d1 * d2)
    t = n1 * (d2 // g) + n2 * (d1 // g)
    e = math.gcd(t, g)
    return _canonical(t // e, (d1 // g) * (d2 // e))


def _multiply_coprime(n1: int, d1: int, n2: int, d2: int) -> Rational:
    # Canonical fractions share factors only crosswise; cancelling them first leaves the
    # products coprime (Knuth, TAOCP vol. 2, 4.5.1).
    g1 = math.gcd(n1, d2)
    g2 = math.gcd(n2, d1)
    return _canonical((n1 // g1) * (n2 // g2), (d1 // g2) * (d2 // g1))


def _rounding_adjustment(
    quotient: int, remainder: int, denominator: int, mode: big_decimal.RoundingMode
) -> int:
    """The unit to add to the truncated ``quotient``; ``remainder`` has the value's sign."""
    if remainder == 0:
        return 0
    negative = remainder < 0
    away = -1 if negative else 1
    direct = {
        "to-zero": 0,
        "from-zero": away,
        "ceil": 0 if negative else 1,
        "floor": -1 if negative else 0,
    }
    if mode in direct:
        return direct[mode]
    twice = abs(remainder) * 2
    if twice != denominator:
        return 0 if twice < denominator else away
    return _tie_adjustment(quotient, negative, mode)


def _tie_adjustment(quotient: int, negative: bool, mode: big_decimal.RoundingMode) -> int:
    """The unit to add when the dropped part is exactly one half."""
    away = -1 if negative else 1
    even = quotient % 2 == 0
    match mode:
        case "half-ceil":
            return 0 if negative else 1
        case "half-floor":
            return -1 if negative else 0
        case "half-from-zero":
            return away
        case "half-even":
            return 0 if even else away
        case "half-odd":
            return away if even else 0
        case _:
            return 0


ZERO = _canonical(0, 1)
ONE = _canonical(1, 1)


def make(numerator: int, denominator: int) -> Rational | None:
    """``numerator / denominator`` in lowest terms, or ``None`` for a zero denominator."""
    return None if denominator == 0 else _reduce(numerator, denominator)


def make_unsafe(numerator: int, denominator: int) -> Rational:
    """``make``; raises ``ZeroDivisionError`` for a zero denominator (Effect's
    ``RangeError``)."""
    if denominator == 0:
        raise ZeroDivisionError("Denominator must be non-zero")
    return _reduce(numerator, denominator)


def from_big_int(n: int) -> Rational:
    """The integer ``n``."""
    return _canonical(n, 1)


def from_big_decimal(n: big_decimal.BigDecimal) -> Rational:
    """The exact value of a decimal: ``0.1`` is ``1/10``."""
    normalized = n.normalize()
    if normalized.scale >= 0:
        return _reduce(normalized.value, 10**normalized.scale)
    return _canonical(normalized.value * 10**-normalized.scale, 1)


def from_number(n: float) -> Rational | None:
    """The exact binary value of a finite float (``0.1`` is ``3602879701896397 / 2**55``),
    or ``None`` for NaN and the infinities; ``-0.0`` is ``0/1``."""
    if not math.isfinite(n):
        return None
    numerator, denominator = float(n).as_integer_ratio()
    return _canonical(numerator, denominator)


def from_number_unsafe(n: float) -> Rational:
    """``from_number``; raises ``ValueError`` for NaN and the infinities."""
    out = from_number(n)
    if out is None:
        raise ValueError(f"Number must be finite, got {js_number(n)}")
    return out


def from_string(text: str, *, max_digits: int = MAX_DIGITS) -> Rational | None:
    """``[+-]digits`` or ``[+-]digits/[+-]digits``, reduced; ``None`` for anything else
    (whitespace, a decimal point, an exponent, a zero denominator) and for more than
    ``max_digits`` significant digits in all."""
    match = _FRACTION.fullmatch(text)
    if match is None:
        return None
    numerator, denominator = match.group(1), match.group(2)
    if _significant(numerator) + _significant(denominator or "") > max_digits:
        return None
    return make(to_int(numerator), 1 if denominator is None else to_int(denominator))


def _significant(digits: str) -> int:
    return len(digits.lstrip("+-").lstrip("0"))


def from_string_unsafe(text: str, *, max_digits: int = MAX_DIGITS) -> Rational:
    """``from_string``; raises ``ValueError`` on invalid text."""
    out = from_string(text, max_digits=max_digits)
    if out is None:
        raise ValueError(f"Invalid rational string: {text[:40]}")
    return out


def sum_all(values: Iterable[Rational]) -> Rational:
    out = ZERO
    for value in values:
        out = out.sum(value)
    return out


def multiply_all(values: Iterable[Rational]) -> Rational:
    out = ONE
    for value in values:
        if value.numerator == 0:
            return ZERO
        out = out.multiply(value)
    return out


__all__ = [
    "MAX_DIGITS",
    "ONE",
    "ZERO",
    "Rational",
    "from_big_decimal",
    "from_big_int",
    "from_number",
    "from_number_unsafe",
    "from_string",
    "from_string_unsafe",
    "make",
    "make_unsafe",
    "multiply_all",
    "sum_all",
]
