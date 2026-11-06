"""Effect's ``encoding/SchemaBinary.test.ts``: wire layout to parser.

The rest of the file is in ``test_schema_binary_declarations.py``,
``test_schema_binary_fingerprint.py`` and ``test_schema_binary_streams.py``.

Omitted (one line each):
- "includes non-enumerable fields in row presence masks": a Python mapping has
  no non-enumerable keys.

Adapted:
- Symbols, ``2n`` literals and ``Schema.ObjectKeyword`` have no Python schema;
  those lines are dropped from their tests.
- "output arena": results are independent ``bytes``, so the two tests check
  that later encodes leave earlier results alone.
- ``__proto__`` is an ordinary key here; the tests check it stays one.
"""
# pyright: reportPrivateUsage=false, reportUnknownMemberType=false

from __future__ import annotations

import enum
import math
from typing import Any

import pytest

import pyfect as fx
from pyfect import schema as S
from pyfect.encoding import schema_binary as B
from pyfect.option import Some
from pyfect.schema._undefined import Undefined

from ._schema_binary import (
    Opt,
    Varying,
    decode,
    encode,
    encode_fp,
    message_of,
    nested_array_frame,
    roundtrip,
    roundtrip_fp,
    same_number,
    schema_error,
    struct,
    struct_of,
    varying,
)

Numbers = S.Array(S.Number)


# --- wire layout ----------------------------------------------------------------------


def test_packs_fixed_size_array_elements() -> None:
    """packs fixed-size array elements"""
    numbers = [1.5, math.nan, -0.0, math.inf]
    assert len(encode(Numbers, numbers)) == 36
    decoded = roundtrip(Numbers, numbers)
    assert decoded[0] == 1.5
    assert math.isnan(decoded[1])
    same_number(decoded[2], -0.0)
    assert decoded[3] == math.inf
    assert len(encode(S.Array(S.Boolean), [True, False, True])) == 6
    assert roundtrip(S.Array(S.Boolean), [True, False, True]) == (True, False, True)


def test_length_prefixes_variable_size_array_elements_and_nested_arrays() -> None:
    """length-prefixes variable-size array elements and nested arrays"""
    assert roundtrip(S.Array(S.String), ["ab", "", "cdé"]) == ("ab", "", "cdé")
    assert roundtrip(S.Array(Numbers), [[1, 2], [], [3]]) == ((1, 2), (), (3,))


def test_round_trips_zero_width_array_elements() -> None:
    """round-trips zero-width array elements"""
    assert roundtrip(S.Array(S.Null), [None, None, None]) == (None, None, None)
    assert roundtrip(S.Array(Undefined), [None, None]) == (None, None)


def test_distinguishes_absent_optionals_from_present_zero_width_values() -> None:
    """distinguishes absent optionals from present zero-width values"""
    schema = struct(value=Opt(Undefined))
    assert roundtrip(schema, {}) == {}
    assert roundtrip(schema, {"value": None}) == {"value": None}
    assert roundtrip(S.Null, None) is None
    assert roundtrip(Undefined, None) is None


def test_round_trips_every_literal_leaf_kind_and_registered_symbols() -> None:
    """round-trips every literal leaf kind and registered symbols"""
    literals = S.Union(S.Literal("text"), S.Literal(1), S.Literal(True))
    for value in ("text", 1, True):
        result = roundtrip(literals, value)
        assert result == value
        assert type(result) is type(value)


def test_omits_the_count_for_fixed_tuples_and_includes_it_for_optional_tuples() -> None:
    """omits the count for fixed tuples and includes it for optional tuples"""
    pair = S.Tuple(S.String, S.Number)
    assert len(encode(pair, ["key", 42])) == 8
    assert roundtrip(pair, ["key", 42]) == ("key", 42)
    optional = S.Tuple(S.Number, S.optional_key(S.Number))
    assert roundtrip(optional, [1]) == (1,)
    assert roundtrip(optional, [1, 2]) == (1, 2)


def test_supports_tuple_rest_and_trailing_slots() -> None:
    """supports tuple rest and trailing slots"""
    schema = S.TupleWithRest(S.Tuple(S.String), S.Number, S.Boolean)
    value = ("head", 1.5, 2.5, 3.5, True)
    assert roundtrip(schema, value) == value
    assert roundtrip(schema, ("head", False)) == ("head", False)


def test_writes_a_length_first_frame_and_rejects_envelope_or_leftovers() -> None:
    """writes a length-first frame and rejects envelope or leftovers"""
    data = encode(S.Number, 1)
    assert list(data) == [2, 0x20, 0x02]
    assert "version 2 envelope, flags 0" in message_of(lambda: decode(S.Number, b"\x02\x21\x02"))
    assert "version 2 envelope, flags 0" in message_of(lambda: decode(S.Number, b"\x02\x30\x02"))
    assert "no leftover bytes" in message_of(lambda: decode(S.Number, data + data))


# --- string content -------------------------------------------------------------------


def test_preserves_a_leading_u_feff_in_strings() -> None:
    """preserves a leading U+FEFF in strings"""
    assert roundtrip(S.String, "﻿report") == "﻿report"


# --- output arena ---------------------------------------------------------------------


def test_keeps_an_earlier_result_stable_through_later_encodes_and_arena_rollover() -> None:
    """keeps an earlier result stable through later encodes and arena rollover"""
    first = encode(S.String, "first")
    expected = bytes(first)
    for i in range(500):
        encode(S.String, f"later-{i}-{'x' * 512}")
        assert first == expected
    assert decode(S.String, first) == "first"


def test_keeps_different_results_independent_inside_a_shared_arena() -> None:
    """keeps different results independent inside a shared arena"""
    results = [encode(S.String, text) for text in ("alpha", "bravo", "charlie")]
    assert [decode(S.String, data) for data in results] == ["alpha", "bravo", "charlie"]


def test_preserves_nested_two_phase_codec_composition() -> None:
    """preserves nested two-phase codec composition"""
    inner = struct(id=S.Number, label=S.String)
    outer = struct(id=S.String, inner=B.to_codec(inner))
    value = {"id": "outer", "inner": {"id": 1, "label": "inner"}}
    assert roundtrip(outer, value) == value


@fx.testing.effect
def test_keeps_concurrent_fiber_results_readable_after_their_producing_turn():
    """keeps concurrent fiber results readable after their producing turn"""
    value = struct(id=S.Number, value=S.String)
    codec = B.to_codec(value)
    encode_ = S.encode_unknown_effect(codec)
    values = [{"id": i, "value": f"value-{i}"} for i in range(100)]

    def one(item: object):
        return encode_(item).flat_map(lambda data: fx.yield_now().as_(data))

    @fx.gen
    def program():
        encoded: Any = yield from fx.for_each(values, one, concurrency="unbounded")
        yield from fx.yield_now()
        assert [S.decode_unknown_sync(codec)(data) for data in encoded] == values

    return program


# --- numbers --------------------------------------------------------------------------


def test_encodes_integral_values_as_sign_magnitude_varints() -> None:
    """encodes integral values as sign-magnitude varints"""
    assert list(encode(S.Number, 0)) == [2, 0x20, 0]
    assert list(encode(S.Number, -0.0)) == [2, 0x20, 1]
    assert list(encode(S.Number, 1)) == [2, 0x20, 2]
    assert list(encode(S.Number, -1)) == [2, 0x20, 3]
    for value in (0, -0.0, 1, -1, 42, -42, 127, -128):
        same_number(roundtrip(S.Number, value), value)


def test_covers_every_varint_width_up_to_the_seven_byte_cap_both_signs() -> None:
    """covers every varint width up to the seven byte cap, both signs"""
    for width in range(1, 8):
        last = 2 ** (7 * width - 1) - 1
        following = 2 ** (7 * width - 1)
        for sign in (1, -1):
            inside = sign * last
            outside = sign * following
            assert len(encode(S.Number, inside)) == 2 + width
            same_number(roundtrip(S.Number, inside), inside)
            assert len(encode(S.Number, outside)) == (10 if width == 7 else 3 + width)
            same_number(roundtrip(S.Number, outside), outside)


def test_encodes_short_decimals_as_a_mantissa_varint_plus_one_scale_byte() -> None:
    """encodes short decimals as a mantissa varint plus one scale byte"""
    assert list(encode(S.Number, 1.5)) == [3, 0x20, 30, 1]
    assert list(encode(S.Number, -0.5)) == [3, 0x20, 11, 1]
    assert list(encode(S.Number, 0.001)) == [3, 0x20, 2, 3]
    assert list(encode(S.Number, 12.5)) == [4, 0x20, 0xFA, 0x01, 1]
    for value in (0.1, 1.3, 4.7, 98.5, -123.456, 12345678.5, 0.00000001):
        same_number(roundtrip(S.Number, value), value)
    inside = 219902325555.1
    assert len(encode(S.Number, inside)) == 9
    same_number(roundtrip(S.Number, inside), inside)
    outside = 219902325555.3
    assert len(encode(S.Number, outside)) == 10
    same_number(roundtrip(S.Number, outside), outside)


def test_keeps_f64_for_values_neither_a_capped_varint_nor_a_decimal_can_hold() -> None:
    """keeps f64 for values neither a capped varint nor a decimal can hold"""
    values = (
        2.220446049250313e-16,
        math.nan,
        math.inf,
        -math.inf,
        2**53 - 1,
        -(2**53 - 1),
        1.7976931348623157e308,
        math.pi,
        1e-9,
        2**48,
        -(2**48),
    )
    for value in values:
        assert len(encode(S.Number, value)) == 10, value
        same_number(roundtrip(S.Number, value), value)


def test_discriminates_struct_number_forms_with_the_field_wire_kind() -> None:
    """discriminates struct number forms with the field wire kind"""
    schema = struct(n=S.Number)
    assert len(encode(schema, {"n": 7})) == 8
    assert len(encode(schema, {"n": 7.5})) == 10
    assert len(encode(schema, {"n": math.pi})) == 15
    for value in (7, 7.5, math.pi):
        assert roundtrip(schema, {"n": value}) == {"n": value}
    same_number(roundtrip(schema, {"n": -0.0})["n"], -0.0)


def test_uses_the_decimal_wire_kind_in_struct_fields_and_record_pairs() -> None:
    """uses the decimal wire kind in struct fields and record pairs"""
    field = struct(n=S.Number.pipe(B.field_id(1)))
    assert list(encode(field, {"n": 7.5})) == [5, 0x20, 13, 0x96, 1, 1]
    record = S.Record(S.String, S.Number)
    assert list(encode(record, {"x": 7.5})) == [8, 0x20, 0, 5, 13, 120, 0x96, 1, 1]
    assert roundtrip(record, {"x": 7.5}) == {"x": 7.5}


def test_packs_a_uniform_number_array_behind_one_mode_byte() -> None:
    """packs a uniform number array behind one mode byte"""
    integers = (0, -0.0, 1, -1, 1000, -1000)
    assert len(encode(Numbers, integers)) == 12
    for got, want in zip(roundtrip(Numbers, integers), integers, strict=True):
        same_number(got, want)
    assert len(encode(Numbers, [1, 2.5])) == 7
    assert roundtrip(Numbers, [1, 2.5]) == (1, 2.5)
    decimals = (-0.0, 0.25, 1e6, -12.75)
    for got, want in zip(roundtrip(Numbers, decimals), decimals, strict=True):
        same_number(got, want)
    assert len(encode(Numbers, [1, math.pi])) == 20
    assert roundtrip(Numbers, [1, math.pi]) == (1, math.pi)
    assert roundtrip(Numbers, []) == ()
    assert roundtrip(S.Array(Numbers), [[1, 2], [], [3.5]]) == ((1, 2), (), (3.5,))


def test_rejects_non_number_elements_in_uniform_number_arrays() -> None:
    """rejects non-number elements in uniform number arrays"""
    for value in ("x", None, True):
        text = message_of(lambda: encode(Numbers, [1, value, 3]))  # noqa: B023
        assert "Expected a number" in text
        assert "at [1]" in text


def test_length_prefixes_each_number_slot_of_a_tuple() -> None:
    """length-prefixes each number slot of a tuple"""
    pair = S.Tuple(S.Number, S.Number)
    assert len(encode(pair, [1, 2])) == 6
    assert len(encode(pair, [1, 2.5])) == 7
    assert len(encode(pair, [1, math.pi])) == 13
    assert roundtrip(pair, [1, 2.5]) == (1, 2.5)
    assert roundtrip(pair, [1, math.pi]) == (1, math.pi)
    rest = S.TupleWithRest(S.Tuple(S.String), S.Number)
    assert roundtrip(rest, ["head", 1, 2.5, 3]) == ("head", 1, 2.5, 3)


def test_carries_every_form_behind_the_union_kind_byte() -> None:
    """carries every form behind the union kind byte"""
    schema = S.Union(S.Number, S.String)
    assert len(encode(schema, 5)) == 4
    assert len(encode(schema, 5.5)) == 5
    assert len(encode(schema, math.pi)) == 11
    for value in (5, 5.5, math.pi, "x"):
        assert roundtrip(schema, value) == value
    same_number(roundtrip(schema, -0.0), -0.0)
    tagged = S.Union(
        struct(_tag=S.Literal("A"), n=S.Number),
        struct(_tag=S.Literal("B"), n=S.Int),
    )
    for value in ({"_tag": "A", "n": 1.5}, {"_tag": "B", "n": -7}):
        assert roundtrip(tagged, value) == value


def test_parses_a_stream_whose_numbers_change_width() -> None:
    """parses a stream whose numbers change width"""
    values = (0, -0.0, 1, -1, 63, 64, 1_000_000, -1_000_000, 1.5, math.nan, 2**53 - 1)
    data = b"".join(encode(S.Number, value) for value in values)
    parser = B.parser(S.Number)
    out: list[Any] = []
    for i in range(len(data)):
        out.extend(parser.feed_sync(data[i : i + 1]))
    parser.end_sync()
    assert len(out) == len(values)
    for got, want in zip(out, values, strict=True):
        same_number(got, want)


def test_emits_a_bare_varint_when_the_schema_proves_the_value_is_an_integer() -> None:
    """emits a bare varint when the schema proves the value is an integer"""
    assert list(encode(S.Int, 1)) == [2, 0x20, 2]
    assert list(encode(S.Natural, 1)) == [2, 0x20, 2]
    assert list(encode(S.Number.check(S.is_int32()), 1)) == [2, 0x20, 2]
    assert len(encode(S.Array(S.Int), [1, 2, 3])) == 6
    assert len(encode(Numbers, [1, 2, 3])) == 7
    assert len(encode(S.Tuple(S.Int, S.Int), [1, 2])) == 4
    assert len(encode(S.Tuple(S.Number, S.Number), [1, 2])) == 6
    for value in (0, 1, -1, 2**48, -(2**48), 2**53 - 1, -(2**53 - 1)):
        same_number(roundtrip(S.Int, value), value)
        same_number(roundtrip(S.Array(S.Int), [value])[0], value)
        same_number(roundtrip(struct(n=S.Int), {"n": value})["n"], value)
    assert roundtrip(S.Array(S.Int), [1, -2, 3]) == (1, -2, 3)


def test_rejects_a_non_integer_that_reaches_the_integer_layout() -> None:
    """rejects a non-integer that reaches the integer layout"""
    codec = B.to_codec(S.Int)
    text = message_of(lambda: S.encode_unknown_sync(codec, disable_checks=True)(1.5))
    assert "an integer" in text


def test_rejects_integer_varints_outside_the_safe_number_range() -> None:
    """rejects integer varints outside the safe-number range"""
    unsafe = bytes((9, 0x20, 0x82, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x20))
    assert "integer" in message_of(lambda: decode(S.Int, unsafe))


def test_rejects_malformed_number_payloads() -> None:
    """rejects malformed number payloads"""
    wide = bytes((10, 0x20, 0, 0, 0, 0, 0, 0, 0, 0, 0))
    assert "Expected f64" in message_of(lambda: decode(S.Number, wide))
    assert "complete value" in message_of(lambda: decode(S.Number, bytes((3, 0x20, 0x80, 0x80))))
    for bad in ((3, 0x20, 30, 0), (3, 0x20, 30, 9), (4, 0x20, 30, 1, 1)):
        assert "Expected decimal" in message_of(lambda: decode(S.Number, bytes(bad)))  # noqa: B023
    run = encode(Numbers, [1, 2, 3])
    unknown_mode = bytearray(run)
    unknown_mode[3] = 3
    assert "Expected f64" in message_of(lambda: decode(Numbers, bytes(unknown_mode)))
    short = bytearray(run[:-1])
    short[0] -= 1
    assert "complete value" in message_of(lambda: decode(Numbers, bytes(short)))


# --- schema evolution -----------------------------------------------------------------


def test_skips_unknown_fields_accepts_field_reorder_and_leaves_missing_optionals_absent() -> None:
    """skips unknown fields, accepts field reorder, and leaves missing optionals absent"""
    writer = struct(a=S.Number, extra=S.String, b=S.String)
    reader = struct(b=S.String, a=S.Number, optional=Opt(S.Boolean))
    data = encode(writer, {"a": 1, "extra": "drop", "b": "keep"})
    assert decode(reader, data) == {"a": 1, "b": "keep"}
    ordered_a = struct(a=S.Number, b=S.String)
    ordered_b = struct(b=S.String, a=S.Number)
    assert encode(ordered_a, {"a": 1, "b": "x"}) == encode(ordered_b, {"a": 1, "b": "x"})


def test_orders_extra_keys_by_raw_utf_8_whatever_the_insertion_order() -> None:
    """orders extra keys by raw UTF-8 whatever the insertion order"""
    record = S.Record(S.String, S.Number)
    wide = "\U00010000"
    replacement = "�"
    assert encode(record, {wide: 1, replacement: 2}) == encode(record, {replacement: 2, wide: 1})
    assert roundtrip(record, {wide: 1, replacement: 2}) == {wide: 1, replacement: 2}
    assert encode(record, {"b": 1, "a": 2}) == encode(record, {"a": 2, "b": 1})


def test_keeps_canonical_key_order_when_record_shapes_change_within_a_frame() -> None:
    """keeps canonical key order when record shapes change within a frame"""
    rows = S.Array(S.Record(S.String, S.Number))
    mixed = ({"b": 2, "a": 1}, {"a": 1, "b": 2}, {"a": 1}, {"c": 3, "a": 1}, {"a": 1, "b": 2})
    assert roundtrip(rows, mixed) == mixed
    other = ({"a": 1, "b": 2}, {"b": 2, "a": 1}, {"a": 1}, {"a": 1, "c": 3}, {"b": 2, "a": 1})
    assert encode(rows, mixed) == encode(rows, other)


def test_uses_field_id_as_the_encoded_side_field_identity() -> None:
    """uses fieldId as the encoded-side field identity"""
    before = struct(oldName=S.String.pipe(B.field_id(1)))
    after = struct(newName=S.String.pipe(B.field_id(1)))
    assert decode(after, encode(before, {"oldName": "value"})) == {"newName": "value"}
    with pytest.raises(ValueError):
        B.field_id(0)
    with pytest.raises(ValueError):
        B.field_id(1.5)  # pyright: ignore[reportArgumentType]


def test_packs_explicit_field_ids_with_scalar_wire_kinds() -> None:
    """packs explicit field ids with scalar wire kinds"""
    schema = struct(
        n=S.Number.pipe(B.field_id(1)),
        flag=S.Boolean.pipe(B.field_id(2)),
        text=S.String.pipe(B.field_id(3)),
    )
    value = {"n": 7, "flag": True, "text": "x"}
    assert list(encode(schema, value)) == [7, 0x20, 9, 14, 20, 24, 1, 120]
    assert roundtrip(schema, value) == value


def test_validates_the_full_field_id_range_and_ignores_tuple_annotations() -> None:
    """validates the full fieldId range and ignores tuple annotations"""
    for id in (-1, math.nan, math.inf, 0x1_0000_0000):
        with pytest.raises(ValueError, match=r"integer in \[1, 4294967295\]"):
            B.field_id(id)  # pyright: ignore[reportArgumentType]
    B.field_id(0xFFFFFFFF)
    maximum = struct(flag=S.Boolean.pipe(B.field_id(0xFFFFFFFF)))
    data = encode(maximum, {"flag": True})
    assert len(data) == 7
    assert list(data[2:]) == [0xFC, 0xFF, 0xFF, 0xFF, 0x7F]
    assert roundtrip(maximum, {"flag": True}) == {"flag": True}
    plain = S.Tuple(S.String)
    annotated = S.Tuple(S.String.pipe(B.field_id(123)))
    assert encode(annotated, ["value"]) == encode(plain, ["value"])


def test_keeps_canonically_distinct_unicode_field_names_distinct() -> None:
    """keeps canonically distinct Unicode field names distinct"""
    composed = "é"
    decomposed = "é"
    schema = struct_of({composed: S.String, decomposed: S.String})
    value = {composed: "composed", decomposed: "decomposed"}
    assert roundtrip(schema, value) == value


def test_skips_unknown_fields_as_opaque_bytes_and_still_rejects_repeated_unknown_ids() -> None:
    """skips unknown fields as opaque bytes and still rejects repeated unknown ids"""
    writer = struct(future=S.Bytes.pipe(B.field_id(7)))
    reader = struct()
    data = encode(writer, {"future": bytes((0x80, 0xFF, 0x10))})
    assert decode(reader, data) == {}
    field = data[2:]
    duplicate = bytes((1 + len(field) * 2, 0x20)) + field + field
    assert "unique field ids" in message_of(lambda: decode(reader, duplicate))


def test_skips_every_scalar_wire_shape_for_unknown_fields() -> None:
    """skips every scalar wire shape for unknown fields"""
    data = bytes((10, 0x20, 7 * 8 + 5, 0, 0, 8 * 8 + 6, 0, 0, 0, 0, 9 * 8 + 7))
    assert decode(struct(), data) == {}


def test_skips_an_unknown_union_member_on_an_optional_struct_field() -> None:
    """skips an unknown union member on an optional struct field"""
    a = struct(_tag=S.Literal("A"), n=S.Number)
    b = struct(_tag=S.Literal("B"), text=S.String)
    writer = struct(event=Opt(S.Union(a, b)))
    reader = struct(event=Opt(S.Union(a)))
    assert decode(reader, encode(writer, {"event": {"_tag": "B", "text": "new"}})) == {}
    value = {"event": {"_tag": "A", "n": 1}}
    assert decode(reader, encode(writer, value)) == value


def test_keeps_tuple_sentinels_in_variant_payloads() -> None:
    """keeps tuple sentinels in variant payloads"""
    schema = S.Union(S.Tuple(S.Literal("A"), S.Number), S.Tuple(S.Literal("B"), S.String))
    assert roundtrip(schema, ("A", 1)) == ("A", 1)
    assert roundtrip(schema, ("B", "value")) == ("B", "value")


_TagA = struct(_tag=S.Literal("A"))
_TagB = struct(_tag=S.Literal("B"))


def test_rejects_unknown_union_members_in_positional_slots() -> None:
    """rejects unknown union members in positional slots"""
    writer = S.Array(S.Union(_TagA, _TagB))
    reader = S.Array(S.Union(_TagA))
    assert "Missing key" in message_of(lambda: decode(reader, encode(writer, [{"_tag": "B"}])))
    writer_tuple = S.Tuple(S.optional_key(S.Union(_TagA, _TagB)))
    reader_tuple = S.Tuple(S.optional_key(S.Union(_TagA)))
    data = encode(writer_tuple, [{"_tag": "B"}])
    assert "known union member" in message_of(lambda: decode(reader_tuple, data))


def test_reports_the_array_or_tuple_index_for_an_unknown_positional_union_member() -> None:
    """reports the array or tuple index for an unknown positional union member"""
    writer = struct(xs=S.Array(S.Union(_TagA, _TagB)))
    reader = struct(xs=S.Array(S.Union(_TagA)))
    data = encode(writer, {"xs": [{"_tag": "B"}]})
    assert 'Missing key\n  at ["xs"][0]' in message_of(lambda: decode(reader, data))
    writer_tuple = struct(xs=S.Tuple(S.String, S.Union(_TagA, _TagB)))
    reader_tuple = struct(xs=S.Tuple(S.String, S.Union(_TagA)))
    data = encode(writer_tuple, {"xs": ["head", {"_tag": "B"}]})
    assert 'Missing key\n  at ["xs"][1]' in message_of(lambda: decode(reader_tuple, data))


class _Mixed(enum.Enum):
    Text = "text"
    Code = 1


def test_uses_kind_tags_for_mixed_enums() -> None:
    """uses kind tags for mixed enums"""
    schema = S.Enum(_Mixed)
    assert roundtrip(schema, _Mixed.Text) is _Mixed.Text
    assert roundtrip(schema, _Mixed.Code) is _Mixed.Code


def test_encodes_record_entries_in_the_reserved_field_zero_map() -> None:
    """encodes record entries in the reserved field zero map"""
    schema = S.Record(S.String, S.Number)
    value = {"z": 1, "a": 2}
    assert roundtrip(schema, value) == value
    assert encode(schema, value) == encode(schema, {"a": 2, "z": 1})


def test_round_trips_proto_named_fields_without_changing_the_prototype() -> None:
    """round-trips __proto__ named fields without changing the prototype"""
    schema = struct_of({"__proto__": S.String, "ok": S.String})
    value = {"__proto__": "named", "ok": "yes"}
    assert roundtrip(schema, value) == value
    assert roundtrip_fp(schema, value) == value


def test_round_trips_proto_record_entries_with_object_values() -> None:
    """round-trips __proto__ record entries with object values without changing the prototype"""
    schema = S.Record(S.String, struct(polluted=S.Boolean))
    value = {"__proto__": {"polluted": True}}
    assert roundtrip(schema, value) == value
    assert roundtrip_fp(schema, value) == value


def test_round_trips_proto_tagged_union_sentinels() -> None:
    """round-trips __proto__ tagged-union sentinels without changing the prototype"""
    a = struct_of({"__proto__": S.Literal("A"), "value": S.String})
    b = struct_of({"__proto__": S.Literal("B"), "value": S.String})
    schema = S.Union(a, b)
    value = {"__proto__": "A", "value": "a"}
    assert roundtrip(schema, value) == value
    assert roundtrip_fp(schema, value) == value


# --- struct row runs ------------------------------------------------------------------

Row = struct(
    id=S.String,
    label=S.String,
    tags=S.Array(S.String),
    attributes=S.Record(S.String, S.String),
)
rows: tuple[dict[str, Any], ...] = tuple(
    {
        "id": f"row-{i}",
        "label": "even" if i % 2 == 0 else "odd",
        "tags": ("red", "blue") if i % 3 == 0 else ("blue",),
        "attributes": {"region": "eu", "worker": f"w{i}"},
    }
    for i in range(6)
)


def test_shares_field_ids_and_repeated_strings_across_rows() -> None:
    """shares field ids and repeated strings across rows"""
    assert roundtrip(S.Array(Row), rows) == rows
    assert roundtrip(S.NonEmptyArray(Row), rows) == rows
    one = len(encode(S.Array(Row), rows[:1]))
    six = len(encode(S.Array(Row), rows))
    assert six < one * 6


def test_keeps_evolution_rules_inside_a_run() -> None:
    """keeps evolution rules inside a run"""
    reader = struct(tags=S.Array(S.String), id=S.String, later=Opt(S.Boolean))
    decoded = decode(S.Array(reader), encode(S.Array(Row), rows))
    assert decoded == tuple({"id": r["id"], "tags": r["tags"]} for r in rows)


def test_declares_a_new_shape_whenever_the_present_fields_change() -> None:
    """declares a new shape whenever the present fields change"""
    assert roundtrip(S.Array(Varying), varying) == tuple(varying)


def test_interns_index_signature_keys_on_the_row_struct_itself() -> None:
    """interns index signature keys on the row struct itself"""
    with_rest = S.StructWithRest(struct(id=S.String), S.Record(S.String, S.String))
    values = ({"id": "a", "note": "1"}, {"id": "b", "note": "2"}, {"id": "c"})
    assert roundtrip(S.Array(with_rest), values) == values


def test_runs_nested_inside_a_run() -> None:
    """runs nested inside a run"""
    inner = struct(k=S.String, v=S.String)
    outer = struct(name=S.String, items=S.Array(inner))
    outers = tuple(
        {"name": f"n{i}", "items": ({"k": "a", "v": "1"}, {"k": "b", "v": "1"})} for i in range(4)
    )
    assert roundtrip(S.Array(outer), outers) == outers


def test_keeps_rows_independent_past_the_30_field_shape_limit() -> None:
    """keeps rows independent past the 30 field shape limit"""
    fields = {f"f{i}": S.String for i in range(35)}
    value = {f"f{i}": f"v{i}" for i in range(35)}
    wide = struct_of(fields)
    assert roundtrip(S.Array(wide), [value, value, value]) == (value, value, value)


def test_rejects_an_unknown_row_shape_and_an_out_of_range_back_reference() -> None:
    """rejects an unknown row shape and an out of range back-reference"""
    simple = S.Array(struct(a=S.String))
    data = encode(simple, [{"a": "x"}, {"a": "x"}])
    assert list(data[-2:]) == [1, 1]
    shape = bytearray(data)
    shape[-2] = 9
    assert "row shape" in message_of(lambda: decode(simple, bytes(shape)))
    ref = bytearray(data)
    ref[-1] = 5
    assert "back-reference" in message_of(lambda: decode(simple, bytes(ref)))


def test_keeps_a_skipped_fields_own_run_out_of_the_readers_tables() -> None:
    """keeps a skipped field's own run out of the reader's tables"""
    writer = struct(keep=S.String, gone=S.Array(struct(p=S.String, q=S.String)))
    reader = struct(keep=S.String)
    values = [
        {"keep": f"k{i}", "gone": [{"p": "z", "q": "z"}, {"p": "z", "q": "z"}]} for i in range(4)
    ]
    decoded = decode(S.Array(reader), encode(S.Array(writer), values))
    assert decoded == tuple({"keep": v["keep"]} for v in values)


def test_interns_every_index_signature_key_including_ones_it_has_no_signature_for() -> None:
    """interns every index signature key, including ones it has no signature for"""
    writer = struct(attrs=S.Record(S.String, S.String))
    keep = S.String.check(S.make_filter(lambda key: key.startswith("keep")))
    reader = struct(attrs=S.Record(keep, S.String))
    values = (
        {"attrs": {"drop": "d", "keep1": "a"}},
        {"attrs": {"keep2": "b"}},
        {"attrs": {"keep1": "c"}},
    )
    assert decode(S.Array(reader), encode(S.Array(writer), values)) == (
        {"attrs": {"keep1": "a"}},
        {"attrs": {"keep2": "b"}},
        {"attrs": {"keep1": "c"}},
    )


def test_keeps_two_fields_sharing_one_layout_on_separate_tables() -> None:
    """keeps two fields sharing one layout on separate tables"""
    writer = struct(keep=S.String, gone=S.String)
    reader = struct(keep=S.String)
    values = (
        {"keep": "first", "gone": "other"},
        {"keep": "other", "gone": "first"},
        {"keep": "first", "gone": "first"},
    )
    decoded = decode(S.Array(reader), encode(S.Array(writer), values))
    assert decoded == tuple({"keep": v["keep"]} for v in values)


def test_holds_references_past_the_point_a_slot_switches_to_a_map() -> None:
    """holds references past the point a slot switches to a map"""
    many = tuple({"v": f"v{i % 21}"} for i in range(60))
    assert roundtrip(S.Array(struct(v=S.String)), many) == many


def test_round_trips_a_slot_that_stops_interning_values_that_never_repeat() -> None:
    """round-trips a slot that stops interning values that never repeat"""
    many = tuple({"v": f"value-{i % 80}"} for i in range(160))
    assert roundtrip(S.Array(struct(v=S.String)), many) == many
    keyed = struct(attributes=S.Record(S.String, S.String))
    records = tuple({"attributes": {f"key-{i % 80}": f"w{i}"}} for i in range(160))
    assert roundtrip(S.Array(keyed), records) == records


def test_gives_each_recursive_occurrence_its_own_run() -> None:
    """gives each recursive occurrence its own run"""
    node: Any = struct(name=S.String, children=S.Array(S.suspend(lambda: node)))
    tree = (
        {
            "name": "a",
            "children": ({"name": "x", "children": ()}, {"name": "x", "children": ()}),
        },
        {"name": "a", "children": ({"name": "y", "children": ({"name": "x", "children": ()},)},)},
    )
    assert roundtrip(S.Array(node), tree) == tree


def test_reports_the_row_index_and_field_name_for_a_missing_key() -> None:
    """reports the row index and field name for a missing key"""
    required = S.Array(struct(a=S.String, b=S.String))
    text = message_of(lambda: encode(required, [{"a": "1", "b": "2"}, {"a": "1"}]))
    assert 'Missing key\n  at [1]["b"]' in text


def test_runs_rows_in_fingerprint_mode_with_mask_declared_shapes() -> None:
    """runs rows in fingerprint mode with mask-declared shapes"""
    assert roundtrip_fp(S.Array(Row), rows) == rows
    one = len(encode_fp(S.Array(Row), rows[:1]))
    six = len(encode_fp(S.Array(Row), rows))
    assert six < one * 6
    assert six < len(encode(S.Array(Row), rows))


def test_declares_fingerprint_shapes_whenever_the_present_fields_change() -> None:
    """declares fingerprint shapes whenever the present fields change"""
    assert roundtrip_fp(S.Array(Varying), varying) == tuple(varying)


def test_rejects_a_fingerprint_shape_mask_with_unknown_bits() -> None:
    """rejects a fingerprint shape mask with unknown bits"""
    data = bytearray(encode_fp(S.Array(Row), rows[:1]))
    assert data[12] == 0
    data[13] = 0x7F
    assert "known row shape" in message_of(
        lambda: decode(S.Array(Row), bytes(data), fingerprint=True)
    )


# --- parser ---------------------------------------------------------------------------


def test_accepts_empty_input_and_spends_the_parser_after_a_successful_end() -> None:
    """accepts empty input and spends the parser after a successful end"""
    parser = B.parser(S.String)
    assert parser.feed_sync(b"") == []
    parser.end_sync()
    assert "parser is spent" in message_of(parser.end_sync)


def test_parses_concatenated_frames_split_across_chunks() -> None:
    """parses concatenated frames split across chunks"""
    schema = struct(a=S.Number)
    first = encode(schema, {"a": 1})
    data = first + encode(schema, {"a": 2})
    parser = B.parser(schema)
    assert parser.feed_sync(data[: len(first) + 3]) == [{"a": 1}]
    assert parser.feed_sync(data[len(first) + 3 :]) == [{"a": 2}]
    parser.end_sync()
    assert "parser is spent" in message_of(lambda: parser.feed_sync(b""))


def test_parses_exact_nested_structs_arrays_and_string_records() -> None:
    """parses exact nested structs, arrays, and string records"""
    schema = struct(
        id=S.Number,
        active=S.Boolean,
        tags=S.Array(S.String),
        metrics=S.Record(S.String, S.Number),
    )
    value = {"id": 1, "active": True, "tags": ("a", "b"), "metrics": {"x": 1, "y": 2}}
    parser = B.parser(schema)
    assert parser.feed_sync(encode(schema, value)) == [value]
    parser.end_sync()


def test_fails_deeply_nested_recursive_frames_with_schema_error() -> None:
    """fails deeply nested recursive frames with SchemaError"""
    nested: Any = S.Array(S.suspend(lambda: nested))
    parser = B.parser(nested)
    frame = nested_array_frame(10_000)
    assert "nesting depth at most" in message_of(lambda: parser.feed_sync(frame))
    assert "parser is spent" in message_of(lambda: parser.feed_sync(b""))


def test_keeps_proto_safe_on_the_exact_parser_path() -> None:
    """keeps __proto__ safe on the exact parser path"""
    schema = struct_of({"__proto__": S.String, "value": S.Number})
    value = {"__proto__": "own", "value": 1}
    parser = B.parser(schema)
    assert parser.feed_sync(encode(schema, value)) == [value]
    parser.end_sync()


def test_retains_schema_predicates_erased_by_the_binary_layout() -> None:
    """retains Schema predicates erased by the binary layout"""

    class _Letters(enum.Enum):
        A = "a"
        B = "b"

    for reader in (S.TemplateLiteral("a"), S.Literal("a"), S.Enum(_Letters)):
        parser = B.parser(reader)
        data = encode(S.String, "zzz")
        schema_error(lambda: parser.feed_sync(data))  # noqa: B023


def test_retains_schema_parsing_for_numeric_record_keys() -> None:
    """retains Schema parsing for numeric record keys"""
    writer = S.Record(S.String, S.Number)
    reader = S.Record(S.Number, S.Number)
    parser = B.parser(reader)
    assert parser.feed_sync(encode(writer, {"01": 1, "1e2": 2, "-0": 3})) == [{0: 3, 1: 1, 100: 2}]
    parser.end_sync()


NonNegative = S.Number.check(S.is_greater_than_or_equal_to(0))


def test_retains_transformations_checks_unions_declarations_and_recursive_validation() -> None:
    """retains transformations, checks, unions, declarations, and recursive validation"""
    transformed = B.parser(S.NumberFromString)
    assert transformed.feed_sync(encode(S.NumberFromString, 123)) == [123]
    transformed.end_sync()
    expected = "greater than or equal to 0"
    data = encode(S.Number, -1)
    assert expected in message_of(lambda: B.parser(NonNegative).feed_sync(data))
    broad = encode(S.Union(S.Number, S.String), -1)
    assert expected in message_of(lambda: B.parser(S.Union(NonNegative, S.String)).feed_sync(broad))
    some = encode(S.Option(S.Number), Some(-1))
    assert expected in message_of(lambda: B.parser(S.Option(NonNegative)).feed_sync(some))
    writer: Any = struct(value=S.Number, children=S.Array(S.suspend(lambda: writer)))
    reader: Any = struct(value=NonNegative, children=S.Array(S.suspend(lambda: reader)))
    tree: dict[str, Any] = {"value": 1, "children": [{"value": -1, "children": []}]}
    invalid = encode(writer, tree)
    assert expected in message_of(lambda: B.parser(reader).feed_sync(invalid))


def test_retains_partial_frames_across_one_byte_feeds() -> None:
    """retains partial frames across one-byte feeds"""
    data = b"".join(encode(S.Number, i) for i in range(100))
    parser = B.parser(S.Number)
    values: list[object] = []
    for i in range(len(data)):
        values.extend(parser.feed_sync(data[i : i + 1]))
    parser.end_sync()
    assert values == list(range(100))
