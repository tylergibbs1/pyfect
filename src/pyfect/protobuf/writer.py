"""Writes the protobuf wire format (Effect's ``protobuf/ProtobufWriter``).

A ``ProtobufWriter`` appends values and returns itself, so writes chain:
``w.tag(1, WireType.Len).string("a")``. A nested message is written between
``fork`` and ``join``, which fills in its length. ``finish`` returns the
bytes and starts the writer over.

Numbers follow JavaScript's conversions, as Effect's do: a 32-bit method
wraps its argument to 32 bits (a ``float`` is truncated, NaN and infinities
are 0), and a 64-bit method takes an ``int``, a ``float`` (truncated) or a
decimal ``str``, wrapped to 64 bits.
"""

from __future__ import annotations

import math
import struct
from typing import Final, Self, cast

from pyfect._js import text_encode
from pyfect._public import publish
from pyfect.protobuf._wire import WireType

_Bytes = bytes
_Float = float
_Bool = bool

_MAX_FIELD_NUMBER: Final = 536870911
_MAX_WIRE_TYPE: Final = 5
_UINT32: Final = 1 << 32
_UINT64: Final = 1 << 64
_F32 = struct.Struct("<f")
_F64 = struct.Struct("<d")


def _to_uint32(n: int | _Float) -> int:
    """JavaScript's ``ToUint32``."""
    if isinstance(n, _Float):
        if not math.isfinite(n):
            return 0
        n = int(n)
    return n % _UINT32


def _to_int32(n: int | _Float) -> int:
    """JavaScript's ``ToInt32``."""
    n = _to_uint32(n)
    return n - _UINT32 if n >= 1 << 31 else n


def _to_uint64(n: int | _Float | str) -> int:
    """A 64-bit integer as its unsigned 64-bit pattern: a ``float`` truncated
    (NaN and infinities are 0), a ``str`` read as a decimal integer."""
    if isinstance(n, str):
        n = int(n)
    elif isinstance(n, _Float):
        if not math.isfinite(n):
            return 0
        n = int(n)
    return n % _UINT64


def _varint(n: int) -> _Bytes:
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return _Bytes(out)


class ProtobufWriter:
    """Builds one message at a time, from ``make``."""

    __slots__ = ("_buf", "_forks")

    def __init__(self) -> None:
        self._buf = bytearray()
        # The offsets of the length placeholders of the values not joined yet.
        self._forks: list[int] = []

    def finish(self) -> _Bytes:
        """The bytes written, which the caller owns; the writer starts over."""
        if self._forks:
            raise RuntimeError("ProtobufWriter.finish with a fork that is not joined")
        out = _Bytes(self._buf)
        self._buf = bytearray()
        return out

    def fork(self) -> Self:
        """Starts a length-delimited value; ``join`` ends it."""
        self._forks.append(len(self._buf))
        self._buf.append(0)
        return self

    def join(self) -> Self:
        """Ends the value of the last ``fork``, writing its length before it."""
        if not self._forks:
            raise RuntimeError("ProtobufWriter.join without a fork")
        start = self._forks.pop()
        length = len(self._buf) - start - 1
        if length < 0x80:
            self._buf[start] = length
        else:
            self._buf[start : start + 1] = _varint(length)
        return self

    def tag(self, field_number: int, wire_type: WireType | int) -> Self:
        """A field's tag. Raises ``ValueError`` for a field number outside
        1 through 536870911 or a wire type outside 0 through 5."""
        if (
            isinstance(field_number, _Bool)
            or not isinstance(cast("object", field_number), int)
            or not 1 <= field_number <= _MAX_FIELD_NUMBER
        ):
            raise ValueError(
                "ProtobufWriter.tag field_number must be an integer from 1 through 536870911"
            )
        if (
            isinstance(wire_type, _Bool)
            or not isinstance(cast("object", wire_type), int)
            or not 0 <= wire_type <= _MAX_WIRE_TYPE
        ):
            raise ValueError("ProtobufWriter.tag wire_type must be an integer from 0 through 5")
        return self.uint32(field_number * 8 + wire_type)

    def uint32(self, n: int | _Float) -> Self:
        self._buf += _varint(_to_uint32(n))
        return self

    def int32(self, n: int | _Float) -> Self:
        """A negative value takes ten bytes, as its 64-bit two's complement."""
        self._buf += _varint(_to_int32(n) % _UINT64)
        return self

    def sint32(self, n: int | _Float) -> Self:
        n = _to_int32(n)
        return self.uint32((n << 1) ^ (n >> 31))

    def uint64(self, n: int | _Float | str) -> Self:
        return self.int64(n)

    def int64(self, n: int | _Float | str) -> Self:
        self._buf += _varint(_to_uint64(n))
        return self

    def sint64(self, n: int | _Float | str) -> Self:
        n = _to_uint64(n)
        signed = n - _UINT64 if n >= 1 << 63 else n
        self._buf += _varint(((signed << 1) ^ (signed >> 63)) % _UINT64)
        return self

    def bool(self, value: _Bool) -> Self:
        self._buf.append(1 if value else 0)
        return self

    def fixed32(self, n: int | _Float) -> Self:
        self._buf += _to_uint32(n).to_bytes(4, "little")
        return self

    def sfixed32(self, n: int | _Float) -> Self:
        return self.fixed32(n)

    def fixed64(self, n: int | _Float | str) -> Self:
        self._buf += _to_uint64(n).to_bytes(8, "little")
        return self

    def sfixed64(self, n: int | _Float | str) -> Self:
        return self.fixed64(n)

    def float(self, n: _Float) -> Self:
        """``n`` as a 32-bit float; one too large for it is an infinity, as
        in JavaScript."""
        try:
            self._buf += _F32.pack(n)
        except OverflowError:
            self._buf += _F32.pack(math.copysign(math.inf, n))
        return self

    def double(self, n: _Float) -> Self:
        self._buf += _F64.pack(n)
        return self

    def bytes(self, data: _Bytes | bytearray | memoryview) -> Self:
        """``data`` with its length before it."""
        self.uint32(len(data))
        return self.raw(data)

    def raw(self, data: _Bytes | bytearray | memoryview) -> Self:
        """``data`` as it is, with no length."""
        self._buf += data
        return self

    def string(self, text: str) -> Self:
        """``text`` as UTF-8 with its length before it; a lone surrogate is
        written as U+FFFD, as ``TextEncoder`` writes it."""
        return self.bytes(text_encode(text))


def make() -> ProtobufWriter:
    return ProtobufWriter()


__all__ = ["ProtobufWriter", "WireType", "make"]

publish(globals())
