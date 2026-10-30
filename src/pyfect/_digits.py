"""ASCII decimal numbers in text from outside: headers, URLs, wire tags.

``str.isdigit`` also accepts digits like ``"²"`` that ``int`` rejects, and
``int`` alone accepts signs, spaces, underscores and non-ASCII digits, so
every such parse goes through ``parse_digits`` (a guard test bans
``.isdigit()`` elsewhere).
"""

from __future__ import annotations


def parse_digits(value: str) -> int | None:
    """``value`` as an int when it is one or more ASCII digits, else ``None``."""
    if not value or not value.isascii() or not value.isdigit():
        return None
    return int(value)
