"""The ``Duration`` transformations (Effect's ``durationFromString``,
``durationFromNanos``, ``durationFromMillis``, ``durationFromIsoString``) between a
``Duration`` and its text, nanoseconds, milliseconds or ISO 8601 text.

Text is what ``duration.from_input`` reads (``"5 seconds"``, ``"Infinity"``), written back
as ``str(duration)`` (``"5000 millis"``, ``"1 nanos"``). An infinite duration has no count
of nanoseconds or ISO 8601 text, so it fails to encode with those.
"""

from __future__ import annotations

from pyfect.duration import Duration, from_input, from_iso, millis, nanos
from pyfect.exit import Exit, Success
from pyfect.exit import fail as fail_exit
from pyfect.schema._options import ParseOptions
from pyfect.schema.issue import InvalidValue, Issue, reported
from pyfect.schema.transformation._transformation import (
    Transformation,
    transform,
    transform_effect,
)


def _invalid[A](expected: str, input: object, options: ParseOptions) -> Exit[A, Issue]:
    return fail_exit(InvalidValue({"expected": expected}, reported(input, options)))


def _decode_text(text: str, options: ParseOptions) -> Exit[Duration, Issue]:
    parsed = from_input(text)
    return _invalid("a valid Duration string", text, options) if parsed is None else Success(parsed)


def _encode_text(duration: Duration, _: ParseOptions) -> Exit[str, Issue]:
    return Success(str(duration))


def _decode_nanos(count: int, _: ParseOptions) -> Exit[Duration, Issue]:
    return Success(nanos(count))


def _encode_nanos(duration: Duration, options: ParseOptions) -> Exit[int, Issue]:
    count = duration.to_nanos()
    if count is None:
        return _invalid("a Duration representable as a bigint", duration, options)
    return Success(count)


def _decode_iso(text: str, options: ParseOptions) -> Exit[Duration, Issue]:
    parsed = from_iso(text)
    if parsed is None:
        return _invalid("an ISO 8601 duration without years or months", text, options)
    return Success(parsed)


def _encode_iso(duration: Duration, options: ParseOptions) -> Exit[str, Issue]:
    text = duration.format_iso()
    return _invalid("a finite Duration", duration, options) if text is None else Success(text)


def _to_millis(duration: Duration) -> float:
    count = duration.to_millis()
    return int(count) if count.is_integer() else count


duration_from_string: Transformation[Duration, str] = transform_effect(
    decode=_decode_text, encode=_encode_text
)
"""A ``Duration`` from Effect's ``Duration`` text (``"5 seconds"``)."""
duration_from_nanos: Transformation[Duration, int] = transform_effect(
    decode=_decode_nanos, encode=_encode_nanos
)
"""A ``Duration`` from a count of nanoseconds."""
duration_from_millis: Transformation[Duration, float] = transform(decode=millis, encode=_to_millis)
"""A ``Duration`` from a count of milliseconds (a fraction rounds to whole nanoseconds)."""
duration_from_iso_string: Transformation[Duration, str] = transform_effect(
    decode=_decode_iso, encode=_encode_iso
)
"""A ``Duration`` from an ISO 8601 duration (``"PT1H30M"``, ``"P1W2D"``); years and
months, which have no fixed length, are rejected. Encodes with days, hours, minutes and
seconds."""
