"""XML's character classes, over UTF-16 code units.

Effect's positions and limits count UTF-16 code units, so the parser runs on
strings in "unit form", where a character outside the BMP is its two surrogates,
as a JavaScript string holds it. ``to_units`` converts input, and ``from_units``
converts what leaves the parser."""

from __future__ import annotations

import re

from pyfect._json_text import stringify

_ASTRAL = re.compile("[\U00010000-\U0010ffff]")


def _pair(match: re.Match[str]) -> str:
    code = ord(match[0]) - 0x10000
    return chr(0xD800 + (code >> 10)) + chr(0xDC00 + (code & 0x3FF))


def to_units(text: str) -> str:
    """``text`` in unit form."""
    return text if text.isascii() else _ASTRAL.sub(_pair, text)


def from_units(text: str) -> str:
    """``text`` with its surrogate pairs back as characters; a lone surrogate
    stays as it is."""
    if text.isascii():
        return text
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")


SPACE = " \n\t\r"
_SPACE_RUN = re.compile(r"[ \n\t\r]*")


def skip_space(s: str, i: int, end: int) -> int:
    match = _SPACE_RUN.match(s, i, end)
    return i if match is None else match.end()


_NAME_START = (
    r"A-Za-z_:\xc0-\xd6\xd8-\xf6\xf8-˿Ͱ-ͽͿ-῿‌-‍"
    r"⁰-↏Ⰰ-⿯、-퟿豈-﷏ﷰ-�\ud800-\udb7f"
)
_NAME = re.compile(
    f"[{_NAME_START}][{_NAME_START}0-9.\\-\\xb7\\u0300-\\u036f\\u203f-\\u2040\\udc00-\\udfff]*"
)
"""Name characters of XML 1.0 fifth edition. Supplementary characters are
accepted by their surrogates, which are paired once input is validated."""


def scan_name(s: str, i: int, end: int) -> int:
    """The end of the name starting at ``i``, or ``i`` when there is none."""
    if i >= end:
        return i
    match = _NAME.match(s, i, end)
    return i if match is None else match.end()


_INVALID_DECODED = re.compile(r"[\0-\x08\x0b\x0c\x0e-\x1f￾￿]")
_INVALID = re.compile(
    r"[\0-\x08\x0b\x0c\x0e-\x1f￾￿]"
    r"|[\ud800-\udbff](?![\udc00-\udfff])|(?<![\ud800-\udbff])[\udc00-\udfff]"
)
"""Characters outside the XML ``Char`` production, including unpaired surrogates."""


def search_invalid(text: str) -> int:
    """The index of the first character outside the XML ``Char`` production, or -1."""
    match = _INVALID.search(text)
    return -1 if match is None else match.start()


def search_invalid_decoded(text: str) -> int:
    """``search_invalid`` for decoded UTF-8, which has no unpaired surrogates."""
    match = _INVALID_DECODED.search(text)
    return -1 if match is None else match.start()


def code_point_at(text: str, i: int) -> str:
    """``U+XXXX`` digits of the character at ``i``."""
    return f"{ord(text[i]):04X}"


def is_char(code: int) -> bool:
    return (
        code in (0x9, 0xA, 0xD)
        or 0x20 <= code <= 0xD7FF
        or 0xE000 <= code <= 0xFFFD
        or 0x10000 <= code <= 0x10FFFF
    )


def is_name(name: str) -> bool:
    units = to_units(name)
    return (
        len(units) > 0
        and scan_name(units, 0, len(units)) == len(units)
        and _INVALID.search(units) is None
    )


def is_reserved_target(target: str) -> bool:
    return len(target) == 3 and target.lower() == "xml"


def is_whitespace(text: str) -> bool:
    return all(char in SPACE for char in text)


def quoted(value: object) -> str:
    """``JSON.stringify(value)`` for a message."""
    return stringify(value)


PUBID = re.compile(r"[ \r\na-zA-Z0-9\-'()+,./:=?;!*#@$_%]*")
