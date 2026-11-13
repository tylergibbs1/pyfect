"""JavaScript's text and number rules for ports that must give Effect's
exact results: arithmetic that gives infinities and NaN where Python raises
(``divide``, ``floor``, ``ceil``), and the text rules:
``String(number)`` (``2`` not ``2.0``, ``1e+21``, ``1.5e-7``), and the
character sets behind JavaScript's regex ``\\s`` and line terminators,
which differ from Python's (a regex copied from Effect must spell them with
these, not ``\\s``, ``.``, ``^`` or ``$``)."""

from __future__ import annotations

import codecs
import math
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import cast


def or_default[A, B](value: A | None, default: B) -> A | B:
    """``value`` unless it is ``None``: JavaScript's ``value ?? default``.
    Python's ``value or default`` is JavaScript's ``||`` (it replaces an
    empty string too), so a port of ``??`` uses this."""
    return default if value is None else value


def js_length(text: str) -> int:
    """``text.length``: UTF-16 code units, so a character outside the BMP
    counts twice (Python's ``len`` counts code points). A port comparing a
    string's length with a limit from Effect uses this."""
    return len(text.encode("utf-16-le", "surrogatepass")) // 2


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
    try:
        return text.encode()
    except UnicodeEncodeError:
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


_SHORT_INT_BITS = 3000
"""Ints below ``2 ** 3000`` (about 900 digits) are well under Python's
4300-digit ``str`` limit."""


def int_text(value: int) -> str:
    """``str(value)`` for an ``int`` of any size: JavaScript's ``BigInt``
    prints in full, where Python's ``str`` raises past 4300 digits. The
    digits are split in halves until each part is short."""
    if value < 0:
        return "-" + int_text(-value)
    if value.bit_length() <= _SHORT_INT_BITS:
        return str(int(value))
    half = int(value.bit_length() * 0.30102999566398) // 2  # log10(2): digits / 2
    high, low = divmod(value, 10**half)
    return int_text(high) + int_text(low).rjust(half, "0")


def to_iso_string(when: datetime) -> str:
    """JavaScript's ``Date.prototype.toISOString``: UTC to the millisecond, a four-digit year,
    ``Z`` (``0999-12-31T23:59:59.999Z``). Not ``strftime``: glibc's ``%Y`` does not pad."""
    utc = when.astimezone(UTC).replace(tzinfo=None)
    return utc.isoformat(timespec="milliseconds") + "Z"


def js_number(value: float) -> str:
    """``value`` as JavaScript prints it (``String(value)``): ``2`` not
    ``2.0``, ``1e-7``, ``0`` for ``-0.0``. An ``int`` (Effect's ``bigint``)
    prints in full, however long."""
    if isinstance(value, int):
        return int_text(value)
    if math.isnan(value):
        return "NaN"
    if math.isinf(value):
        return "Infinity" if value > 0 else "-Infinity"
    if value == 0.0:
        return "0"
    text = repr(value)  # the shortest round-tripping decimal, as JavaScript's
    if "e" not in text:
        # Python writes 1e-4 <= |value| < 1e16 without an exponent, as
        # JavaScript does, but with ``.0`` on a whole number.
        return text.removesuffix(".0")
    sign = "-" if value < 0 else ""
    exact = Decimal(text.removeprefix("-")).normalize().as_tuple()
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


_LITERALS = {True: "true", False: "false", None: "null"}


def js_string(value: object) -> str:
    """``String(value)`` for Python values: ``true`` / ``false``, ``null``
    for ``None``, numbers as ``js_number``, a string as it is, a list or
    tuple as an array (items joined by ``,``, ``None`` items empty), a dict
    as ``[object Object]``, anything else ``str(value)``."""
    match value:
        case str():
            return value
        case bool() | None:
            return _LITERALS[value]
        case int() | float():
            return js_number(value)
        case list() | tuple():
            items = cast("list[object] | tuple[object, ...]", value)
            return ",".join("" if item is None else js_string(item) for item in items)
        case dict():
            return "[object Object]"
        case _:
            return str(value)


def divide(dividend: float, divisor: float) -> float:
    """JavaScript's ``/``: dividing by zero gives a signed infinity, or NaN
    for ``0 / 0`` (Python raises ``ZeroDivisionError``)."""
    if divisor != 0:
        return dividend / divisor
    if dividend == 0 or math.isnan(dividend):
        return math.nan
    return math.copysign(math.inf, dividend) * math.copysign(1.0, divisor)


def remainder(dividend: float, divisor: float) -> float:
    """JavaScript's ``%``: the sign of ``dividend``; NaN for an infinite dividend or a zero
    divisor, and ``dividend`` itself for an infinite divisor (Python's ``%`` takes the
    divisor's sign, and ``math.fmod`` raises)."""
    if math.isinf(dividend) or divisor == 0 or math.isnan(dividend) or math.isnan(divisor):
        return math.nan
    if math.isinf(divisor):
        return dividend
    return math.fmod(dividend, divisor)


def power(base: float, exponent: float) -> float:
    """``Math.pow`` / ``**``: a result past float range is a signed
    infinity, ``0 ** -n`` is an infinity, ``(-8) ** 0.5`` and
    ``1 ** Infinity`` are NaN (Python raises, returns a complex, or 1)."""
    if math.isnan(exponent) or (abs(base) == 1 and math.isinf(exponent)):
        return math.nan
    odd = math.isfinite(exponent) and exponent % 2 == 1
    sign = -1.0 if odd and math.copysign(1.0, base) < 0 else 1.0
    try:
        return math.pow(base, exponent)
    except OverflowError:
        return sign * math.inf
    except ValueError:
        return sign * math.inf if base == 0 else math.nan


def floor(value: float) -> float:
    """``Math.floor``: an infinity or NaN stays as it is (Python raises)."""
    return float(math.floor(value)) if math.isfinite(value) else value


def round(value: float) -> float:
    """``Math.round``: halves go up, ``-0.5 <= x < 0`` gives ``-0``.
    ``floor(x + 0.5)`` is not it: the sum rounds (``0.49999999999999994``
    goes to 1, odd numbers past 2**52 to even)."""
    if not math.isfinite(value):
        return value
    whole = math.floor(value)
    rounded = whole + 1.0 if value - whole >= 0.5 else float(whole)
    return math.copysign(rounded, value) if rounded == 0 else rounded


def ceil(value: float) -> float:
    """``Math.ceil``: an infinity or NaN stays as it is (Python raises)."""
    return float(math.ceil(value)) if math.isfinite(value) else value


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


_SPACES = re.compile(f"[{SPACE}]+")


def split_space(text: str) -> list[str]:
    """``text.split(/\\s+/)`` without its empty pieces: JavaScript's
    whitespace, where ``str.split()`` uses Python's."""
    return [piece for piece in _SPACES.split(text) if piece]


def same_value(a: object, b: object) -> bool:
    """JavaScript's ``Object.is``: the same object, or numbers, strings or
    bytes of one type with one value. ``-0.0`` is not ``0.0``, NaN is NaN,
    and ``1`` is not ``1.0`` or ``True``."""
    if a is b:
        return True
    if type(a) is not type(b) or not isinstance(a, (str, int, float, bytes)):
        return False
    if isinstance(a, float) and isinstance(b, float):
        if math.isnan(a):
            return math.isnan(b)
        return a == b and math.copysign(1.0, a) == math.copysign(1.0, b)
    return a == b


def same_json_value(a: object, b: object) -> bool:
    """``Object.is`` on JSON values: ``same_value`` with ``int`` and ``float``
    as JavaScript's one number type (``1`` is ``1.0``, but not ``True``)."""
    if (
        isinstance(a, (int, float))
        and isinstance(b, (int, float))
        and not isinstance(a, bool)
        and not isinstance(b, bool)
    ):
        if isinstance(a, float) and math.isnan(a):
            return isinstance(b, float) and math.isnan(b)
        return a == b and _is_negative_zero(a) == _is_negative_zero(b)
    return same_value(a, b)


def _is_negative_zero(number: float) -> bool:
    return isinstance(number, float) and number == 0.0 and math.copysign(1.0, number) < 0


_ESCAPES = re.compile(r"(?:%[0-9A-Fa-f]{2})+")
_URI_RESERVED = frozenset(";/?:@&=+$,#")


def _decode_escapes(text: str, keep: frozenset[str]) -> str:
    if "%" in _ESCAPES.sub("", text):
        raise ValueError("URI malformed")

    def run(match: re.Match[str]) -> str:
        escaped = match.group(0)
        data = bytes.fromhex(escaped.replace("%", ""))
        out: list[str] = []
        index = 0
        while index < len(data):
            lead = data[index]
            width = 1 if lead < 0x80 else 2 if lead >> 5 == 6 else 3 if lead >> 4 == 14 else 4
            try:
                char = data[index : index + width].decode()
            except UnicodeDecodeError as error:
                raise ValueError("URI malformed") from error
            out.append(escaped[index * 3 : index * 3 + 3] if char in keep else char)
            index += width
        return "".join(out)

    return _ESCAPES.sub(run, text)


def decode_uri_component(text: str) -> str:
    """``decodeURIComponent``: a stray ``%`` or bad UTF-8 raises
    ``ValueError`` (JavaScript's ``URIError``)."""
    return _decode_escapes(text, frozenset())


def decode_uri(text: str) -> str:
    """``decodeURI``: as ``decode_uri_component``, but escapes of the
    reserved characters ``;/?:@&=+$,#`` stay escaped."""
    return _decode_escapes(text, _URI_RESERVED)
