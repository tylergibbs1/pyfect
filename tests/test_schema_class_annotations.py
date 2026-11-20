"""A schema class field's schema comes from its annotation: ``Annotated``
carries checks and may carry the schema itself, and an annotation with no
schema fails on first use, naming the field. String annotations (this
module's ``from __future__``) are read the same way."""

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


class Unsupported(S.Class):
    value: complex


class Nested(S.TaggedError):
    values: list[complex]


def test_an_annotation_with_no_schema_fails_on_first_use_naming_the_field():
    with pytest.raises(TypeError, match=r"Unsupported\.value: No schema for the annotation"):
        Unsupported(value=1j)


def test_an_unsupported_annotation_inside_a_container_names_the_field():
    with pytest.raises(TypeError, match=r"Nested\.values: No schema for the annotation"):
        S.decode_unknown_sync(Nested)({"values": []})


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


class Order(S.Class):
    amount: Annotated[int, S.Int.check(S.is_greater_than(0))]


def test_a_schema_in_annotated_metadata_is_the_fields_schema():
    assert Order(amount=1).amount == 1
    with pytest.raises(S.SchemaError, match="Expected a value greater than 0"):
        Order(amount=-1)
    SchemaAsserts(Order).decoding().fail(
        {"amount": -1}, 'Expected a value greater than 0\n  at ["amount"]'
    )


class Receipt(S.Class):
    total: Annotated[float, S.FiniteFromString]


def test_an_annotated_codec_decodes_and_encodes_the_field():
    assert S.decode_unknown_sync(Receipt)({"total": "1.5"}) == Receipt(total=1.5)
    assert S.encode_sync(Receipt)(Receipt(total=1.5)) == {"total": "1.5"}
    SchemaAsserts(Receipt).decoding().fail({"total": 1.5}, 'Expected string\n  at ["total"]')


def test_checks_beside_an_annotated_schema_refine_it():
    class Small(S.Class):
        n: Annotated[int, S.is_less_than(10), S.Int.check(S.is_greater_than(0)), "a count"]

    Small(n=5)
    for n, message in [(0, "greater than 0"), (10, "less than 10")]:
        with pytest.raises(S.SchemaError, match=message):
            Small(n=n)


def test_the_annotated_schema_wins_over_the_annotations_own():
    class Named(S.Class):
        name: Annotated[str, S.NonEmptyString]
        value: Annotated[complex, S.declare(_is_complex)]

    assert Named.fields()["name"] is S.NonEmptyString
    assert Named(name="a", value=1j).value == 1j
    with pytest.raises(S.SchemaError):
        Named(name="", value=1j)


NEGATIVE = S.Int.check(S.is_less_than(0))


def test_the_last_of_several_annotated_schemas_wins():
    class Twice(S.Class):
        n: Annotated[int, S.Int.check(S.is_greater_than(100)), NEGATIVE]

    assert Twice.fields()["n"] is NEGATIVE


def test_an_explicit_field_schema_wins_over_an_annotated_schema():
    class Both(S.Class):
        n: Annotated[int, S.Int.check(S.is_greater_than(0))] = S.field(S.Int)

    assert Both(n=-1).n == -1


def test_a_schema_class_in_annotated_metadata_is_its_schema():
    class Holder(S.Class):
        stock: Annotated[object, Stock]

    decoded = S.decode_unknown_sync(Holder)({"stock": {"sku": "a", "on_hand": 1}})
    assert decoded.stock == Stock(sku="a", on_hand=1)


def test_an_annotated_schema_inside_a_container_and_an_optional():
    class Lines(S.Class):
        amounts: list[Annotated[int, S.Int.check(S.is_greater_than(0))]]
        note: Annotated[str, S.NonEmptyString] | None = None

    SchemaAsserts(Lines).decoding().fail(
        {"amounts": [1, 0]}, 'Expected a value greater than 0\n  at ["amounts"][1]'
    )
    with pytest.raises(S.SchemaError):
        Lines(amounts=[1], note="")


class Line(TypedDict):
    amount: Annotated[int, S.Int.check(S.is_greater_than(0))]


def test_a_struct_of_a_typed_dict_reads_an_annotated_schema_too():
    SchemaAsserts(S.Struct(Line)).decoding().fail(
        {"amount": 0}, 'Expected a value greater than 0\n  at ["amount"]'
    )
