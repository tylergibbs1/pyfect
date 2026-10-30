"""``ByteSize``: an exact, non-negative number of bytes (Effect's ``ByteSize``).

A ``ByteSize`` is an ``int`` (Effect's branded ``bigint``), so it compares,
hashes, prints and sorts as one; ``min`` / ``max`` keep the type. Decimal
units (``kB``, ``MB``, ...) are powers of 1,000 and binary units (``KiB``,
``MiB``, ...) powers of 1,024::

    size = byte_size.mebibytes(2)               # 2097152
    byte_size.from_string("1.5 kB")             # 1500
    byte_size.format(byte_size.bytes(1536))     # "1.5 KiB"

Constructors raise ``ValueError`` for what is not a whole, non-negative
number of bytes; the ``from_*`` parsers give ``None`` instead. Arithmetic
that can leave the range (``subtract``, ``times``, ``divide``) gives
``None`` too.
"""

from __future__ import annotations

import json
import re
from collections.abc import Callable
from typing import Literal, NewType, TypeIs, overload

from pyfect._js import SPACE, js_number

ByteSize = NewType("ByteSize", int)

type DecimalUnit = Literal["B", "kB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB", "RB", "QB"]
type BinaryUnit = Literal["B", "KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB"]
type Unit = DecimalUnit | BinaryUnit
type Input = int | float | str
"""What ``from_input`` reads: an ``int`` of any size, a ``float`` that is a
safe integer, or a string ``from_string`` reads."""

_MAX_SAFE_INTEGER = 2**53 - 1

_DECIMAL_NAMES = (
    "kilo",
    "mega",
    "giga",
    "tera",
    "peta",
    "exa",
    "zetta",
    "yotta",
    "ronna",
    "quetta",
)
_BINARY_NAMES = ("kibi", "mebi", "gibi", "tebi", "pebi", "exbi", "zebi", "yobi")
_DECIMAL_SYMBOLS = ("kB", "MB", "GB", "TB", "PB", "EB", "ZB", "YB", "RB", "QB")
_BINARY_SYMBOLS = ("KiB", "MiB", "GiB", "TiB", "PiB", "EiB", "ZiB", "YiB")

# (symbol, factor), smallest first.
_DECIMAL: tuple[tuple[Unit, int], ...] = (
    ("B", 1),
    *((s, 1000**p) for p, s in enumerate(_DECIMAL_SYMBOLS, start=1)),
)
_BINARY: tuple[tuple[Unit, int], ...] = (
    ("B", 1),
    *((s, 1024**p) for p, s in enumerate(_BINARY_SYMBOLS, start=1)),
)
_FACTORS: dict[str, int] = dict(_DECIMAL + _BINARY)


def _names() -> dict[str, int]:
    names = {"B": 1, "byte": 1, "bytes": 1}
    for prefixes, symbols in ((_DECIMAL_NAMES, _DECIMAL_SYMBOLS), (_BINARY_NAMES, _BINARY_SYMBOLS)):
        for prefix, symbol in zip(prefixes, symbols, strict=True):
            factor = _FACTORS[symbol]
            names |= {symbol: factor, f"{prefix}byte": factor, f"{prefix}bytes": factor}
    return names


_UNITS_BY_NAME = _names()
_SYNTAX = re.compile(rf"[{SPACE}]*([0-9]+)(?:\.([0-9]+))?[{SPACE}]*([A-Za-z]+)[{SPACE}]*")

zero = ByteSize(0)


def _invalid(message: str) -> ValueError:
    return ValueError(f"Invalid ByteSize: {message}")


def _safe_integer(value: float) -> int | None:
    """``value`` as an ``int`` when JavaScript's ``Number.isSafeInteger``
    holds for it."""
    if value.is_integer() and abs(value) <= _MAX_SAFE_INTEGER:
        return int(value)
    return None


def _from_quantity(quantity: float, symbol: Unit) -> ByteSize:
    """``quantity`` units of ``symbol``. An ``int`` may be any size; a
    ``float`` must give a whole number of bytes below 2**53. Raises
    ``ValueError`` otherwise or when negative."""
    factor = _FACTORS[symbol]
    if isinstance(quantity, int):
        if quantity < 0:
            raise _invalid(f"expected a non-negative quantity, received {quantity}")
        return ByteSize(quantity * factor)
    value = _safe_integer(quantity * float(factor))
    if value is None or value < 0:
        raise _invalid(
            "expected an exact non-negative safe-integer byte result, "
            f"received {js_number(quantity)} {symbol}"
        )
    return ByteSize(value)


def bytes(value: int) -> ByteSize:
    """``value`` bytes. Raises ``ValueError`` when it is negative."""
    if value < 0:
        raise _invalid(f"expected a non-negative bigint, received {value}")
    return ByteSize(value)


def _unit(symbol: Unit) -> Callable[[float], ByteSize]:
    def construct(value: float) -> ByteSize:
        return _from_quantity(value, symbol)

    construct.__doc__ = (
        f"``value`` {symbol}. A ``float`` must give a whole number of bytes below "
        "2**53; raises ``ValueError`` otherwise or when ``value`` is negative."
    )
    return construct


kilobytes = _unit("kB")
megabytes = _unit("MB")
gigabytes = _unit("GB")
terabytes = _unit("TB")
petabytes = _unit("PB")
exabytes = _unit("EB")
zettabytes = _unit("ZB")
yottabytes = _unit("YB")
ronnabytes = _unit("RB")
quettabytes = _unit("QB")
kibibytes = _unit("KiB")
mebibytes = _unit("MiB")
gibibytes = _unit("GiB")
tebibytes = _unit("TiB")
pebibytes = _unit("PiB")
exbibytes = _unit("EiB")
zebibytes = _unit("ZiB")
yobibytes = _unit("YiB")


def from_string_unsafe(text: str) -> ByteSize:
    """The size ``text`` spells (``"10 MB"``, ``"1.5KiB"``, ``"3 kilobytes"``).
    Raises ``ValueError`` for other syntax, an unknown unit, or a size that
    is not a whole number of bytes."""
    match = _SYNTAX.fullmatch(text)
    if match is None:
        raise _invalid(f"unsupported syntax {_quote(text)}")
    whole, fraction, unit = match.group(1), match.group(2) or "", match.group(3)
    factor = _UNITS_BY_NAME.get(unit)
    if factor is None:
        raise _invalid(f"unsupported unit {_quote(unit)}")
    numerator = int(whole + fraction) * factor
    scale = 10 ** len(fraction)
    if numerator % scale != 0:
        raise _invalid(f"{_quote(text)} does not represent an integral number of bytes")
    return ByteSize(numerator // scale)


def from_string(text: str) -> ByteSize | None:
    """``from_string_unsafe``, with ``None`` in place of the error."""
    try:
        return from_string_unsafe(text)
    except ValueError:
        return None


def from_input_unsafe(value: Input) -> ByteSize:
    """A size from an ``int``, a safe-integer ``float`` or a string.
    Raises ``ValueError`` for anything else or a negative size."""
    if isinstance(value, str):
        return from_string_unsafe(value)
    if isinstance(value, int):
        return bytes(value)
    whole = _safe_integer(value)
    if whole is None or whole < 0:
        raise _invalid(f"expected a non-negative safe integer, received {js_number(value)}")
    return ByteSize(whole)


def from_input(value: Input) -> ByteSize | None:
    """``from_input_unsafe``, with ``None`` in place of the error."""
    try:
        return from_input_unsafe(value)
    except ValueError:
        return None


def is_byte_size(value: object) -> TypeIs[ByteSize]:
    """``value`` is a non-negative ``int`` (not a ``bool``)."""
    return isinstance(value, int) and not isinstance(value, bool) and value >= 0


def is_zero(size: ByteSize) -> bool:
    return size == 0


def to_unit(size: ByteSize, unit: Unit) -> float:
    """``size`` in ``unit``s, as a ``float`` (``to_unit(kibibytes(3), "KiB")``
    is ``3.0``)."""
    return float(size) / float(_FACTORS[unit])


def sum(size: ByteSize, that: ByteSize) -> ByteSize:
    """``size + that``, still a ``ByteSize``."""
    return ByteSize(size + that)


def subtract(size: ByteSize, that: ByteSize) -> ByteSize | None:
    """``size - that``, or ``None`` when ``that`` is larger."""
    return None if size < that else ByteSize(size - that)


def subtract_unsafe(size: ByteSize, that: ByteSize) -> ByteSize:
    """``size - that``. Raises ``ValueError`` when ``that`` is larger."""
    if size < that:
        raise ValueError(f"ByteSize subtraction underflow: {size} - {that}")
    return ByteSize(size - that)


def _scalar(value: float, minimum: int) -> int | None:
    whole = value if isinstance(value, int) else _safe_integer(value)
    return whole if whole is not None and whole >= minimum else None


def times(size: ByteSize, multiplier: float) -> ByteSize | None:
    """``size * multiplier``, or ``None`` unless ``multiplier`` is a
    non-negative whole number."""
    value = _scalar(multiplier, 0)
    return None if value is None else ByteSize(size * value)


def divide(size: ByteSize, divisor: float) -> ByteSize | None:
    """``size // divisor``, or ``None`` unless ``divisor`` is a positive
    whole number."""
    value = _scalar(divisor, 1)
    return None if value is None else ByteSize(size // value)


@overload
def format(
    size: ByteSize,
    *,
    precision: int = 2,
    trailing_zeros: bool = False,
    system: Literal["binary"] = "binary",
    unit: BinaryUnit | None = None,
) -> str: ...
@overload
def format(
    size: ByteSize,
    *,
    precision: int = 2,
    trailing_zeros: bool = False,
    system: Literal["decimal"] = ...,
    unit: DecimalUnit | None = None,
) -> str: ...
def format(
    size: ByteSize,
    *,
    precision: int = 2,
    trailing_zeros: bool = False,
    system: Literal["binary", "decimal"] = "binary",
    unit: Unit | None = None,
) -> str:
    """``size`` as text in the largest unit of ``system`` it fills
    (``"1.5 KiB"``), or in ``unit``. ``precision`` (0 to 20) is the number of
    decimals, rounded half up; ``trailing_zeros`` keeps zeros after the
    point."""
    if not 0 <= precision <= 20:
        raise ValueError(
            f"ByteSize format precision must be an integer from 0 to 20, received {precision}"
        )
    if unit is not None:
        return _format_with(size, unit, precision, trailing_zeros)
    if size == 0:
        return "0 B"
    units = _DECIMAL if system == "decimal" else _BINARY
    index = len(units) - 1
    while index > 0 and size < units[index][1]:
        index -= 1
    if index < len(units) - 1:
        scale = 10**precision
        factor = units[index][1]
        rounded = (size * scale * 2 + factor) // (factor * 2)
        if rounded >= units[1][1] * scale:
            index += 1
    return _format_with(size, units[index][0], precision, trailing_zeros)


def _format_with(size: int, symbol: Unit, precision: int, trailing_zeros: bool) -> str:
    factor = _FACTORS[symbol]
    scale = 10**precision
    rounded = (size * scale * 2 + factor) // (factor * 2)
    whole = rounded // scale
    if precision == 0:
        return f"{whole} {symbol}"
    fraction = str(rounded % scale).rjust(precision, "0")
    if not trailing_zeros:
        fraction = fraction.rstrip("0")
    return f"{whole}{'.' + fraction if fraction else ''} {symbol}"


def _quote(text: str) -> str:
    return json.dumps(text, ensure_ascii=False)


__all__ = [
    "BinaryUnit",
    "ByteSize",
    "DecimalUnit",
    "Input",
    "Unit",
    "bytes",
    "divide",
    "exabytes",
    "exbibytes",
    "format",
    "from_input",
    "from_input_unsafe",
    "from_string",
    "from_string_unsafe",
    "gibibytes",
    "gigabytes",
    "is_byte_size",
    "is_zero",
    "kibibytes",
    "kilobytes",
    "mebibytes",
    "megabytes",
    "pebibytes",
    "petabytes",
    "quettabytes",
    "ronnabytes",
    "subtract",
    "subtract_unsafe",
    "sum",
    "tebibytes",
    "terabytes",
    "times",
    "to_unit",
    "yobibytes",
    "yottabytes",
    "zebibytes",
    "zero",
    "zettabytes",
]
