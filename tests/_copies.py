"""Counting the characters code copies out of a string or onto it, without a clock.

Copying a growing prefix for each piece is quadratic, but memory copies fast enough that timing
sees it only at sizes a test can't afford: ``_growth``'s ratio for a quadratic tops out at 64
over a step of 8, and on CI's runner such guards measured 38x against a bound of 36. A string
from ``Copies.text`` counts instead. Each slice of it, and each string put in front of it with
``+``, adds its length to ``characters``, and slices and sums stay counting strings;
``data`` makes bytes that do the same."""

from __future__ import annotations

from collections.abc import Buffer, Callable
from typing import Any, SupportsIndex


class Copies:
    def __init__(self) -> None:
        self.characters = 0
        """Characters copied, of ``text`` strings, and bytes, of ``data`` ones."""
        copies = self

        class Text(str):
            __slots__ = ()

            def __getitem__(self, key: SupportsIndex | slice, /) -> str:
                if not isinstance(key, slice):
                    return str.__getitem__(self, key)
                part = str.__getitem__(self, key)
                copies.characters += len(part)
                return Text(part)

            def __add__(self, other: str, /) -> str:
                return Text(str.__add__(self, other))

            def __radd__(self, other: str, /) -> str:
                copies.characters += len(other)
                return Text(other + str(self))

        class Data(bytes):
            __slots__ = ()

            def __getitem__(self, key: SupportsIndex | slice, /) -> Any:
                if not isinstance(key, slice):
                    return bytes.__getitem__(self, key)
                part = bytes.__getitem__(self, key)
                copies.characters += len(part)
                return Data(part)

            def __add__(self, other: Buffer, /) -> bytes:
                return Data(bytes.__add__(self, other))

            def __radd__(self, other: bytes, /) -> bytes:
                copies.characters += len(other)
                return Data(other + bytes(self))

        self.text: Callable[[str], str] = Text
        self.data: Callable[[bytes], bytes] = Data
