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
