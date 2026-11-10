"""Glob patterns matched against ``/``-separated paths (Effect's ``Glob``)::

    from pyfect import glob

    ts = glob.make("src/**/*.ts")
    glob.match(ts, "src/a/b.ts")      # True
    ts.match("src/.hidden/b.ts")      # False: wildcards skip dot names
    glob.make("*", dot=True).match(".env")   # True

Syntax: ``*`` and ``?`` within a segment, ``**`` across segments (``dir/**``
includes ``dir``), bracket classes (``[a-z]``, ``[!a]``, ``[[:digit:]]``),
braces (``{a,b}``, nested; more than 10,000 expansions leave the braces
literal) and ``\\`` escapes. A trailing ``/`` matches only directories.
Wildcards skip names that start with ``.`` unless the pattern segment
starts with ``.`` or ``dot`` is set. Matching is case-sensitive and never
backtracks exponentially. ``FileSystem.glob`` walks a directory tree with
the same patterns.
"""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Self

from pyfect.glob import _compile, _match

__all__ = ["Glob", "escape", "make", "match"]


class Glob:
    """A compiled glob pattern; ``make`` builds one."""

    __slots__ = ("_compiled", "dot", "pattern")

    pattern: str
    dot: bool
    """Whether wildcards and ``**`` match names that start with ``.``."""

    def __init__(self, pattern: str, *, dot: bool = False) -> None:
        self.pattern = pattern
        self.dot = dot
        self._compiled = _compile.compile([pattern], dot)

    def match(self, path: str) -> bool:
        """Whether ``path`` (``/``-separated) matches."""
        return _match.match(self._compiled, path)

    def pipe[B](self, f: Callable[[Self], B], /) -> B:
        return f(self)

    def to_json(self) -> dict[str, object]:
        return {"_id": "Glob", "pattern": self.pattern, "dot": self.dot}

    def __repr__(self) -> str:
        return f"Glob(pattern={self.pattern!r}, dot={self.dot!r})"


def make(pattern: str, *, dot: bool = False) -> Glob:
    """Compile ``pattern``; with ``dot``, wildcards and ``**`` also match
    names that start with ``.``."""
    return Glob(pattern, dot=dot)


def match(self: Glob, path: str) -> bool:
    """Whether ``path`` matches the glob (also ``glob.match(path)``)."""
    return self.match(path)


_SPECIAL = re.compile(r"[\\*?\[\]{}]")


def escape(text: str) -> str:
    """``text`` with every glob special character escaped, so it matches
    only itself."""
    return _SPECIAL.sub(lambda m: "\\" + m.group(0), text)
