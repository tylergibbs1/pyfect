"""Counting the characters code copies out of a string or onto it, without a clock.

Copying a growing prefix for each piece is quadratic, but memory copies fast enough that timing
sees it only at sizes a test can't afford: ``_growth``'s ratio for a quadratic tops out at 64
over a step of 8, and on CI's runner such guards measured 38x against a bound of 36. A string
from ``Copies.text`` counts instead. Each slice of it, and each string put in front of it with
``+``, adds its length to ``characters``, and slices and sums stay counting strings."""

from __future__ import annotations

from collections.abc import Callable
from typing import SupportsIndex


class Copies:
    def __init__(self) -> None:
        self.characters = 0
        copies = self

        class Counted(str):
            __slots__ = ()

            def __getitem__(self, key: SupportsIndex | slice, /) -> str:
                part = str.__getitem__(self, key)
                if not isinstance(key, slice):
                    return part
                copies.characters += len(part)
                return Counted(part)

            def __add__(self, other: str, /) -> str:
                return Counted(str.__add__(self, other))

            def __radd__(self, other: str, /) -> str:
                copies.characters += len(other)
                return Counted(other + str(self))

        self.text: Callable[[str], str] = Counted
