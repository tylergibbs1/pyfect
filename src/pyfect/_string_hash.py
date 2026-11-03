"""Effect's ``Hash.string``: the djb2 hash of a string's UTF-16 code units,
with JavaScript's 32-bit integer arithmetic and ``Hash.optimize``. Hash
rings and shard ids depend on the exact values, so they match Effect's."""

from __future__ import annotations

import sys
from array import array
from collections.abc import Sequence

_UTF16_NATIVE = "utf-16-le" if sys.byteorder == "little" else "utf-16-be"


def _int32(n: int) -> int:
    n &= 0xFFFFFFFF
    return n - 0x1_0000_0000 if n & 0x8000_0000 else n


def optimize(n: int) -> int:
    """``(n & 0xbfffffff) | ((n >>> 1) & 0x40000000)`` as a signed int32."""
    u = n & 0xFFFFFFFF
    return _int32((u & 0xBFFFFFFF) | ((u >> 1) & 0x40000000))


def string_hash(text: str) -> int:
    """Effect's ``Hash.string(text)``."""
    # Unsigned 32-bit arithmetic: the same bits as JavaScript's int32 ops.
    if text.isascii():
        units: Sequence[int] = text.encode("ascii")
    else:
        units = array("H", text.encode(_UTF16_NATIVE, "surrogatepass"))
    h = 5381
    for unit in reversed(units):
        h = ((h * 33) & 0xFFFFFFFF) ^ unit
    return optimize(h)
