"""The protobuf wire format, as far as OTLP needs it (Effect's
``observability/internal/protobuf``).

Wire types: 0 varint, 1 64-bit, 2 length-delimited, 5 32-bit.
"""

from __future__ import annotations

import struct
from collections.abc import Callable, Sequence

from pyfect._js import text_encode, trim_start

_VARINT = 0
_FIXED64 = 1
_LENGTH_DELIMITED = 2
_FIXED32 = 5

_UINT64 = 1 << 64
_UINT32 = 1 << 32


def _tag(field_number: int, wire_type: int) -> bytes:
    return encode_varint((field_number << 3) | wire_type)


def encode_varint(value: int) -> bytes:
    """A varint; a negative value is written as its 64-bit two's complement
    (ten bytes)."""
    n = value % _UINT64 if value < 0 else value
    out = bytearray()
    while n > 0x7F:
        out.append((n & 0x7F) | 0x80)
        n >>= 7
    out.append(n)
    return bytes(out)


def encode_fixed64(value: int) -> bytes:
    """``value`` as eight little-endian bytes, wrapped to 64 bits as
    ``DataView.setBigUint64`` wraps it."""
    return struct.pack("<Q", value % _UINT64)


def encode_fixed32(value: int) -> bytes:
    return struct.pack("<I", value % _UINT32)


def encode_double(value: float) -> bytes:
    return struct.pack("<d", value)


_HEX_DIGITS = frozenset("0123456789abcdefABCDEF")


def _parse_hex_pair(pair: str) -> int:
    """``parseInt(pair, 16)`` stored in a ``Uint8Array``: the leading hex
    digits after leading space and an optional sign, wrapped to a byte;
    ``NaN`` is 0."""
    pair = trim_start(pair)
    sign = -1 if pair[:1] == "-" else 1
    digits = pair[1:] if pair[:1] in "+-" else pair
    run = ""
    for char in digits:
        if char not in _HEX_DIGITS:
            break
        run += char
    return sign * int(run, 16) % 256 if run else 0


def encode_hex_bytes(hex_text: str) -> bytes:
    """Each pair of characters as a byte, as Effect's ``encodeHexBytes``
    reads it with ``parseInt(pair, 16)``; a trailing odd character is
    dropped."""
    return bytes(_parse_hex_pair(hex_text[i : i + 2]) for i in range(0, len(hex_text) - 1, 2))


def varint_field(field_number: int, value: int) -> bytes:
    return _tag(field_number, _VARINT) + encode_varint(value)


def bool_field(field_number: int, value: bool) -> bytes:
    return varint_field(field_number, 1 if value else 0)


def fixed64_field(field_number: int, value: int) -> bytes:
    return _tag(field_number, _FIXED64) + encode_fixed64(value)


def fixed32_field(field_number: int, value: int) -> bytes:
    return _tag(field_number, _FIXED32) + encode_fixed32(value)


def double_field(field_number: int, value: float) -> bytes:
    return _tag(field_number, _FIXED64) + encode_double(value)


def length_delimited_field(field_number: int, value: bytes) -> bytes:
    return _tag(field_number, _LENGTH_DELIMITED) + encode_varint(len(value)) + value


def string_field(field_number: int, value: str) -> bytes:
    return length_delimited_field(field_number, text_encode(value))


def bytes_field_from_hex(field_number: int, hex_text: str) -> bytes:
    return length_delimited_field(field_number, encode_hex_bytes(hex_text))


def message_field(field_number: int, message: bytes) -> bytes:
    return length_delimited_field(field_number, message)


def repeated_field[T](
    field_number: int, values: Sequence[T], encode: Callable[[T], bytes]
) -> bytes:
    return b"".join(message_field(field_number, encode(v)) for v in values)


def optional_string_field(field_number: int, value: str | None) -> bytes:
    """The field when ``value`` is a non-empty string, else nothing."""
    return string_field(field_number, value) if value else b""
