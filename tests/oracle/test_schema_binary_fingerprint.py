"""Effect's ``encoding/SchemaBinary.test.ts``: fingerprint mode, layout
fingerprint, codec memoization, generated regressions, direct codec,
encodeManyUnknownSync, and schemas the binary layer validates on its own.

Adapted:
- The ``it.live.prop`` titles run on Hypothesis (a dev dependency here).
- Effect's ``Schema.optional`` is ``optionalKey(UndefinedOr)``; ``_optional``
  builds that, so the fingerprints pinned in Effect's tests hold.
- "rejects an inherited discriminator": a Python mapping has no prototype, so a
  subclass's class attribute stands in for an inherited key.
- ``Schema.Any`` is pyfect's ``S.Any``; ``ObjectKeyword``, ``Symbol`` and
  ``Schema.Date`` lines are dropped (no Python schema).
"""
# pyright: reportPrivateUsage=false, reportUnknownMemberType=false

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from hypothesis import given, settings
from hypothesis import strategies as st

from pyfect import big_decimal as bd
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect.cause import Cause, Die, Fail, Interrupt
from pyfect.encoding import schema_binary as B
from pyfect.option import Some
from pyfect.result import Err
from pyfect.schema._undefined import Undefined

from ._schema_binary import (
    Opt,
    decode,
    encode,
    encode_fp,
    fingerprint_frame,
    fingerprint_of,
    message_of,
    roundtrip,
    roundtrip_fp,
    schema_error,
    struct,
)


def _optional(schema: Any) -> Opt:
    return Opt(S.Union(schema, Undefined))


# --- fingerprint mode -----------------------------------------------------------------

Int = S.Number.check(S.is_int())
Person = struct(name=S.String, age=Int, active=S.Boolean, nickname=_optional(S.String))
person = {"name": "Ada", "age": 36, "active": True}


def test_writes_a_fingerprint_envelope_a_presence_bitmap_and_no_field_ids() -> None:
    """writes a fingerprint envelope, a presence bitmap, and no field ids"""
    prefix = [0x21, 184, 213, 85, 38, 67, 231, 116, 53]
    assert list(encode_fp(Person, person)) == [16, *prefix, 0, 72, 3, 65, 100, 97, 1]
    assert list(encode_fp(Person, {**person, "nickname": "A"})) == [
        19,
        *prefix,
        1,
        2,
        1,
        65,
        72,
        3,
        65,
        100,
        97,
        1,
    ]


def test_leaves_the_default_mode_untouched() -> None:
    """leaves the default mode untouched"""
    expected = encode(Person, person)
    assert expected[1] == 0x20
    assert encode(Person, person, fingerprint=False) == expected


def test_addresses_union_members_by_canonical_position() -> None:
    """addresses union members by canonical position"""
    click = struct(_tag=S.Literal("click"), x=Int)
    key = struct(_tag=S.Literal("key"), code=S.String)
    event = S.Union(click, key)
    prefix = [0x21, 237, 163, 78, 151, 96, 43, 76, 0]
    assert list(encode_fp(event, {"_tag": "click", "x": 3})) == [11, *prefix, 0, 6]
    value = {"_tag": "key", "code": "Esc"}
    frame = list(encode_fp(event, value))
    assert frame == [14, *prefix, 1, 3, 69, 115, 99]
    assert list(encode_fp(S.Union(key, click), value)) == frame
    assert roundtrip_fp(event, value) == value


def test_counts_the_extra_key_map_instead_of_reserving_field_zero() -> None:
    """counts the extra-key map instead of reserving field zero"""
    schema = S.Record(S.String, S.Number)
    assert list(encode_fp(schema, {"b": 2, "a": 1})) == [
        16,
        0x21,
        189,
        249,
        115,
        23,
        65,
        225,
        229,
        6,
        2,
        9,
        97,
        2,
        9,
        98,
        4,
    ]
    assert roundtrip_fp(schema, {"z": 1, "a": 2}) == {"z": 1, "a": 2}
    assert roundtrip_fp(schema, {}) == {}


def test_keeps_the_default_tuple_and_array_layout() -> None:
    """keeps the default tuple and array layout"""
    pair = S.Tuple(S.Boolean, S.String)
    assert list(encode_fp(pair, (True, "x"))) == [
        12,
        0x21,
        3,
        44,
        71,
        25,
        31,
        66,
        141,
        82,
        1,
        1,
        120,
    ]
    assert list(encode_fp(S.Array(Int), [1, -2, 3])) == [
        13,
        0x21,
        206,
        94,
        13,
        113,
        158,
        175,
        76,
        32,
        3,
        2,
        5,
        6,
    ]


def test_inlines_fixed_size_and_zero_width_leaves() -> None:
    """inlines fixed-size and zero-width leaves"""
    schema = struct(
        nothing=S.Null,
        flag=S.Boolean,
        missing=Undefined,
        when=S.DateTimeUtc,
        count=Int,
        label=S.String,
    )
    value = {
        "nothing": None,
        "flag": True,
        "missing": None,
        "when": datetime.fromtimestamp(1, UTC),
        "count": -7,
        "label": "hi",
    }
    assert len(encode_fp(schema, value)) == 23
    assert roundtrip_fp(schema, value) == value


def test_spans_a_presence_bitmap_across_several_bytes() -> None:
    """spans a presence bitmap across several bytes"""
    schema = struct(**{name: _optional(S.Number) for name in "abcdefghij"})
    assert roundtrip_fp(schema, {}) == {}
    assert roundtrip_fp(schema, {"a": 1, "j": 2}) == {"a": 1, "j": 2}
    full = {name: i + 1 for i, name in enumerate("abcdefghij")}
    assert roundtrip_fp(schema, full) == full


def _tree() -> Any:
    self: Any = struct(value=S.Number, children=S.Array(S.suspend(lambda: self)))
    return self


def test_round_trips_native_declarations_recursion_and_mixed_unions() -> None:
    """round-trips native declarations, recursion, and mixed unions"""
    natives = struct(
        option=S.Option(S.String),
        result=S.Result(S.Number, S.String),
        big=S.BigInt,
        bytes=S.Bytes,
        duration=S.Duration,
        decimal=S.BigDecimal,
    )
    value = {
        "option": Some("x"),
        "result": Err("boom"),
        "big": 2**70,
        "bytes": bytes((1, 2, 3)),
        "duration": timedelta(seconds=1.5),
        "decimal": bd.make(123, 2),
    }
    decoded = roundtrip_fp(natives, value)
    assert decoded["option"] == value["option"]
    assert decoded["result"] == value["result"]
    assert decoded["big"] == value["big"]
    assert decoded["bytes"] == bytes((1, 2, 3))
    assert decoded["duration"] == timedelta(seconds=1.5)
    assert (decoded["decimal"].value, decoded["decimal"].scale) == (123, 2)
    tree = {"value": 1, "children": ({"value": 2, "children": ()}, {"value": 3, "children": ()})}
    assert roundtrip_fp(_tree(), tree) == tree
    mixed = S.Union(S.String, S.Number, struct(n=S.Boolean))
    assert roundtrip_fp(mixed, "x") == "x"
    assert roundtrip_fp(mixed, 1.5) == 1.5
    assert roundtrip_fp(mixed, {"n": True}) == {"n": True}


# --- layout fingerprint ---------------------------------------------------------------

Base = struct(name=S.String, age=S.Number)
Value = {"name": "a", "age": 1}


def test_ignores_schema_changes_that_do_not_reach_the_wire() -> None:
    """ignores schema changes that do not reach the wire"""
    baseline = fingerprint_of(Base, Value)
    checked = struct(
        name=S.String.check(S.is_min_length(1)).annotate(description="the name"),
        age=S.Number,
    )
    assert fingerprint_of(checked, Value) == baseline
    assert fingerprint_of(struct(age=S.Number, name=S.String), Value) == baseline
    transformed = struct(name=S.String, age=S.Number.pipe(S.decode_to(S.Number)))
    assert fingerprint_of(transformed, Value) == baseline


def test_does_not_depend_on_the_order_a_literal_union_declares_its_members() -> None:
    """does not depend on the order a literal union declares its members"""
    assert fingerprint_of(S.Literals("a", "b", "c"), "a") == fingerprint_of(
        S.Literals("c", "a", "b"), "a"
    )
    assert fingerprint_of(S.Literals("a", "b"), "a") != fingerprint_of(S.Literals("a", "c"), "a")
    assert fingerprint_of(S.Literal("a"), "a") != fingerprint_of(S.String, "a")


def test_does_not_depend_on_whether_an_acyclic_sub_schema_is_shared_or_repeated() -> None:
    """does not depend on whether an acyclic sub-schema is shared or repeated"""
    point = struct(x=S.Number, y=S.Number)
    pair = {"a": {"x": 1, "y": 2}, "b": {"x": 3, "y": 4}}
    shared = fingerprint_of(struct(a=point, b=point), pair)
    repeated = fingerprint_of(
        struct(a=struct(x=S.Number, y=S.Number), b=struct(x=S.Number, y=S.Number)), pair
    )
    assert shared == repeated
    leaf = {"value": 1, "children": ()}
    assert fingerprint_of(_tree(), leaf) == fingerprint_of(_tree(), leaf)
    both = {"left": leaf, "right": leaf}
    one = _tree()
    assert fingerprint_of(struct(left=one, right=one), both) == fingerprint_of(
        struct(left=_tree(), right=_tree()), both
    )


def test_hashes_the_layout_graph_so_re_factoring_a_recursive_schema_moves_it() -> None:
    """hashes the layout graph, so re-factoring a recursive schema moves it"""
    direct = _tree()
    aliased = struct(value=S.Number, children=S.Array(_tree()))
    mutual_a: Any = struct(value=S.Number, children=S.Array(S.suspend(lambda: mutual_b)))
    mutual_b: Any = struct(value=S.Number, children=S.Array(S.suspend(lambda: mutual_a)))
    tree = {"value": 1, "children": ({"value": 2, "children": ()},)}
    frames = [fingerprint_frame(schema, tree) for schema in (direct, aliased, mutual_a)]
    assert len({payload for _, payload in frames}) == 1
    assert decode(aliased, encode(direct, tree)) == tree
    assert decode(direct, encode(aliased, tree)) == tree
    assert len({fingerprint for fingerprint, _ in frames}) == 3
    text = message_of(lambda: decode(aliased, encode_fp(direct, tree), fingerprint=True))
    assert "Expected matching layout fingerprint" in text


def test_changes_whenever_the_wire_layout_changes() -> None:
    """changes whenever the wire layout changes"""
    baseline = fingerprint_of(Base, Value)
    changed = [
        fingerprint_of(struct(label=S.String, age=S.Number), {"label": "a", "age": 1}),
        fingerprint_of(
            struct(name=S.String, age=S.Number, extra=S.Boolean),
            {"name": "a", "age": 1, "extra": True},
        ),
        fingerprint_of(struct(name=S.String, age=_optional(S.Number)), Value),
        fingerprint_of(struct(name=S.String, age=Int), Value),
        fingerprint_of(struct(name=S.String.pipe(B.field_id(1)), age=S.Number), Value),
        fingerprint_of(struct(name=S.String, age=S.String), {"name": "a", "age": "1"}),
    ]
    assert len({baseline, *changed}) == len(changed) + 1
    assert fingerprint_of(S.Tuple(S.Number, S.Number), (1, 2)) != fingerprint_of(
        S.Tuple(S.Number, S.Number, S.Number), (1, 2, 3)
    )
    assert fingerprint_of(S.Array(S.Number), [1]) != fingerprint_of(S.Tuple(S.Number), (1,))
    a = struct(_tag=S.Literal("a"), n=S.Number)
    b = struct(_tag=S.Literal("b"), s=S.String)
    c = struct(_tag=S.Literal("c"), s=S.String)
    value = {"_tag": "a", "n": 1}
    assert fingerprint_of(S.Union(a, b), value) == fingerprint_of(S.Union(b, a), value)
    assert fingerprint_of(S.Union(a, b), value) != fingerprint_of(S.Union(a, b, c), value)


# --- fingerprint mode failures --------------------------------------------------------

Pair = struct(name=S.String, age=S.Number)
ada = {"name": "Ada", "age": 36}
grace = {"name": "Grace", "age": 45}


def test_fails_closed_when_the_layout_fingerprint_differs() -> None:
    """fails closed when the layout fingerprint differs"""
    frame = encode_fp(Pair, ada)
    other = struct(label=S.String, age=S.Number)
    text = message_of(lambda: decode(other, frame, fingerprint=True))
    assert "Expected matching layout fingerprint" in text


def test_rejects_the_other_modes_frames_in_both_directions() -> None:
    """rejects the other mode's frames in both directions"""
    assert "Expected version 2 envelope, flags 0" in message_of(
        lambda: decode(Pair, encode_fp(Pair, ada))
    )
    assert "Expected version 2 envelope, flags 1" in message_of(
        lambda: decode(Pair, encode(Pair, ada), fingerprint=True)
    )


def test_rejects_truncated_and_oversized_frames() -> None:
    """rejects truncated and oversized frames"""
    frame = encode_fp(Pair, ada)
    short = bytes((5, 0x21)) + frame[2:6]
    assert "Expected complete value" in message_of(lambda: decode(Pair, short, fingerprint=True))
    assert "Expected complete value" in message_of(
        lambda: decode(Pair, frame[:-1], fingerprint=True)
    )
    assert "Expected no leftover bytes" in message_of(
        lambda: decode(Pair, frame + bytes((0,)), fingerprint=True)
    )
    leftover = bytearray(frame)
    leftover[0] = frame[0] + 1
    assert "Expected no leftover bytes" in message_of(
        lambda: decode(Pair, bytes(leftover) + bytes((0,)), fingerprint=True)
    )


def test_rejects_a_union_position_outside_the_member_table() -> None:
    """rejects a union position outside the member table"""
    event = S.Union(
        struct(_tag=S.Literal("a"), n=S.Number), struct(_tag=S.Literal("b"), s=S.String)
    )
    frame = bytearray(encode_fp(event, {"_tag": "b", "s": "x"}))
    frame[10] = 7
    text = message_of(lambda: decode(event, bytes(frame), fingerprint=True))
    assert "Expected known union member" in text


def test_reports_a_required_field_a_newer_writer_left_unreadable_as_missing() -> None:
    """reports a required field a newer writer left unreadable as missing"""
    text_defect: Any = S.String
    schema = struct(reason=S.CauseReason(S.String, text_defect))
    frame = bytearray(encode_fp(schema, {"reason": Fail("boom")}))
    frame[11] = 9
    text = message_of(lambda: decode(schema, bytes(frame), fingerprint=True))
    assert "reason" in text
    assert "Missing key" in text


def test_rejects_duplicate_extra_keys() -> None:
    """rejects duplicate extra keys"""
    schema = S.Record(S.String, S.Number)
    frame = bytearray(encode_fp(schema, {"a": 1, "b": 2}))
    frame[-2] = 97
    text = message_of(lambda: decode(schema, bytes(frame), fingerprint=True))
    assert "Expected unique extra keys" in text


# --- codec memoization ----------------------------------------------------------------


def test_memoizes_by_schema_and_wire_mode() -> None:
    """memoizes by schema and wire mode"""
    schema = struct(id=S.Number, label=S.String)
    codec = B.to_codec(schema)
    assert B.to_codec(schema) is codec
    assert B.to_codec(schema, fingerprint=False) is codec
    fingerprint_codec = B.to_codec(schema, fingerprint=True)
    assert B.to_codec(schema, fingerprint=True) is fingerprint_codec
    assert fingerprint_codec is not codec
    direct = B.to_codec_direct(schema)
    assert B.to_codec_direct(schema) is direct
    assert B.to_codec_direct(schema, fingerprint=False) is direct
    direct_fingerprint = B.to_codec_direct(schema, fingerprint=True)
    assert B.to_codec_direct(schema, fingerprint=True) is direct_fingerprint
    assert direct_fingerprint is not direct


# --- generated regressions ------------------------------------------------------------

_Event = S.Union(
    struct(_tag=S.Literal("Text"), value=S.String),
    struct(_tag=S.Literal("Count"), value=S.Number),
)
Generated = struct(
    flag=S.Boolean,
    count=S.Int,
    ratio=S.Number,
    label=S.String,
    bytes=S.Bytes,
    big=S.BigInt,
    optional=Opt(S.String),
    tuple=S.Tuple(S.String, S.Number, S.Boolean),
    items=S.Array(struct(id=S.Int, name=S.String)),
    attributes=S.Record(S.String, S.Union(S.String, S.Number, S.Boolean, S.Null)),
    event=_Event,
)

_text = st.text(st.characters(exclude_categories=("Cs",)), max_size=8)
_number = st.floats(allow_nan=False)
_safe_int = st.integers(-(2**53) + 1, 2**53 - 1)
_generated: st.SearchStrategy[dict[str, Any]] = st.fixed_dictionaries(
    {
        "flag": st.booleans(),
        "count": _safe_int,
        "ratio": _number,
        "label": _text,
        "bytes": st.binary(max_size=8),
        "big": st.integers(),
        "tuple": st.tuples(_text, _number, st.booleans()),
        "items": st.lists(st.fixed_dictionaries({"id": _safe_int, "name": _text}), max_size=4).map(
            tuple
        ),
        "attributes": st.dictionaries(
            _text, st.one_of(_text, _number, st.booleans(), st.none()), max_size=4
        ),
        "event": st.one_of(
            st.fixed_dictionaries({"_tag": st.just("Text"), "value": _text}),
            st.fixed_dictionaries({"_tag": st.just("Count"), "value": _number}),
        ),
    },
    optional={"optional": _text},
)


@settings(max_examples=100, deadline=None)
@given(_generated)
def test_keeps_every_encoding_entry_point_equivalent_for_generated_nested_values(
    value: dict[str, Any],
) -> None:
    """keeps every encoding entry point equivalent for generated nested values"""
    for fingerprint in (False, True):
        codec = B.to_codec(Generated, fingerprint=fingerprint)
        direct = B.to_codec_direct(Generated, fingerprint=fingerprint)
        frame = S.encode_unknown_sync(codec)(value)
        assert B.encode_unknown_sync(Generated, fingerprint=fingerprint)(value) == frame
        assert B.encoder(Generated, fingerprint=fingerprint).encode(value) == frame
        assert S.decode_unknown_sync(codec)(frame) == value
        assert S.decode_unknown_sync(direct)(frame) == value
        assert B.parser(Generated, fingerprint=fingerprint).feed_sync(frame) == [value]


@settings(max_examples=50, deadline=None)
@given(
    st.lists(_generated, max_size=8),
    st.lists(st.integers(1, 64), min_size=1, max_size=30),
    st.booleans(),
)
def test_parses_generated_batches_across_arbitrary_chunk_boundaries(
    values: list[dict[str, Any]], chunk_sizes: list[int], fingerprint: bool
) -> None:
    """parses generated batches across arbitrary chunk boundaries"""
    data = B.encode_many_unknown_sync(Generated, fingerprint=fingerprint)(values)
    parser = B.parser(Generated, fingerprint=fingerprint)
    decoded: list[object] = []
    offset = 0
    for size in chunk_sizes:
        if offset >= len(data):
            break
        end = min(offset + size, len(data))
        decoded.extend(parser.feed_sync(data[offset:end]))
        offset = end
    if offset < len(data):
        decoded.extend(parser.feed_sync(data[offset:]))
    parser.end_sync()
    assert decoded == values


@settings(max_examples=50, deadline=None)
@given(_generated, st.integers(min_value=0), st.booleans())
def test_rejects_every_generated_truncated_frame(
    value: dict[str, Any], offset: int, fingerprint: bool
) -> None:
    """rejects every generated truncated frame"""
    data = B.encode_unknown_sync(Generated, fingerprint=fingerprint)(value)
    cut = 1 + offset % (len(data) - 1)
    parser = B.parser(Generated, fingerprint=fingerprint)
    assert parser.feed_sync(data[:cut]) == []
    assert "complete value" in message_of(parser.end_sync)


def test_owns_buffered_and_decoded_bytes_independently_of_caller_buffers() -> None:
    """owns buffered and decoded bytes independently of caller buffers"""
    schema = struct(label=S.String, bytes=S.Bytes)
    value = {"label": "fragmented", "bytes": bytes((1, 2, 3, 4))}
    frame = bytearray(encode(schema, value))
    split = len(frame) // 2
    prefix = bytearray(frame[:split])
    parser = B.parser(schema)
    assert parser.feed_sync(prefix) == []  # pyright: ignore[reportArgumentType]
    prefix[:] = bytes(len(prefix))
    [decoded] = parser.feed_sync(memoryview(frame)[split:])  # pyright: ignore[reportArgumentType]
    frame[:] = bytes(len(frame))
    assert decoded == value
    parser.end_sync()


# --- direct codec ---------------------------------------------------------------------


def test_matches_to_codec_on_the_wire_and_round_trips() -> None:
    """matches toCodec on the wire and round-trips"""
    direct = B.to_codec_direct(Pair)
    data = S.encode_unknown_sync(direct)(ada)
    assert data == encode(Pair, ada)
    assert S.decode_unknown_sync(direct)(data) == ada


def test_still_rejects_invalid_input_through_the_binary_layer() -> None:
    """still rejects invalid input, through the binary layer"""
    write = S.encode_unknown_sync(B.to_codec_direct(Pair))
    assert "age" in message_of(lambda: write({"name": "Ada", "age": "old"}))
    assert "age" in message_of(lambda: write({"name": "Ada"}))
    assert "Expected an object" in message_of(lambda: write("Ada"))


def test_rejects_a_wrong_runtime_type_for_every_leaf_an_exact_schema_can_reach() -> None:
    """rejects a wrong runtime type for every leaf an exact schema can reach"""
    cases: tuple[tuple[Any, object, str], ...] = (
        (S.String, 1, "a string"),
        (S.Number, "1", "a number"),
        (S.Boolean, 1, "a boolean"),
        (S.BigInt, "1", "a bigint"),
        (S.Null, 1, "null"),
        (Undefined, 1, "undefined"),
        (S.Bytes, [1, 2], "a Uint8Array"),
        (S.Array(S.String), "ab", "an array"),
        (struct(a=S.String), "a", "an object"),
    )
    for schema, value, expected in cases:
        write = S.encode_unknown_sync(B.to_codec_direct(schema))
        assert f"Expected {expected}" in message_of(lambda: write(value))  # noqa: B023


def test_keeps_failure_exits_on_the_schema_pass_when_only_the_success_side_is_exact() -> None:
    """keeps failure exits on the schema pass when only the success side is exact"""
    schema = S.Exit(struct(id=S.String), S.String, S.Defect())
    direct = B.to_codec_direct(schema)
    sound = B.to_codec(schema)
    exits: tuple[Any, ...] = (
        Exit.succeed({"id": "user-1"}),
        Exit.fail("nope"),
        Exit.die(ValueError("boom")),
        Exit.fail_cause(Cause[str]((Interrupt(7),))),
    )
    for exit_ in exits:
        data = S.encode_unknown_sync(direct)(exit_)
        assert data == S.encode_unknown_sync(sound)(exit_)
        assert repr(S.decode_unknown_sync(direct)(data)) == repr(S.decode_unknown_sync(sound)(data))
    died = S.decode_unknown_sync(direct)(
        S.encode_unknown_sync(direct)(Exit.die(ValueError("boom")))
    )
    assert Exit.is_failure(died)
    reason = died.cause.reasons[0]
    assert isinstance(reason, Die)
    assert isinstance(reason.defect, Exception)
    assert str(reason.defect) == "boom"
    schema_error(lambda: S.encode_unknown_sync(direct)(Exit.succeed({"id": 42})))
    schema_error(lambda: S.encode_unknown_sync(direct)("not an exit"))
    excess = Exit.succeed({"id": "ok", "extra": True})
    assert S.encode_unknown_sync(direct)(excess) == S.encode_unknown_sync(sound)(excess)
    assert "extra" in message_of(
        lambda: S.encode_unknown_sync(direct, on_excess_property="error")(excess)
    )
    assert "extra" in message_of(
        lambda: B.encode_unknown_sync(schema, on_excess_property="error")(excess)
    )


def test_rejects_an_inherited_discriminator_like_the_schema_pass() -> None:
    """rejects an inherited discriminator, like the schema pass"""
    schema = S.Union(
        struct(_tag=S.Literal("A"), value=S.Number), struct(_tag=S.Literal("B"), value=S.String)
    )

    class Inherited(dict[str, object]):
        _tag = "A"

    for fingerprint in (False, True):
        write = S.encode_unknown_sync(B.to_codec_direct(schema, fingerprint=fingerprint))
        schema_error(lambda: write(Inherited(value=1)))  # noqa: B023


def test_reports_excess_properties_when_the_call_site_asks_for_it() -> None:
    """reports excess properties when the call site asks for it"""
    direct = B.to_codec_direct(Pair)
    excess = {**ada, "extra": True}
    assert S.encode_unknown_sync(direct)(excess) == encode(Pair, ada)
    assert "extra" in message_of(
        lambda: S.encode_unknown_sync(direct, on_excess_property="error")(excess)
    )


def test_reports_excess_properties_through_encode_unknown_sync() -> None:
    """reports excess properties through encodeUnknownSync"""
    excess = {**ada, "extra": True}
    assert "extra" in message_of(
        lambda: B.encode_unknown_sync(Pair, on_excess_property="error")(excess)
    )


def test_falls_back_to_to_codec_when_the_binary_layer_cannot_prove_the_schema() -> None:
    """falls back to toCodec when the binary layer cannot prove the schema"""
    checked = S.Number.check(S.is_greater_than_or_equal_to(0))
    direct = B.to_codec_direct(checked)
    assert S.is_(direct)(1)
    assert not S.is_(direct)(-1)
    assert "greater than or equal to 0" in message_of(lambda: S.encode_unknown_sync(direct)(-1))


# --- encodeManyUnknownSync ------------------------------------------------------------

people = [ada, grace]


def test_writes_the_same_bytes_as_concatenated_single_frames() -> None:
    """writes the same bytes as concatenated single frames"""
    many = B.encode_many_unknown_sync(Pair, fingerprint=True)
    assert many(people) == b"".join(encode_fp(Pair, p) for p in people)
    assert B.parser(Pair, fingerprint=True).feed_sync(many(people)) == people
    assert many([]) == b""


def test_reports_the_failing_frame_and_takes_the_fallback_path_for_checked_schemas() -> None:
    """reports the failing frame and takes the fallback path for checked schemas"""
    many = B.encode_many_unknown_sync(Pair)
    assert "age" in message_of(lambda: many([ada, {"name": "Grace"}]))
    checked_schema = struct(age=S.Number.check(S.is_greater_than_or_equal_to(0)))
    checked = B.encode_many_unknown_sync(checked_schema)
    assert checked([{"age": 1}, {"age": 2}]) == encode(checked_schema, {"age": 1}) + encode(
        checked_schema, {"age": 2}
    )
    assert "greater than or equal to 0" in message_of(lambda: checked([{"age": -1}]))


def test_reports_excess_properties() -> None:
    """reports excess properties"""
    excess = {**ada, "extra": True}
    many = B.encode_many_unknown_sync(Pair, on_excess_property="error")
    assert "extra" in message_of(lambda: many([ada, excess]))


# --- schemas the binary layer validates on its own --------------------------------------


def _validates_itself(schema: Any) -> bool:
    try:
        B.encoder(schema, dictionary=True)
    except ValueError as error:
        assert "dictionary" in str(error)
        return False
    return True


def test_covers_never_which_an_inferred_schema_reaches_through_an_empty_array() -> None:
    """covers never, which an inferred schema reaches through an empty array"""
    assert _validates_itself(S.Never)
    row = struct(id=S.String, tags=S.Array(S.Never))
    assert _validates_itself(row)
    value = {"id": "a", "tags": ()}
    assert roundtrip(row, value) == value
    assert "never" in message_of(lambda: encode(row, {"id": "a", "tags": ["x"]}))
    assert not S.is_(B.to_codec(row))({"id": 1, "tags": []})


def test_covers_unknown_and_any_which_the_json_layer_already_rejects_or_accepts() -> None:
    """covers unknown and any, which the JSON layer already rejects or accepts"""
    assert _validates_itself(S.Unknown)
    assert _validates_itself(S.Any)
    row = struct(id=S.String, payload=S.Unknown)
    assert _validates_itself(row)
    value = {"id": "a", "payload": {"nested": [1, "two", True, None]}}
    assert roundtrip(row, value) == value
    assert not S.is_(B.to_codec(row))({"id": 1, "payload": 1})
    payload: dict[str, object] = {}
    payload["self"] = payload
    assert "acyclic value" in message_of(lambda: encode(row, {"id": "a", "payload": payload}))


def test_covers_recursion_on_decode_while_encode_keeps_the_cycle_walk() -> None:
    """covers recursion on decode while encode keeps the cycle walk"""
    node: Any = struct(value=S.String, children=S.Array(S.suspend(lambda: node)))
    assert _validates_itself(node)
    tree = {"value": "root", "children": ({"value": "leaf", "children": ()},)}
    assert roundtrip(node, tree) == tree
    assert not S.is_(B.to_codec(node))({"value": 1, "children": []})
    assert "object" in message_of(lambda: encode(node, {"value": "root", "children": [1]}))
    children: list[object] = []
    cyclic = {"value": "root", "children": children}
    children.append(cyclic)
    assert "acyclic value" in message_of(lambda: encode(node, cyclic))
