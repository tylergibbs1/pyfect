"""``DurationFromString``, ``DurationFromNanos``, ``DurationFromMillis`` and
``DurationFromIsoString``
(Effect's), decoding into the ``Duration`` schema, a ``pyfect.duration.Duration``,
through ``T.duration_from_string`` / ``_nanos`` / ``_millis`` / ``_iso_string``.
"""

from __future__ import annotations

from pyfect import duration as _duration
from pyfect.schema import transformation as T
from pyfect.schema._primitives import BigInt, Number, String
from pyfect.schema._transform import DecodeToSchema, decode_to
from pyfect.schema._values import Duration

DurationFromString: DecodeToSchema[_duration.Duration, str] = String.annotate(
    expected="a string that will be decoded as a Duration"
).pipe(decode_to(Duration, T.duration_from_string))
"""A ``Duration`` read from Effect's ``Duration`` text (``"5 seconds"``)."""
DurationFromNanos: DecodeToSchema[_duration.Duration, int] = BigInt.pipe(
    decode_to(Duration, T.duration_from_nanos)
)
"""A ``Duration`` read from a count of nanoseconds."""
DurationFromMillis: DecodeToSchema[_duration.Duration, float] = Number.pipe(
    decode_to(Duration, T.duration_from_millis)
)
"""A ``Duration`` read from a count of milliseconds."""
DurationFromIsoString: DecodeToSchema[_duration.Duration, str] = String.annotate(
    expected="an ISO 8601 duration string that will be decoded as a Duration"
).pipe(decode_to(Duration, T.duration_from_iso_string))
"""A ``Duration`` read from an ISO 8601 duration (``"PT1H30M"``); years and months are
rejected."""
