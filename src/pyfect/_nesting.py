"""Recursive parsers of untrusted text against Python's recursion limit.

A recursive-descent parser fed a few thousand ``[`` runs out of stack. In
JavaScript that is a ``RangeError`` Effect's parsers catch with every other
error; in Python a ``RecursionError`` is no ``ValueError`` and escaped, a
defect. ``tests/test_deep_nesting.py`` feeds every parser deep input.
"""

from __future__ import annotations

from collections.abc import Callable


def parse_nested[A](parse: Callable[[], A]) -> A:
    """``parse()``, a ``RecursionError`` it raises becoming the ``ValueError``
    a parser raises for text it cannot read."""
    try:
        return parse()
    except RecursionError as cause:
        raise ValueError("the input is nested too deeply") from cause
