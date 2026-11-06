"""ASCII decimal numbers in text from outside: headers, URLs, wire tags.

``str.isdigit`` also accepts digits like ``"²"`` that ``int`` rejects, and
``int`` alone accepts signs, spaces, underscores and non-ASCII digits, and
raises past 4300 digits, so every such parse goes through this module (a
guard test bans ``.isdigit()`` and hand-written digit-run regexes
elsewhere).
"""

from __future__ import annotations

MAX_DIGITS = 1000
"""The most digits ``parse_digits`` reads; longer text is no number."""


def is_digits(value: str) -> bool:
    """``value`` is one or more ASCII digits, however many."""
    return value != "" and value.isascii() and value.isdigit()


def parse_digits(value: str, *, unpadded: bool = False) -> int | None:
    """``value`` as an int when it is 1 to ``MAX_DIGITS`` ASCII digits (with
    no leading zero when ``unpadded``), else ``None``."""
    if len(value) > MAX_DIGITS or not is_digits(value):
        return None
    if unpadded and value[0] == "0" and value != "0":
        return None
    return int(value)


def parse_signed_digits(value: str) -> int | None:
    """``parse_digits`` after an optional ``+`` or ``-``."""
    sign = value[:1]
    if sign in ("+", "-"):
        magnitude = parse_digits(value[1:])
        return None if magnitude is None else (-magnitude if sign == "-" else magnitude)
    return parse_digits(value)


_SHORT_RUN = 4000
"""Digits ``int`` reads in one call (its limit is 4300)."""


def digits_value(value: str) -> int | None:
    """``value`` as an int when it is ASCII digits, however many (what
    JavaScript's ``BigInt`` reads), else ``None``."""
    return _run_value(value) if is_digits(value) else None


def _run_value(run: str) -> int:
    if len(run) <= _SHORT_RUN:
        return int(run)
    half = len(run) // 2
    return _run_value(run[:half]) * 10 ** (len(run) - half) + _run_value(run[half:])


_MAX_ARRAY_INDEX = 2**32 - 2


def array_index(key: str) -> int | None:
    """``key`` as a JavaScript array index, which an object lists first."""
    index = parse_digits(key, unpadded=True)
    return index if index is not None and index <= _MAX_ARRAY_INDEX else None


def in_object_order[A](values: dict[str, A]) -> dict[str, A]:
    """``values`` in ``Object.keys`` order: array indexes ascending, then the
    others as they came."""
    indexes = {key: index for key in values if (index := array_index(key)) is not None}
    ordered = sorted(indexes, key=indexes.__getitem__)
    return {key: values[key] for key in (*ordered, *(k for k in values if k not in indexes))}
