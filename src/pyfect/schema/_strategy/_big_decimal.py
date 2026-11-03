"""``BigDecimal`` values built within their checks' bounds rather than
filtered (Effect's ``internal/arbitrary/bigDecimal.ts``): a coefficient
drawn at a scale, near the bounds' scale or over wide precisions and
exponents, with Effect's special values. Hypothesis shrinks toward the
first special value, zero when the bounds allow it."""

from __future__ import annotations

from dataclasses import dataclass

from hypothesis import strategies as st

from pyfect import big_decimal as bd
from pyfect.schema._arbitrary_constraint import ArbitraryConstraint

_MAX_SAFE = 2**53 - 1
_MAX_GENERATED_BITS = 425
_MAX_EXACT_POWER = 4_096
_ZERO = bd.make(0, 0)


@dataclass(frozen=True, slots=True)
class _Bounds:
    minimum: bd.BigDecimal | None
    exclusive_minimum: bool
    maximum: bd.BigDecimal | None
    exclusive_maximum: bool

    def allows(self, value: bd.BigDecimal) -> bool:
        low, high = self.minimum, self.maximum
        if low is not None and (value < low or (self.exclusive_minimum and value == low)):
            return False
        return high is None or not (value > high or (self.exclusive_maximum and value == high))


def _add_scale(scale: int, offset: int, maximum: int = _MAX_SAFE) -> int:
    return min(maximum, scale + offset)


def _inward(value: bd.BigDecimal | None, exclusive: bool, direction: int) -> bd.BigDecimal | None:
    """The closest value past an exclusive bound, one digit finer."""
    if value is None or not exclusive:
        return value
    if value.scale < _MAX_SAFE:
        return bd.make(value.value * 10 + direction, value.scale + 1)
    return bd.make(value.value + direction, value.scale)


def _digits(value: int) -> int:
    """How many decimal digits ``value`` has, without ``str`` (which refuses
    more than 4300)."""
    n = abs(value)
    count = max(1, int(n.bit_length() * 0.30102999566398120))
    while 10**count <= n:
        count += 1
    while count > 1 and 10 ** (count - 1) > n:
        count -= 1
    return count


def _round_at_scale(
    value: bd.BigDecimal, scale: int, ceil: bool, maximum_power: int = _MAX_EXACT_POWER
) -> int | None:
    """``value``'s coefficient at ``scale``, rounded up or down; ``None``
    when that needs more than ``maximum_power`` digits."""
    if value.value == 0:
        return 0
    difference = scale - value.scale
    if difference >= 0:
        return None if difference > maximum_power else value.value * 10**difference
    if -difference >= _digits(value.value):
        quotient, remainder = 0, value.value
    else:
        divisor = 10**-difference
        quotient = abs(value.value) // divisor * (1 if value.value > 0 else -1)
        remainder = value.value - quotient * divisor
    if ceil and remainder > 0:
        return quotient + 1
    if not ceil and remainder < 0:
        return quotient - 1
    return quotient


type _Range = tuple[int | None, int | None]


def _coefficient_range(scale: int, bounds: _Bounds) -> _Range | None:
    """The coefficients at ``scale`` within ``bounds``, ``None`` when none is."""
    lower, upper = bounds.minimum, bounds.maximum
    low = None if lower is None else _round_at_scale(lower, scale, not bounds.exclusive_minimum)
    high = None if upper is None else _round_at_scale(upper, scale, bounds.exclusive_maximum)
    # A bound past the precision budget is resolved at the other's precision.
    if lower is not None and low is None and high is not None:
        power = max(_MAX_EXACT_POWER, _digits(high))
        low = _round_at_scale(lower, scale, not bounds.exclusive_minimum, power)
    if upper is not None and high is None and low is not None:
        power = max(_MAX_EXACT_POWER, _digits(low))
        high = _round_at_scale(upper, scale, bounds.exclusive_maximum, power)
    if (low is None and lower is not None and lower.value > 0) or (
        high is None and upper is not None and upper.value < 0
    ):
        return None
    if low is not None and bounds.exclusive_minimum:
        low += 1
    if high is not None and bounds.exclusive_maximum:
        high -= 1
    return None if low is not None and high is not None and low > high else (low, high)


@st.composite
def _coefficient(draw: st.DrawFn, span: _Range) -> int:
    low, high = span
    if low is not None and high is not None:
        return draw(st.integers(low, high))
    ordinary = draw(st.integers(0, 3)) != 0
    bits = draw(st.integers(0, 20) if ordinary else st.integers(1, _MAX_GENERATED_BITS))
    lowest = 0 if bits == 0 else 1 << (bits - 1)
    distance = 0 if bits == 0 else draw(st.integers(lowest, (lowest << 1) - 1))
    if low is not None:
        return low + distance
    if high is not None:
        return high - distance
    return distance if draw(st.booleans()) else -distance


@st.composite
def _scale(draw: st.DrawFn, boundary_scale: int | None) -> int:
    mode = draw(st.integers(0, 7))
    if mode <= 5 and boundary_scale is not None:
        return _add_scale(boundary_scale, draw(st.integers(0, 20 if mode == 5 else 2)))
    if mode == 6:
        return draw(st.integers(-6, 20))
    precision = draw(st.integers(1, 128))
    exponent = draw(st.integers(-512, 512))
    return precision - 1 - exponent


def _general(
    bounds: _Bounds, boundary_scale: int | None, witness: bd.BigDecimal
) -> st.SearchStrategy[bd.BigDecimal]:
    @st.composite
    def general(draw: st.DrawFn) -> bd.BigDecimal:
        for _ in range(16):
            scale = draw(_scale(boundary_scale))
            span = _coefficient_range(scale, bounds)
            if span is None:
                continue
            coefficient = draw(_coefficient(span))
            if scale < _MAX_SAFE and draw(st.integers(0, 7)) == 0:
                trailing = draw(st.integers(1, min(8, _MAX_SAFE - scale)))
                return bd.make(coefficient * 10**trailing, scale + trailing)
            return bd.make(coefficient, scale)
        return witness

    return general()


def big_decimals(constraint: ArbitraryConstraint) -> st.SearchStrategy[bd.BigDecimal]:
    """``BigDecimal`` values within ``constraint``'s bounds; ``ValueError``
    when no value is (Effect's ``Unable to derive an arbitrary for
    BigDecimal constraints``)."""
    low, high = constraint.minimum, constraint.maximum
    bounds = _Bounds(
        low if isinstance(low, bd.BigDecimal) else None,
        constraint.exclusive_minimum,
        high if isinstance(high, bd.BigDecimal) else None,
        constraint.exclusive_maximum,
    )
    empty = ValueError("Unable to derive an arbitrary for BigDecimal constraints")
    if bounds.minimum is not None and bounds.minimum == bounds.maximum:
        if bounds.exclusive_minimum or bounds.exclusive_maximum:
            raise empty
        return st.just(bounds.minimum)
    lower = _inward(bounds.minimum, bounds.exclusive_minimum, 1)
    upper = _inward(bounds.maximum, bounds.exclusive_maximum, -1)
    witness = next((v for v in (_ZERO, lower, upper) if v is not None and bounds.allows(v)), None)
    if witness is None:
        raise empty
    target = witness
    if witness.value < 0 and upper is not None and bounds.allows(upper):
        target = upper
    specials = [
        target,
        witness,
        bd.make(1, 1),
        bd.make(1, 0),
        bd.make(10, 0),
        bd.make(-1, 1),
        bd.make(-1, 0),
        bd.make(-10, 0),
        *([bounds.minimum] if bounds.minimum is not None and not bounds.exclusive_minimum else []),
        *([bounds.maximum] if bounds.maximum is not None and not bounds.exclusive_maximum else []),
    ]
    scales = [v.scale for v in (lower, upper) if v is not None]
    boundary_scale = max(scales) if scales else None
    strategies = [st.sampled_from([v for v in specials if bounds.allows(v)])]
    if boundary_scale is not None:
        preferred = _coefficient_range(boundary_scale, bounds)
        if preferred is not None and preferred[0] is not None and preferred[1] is not None:
            coefficients = st.integers(preferred[0], preferred[1])
            strategies.append(coefficients.map(lambda c: bd.make(c, boundary_scale)))
    strategies.append(_general(bounds, boundary_scale, witness))
    return st.one_of(strategies)
