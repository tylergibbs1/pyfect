"""Integer functions Effect's ``BigInt`` module has and Python's ``int`` and ``math`` lack.

The rest of ``BigInt`` is Python's own ``int`` (``docs/PARITY.md`` section 4): ``math.isqrt``
is ``sqrtUnsafe``, ``math.gcd`` is ``gcd``, and so on. ``nth_root`` is ``math.isqrt`` for any
degree::

    big_int.nth_root(30, 3)    # 3
    big_int.nth_root(-27, 3)   # -3
    big_int.nth_root(-16, 4)   # None
"""

from __future__ import annotations

import math

from pyfect._js import js_number

_MAX_SAFE = 2**53 - 1
_MANTISSA_BITS = 53


def _root_floor(n: int, degree: int) -> int:
    """The largest ``r`` with ``r ** degree <= n``, for ``n >= 0``. Newton's method on
    whole numbers, started from a float estimate rounded up, since a start below the root
    overshoots it: the first step lands at or above the floor from any positive start and
    later steps decrease to it (Brent and Zimmermann, Modern Computer Arithmetic, 1.5.2,
    Algorithm 1.14)."""
    if n < 2 or degree == 1:
        return n
    bits = n.bit_length()
    # n < 2 ** bits <= 2 ** degree
    if degree >= bits:
        return 1
    k1 = degree - 1

    def step(x: int) -> int:
        return (k1 * x + n // x**k1) // degree

    shift = max(bits - _MANTISSA_BITS, 0)
    exponent = (shift + math.log2(n >> shift)) / degree
    scale = max(math.floor(exponent) - (_MANTISSA_BITS - 1), 0)
    x = step(math.ceil(2 ** (exponent - scale)) << scale)
    y = step(x)
    while y < x:
        x, y = y, step(y)
    return x


def nth_root(n: int, degree: int) -> int | None:
    """The integer ``degree``-th root of ``n``, rounded toward zero, or ``None`` when ``n`` is
    negative and ``degree`` even (Effect's ``BigInt.nthRoot``). ``degree`` must be a positive
    safe integer, else ``ValueError``."""
    if type(degree) is not int or not 1 <= degree <= _MAX_SAFE:
        raise ValueError(f"Degree must be a positive safe integer, got {js_number(degree)}")
    if n >= 0:
        return _root_floor(n, degree)
    return None if degree % 2 == 0 else -_root_floor(-n, degree)


def nth_root_unsafe(n: int, degree: int) -> int:
    """``nth_root``; raises ``ValueError`` when ``n`` is negative and ``degree`` even."""
    root = nth_root(n, degree)
    if root is None:
        raise ValueError(f"Cannot take an integer root of degree {degree} of {n}")
    return root


__all__ = ["nth_root", "nth_root_unsafe"]
