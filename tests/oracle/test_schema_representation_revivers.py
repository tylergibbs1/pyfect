"""Ports of Effect's ``schema/representation/builtInRevivers.test.ts``.
Each test's docstring is the Effect test title. A revived check or
declaration must decode like the original, keep its representation id
and write the same JSON; Effect's extra asserts that the revived
annotations carry ``toCode`` / ``toJsonSchema`` functions do not apply
(pyfect compiles both from the representation id).

Python mappings: ``ReadonlyMap`` is ``S.Map``, ``ReadonlySet`` is
``S.FrozenSet``, ``Uint8Array`` is ``S.Bytes``, ``Error`` is
``S.ErrorInstance.schema()``; a ``Cause`` / ``Exit`` defect schema is
``S.Defect()``; dates are aware ``datetime``s; ``isPattern``'s flags are
Python's ``re`` flags (an int).

Omitted (§4 rows in docs/PARITY.md):
- No such schemas: "revives isStringSymbol" (no symbols), "revives
  HashMap", "revives HashSet", "revives Chunk" (Python's own collections),
  "revives Date" (a ``datetime`` is ``DateTimeUtc``),
  "revives File", "revives FormData", "revives URLSearchParams" (browser
  types), "revives MutableJson" (``mutable_json_reviver`` revives
  ``S.Json``: Python's JSON values are already mutable).
"""

import datetime as dt
import math
import re
from collections.abc import Sequence
from typing import Any, cast

import pytest

from pyfect import schema as S
from pyfect.exit import Failure, Success
from pyfect.schema import ast
from pyfect.schema import representation as R

EPOCH = "1970-01-01T00:00:00.000Z"


def checks_of(node: ast.AST) -> Sequence[ast.Check[Any]]:
    return node.checks or ()


def codec(schema: object) -> S.Codec[Any, Any]:
    """A revived schema, typed for decoding (Effect's ``as Schema.Codec<unknown>``)."""
    return cast("S.Codec[Any, Any]", schema)


def date(millis: int) -> dt.datetime:
    return dt.datetime.fromtimestamp(millis / 1000, dt.UTC)


def _representation(node: ast.AST | ast.Check[Any]) -> object:
    return (node.annotations or {}).get("representation")


def assert_filter_reviver(
    schema: R.AnySchema,
    id: str,
    payload: R.Json,
    reviver: R.AnyReviver,
    *,
    valid: object,
    invalid: object,
    schemas: tuple[ast.AST, ...] | None = None,
    dependencies: tuple[R.AnyReviver, ...] = (),
) -> None:
    check = checks_of(schema.ast)[-1]
    assert isinstance(check, ast.Filter)
    expected: dict[str, object] = {"id": id, "payload": payload}
    if schemas is not None:
        expected["schemas"] = schemas
    assert _representation(check) == expected
    json = R.to_json(R.to_representation(schema))
    revived = R.from_representation(R.from_json(json), revivers=(reviver, *dependencies))
    assert isinstance(S.decode_unknown_exit(codec(revived))(valid), Success)
    assert isinstance(S.decode_unknown_exit(codec(revived))(invalid), Failure)
    assert R.to_json(R.to_representation(revived)) == json
    revived_check = checks_of(revived.ast)[-1]
    assert isinstance(revived_check, ast.Filter)
    assert _representation(revived_check)["id"] == id  # pyright: ignore[reportIndexIssue]


def assert_declaration_reviver(
    schema: R.AnySchema, id: str, payload: R.Json, reviver: R.AnyReviver
) -> None:
    assert _representation(schema.ast) == {"id": id, "payload": payload}
    json = R.to_json(R.to_representation(schema))
    others = tuple(r for r in R.BUILTIN_REVIVERS if r.id != reviver.id)
    revived = R.from_representation(R.from_json(json), revivers=(reviver, *others))
    assert R.to_json(R.to_representation(revived)) == json
    assert _representation(revived.ast)["id"] == id  # pyright: ignore[reportIndexIssue]


def expect_invalid_payload(json: Any, reviver: R.AnyReviver) -> None:
    path = '["representation"]["checks"][0]["representation"]["payload"]'
    with pytest.raises(R.RepresentationError) as error:
        R.from_representation(R.from_json(json), revivers=(reviver,))
    assert str(error.value) == f"Invalid representation payload for {reviver.id}\n  at {path}"


def _check_representation(check: ast.Check[Any]) -> object:
    return _representation(check)


def test_revives_is_string_finite():
    """revives isStringFinite"""
    assert_filter_reviver(
        S.String.check(S.is_string_finite()),
        "effect/schema/isStringFinite",
        None,
        R.is_string_finite_reviver,
        valid="1.5",
        invalid="Infinity",
    )


def test_revives_is_string_big_int():
    """revives isStringBigInt"""
    assert_filter_reviver(
        S.String.check(S.is_string_big_int()),
        "effect/schema/isStringBigInt",
        None,
        R.is_string_big_int_reviver,
        valid="-10",
        invalid="1.5",
    )


def test_revives_is_min_length():
    """revives isMinLength"""
    assert_filter_reviver(
        S.String.check(S.is_min_length(1.8)),
        "effect/schema/isMinLength",
        {"minLength": 1},
        R.is_min_length_reviver,
        valid="a",
        invalid="",
    )


def test_revives_is_max_length():
    """revives isMaxLength"""
    assert_filter_reviver(
        S.String.check(S.is_max_length(3.8)),
        "effect/schema/isMaxLength",
        {"maxLength": 3},
        R.is_max_length_reviver,
        valid="abc",
        invalid="abcd",
    )


def test_revives_is_between_length():
    """revives isBetweenLength"""
    assert_filter_reviver(
        S.String.check(S.is_between_length(1.8, 3.8)),
        "effect/schema/isBetweenLength",
        {"minimum": 1, "maximum": 3},
        R.is_between_length_reviver,
        valid="ab",
        invalid="",
    )


def test_revives_is_pattern():
    """revives isPattern"""
    assert_filter_reviver(
        S.String.check(S.is_pattern(re.compile("^a+$", re.I))),
        "effect/schema/isPattern",
        {"source": "^a+$", "flags": int(re.I | re.U)},
        R.is_pattern_reviver,
        valid="AAA",
        invalid="bbb",
    )


def test_revives_is_min_code_points():
    """revives isMinCodePoints"""
    assert_filter_reviver(
        S.String.check(S.is_min_code_points(2.8)),
        "effect/schema/isMinCodePoints",
        {"minCodePoints": 2},
        R.is_min_code_points_reviver,
        valid="😀a",
        invalid="😀",
    )


def test_revives_is_max_code_points():
    """revives isMaxCodePoints"""
    assert_filter_reviver(
        S.String.check(S.is_max_code_points(1.8)),
        "effect/schema/isMaxCodePoints",
        {"maxCodePoints": 1},
        R.is_max_code_points_reviver,
        valid="😀",
        invalid="😀a",
    )


def test_revives_is_between_code_points():
    """revives isBetweenCodePoints"""
    assert_filter_reviver(
        S.String.check(S.is_between_code_points(1.8, 1.8)),
        "effect/schema/isBetweenCodePoints",
        {"minimum": 1, "maximum": 1},
        R.is_between_code_points_reviver,
        valid="😀",
        invalid="😀a",
    )


def test_revives_is_trimmed():
    """revives isTrimmed"""
    assert_filter_reviver(
        S.String.check(S.is_trimmed()),
        "effect/schema/isTrimmed",
        None,
        R.is_trimmed_reviver,
        valid="text",
        invalid=" text ",
    )


def test_revives_is_uuid():
    """revives isUUID"""
    assert_filter_reviver(
        S.String.check(S.is_uuid(4)),
        "effect/schema/isUUID",
        {"version": 4},
        R.is_uuid_reviver,
        valid="123e4567-e89b-42d3-a456-426614174000",
        invalid="123e4567-e89b-12d3-a456-426614174000",
    )


def test_revives_is_guid():
    """revives isGUID"""
    assert_filter_reviver(
        S.String.check(S.is_guid()),
        "effect/schema/isGUID",
        None,
        R.is_guid_reviver,
        valid="123e4567-e89b-12d3-a456-426614174000",
        invalid="not-a-guid",
    )


def test_revives_is_ulid():
    """revives isULID"""
    assert_filter_reviver(
        S.String.check(S.is_ulid()),
        "effect/schema/isULID",
        None,
        R.is_ulid_reviver,
        valid="01ARZ3NDEKTSV4RRFFQ69G5FAV",
        invalid="80000000000000000000000000",
    )


def test_revives_is_base64():
    """revives isBase64"""
    assert_filter_reviver(
        S.String.check(S.is_base64()),
        "effect/schema/isBase64",
        None,
        R.is_base64_reviver,
        valid="YQ==",
        invalid="?",
    )


def test_revives_is_base64_url():
    """revives isBase64Url"""
    assert_filter_reviver(
        S.String.check(S.is_base64_url()),
        "effect/schema/isBase64Url",
        None,
        R.is_base64_url_reviver,
        valid="YQ",
        invalid="?",
    )


def test_revives_is_starting_with():
    """revives isStartingWith"""
    assert_filter_reviver(
        S.String.check(S.is_starting_with("pre")),
        "effect/schema/isStartingWith",
        {"startsWith": "pre"},
        R.is_starting_with_reviver,
        valid="prefix",
        invalid="suffix",
    )


def test_revives_is_ending_with():
    """revives isEndingWith"""
    assert_filter_reviver(
        S.String.check(S.is_ending_with("end")),
        "effect/schema/isEndingWith",
        {"endsWith": "end"},
        R.is_ending_with_reviver,
        valid="weekend",
        invalid="ending",
    )


def test_revives_is_including():
    """revives isIncluding"""
    assert_filter_reviver(
        S.String.check(S.is_including("mid")),
        "effect/schema/isIncluding",
        {"includes": "mid"},
        R.is_including_reviver,
        valid="middle",
        invalid="outside",
    )


def test_revives_is_uppercased():
    """revives isUppercased"""
    assert_filter_reviver(
        S.String.check(S.is_uppercased()),
        "effect/schema/isUppercased",
        None,
        R.is_uppercased_reviver,
        valid="ABC1",
        invalid="Abc",
    )


def test_revives_is_lowercased():
    """revives isLowercased"""
    assert_filter_reviver(
        S.String.check(S.is_lowercased()),
        "effect/schema/isLowercased",
        None,
        R.is_lowercased_reviver,
        valid="abc1",
        invalid="Abc",
    )


def test_revives_is_capitalized():
    """revives isCapitalized"""
    assert_filter_reviver(
        S.String.check(S.is_capitalized()),
        "effect/schema/isCapitalized",
        None,
        R.is_capitalized_reviver,
        valid="Hello",
        invalid="hello",
    )


def test_revives_is_uncapitalized():
    """revives isUncapitalized"""
    assert_filter_reviver(
        S.String.check(S.is_uncapitalized()),
        "effect/schema/isUncapitalized",
        None,
        R.is_uncapitalized_reviver,
        valid="hello",
        invalid="Hello",
    )


def test_revives_is_finite():
    """revives isFinite"""
    assert_filter_reviver(
        S.Number.check(S.is_finite()),
        "effect/schema/isFinite",
        None,
        R.is_finite_reviver,
        valid=1,
        invalid=math.inf,
    )


def test_revives_is_int():
    """revives isInt"""
    assert_filter_reviver(
        S.Number.check(S.is_int()),
        "effect/schema/isInt",
        None,
        R.is_int_reviver,
        valid=1,
        invalid=1.5,
    )


def test_revives_is_multiple_of():
    """revives isMultipleOf"""
    assert_filter_reviver(
        S.Number.check(S.is_multiple_of(3)),
        "effect/schema/isMultipleOf",
        {"divisor": 3},
        R.is_multiple_of_reviver,
        valid=6,
        invalid=7,
    )


def test_revives_is_greater_than():
    """revives isGreaterThan"""
    assert_filter_reviver(
        S.Number.check(S.is_greater_than(1)),
        "effect/schema/isGreaterThan",
        {"exclusiveMinimum": 1},
        R.is_greater_than_reviver,
        valid=2,
        invalid=1,
    )


def test_revives_is_greater_than_or_equal_to():
    """revives isGreaterThanOrEqualTo"""
    assert_filter_reviver(
        S.Number.check(S.is_greater_than_or_equal_to(1)),
        "effect/schema/isGreaterThanOrEqualTo",
        {"minimum": 1},
        R.is_greater_than_or_equal_to_reviver,
        valid=1,
        invalid=0,
    )


def test_revives_is_less_than():
    """revives isLessThan"""
    assert_filter_reviver(
        S.Number.check(S.is_less_than(2)),
        "effect/schema/isLessThan",
        {"exclusiveMaximum": 2},
        R.is_less_than_reviver,
        valid=1,
        invalid=2,
    )


def test_revives_is_less_than_or_equal_to():
    """revives isLessThanOrEqualTo"""
    assert_filter_reviver(
        S.Number.check(S.is_less_than_or_equal_to(2)),
        "effect/schema/isLessThanOrEqualTo",
        {"maximum": 2},
        R.is_less_than_or_equal_to_reviver,
        valid=2,
        invalid=3,
    )


def test_revives_is_between():
    """revives isBetween"""
    assert_filter_reviver(
        S.Number.check(S.is_between(minimum=1, maximum=3, exclusive_minimum=True)),
        "effect/schema/isBetween",
        {"minimum": 1, "maximum": 3, "exclusiveMinimum": True},
        R.is_between_reviver,
        valid=2,
        invalid=1,
    )


def test_revives_is_greater_than_big_int():
    """revives isGreaterThanBigInt"""
    assert_filter_reviver(
        S.BigInt.check(S.is_greater_than_big_int(10)),
        "effect/schema/isGreaterThanBigInt",
        {"exclusiveMinimum": "10"},
        R.is_greater_than_big_int_reviver,
        valid=11,
        invalid=10,
    )


def test_revives_is_greater_than_or_equal_to_big_int():
    """revives isGreaterThanOrEqualToBigInt"""
    assert_filter_reviver(
        S.BigInt.check(S.is_greater_than_or_equal_to_big_int(10)),
        "effect/schema/isGreaterThanOrEqualToBigInt",
        {"minimum": "10"},
        R.is_greater_than_or_equal_to_big_int_reviver,
        valid=10,
        invalid=9,
    )


def test_revives_is_less_than_big_int():
    """revives isLessThanBigInt"""
    assert_filter_reviver(
        S.BigInt.check(S.is_less_than_big_int(10)),
        "effect/schema/isLessThanBigInt",
        {"exclusiveMaximum": "10"},
        R.is_less_than_big_int_reviver,
        valid=9,
        invalid=10,
    )


def test_revives_is_less_than_or_equal_to_big_int():
    """revives isLessThanOrEqualToBigInt"""
    assert_filter_reviver(
        S.BigInt.check(S.is_less_than_or_equal_to_big_int(10)),
        "effect/schema/isLessThanOrEqualToBigInt",
        {"maximum": "10"},
        R.is_less_than_or_equal_to_big_int_reviver,
        valid=10,
        invalid=11,
    )


def test_revives_is_between_big_int():
    """revives isBetweenBigInt"""
    assert_filter_reviver(
        S.BigInt.check(S.is_between_big_int(minimum=-10, maximum=10, exclusive_maximum=True)),
        "effect/schema/isBetweenBigInt",
        {"minimum": "-10", "maximum": "10", "exclusiveMaximum": True},
        R.is_between_big_int_reviver,
        valid=0,
        invalid=10,
    )


def test_revives_is_greater_than_date():
    """revives isGreaterThanDate"""
    assert_filter_reviver(
        S.Any.check(S.is_greater_than_date(date(0))),
        "effect/schema/isGreaterThanDate",
        {"exclusiveMinimum": EPOCH},
        R.is_greater_than_date_reviver,
        valid=date(1),
        invalid=date(0),
    )


def test_revives_is_greater_than_or_equal_to_date():
    """revives isGreaterThanOrEqualToDate"""
    assert_filter_reviver(
        S.Any.check(S.is_greater_than_or_equal_to_date(date(0))),
        "effect/schema/isGreaterThanOrEqualToDate",
        {"minimum": EPOCH},
        R.is_greater_than_or_equal_to_date_reviver,
        valid=date(0),
        invalid=date(-1),
    )


def test_revives_is_less_than_date():
    """revives isLessThanDate"""
    assert_filter_reviver(
        S.Any.check(S.is_less_than_date(date(0))),
        "effect/schema/isLessThanDate",
        {"exclusiveMaximum": EPOCH},
        R.is_less_than_date_reviver,
        valid=date(-1),
        invalid=date(0),
    )


def test_revives_is_less_than_or_equal_to_date():
    """revives isLessThanOrEqualToDate"""
    assert_filter_reviver(
        S.Any.check(S.is_less_than_or_equal_to_date(date(0))),
        "effect/schema/isLessThanOrEqualToDate",
        {"maximum": EPOCH},
        R.is_less_than_or_equal_to_date_reviver,
        valid=date(0),
        invalid=date(1),
    )


def test_revives_is_between_date():
    """revives isBetweenDate"""
    assert_filter_reviver(
        S.Any.check(S.is_between_date(minimum=date(0), maximum=date(2), exclusive_maximum=True)),
        "effect/schema/isBetweenDate",
        {"minimum": EPOCH, "maximum": "1970-01-01T00:00:00.002Z", "exclusiveMaximum": True},
        R.is_between_date_reviver,
        valid=date(1),
        invalid=date(2),
    )


def test_revives_is_min_size():
    """revives isMinSize"""
    assert_filter_reviver(
        S.Any.check(S.is_min_size(2)),
        "effect/schema/isMinSize",
        {"minSize": 2},
        R.is_min_size_reviver,
        valid={1, 2},
        invalid={1},
    )


def test_revives_is_max_size():
    """revives isMaxSize"""
    assert_filter_reviver(
        S.Any.check(S.is_max_size(1)),
        "effect/schema/isMaxSize",
        {"maxSize": 1},
        R.is_max_size_reviver,
        valid={1},
        invalid={1, 2},
    )


def test_revives_is_between_size():
    """revives isBetweenSize"""
    assert_filter_reviver(
        S.Any.check(S.is_between_size(1, 2)),
        "effect/schema/isBetweenSize",
        {"minimum": 1, "maximum": 2},
        R.is_between_size_reviver,
        valid={1},
        invalid=set[int](),
    )


def test_revives_is_unique():
    """revives isUnique"""
    assert_filter_reviver(
        S.Any.check(S.is_unique()),
        "effect/schema/isUnique",
        None,
        R.is_unique_reviver,
        valid=[1, 2],
        invalid=[1, 1],
    )


def test_revives_is_unique_key():
    """revives isUniqueKey"""
    assert_filter_reviver(
        S.Any.check(S.is_unique_key()),
        "effect/schema/isUniqueKey",
        None,
        R.is_unique_key_reviver,
        valid=[("a", 1), ("b", 1)],
        invalid=[("a", 1), ("a", 2)],
    )


def test_revives_is_min_properties():
    """revives isMinProperties"""
    assert_filter_reviver(
        S.Any.check(S.is_min_properties(2)),
        "effect/schema/isMinProperties",
        {"minProperties": 2},
        R.is_min_properties_reviver,
        valid={"a": 1, "b": 2},
        invalid={"a": 1},
    )


def test_revives_is_max_properties():
    """revives isMaxProperties"""
    assert_filter_reviver(
        S.Any.check(S.is_max_properties(1)),
        "effect/schema/isMaxProperties",
        {"maxProperties": 1},
        R.is_max_properties_reviver,
        valid={"a": 1},
        invalid={"a": 1, "b": 2},
    )


def test_revives_is_between_properties():
    """revives isBetweenProperties"""
    assert_filter_reviver(
        S.Any.check(S.is_between_properties(1, 2)),
        "effect/schema/isBetweenProperties",
        {"minimum": 1, "maximum": 2},
        R.is_between_properties_reviver,
        valid={"a": 1},
        invalid={},
    )


def test_revives_option_declaration():
    """revives Option"""
    assert_declaration_reviver(S.Option(S.String), "effect/schema/Option", None, R.option_reviver)


def test_revives_result_declaration():
    """revives Result"""
    assert_declaration_reviver(
        S.Result(S.String, S.Number), "effect/schema/Result", None, R.result_reviver
    )


def test_revives_redacted_declaration():
    """revives Redacted"""
    assert_declaration_reviver(
        S.Redacted(S.String), "effect/schema/Redacted", None, R.redacted_reviver
    )


def test_revives_cause_reason_declaration():
    """revives CauseReason"""
    assert_declaration_reviver(
        S.CauseReason(S.String, S.Defect()),
        "effect/schema/CauseReason",
        None,
        R.cause_reason_reviver,
    )


def test_revives_cause_declaration():
    """revives Cause"""
    assert_declaration_reviver(
        S.Cause(S.String, S.Defect()), "effect/schema/Cause", None, R.cause_reviver
    )


def test_revives_error_declaration():
    """revives Error"""
    assert_declaration_reviver(
        S.ErrorInstance.schema(), "effect/schema/Error", None, R.error_instance_reviver
    )


def test_revives_exit_declaration():
    """revives Exit"""
    assert_declaration_reviver(
        S.Exit(S.String, S.Number, S.Defect()), "effect/schema/Exit", None, R.exit_reviver
    )


def test_revives_readonly_map_declaration():
    """revives ReadonlyMap"""
    assert_declaration_reviver(
        S.Map(S.String, S.Number), "effect/schema/ReadonlyMap", None, R.map_reviver
    )


def test_revives_graph_declaration():
    """revives Graph"""
    assert_declaration_reviver(
        S.Graph("directed", S.String, S.Number), "effect/schema/Graph", "directed", R.graph_reviver
    )


def test_revives_readonly_set_declaration():
    """revives ReadonlySet"""
    assert_declaration_reviver(
        S.FrozenSet(S.String), "effect/schema/ReadonlySet", None, R.frozen_set_reviver
    )


def test_revives_reg_exp_declaration():
    """revives RegExp"""
    assert_declaration_reviver(S.RegExp, "effect/schema/RegExp", None, R.reg_exp_reviver)


def test_revives_url_declaration():
    """revives URL"""
    assert_declaration_reviver(S.URL, "effect/schema/URL", None, R.url_reviver)


def test_revives_duration_declaration():
    """revives Duration"""
    assert_declaration_reviver(S.Duration, "effect/schema/Duration", None, R.duration_reviver)


def test_revives_byte_size_declaration():
    """revives ByteSize"""
    assert_declaration_reviver(S.ByteSize, "effect/schema/ByteSize", None, R.byte_size_reviver)


def test_revives_big_decimal_declaration():
    """revives BigDecimal"""
    assert_declaration_reviver(
        S.BigDecimal, "effect/schema/BigDecimal", None, R.big_decimal_reviver
    )


def test_revives_sem_ver_declaration():
    """revives SemVer"""
    assert_declaration_reviver(S.SemVer, "effect/schema/SemVer", None, R.sem_ver_reviver)


def test_revives_sem_ver_range_declaration():
    """revives SemVerRange"""
    assert_declaration_reviver(
        S.SemVerRange, "effect/schema/SemVerRange", None, R.sem_ver_range_reviver
    )


def test_revives_uint8_array_declaration():
    """revives Uint8Array"""
    assert_declaration_reviver(S.Bytes, "effect/schema/Uint8Array", None, R.bytes_reviver)


def test_revives_date_time_utc_declaration():
    """revives DateTimeUtc"""
    assert_declaration_reviver(
        S.DateTimeUtc, "effect/schema/DateTimeUtc", None, R.date_time_utc_reviver
    )


def test_revives_time_zone_offset_declaration():
    """revives TimeZoneOffset"""
    assert_declaration_reviver(
        S.TimeZoneOffset, "effect/schema/TimeZoneOffset", None, R.time_zone_offset_reviver
    )


def test_revives_time_zone_named_declaration():
    """revives TimeZoneNamed"""
    assert_declaration_reviver(
        S.TimeZoneNamed, "effect/schema/TimeZoneNamed", None, R.time_zone_named_reviver
    )


def test_revives_time_zone_declaration():
    """revives TimeZone"""
    assert_declaration_reviver(S.TimeZone, "effect/schema/TimeZone", None, R.time_zone_reviver)


def test_revives_date_time_zoned_declaration():
    """revives DateTimeZoned"""
    assert_declaration_reviver(
        S.DateTimeZoned, "effect/schema/DateTimeZoned", None, R.date_time_zoned_reviver
    )


def test_revives_json_declaration():
    """revives Json"""
    assert_declaration_reviver(S.Json, "effect/schema/Json", None, R.json_reviver)


def test_normalizes_is_between_flags():
    """normalizes isBetween flags"""
    check = S.is_between(minimum=1, maximum=3, exclusive_minimum=False, exclusive_maximum=True)
    assert _check_representation(check) == {
        "id": "effect/schema/isBetween",
        "payload": {"minimum": 1, "maximum": 3, "exclusiveMaximum": True},
    }


def test_rejects_a_non_numeric_is_multiple_of_payload():
    """rejects a non-numeric isMultipleOf payload"""
    json: Any = R.to_json(R.to_representation(S.Number.check(S.is_multiple_of(2))))
    json["representation"]["checks"][0]["representation"]["payload"]["divisor"] = "2"
    expect_invalid_payload(json, R.is_multiple_of_reviver)


def test_rejects_a_non_canonical_is_between_payload():
    """rejects a non-canonical isBetween payload"""
    json: Any = R.to_json(R.to_representation(S.Number.check(S.is_between(minimum=1, maximum=3))))
    json["representation"]["checks"][0]["representation"]["payload"]["exclusiveMinimum"] = False
    expect_invalid_payload(json, R.is_between_reviver)


def test_persists_large_bounds_as_canonical_decimal_strings():
    """persists large bounds as canonical decimal strings"""
    value = 900719925474099312345678901234567890
    assert _check_representation(S.is_greater_than_big_int(value)) == {
        "id": "effect/schema/isGreaterThanBigInt",
        "payload": {"exclusiveMinimum": "900719925474099312345678901234567890"},
    }


def test_normalizes_is_between_big_int_flags():
    """normalizes isBetweenBigInt flags"""
    check = S.is_between_big_int(
        minimum=-1, maximum=1, exclusive_minimum=False, exclusive_maximum=True
    )
    assert _check_representation(check) == {
        "id": "effect/schema/isBetweenBigInt",
        "payload": {"minimum": "-1", "maximum": "1", "exclusiveMaximum": True},
    }


def test_persists_millisecond_precision():
    """persists millisecond precision"""
    assert _check_representation(S.is_greater_than_date(date(123))) == {
        "id": "effect/schema/isGreaterThanDate",
        "payload": {"exclusiveMinimum": "1970-01-01T00:00:00.123Z"},
    }


def test_normalizes_is_between_date_flags():
    """normalizes isBetweenDate flags"""
    check = S.is_between_date(
        minimum=date(-1), maximum=date(1), exclusive_minimum=False, exclusive_maximum=True
    )
    assert _check_representation(check) == {
        "id": "effect/schema/isBetweenDate",
        "payload": {
            "minimum": "1969-12-31T23:59:59.999Z",
            "maximum": "1970-01-01T00:00:00.001Z",
            "exclusiveMaximum": True,
        },
    }


@pytest.mark.parametrize(
    ("check", "id", "payload"),
    [
        (S.is_min_size(-1), "isMinSize", {"minSize": 0}),
        (S.is_max_size(2.9), "isMaxSize", {"maxSize": 2}),
        (S.is_between_size(1.9, 3.7), "isBetweenSize", {"minimum": 1, "maximum": 3}),
        (S.is_min_properties(-1), "isMinProperties", {"minProperties": 0}),
        (S.is_max_properties(2.9), "isMaxProperties", {"maxProperties": 2}),
        (S.is_between_properties(1.9, 3.7), "isBetweenProperties", {"minimum": 1, "maximum": 3}),
    ],
    ids=[
        "normalizes isMinSize",
        "normalizes isMaxSize",
        "normalizes isBetweenSize",
        "normalizes isMinProperties",
        "normalizes isMaxProperties",
        "normalizes isBetweenProperties",
    ],
)
def test_normalizes_cardinality(check: ast.Check[Any], id: str, payload: R.Json):
    """normalizes isMinSize / isMaxSize / isBetweenSize / isMinProperties / isMaxProperties / isBetweenProperties"""  # noqa: E501
    assert _check_representation(check) == {"id": f"effect/schema/{id}", "payload": payload}


def test_rejects_a_non_finite_cardinality():
    """normalizeCardinality: a non-finite bound is a RangeError in Effect"""
    with pytest.raises(ValueError, match="Expected a finite number, got nan"):
        S.is_min_length(math.nan)


def _names() -> R.AnySchema:
    return S.String.check(S.is_pattern(re.compile("^[A-Z]")))


def test_revives_is_property_names():
    """revives isPropertyNames"""
    names = _names()
    assert_filter_reviver(
        S.Any.check(S.is_property_names(names)),
        "effect/schema/isPropertyNames",
        None,
        R.is_property_names_reviver,
        valid={"Alpha": 1},
        invalid={"alpha": 1},
        schemas=(names.ast,),
        dependencies=(R.is_pattern_reviver,),
    )


def test_persists_the_encoded_key_schema_for_is_property_names():
    """persists the encoded key schema for isPropertyNames"""
    names = _names()
    assert _check_representation(S.is_property_names(names)) == {
        "id": "effect/schema/isPropertyNames",
        "payload": None,
        "schemas": (names.ast,),
    }


def test_persists_error_include_stack():
    """persists Error includeStack"""
    assert _representation(S.ErrorInstance.schema(include_stack=True).ast) == {
        "id": "effect/schema/Error",
        "payload": {"includeStack": True},
    }


def test_persists_error_exclude_cause():
    """persists Error excludeCause"""
    assert _representation(S.ErrorInstance.schema(exclude_cause=True).ast) == {
        "id": "effect/schema/Error",
        "payload": {"excludeCause": True},
    }


def test_omits_disabled_error_options():
    """omits disabled Error options"""
    schema = S.ErrorInstance.schema(include_stack=False, exclude_cause=False)
    assert _representation(schema.ast) == {"id": "effect/schema/Error", "payload": None}


def test_persists_a_redacted_label():
    """persists a Redacted label"""
    assert _representation(S.Redacted(S.String, label="password").ast) == {
        "id": "effect/schema/Redacted",
        "payload": {"label": "password"},
    }


def test_persists_redacted_disallow_json_encode():
    """persists Redacted disallowJsonEncode"""
    assert _representation(S.Redacted(S.String, disallow_json_encode=True).ast) == {
        "id": "effect/schema/Redacted",
        "payload": {"disallowJsonEncode": True},
    }


def test_omits_disabled_redacted_options():
    """omits disabled Redacted options"""
    schema = S.Redacted(S.String, label=None, disallow_json_encode=False)
    assert _representation(schema.ast) == {
        "id": "effect/schema/Redacted",
        "payload": None,
    }


def test_revives_a_redacted_label_and_error_options():
    """Python: payload-carrying declarations revive with their options"""
    for schema in (
        S.Redacted(S.String, label="password"),
        S.ErrorInstance.schema(include_stack=True, exclude_cause=True),
    ):
        json = R.to_json(R.to_representation(schema))
        revived = R.from_representation(R.from_json(json), revivers=R.BUILTIN_REVIVERS)
        assert R.to_json(R.to_representation(revived)) == json
