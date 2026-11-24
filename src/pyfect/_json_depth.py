"""How deep JSON text nests, counted before it is parsed, at C speed. The
strings go first: escaped backslashes and quotes are dropped, then all but
brackets and quotes, then each pair of adjacent quotes (which leaves every
other character inside or outside a string as it was), so only the strings
holding a bracket are left to split out. ``bytes.translate`` turns the
brackets into bits (1 opens, 0 closes), ``int(..., 2)`` packs eight to a byte,
and two more translates give each byte's net step and highest point, whose
running sum ``itertools.accumulate`` takes, one item per eight brackets."""

from __future__ import annotations

import re
from itertools import accumulate
from operator import add

_NOT_BRACKETS_OR_QUOTES = bytes(b for b in range(256) if b not in b'[]{}"')
_STRINGS = re.compile(rb'"[^"]*+(?:"|\Z)')
"""A string of brackets, or an unterminated one to the end."""
_BITS = bytes.maketrans(b"[{]}", b"1100")


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


def _structural_brackets(body: bytes) -> bytes:
    """The brackets of the JSON text ``body`` outside its strings; an
    unterminated string hides the rest."""
    if b"\\" in body:
        body = body.replace(b"\\\\", b"").replace(b'\\"', b"")
    marks = body.translate(None, _NOT_BRACKETS_OR_QUOTES).replace(b'""', b"")
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


def within_depth(text: str, limit: int) -> bool:
    """Whether the JSON text ``text`` nests at most ``limit`` deep."""
    # No deeper than it has opening brackets: most texts are counted in two scans.
    if text.count("[") + text.count("{") <= limit:
        return True
    return nesting_depth(text.encode("utf-8", "surrogatepass")) <= limit
