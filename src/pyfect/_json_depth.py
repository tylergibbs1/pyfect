"""How deep JSON text nests, counted before it is parsed, at C speed.

Text holding a backslash first goes through ``codecs.escape_decode``, which
pairs backslashes from the left as JSON does. Translated beforehand into
letters it reads as one-byte escapes (``"`` to ``a``, brackets to ``bfrt``,
the rest to ``n``), an escaped quote comes out as a control byte and an
unescaped one stays ``a``. One translate then keeps only the brackets and
quotes, and dropping each pair of adjacent quotes (which leaves every other
character inside or outside a string as it was) leaves only the strings
holding a bracket to split out. ``bytes.translate`` turns the brackets into
bits (1 opens, 0 closes), ``int(..., 2)`` packs eight to a byte, and two more
translates give each byte's net step and highest point, whose running sum
``itertools.accumulate`` takes, one item per eight brackets."""

from __future__ import annotations

import re
from codecs import escape_decode
from itertools import accumulate
from operator import add

_MARKS = b'[]{}"'
_LETTERS = b"bfrta"
"""What ``_MARKS`` become before ``escape_decode``: escapes it reads as one byte."""
_AS_ESCAPES = bytes(
    _LETTERS[_MARKS.index(byte)] if byte in _MARKS else byte if byte == ord("\\") else ord("n")
    for byte in range(256)
)
_FROM_LETTERS = bytes.maketrans(_LETTERS, _MARKS)
_NOT_LETTERS = bytes(byte for byte in range(256) if byte not in _LETTERS)
_NOT_MARKS = bytes(byte for byte in range(256) if byte not in _MARKS)
_STRINGS = re.compile(rb'"[^"]*+(?:"|\Z)')
"""A string of brackets, or an unterminated one to the end."""
_BITS = bytes.maketrans(b"[{]}", b"1100")
_FIND_COST = 128
"""About how many characters ``str.count`` reads in the time a ``str.find`` call takes."""


def _byte_steps(byte: int) -> tuple[int, int]:
    """The net step of the eight brackets in ``byte``, first in the high bit,
    and the highest the running sum gets in them."""
    level = peak = 0
    for bit in range(7, -1, -1):
        level += 1 if byte >> bit & 1 else -1
        peak = max(peak, level)
    return level, peak


def _signed(value: int) -> int:
    return value & 0xFF


_NETS = bytes(_signed(_byte_steps(byte)[0]) for byte in range(256))
_PEAKS = bytes(_signed(_byte_steps(byte)[1]) for byte in range(256))


def _marks(body: bytes) -> bytes:
    """The brackets and the unescaped quotes of the JSON text ``body``."""
    if b"\\" not in body:
        return body.translate(None, _NOT_MARKS)
    letters = body.translate(_AS_ESCAPES)
    if letters.endswith(b"\\"):
        letters += b"n"  # something for a last lone backslash to escape
    unescaped: bytes = escape_decode(letters)[0]
    return unescaped.translate(_FROM_LETTERS, _NOT_LETTERS)


def _structural_brackets(body: bytes) -> bytes:
    """The brackets of the JSON text ``body`` outside its strings; an
    unterminated string hides the rest."""
    marks = _marks(body)
    if b'"' not in marks:
        return marks
    marks = marks.replace(b'""', b"")
    return _STRINGS.sub(b"", marks) if b'"' in marks else marks


def nesting_depth(body: bytes) -> int:
    """How deep the arrays and objects of the JSON text ``body`` nest, strings
    skipped. Text that is not JSON gets some number; the parse refuses it."""
    bits = _structural_brackets(body).translate(_BITS)
    if not bits:
        return 0
    # Closing brackets to fill the last byte: they never raise the running sum.
    bits += b"0" * (-len(bits) % 8)
    packed = int(bits, 2).to_bytes(len(bits) // 8, "big")
    with (
        memoryview(packed.translate(_NETS)) as nets,
        nets.cast("b") as signed_nets,
        memoryview(packed.translate(_PEAKS)) as peaks,
        peaks.cast("b") as signed_peaks,
    ):
        # Each peak counts from where its byte starts, so none is below zero.
        return max(map(add, accumulate(signed_nets, initial=0), signed_peaks))


def _opens_at_most(text: str, limit: int) -> bool:
    """Whether ``text`` holds at most ``limit`` opening brackets."""
    # Finding the first ``limit + 1`` costs less than counting them all in long text.
    if len(text) <= _FIND_COST * limit:
        return text.count("[") + text.count("{") <= limit
    found = 0
    for bracket in "[{":
        at = text.find(bracket)
        while at != -1:
            found += 1
            if found > limit:
                return False
            at = text.find(bracket, at + 1)
    return True


def within_depth(text: str, limit: int) -> bool:
    """Whether the JSON text ``text`` nests at most ``limit`` deep."""
    # No deeper than it has opening brackets, which settles most texts.
    return (
        _opens_at_most(text, limit) or nesting_depth(text.encode("utf-8", "surrogatepass")) <= limit
    )
