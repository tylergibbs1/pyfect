"""The ISAAC generator behind ``random.with_seed``, ported from Effect's
``ISAAC_CSPRNG`` so a seed gives the same sequence as in Effect.

Effect's copyright notices for this derivative work:
Copyright (c) 2025 Effectful Technologies Inc, under MIT license.
Copyright (c) 2018, William P. "Mac" McMeans, under BSD license.
Original work copyright (c) 2012 Yves-Marie K. Rinquin, under MIT license.
https://github.com/rubycon/isaac.js

State words are unsigned 32-bit ints: JavaScript's int32 bit operations give
the same bit patterns."""

from __future__ import annotations

import math

from pyfect._js import text_encode

_MASK = 0xFFFFFFFF
_GOLDEN = 0x9E3779B9
_MAX_SAFE = 2**53 - 1


def _uint32(seed: float) -> int:
    """JavaScript's ``ToUint32`` of the seed as a JavaScript number (a double:
    an int rounds, and one too big for a float is infinite)."""
    try:
        x = float(seed)
    except OverflowError:
        return 0
    return int(x) & _MASK if math.isfinite(x) else 0


def _seed_words(seed: str | float) -> list[int]:
    if not isinstance(seed, str):
        return [_uint32(seed)]
    data = text_encode(seed)
    return [int.from_bytes(data[i : i + 4], "little") for i in range(0, len(data), 4)]


class Isaac:
    """A seeded ``RandomService``: the same seed gives the same sequence."""

    __slots__ = ("_acc", "_counter", "_generation", "_last", "_memory", "_result")

    def __init__(self, seed: str | float) -> None:
        self._memory = [0] * 256
        self._result = [0] * 256
        self._acc = 0
        self._last = 0
        self._counter = 0
        for i, word in enumerate(_seed_words(seed)):
            self._result[i & 0xFF] = (self._result[i & 0xFF] + word) & _MASK
        self._scramble()
        self._next_block()
        self._generation = 256

    def _scramble(self) -> None:
        s = [_GOLDEN] * 8

        def mix() -> None:
            a, b, c, d, e, f, g, h = s
            a ^= (b << 11) & _MASK
            d = (d + a) & _MASK
            b = (b + c) & _MASK
            b ^= c >> 2
            e = (e + b) & _MASK
            c = (c + d) & _MASK
            c ^= (d << 8) & _MASK
            f = (f + c) & _MASK
            d = (d + e) & _MASK
            d ^= e >> 16
            g = (g + d) & _MASK
            e = (e + f) & _MASK
            e ^= (f << 10) & _MASK
            h = (h + e) & _MASK
            f = (f + g) & _MASK
            f ^= g >> 4
            a = (a + f) & _MASK
            g = (g + h) & _MASK
            g ^= (h << 8) & _MASK
            b = (b + g) & _MASK
            h = (h + a) & _MASK
            h ^= a >> 9
            c = (c + h) & _MASK
            a = (a + b) & _MASK
            s[:] = [a, b, c, d, e, f, g, h]

        for _ in range(4):
            mix()
        memory = self._memory
        for source in (self._result, memory):
            for i in range(0, 256, 8):
                for j in range(8):
                    s[j] = (s[j] + source[i + j]) & _MASK
                mix()
                memory[i : i + 8] = s

    def _next_block(self) -> None:
        memory, result = self._memory, self._result
        acc = self._acc
        self._counter = (self._counter + 1) & _MASK
        last = (self._last + self._counter) & _MASK
        for i in range(256):
            match i & 3:
                case 0:
                    acc ^= (acc << 13) & _MASK
                case 1:
                    acc ^= acc >> 6
                case 2:
                    acc ^= (acc << 2) & _MASK
                case _:
                    acc ^= acc >> 16
            acc = (memory[(i + 128) & 0xFF] + acc) & _MASK
            x = memory[i]
            y = memory[i] = (memory[(x >> 2) & 0xFF] + acc + last) & _MASK
            last = result[i] = (memory[(y >> 10) & 0xFF] + x) & _MASK
        self._acc, self._last = acc, last

    def _next_word(self) -> int:
        if self._generation == 0:
            self._next_block()
            self._generation = 255
        else:
            self._generation -= 1
        return self._result[self._generation]

    def next_double_unsafe(self) -> float:
        hi = self._next_word() & 0x1FFFFF
        lo = self._next_word()
        return (hi * 4294967296 + lo) / 2**53

    def next_int_unsafe(self) -> int:
        return safe_int_of(self.next_double_unsafe())


def safe_int_of(draw: float) -> int:
    """Effect's ``nextIntUnsafe`` from a draw in ``[0, 1)``, in its float arithmetic."""
    return int(math.floor(draw * float(2 * _MAX_SAFE + 1)) + float(-_MAX_SAFE))
