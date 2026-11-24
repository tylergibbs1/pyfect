"""Reads the protobuf wire format (Effect's ``protobuf/ProtobufReader``).

A ``ProtobufReader`` reads one value at a time from bytes: a ``tag``, then
the value its wire type says. ``delimited`` gives a reader of one
length-delimited value, bounded to it, and ``skip`` passes over a value of
an unknown field. Malformed input raises ``ProtobufReaderError`` with the
offset where reading stopped.

The input is untrusted: a varint is at most ten bytes, a tag or a length
at most 32 bits, and a length never reaches past the end of its message.
``skip`` passes over groups with an explicit stack, nested at most
``max_depth`` deep (512 by default).

64-bit integers come as ``int``; the ``*_number`` methods give a ``float``,
rounded as JavaScript's ``Number`` rounds a ``bigint``.
"""

from __future__ import annotations

import struct
from dataclasses import dataclass
from typing import Final, cast

from pyfect._public import publish
from pyfect.errors import TaggedError
from pyfect.protobuf._wire import WireType

_Bytes = bytes
_Float = float
_Bool = bool

_COMPLETE: Final = "a complete value"
_VARINT_64: Final = "a varint of at most 10 bytes"
_MAX_GROUP_DEPTH: Final = 512
_UINT32: Final = 0xFFFFFFFF
_UINT64: Final = (1 << 64) - 1
_INT64_SIGN: Final = 1 << 63
_I32 = struct.Struct("<i")
_U32 = struct.Struct("<I")
_I64 = struct.Struct("<q")
_U64 = struct.Struct("<Q")
_F32 = struct.Struct("<f")
_F64 = struct.Struct("<d")


@dataclass(eq=False)
class ProtobufReaderError(TaggedError):
    """Malformed protobuf bytes: ``message`` says what was expected at
    ``offset``."""

    message: str
    offset: int


class ProtobufReader:
    """A cursor over protobuf bytes, from ``make``. A ``delimited`` child
    shares the bytes and keeps absolute offsets, but has its own end."""

    __slots__ = ("_buf", "_limit", "_pos")

    def __init__(self, data: _Bytes | bytearray | memoryview) -> None:
        # The input itself, not a view of it: a view belongs to the thread that made it.
        self._buf = data
        self._pos = 0
        self._limit = len(self._buf)

    @property
    def offset(self) -> int:
        """The offset of the next byte to read, in the original input."""
        return self._pos

    def is_done(self) -> _Bool:
        return self._pos >= self._limit

    def _fail(self, expected: str) -> ProtobufReaderError:
        return ProtobufReaderError(f"Expected {expected} at offset {self._pos}", self._pos)

    def _need(self, n: int) -> None:
        if self._pos + n > self._limit:
            raise self._fail(_COMPLETE)

    def tag(self) -> int:
        """A field's tag: its number times eight plus its wire type."""
        tag = self._length32()
        if tag >> 3 == 0 or (tag & 7) > WireType.I32:
            raise self._fail("a tag with a nonzero field number and a wire type up to 5")
        return tag

    def _length32(self) -> int:
        # Longer varints are rejected rather than truncated, so that bytes cannot be framed
        # two ways.
        buf, limit = self._buf, self._limit
        result = 0
        for i in range(5):
            if self._pos >= limit:
                raise self._fail(_COMPLETE)
            b = buf[self._pos]
            self._pos += 1
            if i == 4 and b > 0x0F:
                break
            result |= (b & 0x7F) << (7 * i)
            if b < 0x80:
                return result
        raise self._fail("a varint of at most 32 bits")

    def _varint(self) -> int:
        """A varint of up to ten bytes, as an unsigned 64-bit integer."""
        buf, limit = self._buf, self._limit
        result = 0
        for shift in range(0, 70, 7):
            if self._pos >= limit:
                raise self._fail(_COMPLETE)
            b = buf[self._pos]
            self._pos += 1
            result |= (b & 0x7F) << shift
            if b < 0x80:
                return result & _UINT64
        raise self._fail(_VARINT_64)

    def uint32(self) -> int:
        """A varint's low 32 bits."""
        return self._varint() & _UINT32

    def int32(self) -> int:
        n = self.uint32()
        return n - (1 << 32) if n & 0x80000000 else n

    def sint32(self) -> int:
        n = self.uint32()
        return (n >> 1) ^ -(n & 1)

    def uint64(self) -> int:
        return self._varint()

    def int64(self) -> int:
        n = self._varint()
        return n - (1 << 64) if n & _INT64_SIGN else n

    def sint64(self) -> int:
        n = self._varint()
        return (n >> 1) ^ -(n & 1)

    def uint64_number(self) -> _Float:
        return float(self.uint64())

    def int64_number(self) -> _Float:
        return float(self.int64())

    def sint64_number(self) -> _Float:
        return float(self.sint64())

    def bool(self) -> _Bool:
        return self._varint() != 0

    def _fixed(self, size: int, layout: struct.Struct) -> int:
        self._need(size)
        (value,) = layout.unpack_from(self._buf, self._pos)
        self._pos += size
        return value

    def fixed32(self) -> int:
        return self._fixed(4, _U32)

    def sfixed32(self) -> int:
        return self._fixed(4, _I32)

    def fixed64(self) -> int:
        return self._fixed(8, _U64)

    def sfixed64(self) -> int:
        return self._fixed(8, _I64)

    def fixed64_number(self) -> _Float:
        return float(self.fixed64())

    def sfixed64_number(self) -> _Float:
        return float(self.sfixed64())

    def float(self) -> _Float:
        self._need(4)
        (value,) = _F32.unpack_from(self._buf, self._pos)
        self._pos += 4
        return value

    def double(self) -> _Float:
        self._need(8)
        (value,) = _F64.unpack_from(self._buf, self._pos)
        self._pos += 8
        return value

    def _end(self) -> int:
        """Reads a length prefix; the offset where its data ends."""
        length = self._length32()
        self._need(length)
        return self._pos + length

    def bytes(self) -> _Bytes:
        """A length-delimited value, copied."""
        end = self._end()
        out = _Bytes(self._buf[self._pos : end])
        self._pos = end
        return out

    def bytes_view(self) -> memoryview:
        """A length-delimited value, borrowed: a view of the input."""
        end = self._end()
        with memoryview(self._buf) as view:
            out = view[self._pos : end]
        self._pos = end
        return out

    def string(self, *, validate_utf8: _Bool = True) -> str:
        """A length-delimited UTF-8 string; with ``validate_utf8=False``,
        invalid bytes become U+FFFD. A byte order mark is kept."""
        end = self._end()
        data = self._buf[self._pos : end]
        try:
            out = str(data, "utf-8", "strict" if validate_utf8 else "replace")
        except UnicodeDecodeError:
            raise self._fail("valid UTF-8") from None
        self._pos = end
        return out

    def delimited(self) -> ProtobufReader:
        """A reader of the next length-delimited value; this reader moves past it."""
        end = self._end()
        child = ProtobufReader.__new__(ProtobufReader)
        child._buf = self._buf
        child._pos = self._pos
        child._limit = end
        self._pos = end
        return child

    def skip(self, tag: int, max_depth: int = _MAX_GROUP_DEPTH) -> None:  # noqa: PLR0912
        """Passes over the value of ``tag``, and a whole group for a start
        group tag, its groups nested at most ``max_depth`` deep."""
        if (
            isinstance(max_depth, _Bool)
            or not isinstance(cast("object", max_depth), int)
            or max_depth < 0
        ):
            raise ValueError("ProtobufReader.skip max_depth must be a non-negative integer")
        groups: list[int] = []
        while True:
            match tag & 7:
                case WireType.Varint:
                    self._varint()
                case WireType.I64:
                    self._need(8)
                    self._pos += 8
                case WireType.Len:
                    self._pos = self._end()
                case WireType.StartGroup:
                    if len(groups) >= max_depth:
                        raise self._fail(f"groups nested at most {max_depth} deep")
                    groups.append(tag >> 3)
                case WireType.EndGroup:
                    if not groups:
                        raise self._fail(
                            f"a start group tag before the end group tag of field {tag >> 3}"
                        )
                    number = groups.pop()
                    if tag >> 3 != number:
                        raise self._fail(f"an end group tag for field {number}")
                case WireType.I32:
                    self._need(4)
                    self._pos += 4
                case _:
                    raise self._fail("a wire type up to 5")
            if not groups:
                return
            tag = self.tag()


def field_number(tag: int) -> int:
    return tag >> 3


def wire_type(tag: int) -> WireType:
    return WireType(tag & 7)


def make(data: _Bytes | bytearray | memoryview) -> ProtobufReader:
    """A reader of ``data``, which it borrows: ``bytes_view`` shows changes to it."""
    return ProtobufReader(data)


__all__ = [
    "ProtobufReader",
    "ProtobufReaderError",
    "WireType",
    "field_number",
    "make",
    "wire_type",
]

publish(globals())
