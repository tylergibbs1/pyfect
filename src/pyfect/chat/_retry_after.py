"""A platform's ``Retry-After`` as a wait, for every adapter that reads one."""

from __future__ import annotations

import math
import re

from pyfect.duration import Duration, millis

_DECIMAL = re.compile(r"[+-]?(?:[0-9]+(?:\.[0-9]*)?|\.[0-9]+)(?:[eE][+-]?[0-9]+)?")


def parse_retry_after(value: object) -> Duration | None:
    """A wait in seconds, from a ``Retry-After`` header (a string) or a JSON
    ``retry_after`` (a number), rounded up to the millisecond. ``None`` for
    anything else, a negative or an infinite one."""
    if isinstance(value, str):
        text = value.strip()
        if text and _DECIMAL.fullmatch(text) is None:
            return None
        number = float(text) if text else 0.0
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        try:
            number = float(value)
        except OverflowError:
            return None
    else:
        return None
    if not 0 <= number < math.inf:
        return None
    return millis(math.ceil(round(number * 1000, 6)))
