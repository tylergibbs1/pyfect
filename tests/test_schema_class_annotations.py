"""A schema class field's schema comes from its annotation: ``Annotated``
carries checks, and an annotation with no schema fails where the class is
defined. String annotations (this module's ``from __future__``) are read the
same way."""

from __future__ import annotations

from typing import Annotated, NewType, TypedDict, TypeIs

import pytest

import pyfect.schema as S
from pyfect.testing import SchemaAsserts

type NonNegative = Annotated[int, S.is_greater_than_or_equal_to(0)]
Count = NewType("Count", NonNegative)


class Stock(S.Class):
    sku: str
    on_hand: Annotated[int, S.is_greater_than_or_equal_to(0)]


def test_an_annotated_check_runs_when_constructing():
    Stock(sku="a", on_hand=0)
    with pytest.raises(S.SchemaError, match="Expected a value greater than or equal to 0"):
        Stock(sku="a", on_hand=-1)


def test_an_annotated_check_runs_when_decoding():
    SchemaAsserts(Stock).decoding().fail(
        {"sku": "a", "on_hand": -1},
        'Expected a value greater than or equal to 0\n  at ["on_hand"]',
    )


class Bounded(S.Class):
    alias: Annotated[NonNegative, S.is_less_than(10)]
    new_type: Count
    several: Annotated[str, S.is_min_length(2), "not a check", S.is_max_length(3)]


def test_checks_through_aliases_and_new_types_all_run_innermost_first():
    Bounded(alias=9, new_type=Count(0), several="ab")
    for fields, message in [
        ({"alias": -1}, "greater than or equal to 0"),
        ({"alias": 10}, "less than 10"),
        ({"new_type": -1}, "greater than or equal to 0"),
        ({"several": "a"}, "length of at least 2"),
        ({"several": "abcd"}, "length of at most 3"),
    ]:
        with pytest.raises(S.SchemaError, match=message):
            S.decode_unknown_sync(Bounded)({"alias": 0, "new_type": 0, "several": "ab", **fields})


class Basket(S.Class):
    counts: list[Annotated[int, S.is_greater_than_or_equal_to(0)]]


def test_an_annotated_check_inside_a_container_runs_on_each_element():
    SchemaAsserts(Basket).decoding().fail(
        {"counts": [1, -1]}, 'Expected a value greater than or equal to 0\n  at ["counts"][1]'
    )


def test_metadata_that_is_not_a_check_is_ignored():
    class Documented(S.Class):
        n: Annotated[int, "a count"]

    assert Documented.fields()["n"] is S.Int


class Explicit(S.Class):
    n: Annotated[int, S.is_greater_than_or_equal_to(0)] = S.field(S.Int)


def test_an_explicit_field_schema_wins_over_the_annotation():
    assert Explicit(n=-1).n == -1


class Row(TypedDict):
    on_hand: NonNegative


def test_a_struct_of_a_typed_dict_reads_annotated_checks_too():
    SchemaAsserts(S.Struct(Row)).decoding().fail(
        {"on_hand": -1}, 'Expected a value greater than or equal to 0\n  at ["on_hand"]'
    )


def test_an_annotation_with_no_schema_fails_where_the_class_is_defined():
    with pytest.raises(TypeError, match=r"Unsupported\.value: No schema for the annotation"):

        class Unsupported(S.Class):  # pyright: ignore[reportUnusedClass]
            value: complex


def test_an_unsupported_annotation_inside_a_container_fails_at_definition():
    with pytest.raises(TypeError, match=r"Nested\.values: No schema for the annotation"):

        class Nested(S.TaggedError):  # pyright: ignore[reportUnusedClass]
            values: list[complex]


def _is_complex(value: object) -> TypeIs[complex]:
    return isinstance(value, complex)


def test_an_explicit_schema_needs_no_schema_for_its_annotation():
    class Custom(S.Class):
        value: complex = S.field(S.declare(_is_complex))

    assert Custom(value=1j).value == 1j


class Earlier(S.Class):
    later: Later | None = None


class Later(S.Class):
    n: Annotated[int, S.is_greater_than_or_equal_to(0)]


def test_an_annotation_naming_a_later_class_is_derived_on_first_use():
    assert S.decode_unknown_sync(Earlier)({"later": {"n": 1}}) == Earlier(later=Later(n=1))
    with pytest.raises(S.SchemaError, match="greater than or equal to 0"):
        S.decode_unknown_sync(Earlier)({"later": {"n": -1}})


class WaitsForMissing(S.Class):
    value: Missing


class Missing:
    pass


def test_a_later_name_with_no_schema_fails_on_first_use_naming_the_field():
    with pytest.raises(TypeError, match=r"WaitsForMissing\.value: No schema for the annotation"):
        WaitsForMissing.fields()
