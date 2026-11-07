"""JavaScript's ``RegExp`` flags, read once at the boundary into a ``Mode``.

``d`` (indices) and ``g`` (global) change nothing for a test from the start of
the string; ``y`` (sticky) anchors the match there; ``i``, ``m``, ``s`` and
``u`` change how the pattern reads. ``v`` (Unicode sets) is refused.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

_ORDER = "dgimsuvy"
"""The order ``RegExp.prototype.flags`` writes them in."""

_SURROGATE = re.compile("[\ud800-\udfff]")


class EcmaFlagsError(ValueError):
    """Flags ``new RegExp`` rejects, or that pyfect does not run."""


@dataclass(frozen=True, slots=True)
class Mode:
    """How a pattern reads, from its flags."""

    flags: str
    """Canonical: each letter once, in ``RegExp.prototype.flags``' order."""
    unicode: bool
    ignore_case: bool
    multiline: bool
    dot_all: bool
    sticky: bool


UNICODE = Mode("u", unicode=True, ignore_case=False, multiline=False, dot_all=False, sticky=False)


def parse_flags(flags: str) -> Mode:
    """``flags`` as ``new RegExp(source, flags)`` reads them; raises
    ``EcmaFlagsError`` for an unknown or repeated letter, ``v``, and ``i``
    without ``u`` (JavaScript's legacy case folding is not ``re``'s)."""
    if flags == "u":
        return UNICODE
    if any(flag not in _ORDER or flags.count(flag) > 1 for flag in flags):
        raise EcmaFlagsError(f"Invalid flags supplied to RegExp constructor '{flags}'")
    if "v" in flags:
        raise EcmaFlagsError("The v flag (Unicode sets) is not supported")
    if "i" in flags and "u" not in flags:
        raise EcmaFlagsError("The i flag is supported only with the u flag")
    return Mode(
        "".join(flag for flag in _ORDER if flag in flags),
        unicode="u" in flags,
        ignore_case="i" in flags,
        multiline="m" in flags,
        dot_all="s" in flags,
        sticky="y" in flags,
    )


def code_units(text: str) -> str:
    """``text`` as JavaScript's UTF-16 string: one character per code unit."""
    if text.isascii() or max(text) <= "\uffff":
        return text
    data = text.encode("utf-16-le", "surrogatepass")
    return "".join(chr(int.from_bytes(data[i : i + 2], "little")) for i in range(0, len(data), 2))


def joined_pairs(text: str) -> str:
    """``text`` with each surrogate pair one code point, as a Unicode-mode
    pattern reads a JavaScript string holding them."""
    if text.isascii() or _SURROGATE.search(text) is None:
        return text
    return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "surrogatepass")
