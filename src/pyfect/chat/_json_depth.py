"""How deep JSON text nests, counted before it is parsed, at C speed: one
regex pass drops the strings, ``bytes.translate`` keeps the brackets as bits
(1 opens, 0 closes), ``int(..., 2)`` packs eight to a byte, and two more
translates give each byte's net step and highest point, whose running sum
``itertools.accumulate`` takes, one item per eight brackets."""

from __future__ import annotations

import re
from itertools import accumulate
from operator import add

_STRINGS = re.compile(rb'"(?:[^"\\]++|\\.)*+(?:"|\\?\Z)', re.DOTALL)
"""A JSON string, or an unterminated one to the end (a last lone backslash
too), taken whole so that no quote inside it starts another match."""
_NOT_BRACKETS = bytes(b for b in range(256) if b not in b"[]{}")
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


def nesting_depth(body: bytes) -> int:
    """How deep the arrays and objects of the JSON text ``body`` nest, strings
    skipped. Text that is not JSON gets some number; the parse refuses it."""
    bits = _STRINGS.sub(b"", body).translate(_BITS, _NOT_BRACKETS)
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


def within_depth(body: bytes, limit: int) -> bool:
    """Whether the JSON text ``body`` nests at most ``limit`` deep."""
    return nesting_depth(body) <= limit
