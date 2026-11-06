"""SchemaBinary's wire primitives: constants, the number encodings, the hashes,
the ``Writer`` and the failure that carries an issue out of a pass."""

from __future__ import annotations

import math
import struct
from collections.abc import Iterable

from pyfect import _js
from pyfect._js import text_encode
from pyfect.schema import ParseOptions
from pyfect.schema.issue import InvalidValue, Issue, Pointer, reported

ENVELOPE = 0x20
"""Version nibble 2, flags 0."""
ENVELOPE_FINGERPRINT = 0x21
"""Version nibble 2, flag bit 0: fingerprint mode."""

MAX_SAFE = 2**53 - 1

NUMBER_VARINT_MAX_BYTES = 7
NUMBER_VARINT_MAX_MAGNITUDE = 2**48 - 1

NUMBER_RUN_F64 = 0
NUMBER_RUN_VARINT = 1
NUMBER_RUN_DECIMAL = 2

MAX_NESTING_DEPTH = 512
"""Recursive layouts fail here, before the stack does."""
ARRAY_ALLOCATION_SLACK = 1_048_576
ZERO_WIDTH_ARRAY_MAX = 4_194_304

FIELD_WIRE_SIZED = 0
FIELD_WIRE_VARINT = 1
FIELD_WIRE_FIXED64 = 2
FIELD_WIRE_FALSE = 3
FIELD_WIRE_TRUE = 4
FIELD_WIRE_DECIMAL = 5
FIELD_WIRE_FIXED32 = 6
FIELD_WIRE_EMPTY = 7
FIELD_WIRE_FACTOR = 8

DECIMAL_SCALE_MAX = 8
DECIMAL_MANTISSA_MAX = 2**41 - 1
POW10 = (1, 10, 100, 1000, 10000, 100000, 1000000, 10000000, 100000000)

KIND_BOOL = 1
KIND_NULL = 2
KIND_UNDEFINED = 3
KIND_NUMBER = 4
KIND_STRING = 5
KIND_BYTES = 6
KIND_BIGINT = 7
KIND_INT64 = 8
KIND_STRUCT = 9
KIND_VARIANT = 10
KIND_ARRAY = 11
KIND_OPTION = 12
KIND_RESULT = 13
KIND_DURATION = 14
KIND_BIG_DECIMAL = 15
KIND_DATE_TIME_ZONED = 16
KIND_JSON = 17
KIND_EXIT = 18
KIND_CAUSE = 19
KIND_CAUSE_REASON = 20

_F64 = struct.Struct("<d")
_I64 = struct.Struct("<q")
_U32 = struct.Struct("<I")
_I32 = struct.Struct("<i")

F64 = _F64
I64 = _I64
U32 = _U32
I32 = _I32


class IssueError(Exception):
    """A binary pass failed with ``issue``."""

    def __init__(self, issue: Issue) -> None:
        super().__init__("SchemaBinary failure")
        self.issue = issue


class _NoInput:
    __slots__ = ()


NO_INPUT = _NoInput()
"""The failure has no input to report (Effect's ``undefined``)."""


def invalid_value(expected: str, input: object, options: ParseOptions) -> InvalidValue:
    shown = None if input is NO_INPUT else reported(input, options)
    return InvalidValue({"expected": expected}, shown)


def at_path(path: list[object], issue: Issue) -> IssueError:
    """``issue`` at ``path``: the pass's position, made into an issue only
    when it fails."""
    return IssueError(Pointer(tuple(path), issue) if path else issue)


def is_number(value: object) -> bool:
    return isinstance(value, int | float) and not isinstance(value, bool)


def is_negative(value: float) -> bool:
    """``value`` is below zero, or ``-0``."""
    return value < 0 or (value == 0 and math.copysign(1.0, value) < 0)


def is_integral(value: float) -> bool:
    return isinstance(value, int) or value.is_integer()


def is_varint_number(value: float) -> bool:
    return is_integral(value) and -NUMBER_VARINT_MAX_MAGNITUDE <= value <= (
        NUMBER_VARINT_MAX_MAGNITUDE
    )


def is_safe_number(value: float) -> bool:
    return not isinstance(value, bool) and is_integral(value) and abs(value) <= MAX_SAFE


def is_safe_integer(value: object) -> bool:
    return isinstance(value, int | float) and is_safe_number(value)


def as_float(value: float) -> float | None:
    """``value`` as JavaScript's number; ``None`` for an ``int`` past the
    range of a double."""
    try:
        return float(value)
    except OverflowError:
        return None


def rounded_mantissa(value: float, scale: int) -> int:
    return int(_js.round(value * POW10[scale]))


def decimal_scale(value: float) -> int:
    """The scale making ``value`` an exact short-decimal mantissa, or 0."""
    for scale in range(1, DECIMAL_SCALE_MAX + 1):
        mantissa = _js.round(value * POW10[scale])
        if not -DECIMAL_MANTISSA_MAX <= mantissa <= DECIMAL_MANTISSA_MAX:
            return 0
        if mantissa / POW10[scale] == value:
            return scale
    return 0


def sign_magnitude(code: int) -> float:
    """A sign-magnitude code: unlike zigzag it keeps ``-0``, as a float."""
    magnitude = code >> 1
    if not code & 1:
        return magnitude
    return -magnitude if magnitude else -0.0


def fnv32(data: Iterable[int]) -> int:
    value = 0x811C9DC5
    for byte in data:
        value = ((value ^ byte) * 0x01000193) & 0xFFFFFFFF
    return value


def fnv64(data: Iterable[int]) -> int:
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & 0xFFFFFFFFFFFFFFFF
    return value


def uvarint_bytes(n: int) -> bytes:
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def zigzag_code(n: int) -> int:
    return n << 1 if n >= 0 else (-n << 1) - 1


class Writer:
    """The bytes of one encoding pass. ``begin_sized`` reserves a one-byte
    length that ``end_sized`` fills in, widening it when the region is long."""

    __slots__ = ("buf",)

    def __init__(self) -> None:
        self.buf = bytearray()

    def byte(self, b: int) -> None:
        self.buf.append(b)

    def bytes(self, data: bytes) -> None:
        self.buf += data

    def uvarint(self, n: int) -> None:
        buf = self.buf
        while n > 0x7F:
            buf.append((n & 0x7F) | 0x80)
            n >>= 7
        buf.append(n)

    def zigzag(self, n: int) -> None:
        self.uvarint(zigzag_code(n))

    def number_varint(self, n: float) -> None:
        negative = is_negative(n)
        self.uvarint(int(abs(n)) * 2 + (1 if negative else 0))

    def f64(self, n: float) -> None:
        self.buf += F64.pack(n)

    def i64(self, n: int) -> None:
        self.buf += I64.pack(n)

    def u32le(self, n: int) -> None:
        self.buf += U32.pack(n)

    def i32le(self, n: int) -> None:
        self.buf += I32.pack(n)

    def string(self, text: str) -> None:
        self.buf += text_encode(text)

    def begin_sized(self) -> int:
        self.buf.append(0)
        return len(self.buf) - 1

    def end_sized(self, mark: int) -> None:
        self._fill(mark, len(self.buf) - mark - 1)

    def end_sized_run(self, mark: int) -> None:
        """A row-run region prefixes ``length * 2``; odd codes are
        back-references."""
        self._fill(mark, (len(self.buf) - mark - 1) * 2)

    def _fill(self, mark: int, code: int) -> None:
        if code < 0x80:
            self.buf[mark] = code
        else:
            self.buf[mark : mark + 1] = uvarint_bytes(code)
