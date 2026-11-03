"""Arbitrary-precision decimals (Effect's ``BigDecimal``): an ``int`` value
and a ``scale``, the number being ``value * 10 ** -scale``::

    d = big_decimal.from_string_unsafe("123.4500")
    d.format()                        # "123.45"
    d.divide_unsafe(BigDecimal(3, 0))  # 100 significant digits, rounded half up
    d.round(scale=1, mode="half-even")

``decimal.Decimal`` rounds every result to its context's precision (28
digits by default) and keeps signed zeros and exponents apart; a
``BigDecimal`` is exact for ``+``, ``-`` and ``*``, divides to 100
significant digits as Effect does, and ``==`` / ``hash`` / ``<`` compare
values (``2`` equals ``2.00``). The scale is any integer from
``-(2**53 - 1)`` to ``2**53 - 1``.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Literal

from pyfect._digits import digits_value
from pyfect._js import int_text, js_number

_MAX_SAFE = 2**53 - 1
_DEFAULT_PRECISION = 100
_MAX_COMPARISON_SCALE_ALIGNMENT = 100

type RoundingMode = Literal[
    "ceil",
    "floor",
    "to-zero",
    "from-zero",
    "half-ceil",
    "half-floor",
    "half-to-zero",
    "half-from-zero",
    "half-even",
    "half-odd",
]


def _check_scale(scale: int) -> int:
    if type(scale) is not int or not -_MAX_SAFE <= scale <= _MAX_SAFE:
        raise ValueError(f"Scale must be a safe integer, got {js_number(scale)}")
    return scale


def _tdiv(a: int, b: int) -> int:
    """JavaScript's ``bigint`` division: truncated toward zero."""
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _trem(a: int, b: int) -> int:
    """JavaScript's ``bigint`` ``%``: the sign of the dividend."""
    return a - b * _tdiv(a, b)


def _cmp(a: int, b: int) -> Literal[-1, 0, 1]:
    return -1 if a < b else 1 if a > b else 0


@dataclass(frozen=True, slots=True, eq=False)
class BigDecimal:
    """``value * 10 ** -scale``; the constructor is Effect's ``make``."""

    value: int
    scale: int
    _normalized: BigDecimal | None = field(default=None, init=False, repr=False)

    def __post_init__(self) -> None:
        _check_scale(self.scale)

    # --- representation ---------------------------------------------------------------

    def normalize(self) -> BigDecimal:
        """The same number without trailing zeros in ``value`` (``0`` has
        scale 0); remembered once computed."""
        if self._normalized is not None:
            return self._normalized
        if self.value == 0:
            out = _ZERO
        else:
            digits = int_text(self.value)
            stripped = digits.rstrip("0")
            trailing = len(digits) - len(stripped)
            out = self if trailing == 0 else _normalized(int(stripped), self.scale - trailing)
        object.__setattr__(self, "_normalized", out)
        return out

    def rescale(self, scale: int) -> BigDecimal:
        """The number at ``scale``, digits beyond it truncated toward zero
        (Effect's ``scale``)."""
        if scale > self.scale:
            return BigDecimal(self.value * 10 ** (scale - self.scale), scale)
        if scale < self.scale:
            return BigDecimal(_tdiv(self.value, 10 ** (self.scale - scale)), scale)
        return self

    def format(self) -> str:
        """Plain notation, or exponential when the normalized scale is 16 or
        more either way."""
        n = self.normalize()
        if abs(n.scale) >= 16:
            return n.to_exponential()
        negative = n.value < 0
        absolute = int_text(-n.value if negative else n.value)
        if n.scale > 0:
            digits = absolute.rjust(n.scale + 1, "0")
            point = len(digits) - n.scale
            complete = f"{digits[:point]}.{digits[point:]}"
        else:
            complete = absolute + "0" * -n.scale
        return f"-{complete}" if negative else complete

    def to_exponential(self) -> str:
        """``d[.ddd]e±n``, as JavaScript's ``toExponential()``."""
        if self.value == 0:
            return "0e+0"
        n = self.normalize()
        digits = int_text(n.value)
        point = 2 if n.value < 0 else 1
        head, tail = digits[:point], digits[point:]
        exp = len(tail) - n.scale
        return f"{head}{'.' + tail if tail else ''}e{'+' if exp >= 0 else ''}{exp}"

    def to_number_unsafe(self) -> float:
        """The nearest float (``Number(format(n))``)."""
        return float(self.format())

    def __str__(self) -> str:
        return self.format()

    def __repr__(self) -> str:
        return f"BigDecimal({self.format()})"

    # --- predicates -------------------------------------------------------------------

    def sign(self) -> Literal[-1, 0, 1]:
        return _cmp(self.value, 0)

    def is_integer(self) -> bool:
        return self.normalize().scale <= 0

    def is_zero(self) -> bool:
        return self.value == 0

    def is_negative(self) -> bool:
        return self.value < 0

    def is_positive(self) -> bool:
        return self.value > 0

    # --- arithmetic -------------------------------------------------------------------

    def sum(self, that: BigDecimal) -> BigDecimal:
        if that.value == 0:
            return self
        if self.value == 0:
            return that
        if self.scale > that.scale:
            return BigDecimal(that.rescale(self.scale).value + self.value, self.scale)
        if self.scale < that.scale:
            return BigDecimal(self.rescale(that.scale).value + that.value, that.scale)
        return BigDecimal(self.value + that.value, self.scale)

    def subtract(self, that: BigDecimal) -> BigDecimal:
        if that.value == 0:
            return self
        if self.value == 0:
            return BigDecimal(-that.value, that.scale)
        if self.scale > that.scale:
            return BigDecimal(self.value - that.rescale(self.scale).value, self.scale)
        if self.scale < that.scale:
            return BigDecimal(self.rescale(that.scale).value - that.value, that.scale)
        return BigDecimal(self.value - that.value, self.scale)

    def multiply(self, that: BigDecimal) -> BigDecimal:
        if self.value == 0 or that.value == 0:
            return _ZERO
        return BigDecimal(self.value * that.value, self.scale + that.scale)

    def divide(self, that: BigDecimal) -> BigDecimal | None:
        """The quotient to 100 significant digits, the last rounded half up;
        ``None`` for a zero divisor."""
        return None if that.value == 0 else self.divide_unsafe(that)

    def divide_unsafe(self, that: BigDecimal) -> BigDecimal:
        """``divide``; raises ``ZeroDivisionError`` for a zero divisor."""
        if that.value == 0:
            raise ZeroDivisionError("Division by zero")
        if self.value == 0:
            return _ZERO
        scale = self.scale - that.scale
        if self.value == that.value:
            return BigDecimal(1, scale)
        return _divide(self.value, that.value, scale, _DEFAULT_PRECISION)

    def remainder(self, divisor: BigDecimal) -> BigDecimal | None:
        """The remainder with the dividend's sign; ``None`` for a zero divisor."""
        return None if divisor.value == 0 else self.remainder_unsafe(divisor)

    def remainder_unsafe(self, divisor: BigDecimal) -> BigDecimal:
        if divisor.value == 0:
            raise ZeroDivisionError("Division by zero")
        scale = max(self.scale, divisor.scale)
        return BigDecimal(_trem(self.rescale(scale).value, divisor.rescale(scale).value), scale)

    def abs(self) -> BigDecimal:
        return BigDecimal(-self.value, self.scale) if self.value < 0 else self

    def negate(self) -> BigDecimal:
        return BigDecimal(-self.value, self.scale)

    def __add__(self, that: BigDecimal) -> BigDecimal:
        return self.sum(that)

    def __sub__(self, that: BigDecimal) -> BigDecimal:
        return self.subtract(that)

    def __mul__(self, that: BigDecimal) -> BigDecimal:
        return self.multiply(that)

    def __truediv__(self, that: BigDecimal) -> BigDecimal:
        return self.divide_unsafe(that)

    def __mod__(self, that: BigDecimal) -> BigDecimal:
        return self.remainder_unsafe(that)

    def __neg__(self) -> BigDecimal:
        return self.negate()

    def __abs__(self) -> BigDecimal:
        return self.abs()

    # --- rounding ---------------------------------------------------------------------

    def truncate(self, scale: int = 0) -> BigDecimal:
        """Digits beyond ``scale`` dropped (toward zero)."""
        if self.scale <= scale:
            return self
        return BigDecimal(_tdiv(self.value, 10 ** (self.scale - scale)), scale)

    def ceil(self, scale: int = 0) -> BigDecimal:
        truncated = self.truncate(scale)
        if self.value > 0 and truncated < self:
            return truncated.sum(BigDecimal(1, scale))
        return truncated

    def floor(self, scale: int = 0) -> BigDecimal:
        truncated = self.truncate(scale)
        if self.value < 0 and truncated > self:
            return truncated.sum(BigDecimal(-1, scale))
        return truncated

    def digit_at(self, scale: int) -> int:
        """The digit at ``scale`` (0 the units, 1 the tenths, -1 the tens),
        negative for a negative number."""
        if self.scale < scale:
            return 0
        return _trem(_tdiv(self.value, 10 ** (self.scale - scale)), 10)

    def round(self, *, scale: int = 0, mode: RoundingMode = "half-from-zero") -> BigDecimal:  # noqa: PLR0911
        """Rounded to ``scale`` digits by ``mode``."""
        up, down = BigDecimal(5, scale + 1), BigDecimal(-5, scale + 1)
        match mode:
            case "ceil":
                return self.ceil(scale)
            case "floor":
                return self.floor(scale)
            case "to-zero":
                return self.truncate(scale)
            case "from-zero":
                return self.ceil(scale) if self.value > 0 else self.floor(scale)
            case "half-ceil":
                return self.sum(up).floor(scale)
            case "half-floor":
                return self.sum(down).ceil(scale)
            case "half-to-zero":
                return self.sum(up).floor(scale) if self.value < 0 else self.sum(down).ceil(scale)
            case "half-from-zero":
                return self.sum(down).ceil(scale) if self.value < 0 else self.sum(up).floor(scale)
            case "half-even" | "half-odd":
                half_ceil, half_floor = self.sum(up).floor(scale), self.sum(down).ceil(scale)
                if half_ceil == half_floor:
                    return half_ceil
                even = _trem(half_ceil.digit_at(scale), 2) == 0
                return half_ceil if even == (mode == "half-even") else half_floor

    # --- comparison -------------------------------------------------------------------

    def compare(self, that: BigDecimal) -> Literal[-1, 0, 1]:
        """Effect's ``Order``: ``-1``, ``0`` or ``1``."""
        if self.scale == that.scale:
            return _cmp(self.value, that.value)
        mine, theirs = self.sign(), that.sign()
        if mine != theirs:
            return -1 if mine < theirs else 1
        if mine == 0:
            return 0
        difference = self.scale - that.scale
        if abs(difference) > _MAX_COMPARISON_SCALE_ALIGNMENT:
            return _magnitude(that, self) if mine == -1 else _magnitude(self, that)
        power = 10 ** abs(difference)
        if difference > 0:
            return _cmp(self.value, that.value * power)
        return _cmp(self.value * power, that.value)

    def between(self, *, minimum: BigDecimal, maximum: BigDecimal) -> bool:
        """``minimum <= self <= maximum``."""
        return minimum <= self <= maximum

    def clamp(self, *, minimum: BigDecimal, maximum: BigDecimal) -> BigDecimal:
        """``self`` held within ``minimum`` and ``maximum``."""
        return min(max(self, minimum), maximum)

    def __eq__(self, other: object) -> bool:
        if not isinstance(other, BigDecimal):
            return NotImplemented
        return self.compare(other) == 0

    def __hash__(self) -> int:
        n = self.normalize()
        return hash((n.value, n.scale))

    def __lt__(self, other: BigDecimal) -> bool:
        return self.compare(other) < 0

    def __le__(self, other: BigDecimal) -> bool:
        return self.compare(other) <= 0

    def __gt__(self, other: BigDecimal) -> bool:
        return self.compare(other) > 0

    def __ge__(self, other: BigDecimal) -> bool:
        return self.compare(other) >= 0


def _normalized(value: int, scale: int) -> BigDecimal:
    out = BigDecimal(value, scale)
    object.__setattr__(out, "_normalized", out)
    return out


_ZERO = _normalized(0, 0)
_ONE = _normalized(1, 0)


def _magnitude(a: BigDecimal, b: BigDecimal) -> Literal[-1, 0, 1]:
    """Compare ``|a|`` and ``|b|`` without aligning their scales."""
    a_digits, b_digits = int_text(abs(a.value)), int_text(abs(b.value))
    exponent = len(a_digits) - len(b_digits) - a.scale + b.scale
    if exponent != 0:
        return -1 if exponent < 0 else 1
    width = max(len(a_digits), len(b_digits))
    left, right = a_digits.ljust(width, "0"), b_digits.ljust(width, "0")
    return -1 if left < right else 1 if left > right else 0


def round_terminal(n: int) -> int:
    """``1`` when the leading digit of ``n`` is 5 or more, else ``0``."""
    return 0 if int(int_text(abs(n))[0]) < 5 else 1


def _divide(num: int, den: int, scale: int, precision: int) -> BigDecimal:
    negate = (num < 0) != (den < 0)
    num, den = abs(num), abs(den)
    while num < den:
        num *= 10
        scale += 1
    quotient, remainder = divmod(num, den)
    if remainder == 0:
        return BigDecimal(-quotient if negate else quotient, scale)
    count = len(int_text(quotient))
    remainder *= 10
    while remainder != 0 and count < precision:
        q, r = divmod(remainder, den)
        quotient = quotient * 10 + q
        remainder = r * 10
        count += 1
        scale += 1
    if remainder != 0:
        quotient += round_terminal(remainder // den)
    return BigDecimal(-quotient if negate else quotient, scale)


# --- constructors -------------------------------------------------------------------


def make(value: int, scale: int) -> BigDecimal:
    """``value * 10 ** -scale``; raises ``ValueError`` for a scale past
    ``2**53 - 1`` either way."""
    return BigDecimal(value, scale)


def make_normalized_unsafe(value: int, scale: int) -> BigDecimal:
    """A ``BigDecimal`` already normalized; raises ``ValueError`` when
    ``value`` ends in a zero."""
    if value != 0 and value % 10 == 0:
        raise ValueError("Value must be normalized")
    _check_scale(scale)
    return _normalized(value, scale)


def from_big_int(n: int) -> BigDecimal:
    return BigDecimal(n, 0)


def from_number(n: float) -> BigDecimal | None:
    """The decimal JavaScript prints for ``n`` (``0.1`` is ``0.1``, not the
    binary fraction); ``None`` for NaN and the infinities."""
    if not math.isfinite(n):
        return None
    text = js_number(n)
    if "e" in text:
        return from_string(text)
    lead, _, trail = text.partition(".")
    return BigDecimal(int(lead + trail), len(trail))


def from_number_unsafe(n: float) -> BigDecimal:
    """``from_number``; raises ``ValueError`` for a non-finite ``n``."""
    out = from_number(n)
    if out is None:
        raise ValueError(f"Number must be finite, got {js_number(n)}")
    return out


def _finite_int(text: str) -> int | None:
    """``[+-]digits`` as an int (JavaScript's ``BigInt``), else ``None``."""
    sign = text[:1]
    if sign not in ("+", "-"):
        return digits_value(text)
    magnitude = digits_value(text[1:])
    return None if magnitude is None else -magnitude if sign == "-" else magnitude


def from_string(text: str) -> BigDecimal | None:
    """``[+-]digits[.digits][e[+-]digits]`` (``""`` is zero); ``None`` for
    anything else or a scale past ``2**53 - 1``."""
    if text == "":
        return _ZERO
    base, exp = text, 0
    separator = next((i for i, c in enumerate(text) if c in "eE"), -1)
    if separator != -1:
        base, parsed = text[:separator], _finite_int(text[separator + 1 :])
        if base == "" or parsed is None or not -_MAX_SAFE <= parsed <= _MAX_SAFE:
            return None
        exp = parsed
    lead, dot, fraction = base.partition(".")
    value = _finite_int(lead + fraction if dot else base)
    if value is None:
        return None
    scale = len(fraction) - exp
    if not -_MAX_SAFE <= scale <= _MAX_SAFE:
        return None
    return BigDecimal(value, scale)


def from_string_unsafe(text: str) -> BigDecimal:
    """``from_string``; raises ``ValueError`` for an invalid string."""
    out = from_string(text)
    if out is None:
        raise ValueError(f"Invalid numerical string: {text}")
    return out


def sum_all(values: Iterable[BigDecimal]) -> BigDecimal:
    out = _ZERO
    for n in values:
        out = out.sum(n)
    return out


def multiply_all(values: Iterable[BigDecimal]) -> BigDecimal:
    out = _ONE
    for n in values:
        if n.value == 0:
            return _ZERO
        out = out.multiply(n)
    return out


__all__ = [
    "BigDecimal",
    "RoundingMode",
    "from_big_int",
    "from_number",
    "from_number_unsafe",
    "from_string",
    "from_string_unsafe",
    "make",
    "make_normalized_unsafe",
    "multiply_all",
    "round_terminal",
    "sum_all",
]
