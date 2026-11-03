"""Effect's ``Hash.hash`` on the keys ``pyfect._equal.equal_key`` makes, so a
``HashMap`` / ``HashSet`` places its entries, and iterates them, as Effect's
does.

Strings, numbers, booleans, ``None`` (``null``), bytes (a ``Uint8Array``),
lists and tuples (arrays), dicts (objects when every key is a string, else
``Map``) and sets get Effect's hash. Other values have no JavaScript
counterpart and use their own ``__hash__`` (Effect's ``Hash.symbol``).
Results are unsigned 32-bit (``hash >>> 0``), the bits Effect's trie reads.
"""

from __future__ import annotations

import math
import struct
from collections.abc import Hashable
from functools import lru_cache
from typing import cast

from pyfect._string_hash import string_hash

_U32 = 0xFFFFFFFF


def _imul(a: int, b: int) -> int:
    return (a * b) & _U32


def _mix(h: int) -> int:
    h &= _U32
    h ^= h >> 16
    h = _imul(h, 0x85EBCA6B)
    h ^= h >> 13
    h = _imul(h, 0xC2B2AE35)
    return h ^ (h >> 16)


def _optimize(h: int) -> int:
    h &= _U32
    return (h & 0xBFFFFFFF) | ((h >> 1) & 0x40000000)


def _combine(a: int, b: int) -> int:
    return _mix(_imul(a, 0x9E3779B1) + _imul(b, 0x85EBCA6B))


@lru_cache(maxsize=1 << 14)
def _string(text: str) -> int:
    return string_hash(text) & _U32


def _number(n: float) -> int:
    if math.isnan(n):
        n = math.nan
    elif -(1 << 31) <= n < (1 << 31) and n == int(n):
        return _optimize(int(n))
    high, low = struct.unpack(">II", struct.pack(">d", n))
    return _optimize(_combine(high, low))


def _int(n: int) -> int:
    if -(1 << 31) <= n < (1 << 31):
        return _optimize(n)
    if _is_float(n):
        return _number(float(n))  # a JavaScript number, equal to its float
    return _string(str(n))  # a BigInt


def _is_float(n: int) -> bool:
    # Exactly a finite float: at most 53 significant bits, below 2**1024.
    # (``float(n) == n`` raises OverflowError past the float range.)
    odd = n >> ((n & -n).bit_length() - 1)
    return n.bit_length() <= 1024 and odd.bit_length() <= 53


def _array(items: tuple[Hashable, ...]) -> int:
    h = 6151
    for item in items:
        h = _combine(h, effect_hash(item))
    return _optimize(h)


_MAP_SEED = _string("Map")
_SET_SEED = _string("Set")
_NULL = _optimize(_mix(_string("null")))
_TRUE = _optimize(_mix(_string("true")))
_FALSE = _optimize(_mix(_string("false")))


def _mapping(pairs: frozenset[tuple[Hashable, Hashable]]) -> int:
    h = 12289 if all(type(k) is str for k, _ in pairs) else _MAP_SEED
    for key, value in pairs:
        h ^= _combine(effect_hash(key), effect_hash(value))
    return _optimize(h)


def _set(items: frozenset[Hashable]) -> int:
    h = _SET_SEED
    for item in items:
        h ^= _combine(_SET_SEED, effect_hash(item))
    return _optimize(h)


def effect_hash(ident: Hashable) -> int:
    """Effect's ``Hash.hash`` of the value ``ident`` (an ``equal_key``)
    stands for."""
    match ident:
        case str():
            return _string(ident)
        case int():
            return _int(ident)
        case float():
            return _number(ident)
        case None:
            return _NULL
        case _:
            return _other(ident)


def _other(ident: Hashable) -> int:
    kind = type(ident)
    if kind is bytes:
        return _array(tuple(cast("bytes", ident)))
    if kind is tuple:
        return _tagged(cast("tuple[object, Hashable]", ident))
    return hash(ident) & _U32


def _tagged(ident: tuple[object, Hashable]) -> int:
    # ``equal_key``'s tagged forms; every tuple key is one of them.
    tag, payload = ident
    if tag is bool:
        return _TRUE if payload else _FALSE
    if tag is float:
        return _number(math.nan)
    if tag is tuple:
        return _array(cast("tuple[Hashable, ...]", payload))
    if tag is dict:
        return _mapping(cast("frozenset[tuple[Hashable, Hashable]]", payload))
    return _set(cast("frozenset[Hashable]", payload))
