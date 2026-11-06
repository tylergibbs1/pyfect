"""Number, bigint and date checks (Effect's ``isFinite``, ``isInt``,
``isGreaterThan``, ``isBetweenBigInt``, ``isGreaterThanDate``, ...).

Number checks take ``int`` and ``float``. ``is_int`` is JavaScript's
``Number.isSafeInteger`` over either (``2.0``, not ``2 ** 53``); past that use
``S.BigInt``. The ``_big_int`` variants are the same checks over ``int``
with Effect's ``bigint`` text (``"a value greater than 5n"``). A bound must
be finite: a non-finite one raises ``ValueError`` (Effect's ``RangeError``).
"""

from __future__ import annotations

import math
from collections.abc import Callable, Mapping
from datetime import datetime
from decimal import Decimal

from pyfect._js import js_number
from pyfect.logger._text import iso_millis
from pyfect.schema._checks_order import (
    Between,
    Bound,
    make_is_between,
    make_is_greater_than,
    make_is_greater_than_or_equal_to,
    make_is_less_than,
    make_is_less_than_or_equal_to,
)
from pyfect.schema.ast import Filter, FilterGroup, filter_of

_MAX_SAFE_INTEGER = 2**53 - 1


def _representation(id: str, payload: object) -> dict[str, object]:
    return {"representation": {"id": f"effect/schema/{id}", "payload": payload}}


def _finite(bound: float) -> float:
    if not (isinstance(bound, int) or math.isfinite(bound)):
        raise ValueError(f"Expected a finite number, got {js_number(bound)}")
    return bound


def is_finite(**annotations: object) -> Filter[float]:
    """Not ``NaN`` nor an infinity."""
    return filter_of(
        lambda n: isinstance(n, int) or math.isfinite(n),
        {"expected": "a finite number", **_representation("isFinite", None), **annotations},
    )


def _is_safe_integer(n: float) -> bool:
    return (isinstance(n, int) or n.is_integer()) and abs(n) <= _MAX_SAFE_INTEGER


def is_int(**annotations: object) -> Filter[float]:
    """A safe integer, as an ``int`` or a ``float``."""
    return filter_of(
        _is_safe_integer,
        {"expected": "an integer", **_representation("isInt", None), **annotations},
    )


def int_value(**annotations: object) -> Filter[float]:
    """``is_int`` for the ``Int`` schema: a safe ``int`` only, as its type says."""
    return filter_of(
        lambda n: isinstance(n, int) and abs(n) <= _MAX_SAFE_INTEGER,
        {"expected": "an integer", **_representation("isInt", None), **annotations},
    )


def _number_bound(id: str, key: str) -> Callable[[float], Mapping[str, object]]:
    return lambda bound: _representation(id, {key: _finite(bound)})


is_greater_than: Bound[float] = make_is_greater_than(
    formatter=js_number, annotate=_number_bound("isGreaterThan", "exclusiveMinimum")
)
is_greater_than_or_equal_to: Bound[float] = make_is_greater_than_or_equal_to(
    formatter=js_number, annotate=_number_bound("isGreaterThanOrEqualTo", "minimum")
)
is_less_than: Bound[float] = make_is_less_than(
    formatter=js_number, annotate=_number_bound("isLessThan", "exclusiveMaximum")
)
is_less_than_or_equal_to: Bound[float] = make_is_less_than_or_equal_to(
    formatter=js_number, annotate=_number_bound("isLessThanOrEqualTo", "maximum")
)


def _between_payload(
    id: str, encode: Callable[[object], object]
) -> Callable[[object, object, bool, bool], Mapping[str, object]]:
    def annotate(
        minimum: object, maximum: object, exclusive_minimum: bool, exclusive_maximum: bool
    ) -> Mapping[str, object]:
        payload = {"minimum": encode(minimum), "maximum": encode(maximum)}
        if exclusive_minimum:
            payload["exclusiveMinimum"] = True
        if exclusive_maximum:
            payload["exclusiveMaximum"] = True
        return _representation(id, payload)

    return annotate


def _finite_payload(bound: object) -> object:
    return _finite(bound) if isinstance(bound, int | float) else bound


is_between: Between[float] = make_is_between(
    formatter=js_number, annotate=_between_payload("isBetween", _finite_payload)
)


def _decimal_parts(n: float) -> tuple[int, int]:
    """``n`` as ``coefficient * 10 ** exponent``, from its shortest decimal
    spelling (JavaScript's ``toExponential``) or exactly for an integer."""
    if isinstance(n, int) or n.is_integer():
        return int(n), 0
    sign, digits, exponent = Decimal(repr(n)).as_tuple()
    coefficient = int("".join(map(str, digits)))
    return (-coefficient if sign else coefficient), int(exponent)


def _is_multiple(n: float, divisor: float) -> bool:
    """Effect's ``Number.remainder(n, divisor) === 0``, computed exactly."""
    if not (isinstance(n, int) or math.isfinite(n)):
        return False
    n_coefficient, n_exponent = _decimal_parts(n)
    d_coefficient, d_exponent = _decimal_parts(divisor)
    exponent = min(n_exponent, d_exponent)
    scaled = d_coefficient * 10 ** (d_exponent - exponent)
    return (n_coefficient * 10 ** (n_exponent - exponent)) % scaled == 0


def is_multiple_of(divisor: float, /, **annotations: object) -> Filter[float]:
    """A multiple of ``divisor`` (its sign ignored), decided on the numbers'
    shortest decimal spellings: ``0.3`` is a multiple of ``0.1``. A zero or
    non-finite divisor raises ``ValueError``."""
    if not (isinstance(divisor, int) or math.isfinite(divisor)) or divisor == 0:
        raise ValueError(f"Expected a finite non-zero number, got {js_number(divisor)}")
    divisor = abs(divisor)
    return filter_of(
        lambda n: _is_multiple(n, divisor),
        {
            "expected": f"a value that is a multiple of {js_number(divisor)}",
            **_representation("isMultipleOf", {"divisor": divisor}),
            **annotations,
        },
    )


def is_int32(**annotations: object) -> FilterGroup[float]:
    """An integer from ``-2 ** 31`` to ``2 ** 31 - 1``."""
    return FilterGroup(
        (is_int(), is_between(minimum=-2147483648, maximum=2147483647)),
        {"expected": "a 32-bit integer", **annotations},
    )


def is_uint32(**annotations: object) -> FilterGroup[float]:
    """An integer from ``0`` to ``2 ** 32 - 1``."""
    return FilterGroup(
        (is_int(), is_between(minimum=0, maximum=4294967295)),
        {"expected": "a 32-bit unsigned integer", **annotations},
    )


def _big_int(value: int) -> str:
    return f"{value}n"


def _big_int_bound(id: str, key: str) -> Callable[[int], Mapping[str, object]]:
    return lambda bound: _representation(id, {key: str(bound)})


is_greater_than_big_int: Bound[int] = make_is_greater_than(
    formatter=_big_int, annotate=_big_int_bound("isGreaterThanBigInt", "exclusiveMinimum")
)
is_greater_than_or_equal_to_big_int: Bound[int] = make_is_greater_than_or_equal_to(
    formatter=_big_int, annotate=_big_int_bound("isGreaterThanOrEqualToBigInt", "minimum")
)
is_less_than_big_int: Bound[int] = make_is_less_than(
    formatter=_big_int, annotate=_big_int_bound("isLessThanBigInt", "exclusiveMaximum")
)
is_less_than_or_equal_to_big_int: Bound[int] = make_is_less_than_or_equal_to(
    formatter=_big_int, annotate=_big_int_bound("isLessThanOrEqualToBigInt", "maximum")
)
is_between_big_int: Between[int] = make_is_between(
    formatter=_big_int, annotate=_between_payload("isBetweenBigInt", str)
)


def _date_bound(id: str, key: str) -> Callable[[datetime], Mapping[str, object]]:
    return lambda bound: _representation(id, {key: iso_millis(bound)})


def _date_payload(bound: object) -> object:
    return iso_millis(bound) if isinstance(bound, datetime) else bound


is_greater_than_date: Bound[datetime] = make_is_greater_than(
    formatter=iso_millis, annotate=_date_bound("isGreaterThanDate", "exclusiveMinimum")
)
is_greater_than_or_equal_to_date: Bound[datetime] = make_is_greater_than_or_equal_to(
    formatter=iso_millis, annotate=_date_bound("isGreaterThanOrEqualToDate", "minimum")
)
is_less_than_date: Bound[datetime] = make_is_less_than(
    formatter=iso_millis, annotate=_date_bound("isLessThanDate", "exclusiveMaximum")
)
is_less_than_or_equal_to_date: Bound[datetime] = make_is_less_than_or_equal_to(
    formatter=iso_millis, annotate=_date_bound("isLessThanOrEqualToDate", "maximum")
)
is_between_date: Between[datetime] = make_is_between(
    formatter=iso_millis, annotate=_between_payload("isBetweenDate", _date_payload)
)
