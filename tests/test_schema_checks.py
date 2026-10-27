"""Checks, literals, enums and unions at the schema boundary, on Python's own
values. Messages were printed by Effect's ``Schema`` under Node where Effect
has the same case."""

import enum
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Literal, Never, NewType, TypeIs

import pytest

from pyfect import schema as S
from pyfect.brand import Brand, BrandError
from pyfect.cause import Die
from pyfect.exit import Failure
from pyfect.testing import SchemaAsserts

type AnyCodec = S.Codec[object, object, Never, Never]
type Dict = Mapping[str, int]
Record = S.Bottom[Dict](S.ast.unknown)
"""A stand-in for ``Record`` (not ported yet): any value, typed as a mapping."""
Items = S.Bottom[list[object]](S.ast.unknown)


# ------------------------------------------------------------- literals


@pytest.mark.parametrize(
    ("literal", "accepted", "rejected"),
    [
        (1, [1], [True, 1.0, "1"]),
        (1.5, [1.5], [True, "1.5"]),
        (2.0, [2.0], [2, True]),
        (True, [True], [1, 1.0]),
        (None, [None], [0, "", False]),
        ("a", ["a"], [b"a"]),
    ],
)
def test_a_literal_matches_values_of_its_own_kind(
    literal: S.LiteralValue, accepted: list[object], rejected: list[object]
):
    guard = S.is_(S.Literal(literal))
    assert [guard(v) for v in accepted] == [True] * len(accepted)
    assert [guard(v) for v in rejected] == [False] * len(rejected)


@pytest.mark.parametrize(
    ("schema", "input", "expected"),
    [
        (S.Literals("a", 1, True), "x", 'Expected "a" | 1 | true, got "x"'),
        (S.Literal(1e21), 2, "Expected 1e+21, got 2"),
        (S.Literal(-0.0), 2, "Expected 0, got 2"),
        (S.Literal(None), 2, "Expected null, got 2"),
        (S.Literal("a").annotate(message="M"), "x", "M"),
        (S.Literals("a", "b").annotate(identifier="AB"), "x", 'Expected AB, got "x"'),
    ],
)
def test_literal_messages(schema: AnyCodec, input: object, expected: str):
    SchemaAsserts(schema).decoding(report_input=True).fail(input, expected)


def test_literals_members_and_map_members():
    schema = S.Literals("a", "b")
    assert [m.literal for m in schema.members] == ["a", "b"]
    mapped = schema.map_members(lambda ms: [m.check(S.is_min_length(2)) for m in ms])
    SchemaAsserts(mapped).decoding().fail("a", "Expected a value with a length of at least 2")


# ---------------------------------------------------------------- enums


class Color(enum.Enum):
    RED = "red"
    ONE = 1


def test_an_enum_encodes_members_after_checking_them():
    is_red: S.Filter[Color] = S.make_filter(lambda c: c is Color.RED, expected="red")
    asserts = SchemaAsserts(S.Enum(Color).check(is_red))
    asserts.decoding().succeed("red", Color.RED)
    asserts.decoding().fail(1, "Expected red")
    asserts.encoding().succeed(Color.RED, "red")
    asserts.encoding().fail(Color.ONE, "Expected red")
    asserts.encoding(report_input=True).fail("red", 'Expected Color, got "red"')


def test_an_enum_value_must_be_a_string_or_a_number():
    with pytest.raises(TypeError, match="must be a string or a number"):
        S.Enum(enum.Enum("E", {"A": True}))
    with pytest.raises(TypeError, match="must be a string or a number"):
        S.Enum(enum.Enum("E", {"A": (1, 2)}))


def test_an_enum_in_a_union_takes_its_values():
    decoding = SchemaAsserts(S.Union(S.Enum(Color), S.Boolean)).decoding()
    decoding.succeed(1, Color.ONE)
    decoding.succeed(True)
    decoding.fail(None, 'Expected "red" | 1 | boolean')


# --------------------------------------------------------------- unions


def test_a_python_int_is_a_number_and_a_bigint():
    decoding = SchemaAsserts(S.Union(S.BigInt, S.String)).decoding()
    decoding.succeed(10**30)
    decoding.fail(1.5, "Expected bigint | string")


def test_one_of_reports_the_input_under_report_input():
    schema = S.Union(S.String, S.String, mode="one_of")
    SchemaAsserts(schema).decoding(report_input=True).fail(
        "a", 'Expected exactly one member to match the input "a"'
    )


def test_a_union_reports_every_failing_candidate():
    schema = S.Union(S.String.check(S.is_min_length(2)), S.String.check(S.is_max_length(0)))
    SchemaAsserts(schema).decoding().fail(
        "a",
        "Expected a value with a length of at least 2\nExpected a value with a length of at most 0",
    )


def test_a_check_on_a_union_runs_after_a_member_matches():
    schema = S.Union(S.String, S.Number).check(S.make_filter(lambda _: False))
    SchemaAsserts(schema).decoding().fail("x", "Expected <filter>")


def test_union_map_members_drops_checks_unless_asked_to_keep_them():
    schema = S.Union(S.String, mode="one_of").check(S.make_filter(lambda _: False))
    widened = schema.map_members(lambda members: (*members, S.Number))
    SchemaAsserts(widened).decoding().succeed(1)
    kept = schema.map_members(lambda members: (*members, S.Number), unsafe_preserve_checks=True)
    SchemaAsserts(kept).decoding().fail(1, "Expected <filter>")


# ---------------------------------------------------------- annotations


@pytest.mark.parametrize(
    ("schema", "input", "expected"),
    [
        (S.String.check(S.is_min_length(1)).annotate(message="custom"), 1, "Expected string"),
        (S.String.check(S.is_min_length(1)).annotate(message="custom"), "", "custom"),
        (S.String.check(S.is_min_length(2)).annotate(identifier="X"), 1, "Expected X"),
        (S.String.annotate(identifier="X").check(S.is_min_length(2)), 1, "Expected string"),
        (
            S.String.check(S.is_min_length(2)).annotate(identifier="X"),
            "a",
            "Expected a value with a length of at least 2",
        ),
    ],
)
def test_annotate_after_a_check_annotates_the_check(schema: AnyCodec, input: object, expected: str):
    SchemaAsserts(schema).decoding().fail(input, expected)


# ---------------------------------------------------------------- filters


FILTER_OUTPUTS: list[tuple[S.Check[str], str | None]] = [
    (S.make_filter(lambda _: False), 'Expected <filter>, got "a"'),
    (S.make_filter(lambda _: "msg"), "msg"),
    (S.make_filter(lambda _: ["x", "y"]), "x\ny"),
    (S.make_filter(lambda _: []), None),
    (S.make_filter(lambda _: (("k",), "bad")), 'bad\n  at ["k"]'),
    (S.make_filter(lambda _: False, expected="good"), 'Expected good, got "a"'),
]


@pytest.mark.parametrize(("check", "expected"), FILTER_OUTPUTS)
def test_filter_outputs(check: S.Check[str], expected: str | None):
    decoding = SchemaAsserts(S.String.check(check)).decoding(report_input=True)
    if expected is None:
        decoding.succeed("a")
    else:
        decoding.fail("a", expected)


def test_groups_report_their_members():
    group = S.make_filter_group(S.is_min_length(2), S.is_max_length(0), expected="ignored")
    asserts = SchemaAsserts(S.String.check(group))
    asserts.decoding().fail("a", "Expected a value with a length of at least 2")
    asserts.decoding(errors="all").fail(
        "a",
        "Expected a value with a length of at least 2\nExpected a value with a length of at most 0",
    )
    paired = S.is_min_length(2).and_(S.is_max_length(0))
    SchemaAsserts(S.String.check(paired)).decoding(errors="all").fail(
        "a",
        "Expected a value with a length of at least 2\nExpected a value with a length of at most 0",
    )


def test_an_aborted_check_in_a_group_stops_the_checks_after_the_group():
    reject: S.Filter[str] = S.make_filter(lambda _: False)
    inside: S.Filter[str] = S.make_filter(lambda _: "inside")
    group = S.make_filter_group(reject.abort(), inside)
    schema = S.String.check(group, S.make_filter(lambda _: "after"))
    SchemaAsserts(schema).decoding(errors="all").fail("a", "Expected <filter>")


@pytest.mark.parametrize(
    ("check", "valid"),
    [
        (S.is_uuid(), "00000000-0000-0000-0000-000000000000"),
        (S.is_guid(), "123e4567-e89b-12d3-a456-426614174000"),
        (S.is_ulid(), "01ARZ3NDEKTSV4RRFFQ69G5FAV"),
        (S.is_string_finite(), "1e5"),
        (S.is_string_big_int(), "12"),
    ],
)
def test_built_in_patterns_reject_a_trailing_newline(check: S.Check[str], valid: str):
    # JavaScript's ``$`` ends the string; Python's also matches before a final "\n".
    is_valid = S.is_(S.String.check(check))
    assert is_valid(valid)
    assert not is_valid(valid + "\n")


def test_an_outer_check_message_wins_over_a_nested_one():
    inner: S.Filter[str] = S.make_filter(lambda _: False, message="inner")

    def nested(_: str) -> S.issue.Issue:
        return S.issue.Filter(inner, S.issue.InvalidValue())

    asserts = SchemaAsserts(S.String.check(S.make_filter(nested, message="outer")))
    asserts.decoding().fail("a", "outer")
    SchemaAsserts(S.String.check(S.make_filter(nested))).decoding().fail("a", "inner")


def test_disable_checks_skips_them():
    SchemaAsserts(S.String.check(S.is_min_length(2))).decoding(disable_checks=True).succeed("a")


def test_a_check_that_raises_is_a_defect():
    def boom(_: str) -> bool:
        raise ZeroDivisionError

    exit = S.decode_unknown_exit(S.String.check(S.make_filter(boom)))("a")
    assert isinstance(exit, Failure)
    assert isinstance(exit.cause.reasons[0], Die)


def is_short(s: str) -> TypeIs[Literal["a"]]:
    return s == "a"


def test_refine_narrows_and_aborts():
    schema = S.String.pipe(S.refine(is_short, expected="a")).check(S.is_min_length(2))
    asserts = SchemaAsserts(schema)
    asserts.decoding(errors="all").fail("b", "Expected a")
    asserts.decoding().fail("a", "Expected a value with a length of at least 2")


def test_from_brand_runs_every_check_of_the_brand():
    Small = NewType("Small", float)
    small = Brand[float, Small].check(S.is_greater_than(0), S.is_less_than(10))
    asserts = SchemaAsserts(S.Number.pipe(S.from_brand(small)))
    asserts.decoding().succeed(5)
    asserts.decoding(errors="all").fail(
        float("nan"), "Expected a value greater than 0\nExpected a value less than 10"
    )


def test_a_brand_error_formats_its_issue():
    Small = NewType("Small", float)
    small = Brand[float, Small].check(S.is_greater_than(0), S.is_less_than(10))
    with pytest.raises(BrandError) as raised:
        small(float("nan"))
    assert str(raised.value) == "Expected a value greater than 0\nExpected a value less than 10"


# ------------------------------------------------------ number / dates


@pytest.mark.parametrize(
    ("check", "accepted", "rejected", "message"),
    [
        (S.is_multiple_of(0.1), [0.3, 0.7], 0.35, "Expected a value that is a multiple of 0.1"),
        (S.is_multiple_of(1.5), [4.5], 4, "Expected a value that is a multiple of 1.5"),
        (S.is_multiple_of(2), [1e300], float("nan"), "Expected a value that is a multiple of 2"),
        (S.is_greater_than(1e-7), [1], 0, "Expected a value greater than 1e-7"),
        (S.is_finite(), [1.5], float("inf"), "Expected a finite number"),
        (
            S.is_uint32(),
            [0, 4294967295],
            -1,
            "Expected a value between 0 and 4294967295",
        ),
    ],
)
def test_number_checks(check: S.Check[float], accepted: list[float], rejected: float, message: str):
    decoding = SchemaAsserts(S.Number.check(check)).decoding()
    for value in accepted:
        decoding.succeed(value)
    decoding.fail(rejected, message)


def test_bounds_must_be_finite():
    with pytest.raises(ValueError, match=r"^Expected a finite number, got Infinity$"):
        S.is_greater_than(float("inf"))


@pytest.mark.parametrize(
    ("schema", "accepted", "rejected", "message"),
    [
        (S.Int, [0, -3, 10**30], 1.0, "Expected an integer"),
        (S.Int, [], True, "Expected number"),
        (S.Port, [0, 65535], 65536, "Expected a port number"),
        (S.Char, ["a", "😀"], "ab", "Expected a value with a length of 1"),
        (S.NonEmptyString, ["a"], "", "Expected a value with a length of at least 1"),
        (S.Finite, [1.5], float("nan"), "Expected a finite number"),
    ],
)
def test_refined_primitives(
    schema: AnyCodec, accepted: list[object], rejected: object, message: str
):
    decoding = SchemaAsserts(schema).decoding()
    for value in accepted:
        decoding.succeed(value)
    decoding.fail(rejected, message)


def test_big_int_checks_print_n():
    schema = S.BigInt.check(S.is_between_big_int(minimum=5, maximum=7, exclusive_maximum=True))
    SchemaAsserts(schema).decoding().fail(1, "Expected a value between 5n and 7n (excluded)")


def test_date_checks_print_iso_dates():
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    schema = S.Bottom[datetime](S.ast.unknown).check(S.is_greater_than_date(epoch))
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed(epoch + timedelta(milliseconds=1))
    decoding.fail(
        epoch - timedelta(milliseconds=1), "Expected a value greater than 1970-01-01T00:00:00.000Z"
    )


# ------------------------------------------------------- sizes and keys


PROPERTY_CHECKS: list[tuple[S.Check[Dict], list[Dict], Dict, str]] = [
    (S.is_min_properties(1), [{"a": 1}], {}, "Expected a value with at least 1 entry"),
    (S.is_max_properties(1), [{}], {"a": 1, "b": 2}, "Expected a value with at most 1 entry"),
    (
        S.is_between_properties(2, 2),
        [{"a": 1, "b": 2}],
        {"a": 1},
        "Expected a value with exactly 2 entries",
    ),
]


@pytest.mark.parametrize(("check", "accepted", "rejected", "message"), PROPERTY_CHECKS)
def test_property_count_checks(
    check: S.Check[Dict], accepted: list[Dict], rejected: Dict, message: str
):
    decoding = SchemaAsserts(Record.check(check)).decoding()
    for value in accepted:
        decoding.succeed(value)
    decoding.fail(rejected, message)


def test_is_property_names_reports_each_bad_key_at_its_path():
    keys = S.is_property_names(S.String.check(S.is_pattern("^[A-Z]")))
    asserts = SchemaAsserts(Record.check(keys))
    asserts.decoding().succeed({"Ab": 1})
    asserts.decoding().fail({"ab": 1}, 'Expected a string matching the RegExp ^[A-Z]\n  at ["ab"]')
    asserts.decoding(errors="all").fail(
        {"ab": 1, "cd": 2},
        'Expected a string matching the RegExp ^[A-Z]\n  at ["ab"]\n'
        'Expected a string matching the RegExp ^[A-Z]\n  at ["cd"]',
    )


def test_is_unique_compares_with_equality():
    decoding = SchemaAsserts(Items.check(S.is_unique())).decoding()
    decoding.succeed([1, "1", [1]])
    decoding.fail([{"a": 1}, {"a": 1}], "Expected an array with unique items")


def test_is_min_size_checks_any_sized_value():
    decoding = SchemaAsserts(Items.check(S.is_min_size(2))).decoding()
    decoding.succeed([1, 2])
    decoding.fail([1], "Expected a value with a size of at least 2")
