"""``DurationFromString``, ``DurationFromNanos`` and ``DurationFromMillis``
(Effect's), decoding into pyfect's ``Duration`` schema, a ``timedelta``,
through ``T.duration_from_string`` / ``_nanos`` / ``_millis`` (their
limits are in ``schema/transformation/_durations.py``).
"""

from __future__ import annotations

from datetime import timedelta

from pyfect.schema import transformation as T
from pyfect.schema._primitives import BigInt, Number, String
from pyfect.schema._transform import DecodeToSchema, decode_to
from pyfect.schema._values import Duration

DurationFromString: DecodeToSchema[timedelta, str] = String.annotate(
    expected="a string that will be decoded as a Duration"
).pipe(decode_to(Duration, T.duration_from_string))
"""A ``timedelta`` read from Effect's ``Duration`` text (``"5 seconds"``)."""
DurationFromNanos: DecodeToSchema[timedelta, int] = BigInt.pipe(
    decode_to(Duration, T.duration_from_nanos)
)
"""A ``timedelta`` read from a count of nanoseconds."""
DurationFromMillis: DecodeToSchema[timedelta, float] = Number.pipe(
    decode_to(Duration, T.duration_from_millis)
)
"""A ``timedelta`` read from a count of milliseconds."""
