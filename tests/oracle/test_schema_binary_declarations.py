"""Effect's ``encoding/SchemaBinary.test.ts``: the rest of "parser", native
declarations, generic declarations and recursion, parse options, layout and
data errors.

Omitted (one line each):
- "keeps parser index-signature caching bounded with FIFO eviction",
  "does not thrash the index-signature cache above its bound": the key
  classification cache is a JavaScript optimization this port has none of, and
  they count its hits.

Adapted:
- ``Schema.Chunk`` is ``S.List``.
- ``Schema.Date`` has no Python schema (``S.DateTimeUtc`` is a ``datetime``); its
  lines use ``DateTimeUtc``. Symbols are dropped.
- ``datetime`` covers years 1 to 9999: the boundaries are those, and reading past
  them is the failure.
"""
# pyright: reportPrivateUsage=false, reportUnknownMemberType=false

from __future__ import annotations

from datetime import UTC, datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo

import pytest

import pyfect as fx
from pyfect import big_decimal as bd
from pyfect import duration
from pyfect import exit as Exit
from pyfect import schema as S
from pyfect.cause import Cause, Die, Fail, Interrupt
from pyfect.encoding import schema_binary as B
from pyfect.hash_map import HashMap
from pyfect.hash_set import HashSet
from pyfect.option import Some
from pyfect.result import Err, Ok
from pyfect.schema import getter as G
from pyfect.schema import issue as Issue
from pyfect.schema import transformation as T

from ._schema_binary import (
    Opt,
    decode,
    encode,
    fingerprint_frame,
    int64_frame,
    message_of,
    roundtrip,
    roundtrip_fp,
    schema_error,
    struct,
    struct_of,
    uvarint,
)

AnyDefect: Any = S.Unknown

# --- parser ---------------------------------------------------------------------------


def test_waits_for_a_fragmented_multi_byte_frame_header() -> None:
    """waits for a fragmented multi-byte frame header"""
    value = "x" * 300
    data = encode(S.String, value)
    parser = B.parser(S.String)
    assert parser.feed_sync(data[:1]) == []
    assert parser.feed_sync(data[1:]) == [value]
    parser.end_sync()


def test_uses_the_bigint_header_path_for_longer_safe_lengths() -> None:
    """uses the bigint header path for longer safe lengths"""
    data = bytes((0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0x0F))
    parser = B.parser(S.String, max_frame_size=1)
    assert parser.feed_sync(data[:7]) == []
    assert "frame within maxFrameSize" in message_of(lambda: parser.feed_sync(data[7:]))


def test_isolates_index_signature_caches_by_parser_options() -> None:
    """isolates index-signature caches by parser options"""
    key = S.String.check(S.make_filter(lambda key: key.startswith("allowed-")))
    data = encode(S.Record(S.String, S.Number), {"denied": 1})
    reader = S.Record(key, S.Number)
    strict = B.parser(reader)
    unchecked = B.parser(reader, disable_checks=True)
    assert strict.feed_sync(data) == [{}]
    assert unchecked.feed_sync(data) == [{"denied": 1}]
    strict.end_sync()
    unchecked.end_sync()


def test_keeps_nested_schema_binary_decodes_independent_from_the_outer_reader() -> None:
    """keeps nested SchemaBinary decodes independent from the outer reader"""
    inner = struct(id=S.Number, label=S.String)
    outer = struct(id=S.String, inner=B.to_codec(inner))
    first = {"id": "first", "inner": {"id": 1, "label": "one"}}
    second = {"id": "second", "inner": {"id": 2, "label": "two"}}
    parser = B.parser(outer)
    assert parser.feed_sync(encode(outer, first) + encode(outer, second)) == [first, second]
    parser.end_sync()


def test_returns_a_checked_out_one_shot_reader_after_an_exceptional_decode() -> None:
    """returns a checked-out one-shot reader after an exceptional decode"""
    assert "utf-8" in message_of(lambda: decode(S.String, bytes((2, 0x20, 0xFF))))
    assert decode(S.String, encode(S.String, "after failure")) == "after failure"


def test_delivers_completed_values_before_reporting_a_later_failure() -> None:
    """delivers completed values before reporting a later failure"""
    good = encode(S.Number, 1)
    bad = encode(S.Number, 2)[:2]
    parser = B.parser(S.Number)
    assert parser.feed_sync(good + bad) == [1]
    assert "complete value" in message_of(parser.end_sync)
    assert "parser is spent" in message_of(lambda: parser.feed_sync(b""))


def test_stashes_a_malformed_complete_frame_after_returning_earlier_values() -> None:
    """stashes a malformed complete frame after returning earlier values"""
    good = encode(S.Number, 1)
    bad = bytearray(encode(S.Number, 2))
    bad[1] = 0x10
    parser = B.parser(S.Number)
    assert parser.feed_sync(good + bytes(bad)) == [1]
    assert "version 2 envelope, flags 0" in message_of(lambda: parser.feed_sync(b""))
    assert "parser is spent" in message_of(parser.end_sync)


def test_enforces_max_frame_size() -> None:
    """enforces maxFrameSize"""
    data = encode(S.String, "too large")
    parser = B.parser(S.String, max_frame_size=2)
    assert "frame within maxFrameSize" in message_of(lambda: parser.feed_sync(data))
    exact = B.parser(S.String, max_frame_size=data[0])
    assert exact.feed_sync(data) == ["too large"]
    exact.end_sync()


def test_fails_a_ten_byte_unterminated_length_immediately() -> None:
    """fails a ten-byte unterminated length immediately"""
    parser = B.parser(S.String, report_input=True)
    error = schema_error(lambda: parser.feed_sync(bytes((0x80,)) * 10))
    assert "uvarint" in error.message
    assert Issue.has_input(error.issue)


def test_rejects_a_terminated_header_above_the_safe_integer_bound() -> None:
    """rejects a terminated header above the safe-integer bound"""
    data = bytes((0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x10))
    parser = B.parser(S.String)
    assert "safe integer length" in message_of(lambda: parser.feed_sync(data))
    assert "parser is spent" in message_of(lambda: parser.feed_sync(b""))


@fx.testing.effect
def test_wraps_feed_and_end_in_schema_error_effects():
    """wraps feed and end in SchemaError effects"""
    parser = B.parser(S.Number)
    values = yield from parser.feed(encode(S.Number, 1))
    assert values == [1]
    yield from parser.end


@fx.testing.effect
def test_fails_malformed_feed_and_truncated_end_through_the_effect_surface():
    """fails malformed feed and truncated end through the Effect surface"""
    malformed = B.parser(S.Boolean)
    feed_error = yield from malformed.feed(bytes((2, 0x20, 2))).flip()
    assert isinstance(feed_error, S.SchemaError)
    truncated = B.parser(S.String)
    yield from truncated.feed(bytes((2, 0x20)))
    end_error = yield from truncated.end.flip()
    assert isinstance(end_error, S.SchemaError)


# --- native declarations --------------------------------------------------------------


def test_round_trips_bigint_date_bytes_option_and_result() -> None:
    """round-trips bigint, Date, bytes, Option, and Result"""
    assert roundtrip(S.BigInt, -12345678901234567890) == -12345678901234567890
    moment = datetime(1969, 12, 30, 13, 42, 23, 211000, tzinfo=UTC)
    assert roundtrip(S.DateTimeUtc, moment) == moment
    assert roundtrip(S.Bytes, bytes((0, 1, 255))) == bytes((0, 1, 255))
    assert roundtrip(S.Option(S.String), Some("value")) == Some("value")
    assert roundtrip(S.Result(S.Number, S.String), Err("error")) == Err("error")


def test_round_trips_duration_and_normalized_big_decimal() -> None:
    """round-trips Duration and normalized BigDecimal"""
    assert roundtrip(S.Duration, duration.millis(1.5)).to_nanos_unsafe() == 1_500_000
    assert roundtrip(S.Duration, duration.infinity) is duration.infinity
    assert roundtrip(S.Duration, duration.negative_infinity) is duration.negative_infinity
    assert roundtrip(S.Duration, duration.nanos(-7)).to_nanos_unsafe() == -7
    decimal = roundtrip(S.BigDecimal, bd.make(100, 2))
    assert (decimal.value, decimal.scale) == (1, 0)
    negative = roundtrip(S.BigDecimal, bd.make(-123, -4))
    assert (negative.value, negative.scale) == (-123, -4)


def test_round_trips_the_empty_and_success_branches_of_native_sums() -> None:
    """round-trips the empty and success branches of native sums"""
    assert roundtrip(S.Option(S.String), None) is None
    assert roundtrip(S.Result(S.Number, S.String), Ok(42)) == Ok(42)
    exit_ = roundtrip(S.Exit(S.Number, S.String, AnyDefect), Exit.succeed(42))
    assert exit_ == Exit.succeed(42)


def test_skips_future_cause_reason_tags_inside_cause() -> None:
    """skips future CauseReason tags inside Cause"""
    schema = S.Cause(S.String, AnyDefect)
    decoded = decode(schema, bytes((7, 0x20, 2, 1, 99, 2, 0, 0x78)))
    assert decoded.reasons == (Fail("x"),)
    reason = S.CauseReason(S.String, AnyDefect)
    assert "Missing key" in message_of(lambda: decode(reason, bytes((2, 0x20, 99))))


def test_round_trips_utc_and_zoned_date_time_values() -> None:
    """round-trips UTC and zoned DateTime values"""
    utc = datetime(1969, 12, 30, 13, 42, 23, 211000, tzinfo=UTC)
    assert roundtrip(S.DateTimeUtc, utc) == utc
    instant = datetime(1970, 1, 2, 10, 17, 36, 789000, tzinfo=UTC)
    for zone in (timezone(timedelta(hours=1)), ZoneInfo("Europe/London")):
        zoned = instant.astimezone(zone)
        decoded = roundtrip(S.DateTimeZoned, zoned)
        assert decoded == zoned
        assert decoded.utcoffset() == zoned.utcoffset()
        assert decoded.tzname() == zoned.tzname()


def test_validates_date_time_utc_epoch_millisecond_boundaries() -> None:
    """validates DateTimeUtc epoch millisecond boundaries"""
    lowest = -62135596800000
    highest = 253402300799999
    assert decode(S.DateTimeUtc, int64_frame(lowest)) == datetime.min.replace(tzinfo=UTC)
    assert decode(S.DateTimeUtc, int64_frame(highest)).year == 9999
    for millis in (lowest - 1, highest + 1, -8_640_000_000_000_001, 8_640_000_000_000_001):
        text = message_of(lambda: decode(S.DateTimeUtc, int64_frame(millis)))  # noqa: B023
        assert "valid DateTime" in text


def test_round_trips_exit_cause_and_cause_reason() -> None:
    """round-trips Exit, Cause, and CauseReason"""
    schema = S.Cause(S.String, AnyDefect)
    cause = Cause((Fail("boom"), Die({"defect": True}), Interrupt(0), Interrupt(None)))
    decoded = roundtrip(schema, cause)
    assert [type(r) for r in decoded.reasons] == [Fail, Die, Interrupt, Interrupt]
    assert decoded.reasons[2].fiber_id == 0
    assert decoded.reasons[3].fiber_id is None
    assert roundtrip(S.CauseReason(S.String, AnyDefect), Fail("failure")) == Fail("failure")
    failed = roundtrip(S.Exit(S.Number, S.String, AnyDefect), Exit.fail_cause(cause))
    assert Exit.is_failure(failed)


def test_round_trips_both_exit_branches_in_fingerprint_mode() -> None:
    """round-trips both Exit branches in fingerprint mode"""
    schema = S.Exit(S.Number, S.String, AnyDefect)
    cause = Cause((Fail("boom"), Die({"defect": True})))
    assert Exit.is_success(roundtrip_fp(schema, Exit.succeed(7)))
    failure = roundtrip_fp(schema, Exit.fail_cause(cause))
    assert [type(r) for r in failure.cause.reasons] == [Fail, Die]
    assert (
        fingerprint_frame(schema, Exit.fail_cause(cause))[0]
        != fingerprint_frame(S.Cause(S.String, AnyDefect), cause)[0]
    )


# --- generic declarations and recursion -------------------------------------------------


class _Person(S.Class):
    name: str


class _Event(S.TaggedClass, tag="Event"):
    value: float


def test_uses_declaration_codec_links_for_collections_redacted_class_and_tagged_class() -> None:
    """uses declaration codec links for collections, Redacted, Class, and TaggedClass"""
    from pyfect import redacted

    assert roundtrip(S.List(S.Number), [1, 2, 3]) == [1, 2, 3]
    hash_map = roundtrip(S.HashMap(S.String, S.Number), HashMap.make(("a", 1.0), ("b", 2.0)))
    assert hash_map.get("a") == Some(1)
    assert hash_map.get("b") == Some(2)
    hash_set = roundtrip(S.HashSet(S.String), HashSet.make("a", "b"))
    assert hash_set.has("a")
    assert hash_set.has("b")
    assert roundtrip(S.Map(S.String, S.Number), {"a": 1, "b": 2}) == {"a": 1, "b": 2}
    assert roundtrip(S.FrozenSet(S.String), frozenset(("a", "b"))) == frozenset(("a", "b"))
    secret = roundtrip(S.Redacted(S.String), redacted.make("secret"))
    assert redacted.value(secret) == "secret"
    person = roundtrip(_Person, _Person(name="Ada"))
    assert isinstance(person, _Person)
    assert person.name == "Ada"
    event = roundtrip(_Event, _Event(value=1))
    assert isinstance(event, _Event)
    assert event.value == 1


def _tree() -> Any:
    node: Any = struct(value=S.Number, children=S.Array(S.suspend(lambda: node)))
    return node


def test_compiles_and_round_trips_recursive_suspended_schemas() -> None:
    """compiles and round-trips recursive suspended schemas"""
    value = {"value": 1, "children": ({"value": 2, "children": ()},)}
    assert roundtrip(_tree(), value) == value


def test_fails_cyclic_json_values_with_the_acyclic_value_issue() -> None:
    """fails cyclic JSON values with the acyclic value issue"""
    value: dict[str, object] = {}
    value["self"] = value
    assert "acyclic value" in message_of(lambda: encode(S.Unknown, value))


def test_fails_cyclic_recursive_struct_values_with_the_acyclic_value_issue() -> None:
    """fails cyclic recursive struct values with the acyclic value issue"""
    node: Any = struct(value=S.Number, next=Opt(S.suspend(lambda: node)))
    value: dict[str, object] = {"value": 1}
    value["next"] = value
    assert "acyclic value" in message_of(lambda: encode(node, value))


def test_fails_array_mediated_cycles_with_the_acyclic_value_issue() -> None:
    """fails array-mediated cycles with the acyclic value issue"""
    node_schema: Any = struct(name=S.String, children=S.Array(S.suspend(lambda: node_schema)))
    children: list[object] = []
    node = {"name": "root", "children": children}
    children.append(node)
    assert "acyclic value" in message_of(lambda: encode(node_schema, node))
    unknown: list[object] = []
    unknown.append(unknown)
    assert "acyclic value" in message_of(lambda: encode(S.Unknown, unknown))


def test_accepts_shared_recursive_values_that_are_dags_rather_than_cycles() -> None:
    """accepts shared recursive values that are DAGs rather than cycles"""
    leaf = {"value": 2, "children": ()}
    value = {"value": 1, "children": (leaf, leaf)}
    assert roundtrip(_tree(), value) == value


def test_rejects_non_serializable_json_values_without_calling_them_cycles() -> None:
    """rejects non-serializable JSON values without calling them cycles"""
    for value in (object(), lambda: 1):
        text = message_of(lambda: encode(S.Unknown, value))  # noqa: B023
        assert "JSON-serializable value" in text
        assert "acyclic value" not in text


def test_runs_user_encoding_links_before_the_binary_layer() -> None:
    """runs user encoding links before the binary layer"""
    assert len(encode(S.NumberFromString, 123)) == 5
    assert roundtrip(S.NumberFromString, 123) == 123
    before = struct(value=S.NumberFromString.pipe(B.field_id(7)))
    after = struct(renamed=S.NumberFromString.pipe(B.field_id(7)))
    assert decode(after, encode(before, {"value": 123})) == {"renamed": 123}


@fx.testing.effect
def test_round_trips_a_yielding_transform_effect_through_schema_parser_effect_apis():
    """round-trips a yielding transformEffect through SchemaParser Effect APIs"""
    schema = S.String.pipe(
        S.decode_to(
            S.Number,
            T.Transformation(
                G.transform_effect(lambda s, _: fx.yield_now().as_(float(s))),
                G.transform_effect(lambda n, _: fx.yield_now().as_(str(n))),
            ),
        )
    )
    codec = B.to_codec(schema)
    data = yield from S.encode_unknown_effect(codec)(123)
    decoded = yield from S.decode_unknown_effect(codec)(data)
    assert decoded == 123


def test_keeps_a_sound_runtime_type_guard_on_the_derived_codec() -> None:
    """keeps a sound runtime type guard on the derived codec"""
    codec = B.to_codec(struct(name=S.String, age=S.Number))
    assert S.is_(codec)({"name": "Ada", "age": 42})
    assert not S.is_(codec)({"nope": 1})


def test_keeps_a_sound_runtime_type_guard_on_recursive_derived_codecs() -> None:
    """keeps a sound runtime type guard on recursive derived codecs"""
    codec = B.to_codec(_tree())
    assert S.is_(codec)({"value": 1, "children": []})
    assert not S.is_(codec)({"nope": 1})
    assert not S.is_(struct(inner=codec))({"inner": {"nope": 1}})


# --- parse options --------------------------------------------------------------------

NonNegative = S.Number.check(S.is_greater_than_or_equal_to(0))


def test_honors_checks_and_disable_checks() -> None:
    """honors checks and disableChecks"""
    data = encode(S.Number, -1.5)
    assert "greater than or equal to 0" in message_of(lambda: decode(NonNegative, data))
    parser = B.parser(NonNegative, disable_checks=True)
    assert parser.feed_sync(data) == [-1.5]
    parser.end_sync()


def test_honors_disable_checks_for_recursive_schemas() -> None:
    """honors disableChecks for recursive schemas"""
    reader: Any = struct(value=NonNegative, children=S.Array(S.suspend(lambda: reader)))
    value = {"value": -1.5, "children": ()}
    data = encode(_tree(), value)
    parser = B.parser(reader, disable_checks=True)
    assert parser.feed_sync(data) == [value]
    parser.end_sync()
    assert S.decode_unknown_sync(B.to_codec(reader), disable_checks=True)(data) == value


def test_keeps_one_shot_index_signature_caching_within_each_options_call() -> None:
    """keeps one-shot index-signature caching within each options call"""
    key = S.String.check(S.make_filter(lambda key: key.startswith("allowed-")))
    codec = B.to_codec(S.Record(key, S.Number))
    data = encode(S.Record(S.String, S.Number), {"denied": 1})
    assert S.decode_unknown_sync(codec)(data) == {}
    assert S.decode_unknown_sync(codec, disable_checks=True)(data) == {"denied": 1}


def test_honors_errors_all_for_missing_fields() -> None:
    """honors errors all for missing fields"""
    data = encode(struct(), {})
    reader = B.to_codec(struct(a=S.String, b=S.Number))
    text = message_of(lambda: S.decode_unknown_sync(reader, errors="all")(data))
    assert text.count("Missing key") == 2


def test_ignores_excess_property_options_at_the_binary_boundary() -> None:
    """ignores excess-property options at the binary boundary"""
    writer = struct(extra=S.String, known=S.Number)
    reader = struct(known=S.Number)
    data = encode(writer, {"extra": "drop", "known": 1})
    decode_ = S.decode_unknown_sync(B.to_codec(reader), on_excess_property="error")
    assert decode_(data) == {"known": 1}
    parser = B.parser(reader, on_excess_property="error")
    assert parser.feed_sync(data) == [{"known": 1}]


# --- layout and data errors -------------------------------------------------------------


def test_throws_error_while_compiling_invalid_layouts() -> None:
    """throws Error while compiling invalid layouts"""

    def anything(_: object) -> bool:
        return True

    declaration = S.declare(anything)  # pyright: ignore[reportArgumentType, reportUnknownVariableType]
    with pytest.raises(ValueError, match="declaration <anonymous> has no toCodecJson or toCodec"):
        B.to_codec(declaration)  # pyright: ignore[reportUnknownArgumentType]
    with pytest.raises(ValueError, match="union members are not uniquely identifiable"):
        B.to_codec(S.Union(struct(a=S.String), struct(b=S.Number)))
    with pytest.raises(ValueError, match="Binary layout field id collision: 1"):
        B.to_codec(struct(a=S.String.pipe(B.field_id(1)), b=S.String.pipe(B.field_id(1))))
    with pytest.raises(ValueError, match=r"field id collision: 1836165160 \(hashed, explicit\)"):
        B.to_codec(struct(hashed=S.String, explicit=S.String.pipe(B.field_id(1836165160))))
    with pytest.raises(ValueError, match="Binary layout sentinel collision: 3370793117"):
        B.to_codec(
            S.Union(struct(_tag=S.Literal("1a0a49t3mq")), struct(_tag=S.Literal("m7r4q02dm7")))
        )


def test_uses_schema_issue_for_binary_failures() -> None:
    """uses SchemaIssue for binary failures"""
    error = schema_error(lambda: decode(S.Boolean, bytes((2, 0x20, 2))))
    assert Issue.is_issue(error.issue)
    assert "bool" in error.message


@fx.testing.effect
def test_preserves_the_schema_parser_issue_and_schema_schema_error_surfaces():
    """preserves the SchemaParser Issue and Schema SchemaError surfaces"""
    error = yield from S.decode_unknown_effect(B.to_codec(S.Boolean))(bytes((2, 0x20, 2))).flip()
    assert isinstance(error, S.SchemaError)
    assert Issue.is_issue(error.issue)


def test_reports_a_missing_fixed_tuple_slot_as_missing_key() -> None:
    """reports a missing fixed tuple slot as MissingKey"""
    data = encode(S.Tuple(), ())
    assert "Missing key" in message_of(lambda: decode(S.Tuple(S.String), data))


def test_rejects_malformed_lengths_and_text() -> None:
    """rejects malformed lengths and text"""
    assert "nonzero frame length" in message_of(lambda: decode(S.String, bytes((0,))))
    long = bytes((0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x80, 0x10))
    assert "safe integer length" in message_of(lambda: decode(S.String, long))
    assert "utf-8" in message_of(lambda: decode(S.String, bytes((2, 0x20, 0xFF))))
    short = bytes((8, 0x20, 0, 0, 0, 0, 0, 0, 0))
    assert "int64" in message_of(lambda: decode(S.DateTimeUtc, short))
    assert "empty" in message_of(lambda: decode(S.Null, bytes((2, 0x20, 0))))
    assert "json" in message_of(lambda: decode(S.Unknown, bytes((2, 0x20, 0x7B))))


def test_rejects_invalid_native_tags_and_payload_shapes() -> None:
    """rejects invalid native tags and payload shapes"""
    cases: tuple[tuple[Any, tuple[int, ...], str], ...] = (
        (S.Duration, (2, 0x20, 3), "duration"),
        (S.Option(S.String), (2, 0x20, 2), "bool"),
        (S.Option(S.String), (3, 0x20, 0, 0), "empty"),
        (S.Result(S.String, S.String), (2, 0x20, 2), "bool"),
        (S.Exit(S.String, S.String, AnyDefect), (2, 0x20, 2), "bool"),
        (S.DateTimeZoned, (10, 0x20, 0, 0, 0, 0, 0, 0, 0, 0, 2), "time zone"),
        (S.DateTimeZoned, (10, 0x20, 0, 0, 0, 0, 0, 0, 0, 0, 0), "time zone"),
    )
    for schema, data, expected in cases:
        assert expected in message_of(lambda: decode(schema, bytes(data)))  # noqa: B023


def test_rejects_attacker_sized_zero_width_array_counts() -> None:
    """rejects attacker-sized zero-width array counts"""
    data = bytes((6, 0x20, 0x80, 0x80, 0x80, 0x80, 0x10))
    text = message_of(lambda: decode(S.Array(S.Null), data))
    assert "array count within allocation limit" in text


def test_round_trips_zero_width_arrays_across_the_allocation_slack_boundary() -> None:
    """round-trips zero-width arrays across the allocation slack boundary"""
    schema = S.Array(S.Null)
    for count in (1_048_576, 1_048_577):
        data = encode(schema, [None] * count)
        assert len(data) == 5
        decoded = decode(schema, data)
        assert len(decoded) == count
        assert decoded[0] is None
        assert decoded[count - 1] is None


def test_rejects_duplicate_struct_field_ids_and_extra_keys() -> None:
    """rejects duplicate struct field ids and extra keys"""
    schema = struct(value=S.String)
    field = encode(schema, {"value": "x"})[2:]
    duplicate = bytes((1 + len(field) * 2, 0x20)) + field + field
    assert "unique field ids" in message_of(lambda: decode(schema, duplicate))
    record = S.Record(S.String, S.Number)
    pair = encode(record, {"a": 1})[4:]
    twice = bytes((3 + len(pair) * 2, 0x20, 0, len(pair) * 2)) + pair + pair
    assert "unique extra keys" in message_of(lambda: decode(record, twice))


def test_rejects_declared_field_names_in_the_extra_key_map() -> None:
    """rejects declared field names in the extra-key map"""
    declared = struct(id=S.String, note=Opt(S.String))
    extras = S.Record(S.String, S.Number)
    reader = S.StructWithRest(declared, extras)

    def collide(key: str) -> bytes:
        body = encode(declared, {"id": "ok"})[2:] + encode(extras, {key: 7})[2:]
        return bytes((*uvarint(len(body) + 1), 0x20)) + body

    for key in ("id", "note"):
        assert "declared field" in message_of(lambda: decode(reader, collide(key)))  # noqa: B023


def test_rejects_a_duplicate_field_id_after_an_unknown_union_decodes_as_absent() -> None:
    """rejects a duplicate field id after an unknown union decodes as absent"""
    a = struct(_tag=S.Literal("A"))
    b = struct(_tag=S.Literal("B"), value=S.String)
    writer = struct(event=Opt(S.Union(a, b)))
    reader = struct(event=Opt(S.Union(a)))
    field = encode(writer, {"event": {"_tag": "B", "value": "new"}})[2:]
    duplicate = bytes((1 + len(field) * 2, 0x20)) + field + field
    assert "unique field ids" in message_of(lambda: decode(reader, duplicate))


def test_does_not_satisfy_wide_field_presence_from_the_extra_key_map() -> None:
    """does not satisfy wide-field presence from the extra-key map"""
    fields = {f"field{i}": S.String for i in range(34)}
    extras = {f"extra{i}": f"value{i}" for i in range(34)}
    record = S.Record(S.String, S.String)
    schema = S.StructWithRest(struct_of(fields), record)
    data = encode(record, extras)
    text = message_of(lambda: S.decode_unknown_sync(B.to_codec(schema), errors="all")(data))
    assert text.count("Missing key") == 34


def test_validates_literals_instead_of_leaning_on_the_schema_pass() -> None:
    """validates literals instead of leaning on the schema pass"""
    tagged = struct(kind=S.Literal("ok"))
    loose = struct(kind=S.String)
    assert '"ok"' in message_of(lambda: decode(tagged, encode(loose, {"kind": "nope"})))
    assert '"ok"' in message_of(lambda: encode(tagged, {"kind": "nope"}))
    level = struct(kind=S.Literals("info", "warning"))
    assert decode(level, encode(loose, {"kind": "warning"})) == {"kind": "warning"}
    text = message_of(lambda: decode(level, encode(loose, {"kind": "debug"})))
    assert '"info" | "warning"' in text


def test_rejects_a_date_outside_the_representable_range() -> None:
    """rejects a Date outside the representable range"""
    data = bytearray(encode(S.DateTimeUtc, datetime.fromtimestamp(0, UTC)))
    data[-8:] = bytes((0, 0, 0, 0, 0, 0, 0, 0x7F))
    assert "valid DateTime" in message_of(lambda: decode(S.DateTimeUtc, bytes(data)))


def test_fails_never_values_and_unregistered_symbols_through_schema_error() -> None:
    """fails Never values and unregistered symbols through SchemaError"""
    schema_error(lambda: encode(S.Never, None))
    schema_error(lambda: decode(S.Never, bytes((1, 0x20))))
