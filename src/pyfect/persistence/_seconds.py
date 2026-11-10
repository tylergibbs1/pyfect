"""Effect's millisecond ``Duration`` arithmetic, in whole nanoseconds as
Effect's is, and ``SECONDS_FROM_MILLIS``: a duration in ``Seconds``
written as milliseconds (Effect's ``Schema.DurationFromMillis``)."""

from __future__ import annotations

import math
from typing import TypeIs

from pyfect import _js as js
from pyfect import schema as S
from pyfect.duration import Duration, to_millis
from pyfect.duration import millis as duration_millis
from pyfect.schema import transformation as T


def _is_seconds(value: object) -> TypeIs[Duration]:
    return isinstance(value, Duration)


def _round_away(value: float) -> int:
    return int(math.copysign(js.round(abs(value)), value))


def whole_nanos(millis: float) -> float:
    """``millis`` rounded to whole nanoseconds, ties away from zero, as
    Effect's ``Duration`` keeps a fractional millisecond count."""
    if not math.isfinite(millis) or float(millis).is_integer():
        return millis
    return _round_away(millis * 1_000_000) / 1_000_000


def millis(value: float) -> Duration:
    """Effect's ``Duration.millis``; NaN is zero."""
    return duration_millis(value)


def divide_millis(millis: float, by: float) -> float:
    """``millis`` divided by ``by`` in whole nanoseconds, as Effect's
    ``Duration.divideUnsafe``: a non-finite ``by`` gives zero, a zero one
    an infinity. A duration of a fractional millisecond count is held in
    nanoseconds there, divided as an integer (truncated); Effect gives zero
    when ``by`` is not an integer too, which would turn a limit off, so
    that case rounds instead."""
    if not math.isfinite(by):
        return 0.0
    if math.isinf(millis):
        return 0.0 if by == 0 else millis * math.copysign(1.0, by)
    if float(millis).is_integer():
        quotient = js.divide(millis, by)
        return 0.0 if math.isnan(quotient) else whole_nanos(quotient)
    nanos = _round_away(millis * 1_000_000)
    if by == 0:
        return math.copysign(math.inf, nanos) * math.copysign(1.0, by)
    if not float(by).is_integer():
        return _round_away(nanos / by) / 1_000_000
    quotient = abs(nanos) // abs(int(by))
    return quotient * (1 if (nanos < 0) == (by < 0) else -1) / 1_000_000


SECONDS_FROM_MILLIS = S.Finite.pipe(
    S.decode_to(
        S.declare(_is_seconds, expected="Seconds"),
        T.transform(decode=millis, encode=to_millis),
    )
)
