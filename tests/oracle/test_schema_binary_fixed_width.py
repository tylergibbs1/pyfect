"""Effect's ``encoding/SchemaBinary.test.ts``, its ``fixed-width integers`` block.

Adapted: Python has one ``int`` type for Effect's ``number`` and ``bigint``, so
the out-of-range cases drop ``1n`` for ``uint32`` (a valid ``1`` here) and
use ``1.0`` where Effect gives ``uint64`` / ``int64`` the number ``1``.
``Schema.Date`` in the fingerprint set is ``S.DateTimeUtc`` (pyfect writes
both with the same layout).
"""
# pyright: reportUnknownMemberType=false

from __future__ import annotations

import math
from datetime import UTC, datetime
from typing import Any

import pytest

from pyfect import schema as S
from pyfect.encoding import schema_binary as B

from ._schema_binary import (
    Opt,
    encode,
    fingerprint_frame,
    fingerprint_of,
    roundtrip,
    roundtrip_fp,
    same_number,
    schema_error,
    struct,
)


def _packet() -> Any:
    return struct(version=B.uint32, offset=B.int32, sequence=B.uint64, timestamp=B.int64)


_PACKETS: list[dict[str, int]] = [
    {"version": 0, "offset": -(2**31), "sequence": 0, "timestamp": -(2**63)},
    {
        "version": 2**32 - 1,
        "offset": 2**31 - 1,
        "sequence": 2**64 - 1,
        "timestamp": 2**63 - 1,
    },
    {"version": 1, "offset": -1, "sequence": 1, "timestamp": -1},
]
_ONES = [1, 0, 0, 0, 0, 0, 0, 0]
_ALL_SET = [255] * 8


def _decode(schema: Any, data: bytes) -> Any:
    return S.decode_unknown_sync(B.to_codec(schema))(data)


def test_writes_little_endian_four_and_eight_byte_payloads() -> None:
    """writes little-endian four and eight byte payloads"""
    assert list(encode(B.uint32, 1)) == [5, 0x20, 1, 0, 0, 0]
    assert list(encode(B.int32, -1)) == [5, 0x20, 255, 255, 255, 255]
    assert list(encode(B.uint64, 1)) == [9, 0x20, *_ONES]
    assert list(encode(B.int64, -1)) == [9, 0x20, *_ALL_SET]
    # signedness is the schema's reading of the same bits
    assert list(encode(B.uint64, 2**64 - 1)) == [9, 0x20, *_ALL_SET]
    for value in [0, 1, 2**32 - 1]:
        same_number(roundtrip(B.uint32, value), value)
    for value in [-(2**31), -1, 0, 2**31 - 1]:
        same_number(roundtrip(B.int32, value), value)
    for value in [0, 1, 2**64 - 1]:
        assert roundtrip(B.uint64, value) == value
    for value in [-(2**63), -1, 0, 2**63 - 1]:
        assert roundtrip(B.int64, value) == value
    assert "32" in schema_error(lambda: _decode(B.uint32, bytes((3, 0x20, 1, 0)))).message
    assert "64" in schema_error(lambda: _decode(B.int64, bytes((5, 0x20, 1, 0, 0, 0)))).message


def test_tags_struct_fields_fixed32_and_keeps_eight_byte_integers_length_prefixed() -> None:
    """tags struct fields fixed32 and keeps eight byte integers length-prefixed"""
    packet = _packet()
    # length, envelope, tag 1 * 8 + fixed32, payload
    fixed32 = struct(n=B.uint32.pipe(B.field_id(1)))
    assert list(encode(fixed32, {"n": 1})) == [6, 0x20, 14, 1, 0, 0, 0]
    # fixed64 belongs to f64, so eight byte integers ride the sized kind
    sized64 = struct(n=B.int64.pipe(B.field_id(1)))
    assert list(encode(sized64, {"n": 1})) == [11, 0x20, 8, 8, *_ONES]
    for value in _PACKETS:
        assert roundtrip(packet, value) == value
    # extra checks and annotations keep the opt-in
    narrowed = B.uint32.annotate(description="small").check(S.is_less_than(10))
    assert list(encode(narrowed, 1)) == [5, 0x20, 1, 0, 0, 0]


def test_rejects_out_of_range_and_non_integer_values_instead_of_wrapping() -> None:
    """rejects out-of-range and non-integer values instead of wrapping, with or without the schema pass"""  # noqa: E501
    packet = _packet()
    cases: list[tuple[Any, list[object]]] = [
        (B.uint32, [-1, 2**32, 1.5, math.nan, "1"]),
        (B.int32, [-(2**31) - 1, 2**31, 0.5]),
        (B.uint64, [-1, 2**64, 1.0]),
        (B.int64, [-(2**63) - 1, 2**63, 1.0]),
    ]
    for schema, values in cases:
        codec = B.to_codec(schema)
        for value in values:
            schema_error(lambda: S.encode_unknown_sync(codec)(value))  # noqa: B023
            schema_error(lambda: S.encode_unknown_sync(codec, disable_checks=True)(value))  # noqa: B023
    codec = B.to_codec(B.uint32)
    message = schema_error(lambda: S.encode_unknown_sync(codec, disable_checks=True)(2**32)).message
    assert "32-bit" in message or "integer" in message
    # the binary layer validates these on its own, so the schema pass is redundant
    B.encoder(packet, dictionary=True)


def test_never_reads_another_number_form_as_a_fixed_width_integer_or_the_reverse() -> None:
    """never reads another number form as a fixed-width integer, or the reverse"""
    number = struct(n=S.Number)
    # varint, decimal and f64 forms of a plain number field
    for n in [1, 1.5, math.pi]:
        data = encode(number, {"n": n})
        for reader in [struct(n=B.int32), struct(n=B.int64)]:
            error = schema_error(lambda: _decode(reader, data))  # noqa: B023
            assert "Missing key" in error.message
            assert "n" in error.message
    fixed32 = encode(struct(n=B.uint32), {"n": 1})
    fixed64 = encode(struct(n=B.int64), {"n": 1})
    for reader in [number, struct(n=S.Int), struct(n=S.BigInt)]:
        schema_error(lambda: _decode(reader, fixed32))  # noqa: B023
        schema_error(lambda: _decode(reader, fixed64))  # noqa: B023
    # an optional reader skips the unknown shape like any other evolution
    optional = struct(n=Opt(S.Number))
    assert _decode(optional, fixed32) == {}
    assert _decode(optional, fixed64) == {}


def test_packs_uniform_arrays_and_row_runs_without_per_element_framing() -> None:
    """packs uniform arrays and row runs without per-element framing"""
    packet = _packet()
    # length, envelope, count, packed payloads
    uint32s = [10, 0x20, 2, 1, 0, 0, 0, 2, 0, 0, 0]
    assert list(encode(S.Array(B.uint32), [1, 2])) == uint32s
    assert list(encode(S.Array(B.uint64), [1])) == [10, 0x20, 1, *_ONES]
    int32s = [-(2**31), -1, 0, 2**31 - 1]
    assert list(roundtrip(S.Array(B.int32), int32s)) == int32s
    int64s = [-(2**63), -1, 0, 2**63 - 1]
    assert list(roundtrip(S.Array(B.int64), int64s)) == int64s
    assert list(roundtrip(S.Array(B.uint32), [])) == []

    assert list(roundtrip(S.Array(packet), _PACKETS)) == _PACKETS
    assert list(roundtrip_fp(S.Array(packet), _PACKETS)) == _PACKETS
    # the row shape is declared once, so later rows all cost the same
    one = len(encode(S.Array(packet), _PACKETS[:1]))
    two = len(encode(S.Array(packet), _PACKETS[:2]))
    three = len(encode(S.Array(packet), _PACKETS))
    assert three - two == two - one


def test_fills_positional_fingerprint_slots_and_tells_the_four_widths_apart() -> None:
    """fills positional fingerprint slots and tells the four widths apart"""
    packet = _packet()
    pair = struct(a=B.uint32.pipe(B.field_id(1)), b=B.int64.pipe(B.field_id(2)))
    assert list(fingerprint_frame(pair, {"a": 1, "b": 1})[1]) == [1, 0, 0, 0, *_ONES]
    for value in _PACKETS:
        assert roundtrip_fp(packet, value) == value
    fingerprints = {
        fingerprint_of(B.uint32, 1),
        fingerprint_of(B.int32, 1),
        fingerprint_of(S.Int, 1),
        fingerprint_of(S.Number, 1),
        fingerprint_of(B.uint64, 1),
        fingerprint_of(B.int64, 1),
        fingerprint_of(S.BigInt, 1),
        fingerprint_of(S.DateTimeUtc, datetime.fromtimestamp(0.001, UTC)),
    }
    assert len(fingerprints) == 8


# --- to_codec_strict (Effect's internal ``toCodecStrict``, used by EventLog) ----------


def test_to_codec_strict_rejects_what_the_default_codec_skips() -> None:
    writer = struct(a=S.Number, extra=S.String)
    reader = struct(a=S.Number)
    data = encode(writer, {"a": 1, "extra": "x"})
    assert _decode(reader, data) == {"a": 1}
    message = schema_error(lambda: S.decode_unknown_sync(B.to_codec_strict(reader))(data)).message
    assert "a known field id" in message
    # the same field with another wire kind
    fixed = encode(struct(a=B.uint32), {"a": 1})
    optional = struct(a=Opt(S.Number))
    assert _decode(optional, fixed) == {}
    message = schema_error(
        lambda: S.decode_unknown_sync(B.to_codec_strict(optional))(fixed)
    ).message
    assert "matching field wire kind" in message
    # a union member the reader does not know
    wide = S.Union(S.String, S.Number)
    narrow = S.Union(S.String, S.Boolean)
    member = encode(wide, 1)
    message = schema_error(lambda: S.decode_unknown_sync(B.to_codec_strict(narrow))(member)).message
    assert "known union member" in message
    # what it knows reads as the default codec reads it
    assert S.decode_unknown_sync(B.to_codec_strict(writer))(data) == {"a": 1, "extra": "x"}
    assert B.to_codec_strict(writer) is B.to_codec_strict(writer)


@pytest.mark.parametrize("schema", [B.int32, B.uint32, B.int64, B.uint64])
def test_fixed_width_integers_are_validated_by_the_binary_layer_alone(schema: Any) -> None:
    # A schema with only the fixed-width check is exact, so it may use a dictionary.
    B.encoder(struct(n=schema), dictionary=True)
    with pytest.raises(ValueError, match="dictionary"):
        B.encoder(
            struct(
                n=schema.check(
                    S.is_greater_than(0)
                    if schema in (B.int32, B.uint32)
                    else S.is_greater_than_big_int(0)
                )
            ),
            dictionary=True,
        )
