"""What the ported ``SchemaBinary`` tests share."""

from __future__ import annotations

import math
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, NotRequired, TypedDict

import pytest

from pyfect import schema as S
from pyfect.encoding import schema_binary as B


@dataclass(frozen=True)
class Opt:
    """An optional key of ``struct``."""

    schema: Any


def struct(**fields: Any) -> S.StructSchema[Any, Any, Any]:
    return struct_of(fields)


def struct_of(fields: dict[str, Any]) -> S.StructSchema[Any, Any, Any]:
    """Effect's ``Schema.Struct({...})``, from values instead of a TypedDict."""
    annotations = {
        k: NotRequired[object] if isinstance(v, Opt) else object for k, v in fields.items()
    }
    typed_dict: Any = TypedDict("Row", annotations)  # pyright: ignore[reportGeneralTypeIssues, reportArgumentType]
    given = {k: v.schema if isinstance(v, Opt) else v for k, v in fields.items()}
    return S.Struct(typed_dict, **given)


def encode(schema: Any, value: object, **options: Any) -> bytes:
    return S.encode_unknown_sync(B.to_codec(schema, **options))(value)


def decode(schema: Any, data: bytes, **options: Any) -> Any:
    return S.decode_unknown_sync(B.to_codec(schema, **options))(data)


def roundtrip(schema: Any, value: object) -> Any:
    return decode(schema, encode(schema, value))


def encode_fp(schema: Any, value: object) -> bytes:
    return encode(schema, value, fingerprint=True)


def roundtrip_fp(schema: Any, value: object) -> Any:
    return decode(schema, encode_fp(schema, value), fingerprint=True)


def uvarint(value: int) -> list[int]:
    out: list[int] = []
    while value > 0x7F:
        out.append((value & 0x7F) | 0x80)
        value >>= 7
    out.append(value)
    return out


def nested_array_frame(depth: int) -> bytes:
    lengths = [1]
    for i in range(depth):
        child = lengths[i]
        lengths.append(1 + len(uvarint(child)) + child)
    body = lengths[depth]
    out = bytearray(uvarint(body + 1))
    out.append(0x20)
    for i in range(depth, 0, -1):
        out.append(1)
        out += bytes(uvarint(lengths[i - 1]))
    out.append(0)
    return bytes(out)


def int64_frame(value: int) -> bytes:
    return bytes((9, 0x20)) + value.to_bytes(8, "little", signed=True)


def same_number(actual: object, expected: float) -> None:
    """``Object.is`` on JavaScript's one number type: ``1`` is ``1.0``,
    ``-0`` is not ``0``, ``NaN`` is ``NaN``."""
    assert isinstance(actual, int | float), actual
    if math.isnan(expected):
        assert math.isnan(actual)
        return
    assert actual == expected
    assert math.copysign(1.0, actual) == math.copysign(1.0, expected)


def fingerprint_frame(schema: Any, value: object) -> tuple[bytes, bytes]:
    """A fingerprint frame's layout hash and the payload after it."""
    data = encode_fp(schema, value)
    offset = 0
    while data[offset] & 0x80:
        offset += 1
    offset += 1
    assert data[offset] == 0x21
    return data[offset + 1 : offset + 9], data[offset + 9 :]


def fingerprint_of(schema: Any, value: object) -> bytes:
    return fingerprint_frame(schema, value)[0]


def schema_error(f: Callable[[], object]) -> S.SchemaError:
    with pytest.raises(S.SchemaError) as caught:
        f()
    return caught.value


def message_of(f: Callable[[], object]) -> str:
    return schema_error(f).message


Varying = struct(id=S.String, a=Opt(S.String), b=Opt(S.Number))
varying: list[dict[str, Any]] = [
    {"id": "0", "a": "x"},
    {"id": "1"},
    {"id": "2", "a": "x", "b": 1},
    {"id": "3", "a": "x"},
    {"id": "4", "b": 2},
]
