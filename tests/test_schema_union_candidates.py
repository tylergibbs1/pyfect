"""Which union members an input selects (Effect's candidate index) and how a
union names its members when none takes the input."""

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any, Literal, NotRequired, TypedDict, cast

import pyfect as fx
from pyfect import schema as S
from pyfect.option import Some
from pyfect.schema import ast
from pyfect.schema.issue import Issue
from pyfect.testing import SchemaAsserts


def _recover[T](value: T) -> Callable[[Issue], fx.Effect[Some[T], Issue]]:
    return lambda _: fx.succeed(Some(value))


class _A(TypedDict):
    _tag: Literal["A"]
    a: float


class _B(TypedDict):
    _tag: Literal["B"]
    b: float


class _X(TypedDict):
    x: float


class _Y(TypedDict):
    y: float


class _Pair(TypedDict):
    first: Literal["x"]
    second: Literal["y"]


class _KindA(TypedDict):
    kind: Literal["a"]


class _KindB(TypedDict):
    kind: Literal["b"]


class _Kind(TypedDict):
    kind: str


class _MaybeTagged(TypedDict):
    _tag: NotRequired[Literal["A"]]
    a: float


# ------------------------------------------------------------ selection


def test_a_never_member_does_not_stop_the_members_after_it():
    schema = S.Union(S.Never, S.TaggedStruct(_A), S.TaggedStruct(_B))
    SchemaAsserts(schema).decoding().succeed({"_tag": "B", "b": 1.0})


def test_a_member_is_selected_by_any_sentinel_the_input_holds():
    # The first literal key is missing (neutral), the second one matches: the
    # member is tried and reports the missing key.
    SchemaAsserts(S.Union(S.Struct(_Pair))).decoding().fail(
        {"second": "y"}, 'Missing key\n  at ["first"]'
    )


def test_a_nested_union_of_booleans_takes_a_boolean():
    schema = S.Union(S.Union(S.Literal(True), S.Literal(False)), S.String)
    decoding = SchemaAsserts(schema).decoding()
    decoding.succeed(True)
    decoding.succeed(False)


def test_an_object_with_attributes_selects_the_struct_members_by_kind():
    @dataclass
    class Point:
        x: float

    schema = S.Union(S.TaggedStruct(_A), S.Struct(_X))
    SchemaAsserts(schema).decoding().succeed(Point(1.0), {"x": 1.0})


def test_a_function_is_no_candidate_of_a_struct_member():
    def f() -> None: ...

    # No member is tried: one ``Expected`` for the union, not one per member.
    schema = S.Union(S.Struct(_X), S.Struct(_Y))
    SchemaAsserts(schema).decoding().fail(f, "Expected object")


def test_a_recovering_tuple_element_holds_no_sentinel():
    tagged = S.Tuple(S.Literal("a").pipe(S.catch_decoding(_recover("a"))), S.Number)
    schema = S.Union(tagged, S.Tuple(S.Literal("b"), S.String))
    SchemaAsserts(schema).decoding().succeed(["c", 1.0], ("a", 1.0))


def test_a_recovering_key_of_a_transformed_member_holds_no_sentinel():
    source = S.Struct(_KindA, kind=S.Literal("a").pipe(S.catch_decoding(_recover("a"))))
    schema = S.Union(source.pipe(S.decode_to(S.Struct(_Kind))), S.Struct(_KindB))
    SchemaAsserts(schema).decoding().succeed({"kind": "c"}, {"kind": "a"})


def test_a_class_is_no_candidate_for_a_string():
    class Point(S.Class):
        x: float

    # Only the number member is tried: one ``Expected`` for the union.
    SchemaAsserts(S.Union(Point, S.Number)).decoding().fail("s", "Expected object | number")


def test_a_constructed_one_of_union_selects_members_missing_their_tag():
    schema = S.Union(S.TaggedStruct(_A), S.TaggedStruct(_B), mode="one_of")
    # The tag is left out: the constructor fills it in.
    assert S.make(schema)(cast("_A", {"a": 1.0})) == {"_tag": "A", "a": 1.0}


def test_a_suspended_case_of_a_tagged_union_keeps_its_tag():
    tagged = S.Union(S.Struct(_A), S.suspend(lambda: S.Struct(_B))).pipe(S.to_tagged_union("_tag"))
    assert list(tagged.cases) == ["A", "B"]


# ------------------------------------------------------------- messages


def _union_expects(schema: S.Codec[Any, Any], expected: str) -> None:
    union: S.Codec[Any, Any] = S.Union(schema, S.Number)
    SchemaAsserts(union).decoding().fail("s", f"Expected {expected} | number")


def test_a_union_names_a_member_by_its_literal_parts():
    _union_expects(S.Struct(_MaybeTagged), '{ readonly "_tag"?: "A", ... }')
    _union_expects(S.Tuple(S.Literal("a"), S.Literal("b")), 'readonly [ "a", "b", ... ]')
    _union_expects(
        S.Tuple(S.Literal("a"), S.optional_key(S.Literal("b"))), 'readonly [ "a", "b"?, ... ]'
    )
    number_key: S.Codec[Any, Any] = S.Bottom(
        ast.Objects((ast.PropertySignature(1, ast.Literal("a")),))
    )
    _union_expects(number_key, '{ readonly 1: "a", ... }')
    mutable: S.Codec[Any, Any] = S.Bottom(
        ast.Arrays((ast.Element(ast.Literal("a")),), mutable=True)
    )
    _union_expects(mutable, '[ "a", ... ]')


def test_a_union_names_tagged_classes_by_their_tags():
    class Circle(S.TaggedClass):
        radius: float

    class Square(S.TaggedClass):
        side: float

    SchemaAsserts(S.Union(Circle, Square)).decoding().fail(
        "s", 'Expected { readonly "_tag": "Circle", ... } | { readonly "_tag": "Square", ... }'
    )


def test_a_union_takes_its_expected_annotation():
    schema = S.Union(S.String, S.Number).annotate(expected="a string or a number")
    SchemaAsserts(schema).decoding().fail(None, "Expected a string or a number")


def test_a_one_of_union_reports_the_input_no_member_takes():
    schema = S.Union(S.String, S.Number, mode="one_of")
    SchemaAsserts(schema).decoding(report_input=True).fail(
        True, "Expected string | number, got true"
    )


def test_a_flipped_union_checks_the_values_it_encodes_from():
    # Encoding a flipped union decodes: its checks see the decoded numbers.
    schema = S.Union(S.NumberFromString, S.Boolean).check(
        S.make_filter(lambda value: value != 3, expected="not 3")
    )
    SchemaAsserts(S.flip(schema)).encoding().fail("3", "Expected not 3")
