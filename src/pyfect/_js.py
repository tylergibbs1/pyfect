"""JavaScript's text rules for ports that must give Effect's exact strings:
``String(number)`` (``2`` not ``2.0``, ``1e+21``, ``1.5e-7``), and the
character sets behind JavaScript's regex ``\\s`` and line terminators,
which differ from Python's (a regex copied from Effect must spell them with
these, not ``\\s``, ``.``, ``^`` or ``$``)."""

from __future__ import annotations

import codecs
import math
from decimal import Decimal


def js_sort_key(text: str) -> bytes:
    """The key sorting strings as JavaScript's ``sort()`` does: by UTF-16
    code units, not code points (``"\\U00010000"`` before ``"\\uffff"``)."""
    return text.encode("utf-16-be", "surrogatepass")


def to_well_formed(text: str) -> str:
    """``String.prototype.toWellFormed``: a surrogate pair becomes its
    character and a lone surrogate U+FFFD."""
    try:
        text.encode()
    except UnicodeEncodeError:
        return text.encode("utf-16-le", "surrogatepass").decode("utf-16-le", "replace")
    return text


def text_encode(text: str) -> bytes:
    """``TextEncoder.encode``: UTF-8 where a surrogate pair is one character
    and a lone surrogate becomes U+FFFD (Python's ``encode`` raises)."""
    return to_well_formed(text).encode()


def text_decoder(
    encoding: str = "utf-8", *, fatal: bool = False, ignore_bom: bool = False
) -> codecs.IncrementalDecoder:
    """``new TextDecoder(encoding, { fatal, ignoreBOM })`` as an incremental
    decoder: bad bytes become U+FFFD (or raise with ``fatal``), and a UTF-8
    byte-order mark is dropped unless ``ignore_bom``, again after each
    ``reset``."""
    name = codecs.lookup(encoding).name
    if name == "utf-8" and not ignore_bom:
        name = "utf-8-sig"
    return codecs.getincrementaldecoder(name)("strict" if fatal else "replace")


def js_number(value: float) -> str:
    """``value`` as JavaScript prints it. An ``int`` (Effect's ``bigint``)
    prints in full."""
    if isinstance(value, int):
        return str(value)
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0.0:
        return "0"
    sign = "-" if value < 0 else ""
    # repr is the shortest round-tripping decimal, as JavaScript's.
    exact = Decimal(repr(abs(value))).normalize().as_tuple()
    digits = "".join(map(str, exact.digits))
    k = len(digits)
    n = k + int(exact.exponent)  # value = 0.digits * 10**n
    if k <= n <= 21:
        body = digits + "0" * (n - k)
    elif 0 < n <= 21:
        body = digits[:n] + "." + digits[n:]
    elif -6 < n <= 0:
        body = "0." + "0" * -n + digits
    else:
        mantissa = digits[0] + ("." + digits[1:] if k > 1 else "")
        body = f"{mantissa}e{'+' if n - 1 >= 0 else '-'}{abs(n - 1)}"
    return sign + body


SPACE = "\t\n\v\f\r \u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
"""The characters of JavaScript's ``\\s`` (and ``String.prototype.trim``), as a
regex class body. Python's ``\\s`` also takes ``\\x1c``-``\\x1f`` and ``\\x85``
and misses the byte-order mark."""

LINE_END = "\n\r\u2028\u2029"
"""JavaScript's line terminators, as a regex class body: what ``.`` excludes
and where multiline ``^`` / ``$`` match."""

_TRIM = SPACE.replace("\u2000-\u200a", "".join(map(chr, range(0x2000, 0x200B))))


def trim(text: str) -> str:
    """``String.prototype.trim``: strips JavaScript's whitespace only."""
    return text.strip(_TRIM)


def trim_start(text: str) -> str:
    """``String.prototype.trimStart``."""
    return text.lstrip(_TRIM)


def trim_end(text: str) -> str:
    """``String.prototype.trimEnd``."""
    return text.rstrip(_TRIM)


def same_value(a: object, b: object) -> bool:
    """JavaScript's ``Object.is``: the same object, or numbers, strings or
    bytes of one type with one value. ``-0.0`` is not ``0.0``, NaN is NaN,
    and ``1`` is not ``1.0`` or ``True``."""
    if a is b:
        return True
    if type(a) is not type(b) or not isinstance(a, str | int | float | bytes):
        return False
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a):
            return math.isnan(b)
        return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)
    return a == b
