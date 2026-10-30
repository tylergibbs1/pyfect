"""Effect's ``Hash.string``: the djb2 hash of a string's UTF-16 code units,
with JavaScript's 32-bit integer arithmetic and ``Hash.optimize``. Hash
rings and shard ids depend on the exact values, so they match Effect's."""

from __future__ import annotations


def _int32(n: int) -> int:
    n &= 0xFFFFFFFF
    return n - 0x1_0000_0000 if n & 0x8000_0000 else n


def optimize(n: int) -> int:
    """``(n & 0xbfffffff) | ((n >>> 1) & 0x40000000)`` as a signed int32."""
    u = n & 0xFFFFFFFF
    return _int32((u & 0xBFFFFFFF) | ((u >> 1) & 0x40000000))


def string_hash(text: str) -> int:
    """Effect's ``Hash.string(text)``."""
    units = text.encode("utf-16-le", "surrogatepass")
    h = 5381
    for i in range(len(units) - 2, -1, -2):
        h = _int32(h * 33) ^ (units[i] | units[i + 1] << 8)
    return optimize(h)
