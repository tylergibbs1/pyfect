"""A check in a field's `Annotated` metadata that can't run on the value (a length check on an
int) raises a `TypeError` naming the field and the check, chained from what the check raised.

It used to raise `RuntimeError: Constructor adapter can only throw schema issues` (or `Sync
adapter can only throw schema errors` when decoding), naming neither. Effect has no schema
error for a filter that throws (the exception escapes as a defect), and pyright can't see a
check inside `Annotated`, so this is the first place the mistake shows. Defining the class
still succeeds: a default, a union or an optional field may never meet the check.
"""

from __future__ import annotations

from typing import Annotated, TypedDict

import pytest

from pyfect import schema as S


class Bin(S.Class):
    count: Annotated[int, S.is_min_length(1)]


class Mixed(S.Class):
    v: Annotated[int | str, S.is_min_length(1)]


class Rows(S.Class):
    xs: list[Annotated[int, S.is_min_length(1)]]


class Custom(S.Class):
    n: Annotated[int, S.make_filter(lambda s: len(s) > 0)]  # pyright: ignore[reportArgumentType]


class Line(TypedDict):
    quantity: Annotated[int, S.is_min_length(1)]


_BIN = (
    "Bin.count: the check is_min_length (a value with a length of at least 1) raised on 3: "
    "TypeError: object of type 'int' has no len(). Give the field a check that fits its type"
)


def test_constructing_names_the_field_and_the_check():
    with pytest.raises(TypeError) as raised:
        Bin(count=3)
    assert str(raised.value) == _BIN
    assert isinstance(raised.value.__cause__, TypeError)
    assert str(raised.value.__cause__) == "object of type 'int' has no len()"


def test_decoding_names_the_field_and_the_check():
    with pytest.raises(TypeError) as raised:
        S.decode_unknown_sync(Bin)({"count": 3})
    assert str(raised.value) == _BIN


def test_a_value_of_the_wrong_type_is_still_a_schema_error():
    with pytest.raises(S.SchemaError):
        S.decode_unknown_sync(Bin)({"count": "x"})


def test_a_union_field_fails_only_for_the_member_the_check_does_not_fit():
    assert Mixed(v="ab").v == "ab"
    with pytest.raises(TypeError, match=r"^Mixed\.v: the check is_min_length .* raised on 1: "):
        Mixed(v=1)


def test_a_check_inside_a_container_names_the_field():
    assert Rows(xs=[]).xs == []
    with pytest.raises(TypeError, match=r"^Rows\.xs: the check is_min_length "):
        Rows(xs=[1])


def test_a_check_without_a_name_is_called_a_check():
    with pytest.raises(TypeError) as raised:
        Custom(n=1)
    assert str(raised.value) == (
        "Custom.n: the check raised on 1: TypeError: object of type 'int' has no len(). "
        "Give the field a check that fits its type"
    )


def test_a_typed_dict_key_is_named_too():
    with pytest.raises(TypeError, match=r"^Line\['quantity'\]: the check is_min_length "):
        S.decode_unknown_sync(S.Struct(Line))({"quantity": 1})


def test_defining_the_class_still_succeeds():
    class WithDefault(S.Class):
        count: Annotated[int, S.is_min_length(1)] = 0

    assert S.decode_unknown_sync(WithDefault)({}).count == 0
